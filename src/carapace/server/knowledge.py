"""Read-only browsing of the per-user knowledge repo working tree."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from loguru import logger
from pydantic import BaseModel, ValidationError

from ..api_keys import Access, Scope
from ..auth import UserIdentity
from ..credentials import UnknownBackendError
from ..git.store import GitStore
from ..models.credentials import CredentialRegistryProtocol
from ..models.git import FileCommit
from ..models.skills import SkillCarapaceConfig
from ..session.sent_files import INLINE_MIME_TYPES, guess_mime
from ..skills import SkillDocument, parse_skill_document
from .artifact_rendering import artifact_headers
from .auth import require
from .state import server_module

server = server_module()

router = APIRouter()

# Files above this size are download-only: the browser inlines contents into the
# listing response, and huge blobs would bloat it for no benefit.
MAX_INLINE_TEXT_BYTES = 1024 * 1024

# Markers for the directory conventions the browser renders specially.
SKILL_DOC = "SKILL.md"
README_NAMES = frozenset({"readme.md", "readme"})


def read_text_content(target: Path, size: int) -> str | None:
    """Decode *target* as UTF-8 text, or return ``None`` if binary or too large.

    Same heuristic git uses: a NUL byte means binary. UTF-8 decoding catches the
    rest, so extensionless files (``.gitignore``, ``Dockerfile``) read as text.
    """
    if size > MAX_INLINE_TEXT_BYTES:
        return None
    data = target.read_bytes()
    if b"\0" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


class KnowledgeEntry(BaseModel):
    name: str
    type: Literal["file", "dir"]
    size: int | None = None
    # Files only: mtime of the working-tree file. A checkout or pull rewrites it, so
    # it is only the fallback for entries `commit` does not cover (uncommitted files).
    modified: datetime | None = None
    # Newest commit touching this entry; None for uncommitted paths.
    commit: FileCommit | None = None
    # Recognized directory conventions get a `kind` plus a human label the client
    # renders where a file would show its size.
    kind: Literal["session", "skill", "artifact"] | None = None
    label: str | None = None
    session_id: str | None = None


def session_archive_entry(directory: Path, root: Path) -> tuple[str | None, str] | None:
    """Return ``(title, session_id)`` if *directory* is a session archive, else ``None``.

    Detection is by the ``conversation.json`` marker rather than the path layout,
    so it survives a reconfigured ``path_prefix``. Title may be None for untitled
    (or private, never-titled) sessions; the session id is always the dir name.
    """
    archive = contained_target(directory / "conversation.json", root)
    if archive is None or not archive.is_file():
        return None
    # ponytail: parses the whole archive (up to MAX_INLINE_TEXT_BYTES) for one field,
    # since "session" sorts last in the JSON. Cache by (path, mtime) if listing a
    # month of sessions ever gets slow. The cap matters: this runs for every subdir
    # of a listing, on files a pushing client controls the size of.
    if archive.stat().st_size > MAX_INLINE_TEXT_BYTES:
        return None
    try:
        payload = json.loads(archive.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        # The repo is user-writable; a hand-mangled archive must not break browsing.
        logger.debug(f"Ignoring unreadable session archive {archive}: {exc}")
        return None
    session = payload.get("session") if isinstance(payload, dict) else None
    if not isinstance(session, dict):
        return None
    title = session.get("title")
    session_id = session.get("session_id")
    return (title if isinstance(title, str) and title.strip() else None), (
        session_id if isinstance(session_id, str) and session_id else directory.name
    )


class KnowledgeSkill(BaseModel):
    """Frontmatter of a skill dir's SKILL.md, rendered as a card above its prose."""

    name: str
    description: str = ""
    # None when metadata.carapace is absent or fails validation; the prose still renders.
    carapace: SkillCarapaceConfig | None = None


class KnowledgeDirListing(BaseModel):
    type: Literal["dir"] = "dir"
    path: str
    entries: list[KnowledgeEntry]
    # Recognized directory conventions get their defining document inlined, rendered
    # below the listing (a skill dir's SKILL.md, frontmatter stripped into `skill`).
    kind: Literal["skill"] | None = None
    doc_name: str | None = None
    doc: str | None = None
    skill: KnowledgeSkill | None = None
    # Per secret vault_path referenced by the skill (credentials + mcp auth):
    # "present" | "absent" | "error" (vault unreachable). Empty unless a skill dir.
    vault_status: dict[str, str] = {}


class KnowledgeFileInfo(BaseModel):
    type: Literal["file"] = "file"
    path: str
    name: str
    size: int
    mime: str
    # Decoded contents for text files within MAX_INLINE_TEXT_BYTES; None for binary
    # or oversized files, which the client offers as a download instead.
    content: str | None = None


def contained_target(child: Path, root: Path) -> Path | None:
    """Resolve *child*, or return None if it is unreadable or out of bounds.

    Listing a directory means reading through its entries (a SKILL.md, a README, a
    session's conversation.json), and a symlink committed into the repo can point
    anywhere. Every such read resolves through here first, so the guards that
    ``resolve_target`` applies to the browsed path also cover the reads the listing
    does on its own: outside the repo, and inside ``.git`` (which holds the remote
    URL with its access token).
    """
    try:
        target = child.resolve(strict=True)
    except (OSError, RuntimeError):
        # Broken symlink, symlink loop, or an unreadable parent: nothing to read.
        return None
    if not target.is_relative_to(root):
        return None
    return None if ".git" in target.relative_to(root).parts else target


def resolve_target(root: Path, raw_path: str) -> Path:
    """Resolve *raw_path* inside an already-resolved *root*, rejecting traversal and ``.git``."""
    target = contained_target(root / raw_path, root) if raw_path else root
    if target is None:
        raise HTTPException(status_code=404, detail="Not found")
    return target


def validate_artifact_slug(slug: str) -> None:
    if not slug or slug in {".", ".."} or "/" in slug or "\\" in slug:
        raise HTTPException(status_code=404, detail="Not found")


def resolve_artifact_index(root: Path, slug: str) -> Path:
    validate_artifact_slug(slug)
    directory = resolve_target(root, f"artifacts/{slug}")
    if directory != root / "artifacts" / slug or not directory.is_dir():
        raise HTTPException(status_code=404, detail="Not found")
    target = resolve_target(directory, "index.html")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return target


class _ArtifactTitleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_title = False
        self.finished = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self.in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"title", "head"}:
            self.in_title = False
            self.finished = True

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.parts.append(data)


def artifact_title(index: Path) -> str | None:
    parser = _ArtifactTitleParser()
    with index.open(encoding="utf-8", errors="replace") as document:
        while chunk := document.read(4096):
            parser.feed(chunk)
            if parser.finished:
                break
    return " ".join("".join(parser.parts).split()) or None


def build_entry(child: Path, root: Path) -> KnowledgeEntry:
    resolved = contained_target(child, root)
    if resolved is None:
        # Dangling or escaping symlink: name it, but never read through it.
        return KnowledgeEntry(name=child.name, type="file")
    if not resolved.is_dir():
        stat = resolved.stat()
        return KnowledgeEntry(
            name=child.name,
            type="file",
            size=stat.st_size,
            modified=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
        )
    relative = resolved.relative_to(root).parts
    if len(relative) == 2 and relative[0] == "artifacts":
        index = contained_target(resolved / "index.html", resolved)
        if index is not None and index.is_file():
            return KnowledgeEntry(name=child.name, type="dir", kind="artifact", label=artifact_title(index))
    archive = session_archive_entry(resolved, root)
    if archive is not None:
        title, session_id = archive
        return KnowledgeEntry(name=child.name, type="dir", kind="session", label=title, session_id=session_id)
    if contained_target(resolved / SKILL_DOC, root) is not None:
        return KnowledgeEntry(name=child.name, type="dir", kind="skill")
    return KnowledgeEntry(name=child.name, type="dir")


def find_readme(target: Path, entries: list[KnowledgeEntry], root: Path) -> Path | None:
    """Pick the directory's README, matched case-insensitively against the listing."""
    for entry in entries:
        if entry.type == "file" and entry.name.lower() in README_NAMES:
            return contained_target(target / entry.name, root)
    return None


def inline_doc(target: Path, entries: list[KnowledgeEntry], listing: KnowledgeDirListing, root: Path) -> None:
    """Attach the directory's defining document, so the browser needs no second request.

    A SKILL.md marks a skill dir (the marker SkillRegistry scans for) and gets its
    frontmatter split out; any other directory falls back to its README.
    """
    skill_doc = contained_target(target / SKILL_DOC, root)
    if skill_doc is not None and skill_doc.is_file():
        raw = read_text_content(skill_doc, skill_doc.stat().st_size)
        if raw is None:
            return
        document = parse_skill_document(raw, fallback_name=target.name)
        listing.kind = "skill"
        listing.doc_name = SKILL_DOC
        listing.doc = document.body
        listing.skill = KnowledgeSkill(
            name=document.name,
            description=document.description,
            carapace=parse_carapace_config(document, target.name),
        )
        return

    readme = find_readme(target, entries, root)
    if readme is None or not readme.is_file():
        return
    raw = read_text_content(readme, readme.stat().st_size)
    if raw is not None:
        listing.doc_name = readme.name
        listing.doc = raw


def list_dir(root: Path, target: Path) -> KnowledgeDirListing:
    # `.git` is filtered by name here rather than left to contained_target, which would
    # report it as an unreadable entry instead of hiding it.
    entries = [build_entry(child, root) for child in target.iterdir() if child.name != ".git"]
    entries.sort(key=lambda e: (e.type != "dir", e.name.casefold()))
    rel = target.relative_to(root)
    listing = KnowledgeDirListing(path="" if rel == Path() else rel.as_posix(), entries=entries)
    inline_doc(target, entries, listing, root)
    return listing


async def attach_commits(git_store: GitStore, listing: KnowledgeDirListing) -> None:
    """Fill in each entry's newest commit. Silent no-op on a repo without commits."""
    commits = await git_store.last_commits(listing.path)
    if not commits:
        return
    for entry in listing.entries:
        entry.commit = commits.get(entry.name)


def parse_carapace_config(document: SkillDocument, skill_name: str) -> SkillCarapaceConfig | None:
    """Validate ``metadata.carapace``, or return None if absent or malformed."""
    raw = document.metadata.get("carapace")
    if raw is None:
        return None
    try:
        return SkillCarapaceConfig.model_validate(raw)
    except ValidationError as exc:
        # Skills are user-authored; a bad declaration must not break browsing.
        logger.warning(f"Invalid metadata.carapace in SKILL.md for skill '{skill_name}': {exc}")
        return None


def _skill_secret_refs(cfg: SkillCarapaceConfig) -> list[str]:
    """All vault paths a skill references (credentials + MCP auth), de-duplicated."""
    refs = {c.vault_path for c in cfg.credentials}
    refs |= {m.auth.vault_path for m in cfg.mcp if m.auth is not None}
    return sorted(refs)


async def resolve_vault_status(cfg: SkillCarapaceConfig, registry: CredentialRegistryProtocol) -> dict[str, str]:
    """Check each referenced vault path for existence (metadata only, never values).

    Status per path: ``present`` (a loaded backend has it), ``absent`` (a loaded
    backend lacks it), ``unconfigured`` (the named backend is not registered — e.g.
    the file backend is disabled), or ``error`` (backend reachable but failed).
    """
    status: dict[str, str] = {}
    for ref in _skill_secret_refs(cfg):
        try:
            await registry.fetch_metadata(ref)
            status[ref] = "present"
        except UnknownBackendError:
            status[ref] = "unconfigured"
        except KeyError:
            status[ref] = "absent"
        except Exception:
            status[ref] = "error"
    return status


@router.get("/knowledge/browse", response_model=None)
@router.get("/knowledge/browse/{path:path}", response_model=None)
async def browse_knowledge(
    user: Annotated[UserIdentity, Depends(require(Scope.knowledge, Access.read))],
    path: str = "",
    raw: Annotated[bool, Query()] = False,
    download: Annotated[bool, Query()] = False,
) -> KnowledgeDirListing | KnowledgeFileInfo | FileResponse:
    handle = server._knowledge_repo_registry.get_for_user(user.username)
    root = handle.knowledge_dir.resolve()
    if not root.is_dir():
        return KnowledgeDirListing(path="", entries=[])
    target = resolve_target(root, path)
    if target.is_dir():
        listing = list_dir(root, target)
        await attach_commits(handle.git_store, listing)
        if listing.skill is not None and listing.skill.carapace is not None:
            try:
                registry = await server._credential_registry_for_user(user.username)
                listing.vault_status = await resolve_vault_status(listing.skill.carapace, registry)
            except Exception as exc:
                logger.warning(f"Vault status lookup failed for skill '{target.name}': {exc}")
        return listing
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    rel = target.relative_to(root).as_posix()
    if raw or download:
        mime = guess_mime(target.name)
        # Repo contents come from a sandboxed agent's `git push`, and this is served
        # from the app origin under a cookie session. Only images render inline (the
        # browser's <img>); a pushed .html or .svg would otherwise run script here.
        inline = raw and mime in INLINE_MIME_TYPES
        return FileResponse(
            target,
            media_type=mime if inline else "application/octet-stream",
            filename=target.name,
            content_disposition_type="inline" if inline else "attachment",
        )
    size = target.stat().st_size
    mime = guess_mime(target.name)
    return KnowledgeFileInfo(
        path=rel,
        name=target.name,
        size=size,
        mime=mime,
        # Only the types the client renders as an <img> skip their contents; anything
        # else it cannot display (an SVG, say) is still worth showing as source.
        content=None if mime in INLINE_MIME_TYPES else read_text_content(target, size),
    )


@router.get("/artifacts/{slug}")
async def render_artifact(
    user: Annotated[UserIdentity, Depends(require(Scope.knowledge, Access.read))],
    slug: str,
) -> FileResponse:
    handle = server._knowledge_repo_registry.get_for_user(user.username)
    target = resolve_artifact_index(handle.knowledge_dir.resolve(), slug)
    return FileResponse(target, media_type="text/html", headers=artifact_headers())
