"""Read-only browsing of the per-user knowledge repo working tree."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from loguru import logger
from pydantic import BaseModel

from ..api_keys import Access, Scope
from ..artifacts import artifact_index, artifact_title, is_artifact_slug
from ..auth import UserIdentity
from ..builder.skill_builds import BuildState, RetryRefusedError, SkillBuilds, SkillCommand
from ..builder.skill_updates import SkillUpdates, UpdateRefusedError, UpdateState
from ..builder.skills_head import skills_flake_at_head
from ..git.store import ConcurrentChangeError, GitStore
from ..knowledge import contained_target
from ..models.git import FileCommit
from ..models.skills import SkillCarapaceConfig
from ..session.manager import SessionManager
from ..session.sent_files import INLINE_MIME_TYPES, guess_mime
from ..skills import SkillDocumentError, SkillsFlakeError, parse_skill_document, read_skills_flake
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
    shared: bool = False


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
    # None when metadata.carapace is absent or invalid; the prose still renders.
    carapace: SkillCarapaceConfig | None = None
    # Why the frontmatter is unusable: a broken skill stays browsable so it can be fixed.
    error: str | None = None


class KnowledgeSkillBuild(BaseModel):
    """How the skill is built at HEAD; uncommitted edits are not built."""

    state: BuildState
    key: str
    commands: dict[str, SkillCommand]
    # Why it failed or is unavailable: the end of the build log, or what went wrong before it.
    log_tail: str


class KnowledgeSkillUpdate(BaseModel):
    state: UpdateState
    available_rev: str | None
    available_at: datetime | None
    detail: str


class KnowledgeSkillSource(BaseModel):
    """A skill skills/flake.nix lists at HEAD: where it comes from, and the last update check's verdict."""

    name: str
    # The skill's directory in the repo, for a local skill.
    path: str | None
    origin: str
    locked_rev: str | None
    locked_at: datetime | None
    # None until a check covered it.
    update: KnowledgeSkillUpdate | None


class KnowledgeSkillSources(BaseModel):
    skills: list[KnowledgeSkillSource]
    checked_at: datetime | None
    checking: bool
    # Why the last check could not run at all (no builder, builder unreachable).
    check_error: str | None


class ArtifactSession(BaseModel):
    session_id: str
    title: str | None = None


class KnowledgeArtifact(BaseModel):
    slug: str
    title: str
    created_in: ArtifactSession | None = None
    updated_in: ArtifactSession | None = None


class KnowledgeDirListing(BaseModel):
    type: Literal["dir"] = "dir"
    path: str
    entries: list[KnowledgeEntry]
    # Recognized directory conventions get their defining document inlined, rendered
    # below the listing (a skill dir's SKILL.md, frontmatter stripped into `skill`).
    kind: Literal["skill", "artifact"] | None = None
    doc_name: str | None = None
    doc: str | None = None
    skill: KnowledgeSkill | None = None
    build: KnowledgeSkillBuild | None = None
    artifact: KnowledgeArtifact | None = None
    # On the root and skills/: why the repo has no skills (skills/flake.nix or its lock unusable), with the fix.
    skills_error: str | None = None


class KnowledgeFileInfo(BaseModel):
    type: Literal["file"] = "file"
    path: str
    name: str
    size: int
    mime: str
    # Decoded contents for text files within MAX_INLINE_TEXT_BYTES; None for binary
    # or oversized files, which the client offers as a download instead.
    content: str | None = None
    artifact: KnowledgeArtifact | None = None


def resolve_target(root: Path, raw_path: str) -> Path:
    """Resolve *raw_path* inside an already-resolved *root*, rejecting traversal and ``.git``."""
    target = contained_target(root / raw_path, root) if raw_path else root
    if target is None:
        raise HTTPException(status_code=404, detail="Not found")
    return target


def validate_artifact_slug(slug: str) -> None:
    if not is_artifact_slug(slug):
        raise HTTPException(status_code=404, detail="Not found")


def resolve_artifact_index(root: Path, slug: str) -> Path:
    target = artifact_index(root, slug)
    if target is None:
        raise HTTPException(status_code=404, detail="Not found")
    return target


def artifact_info(target: Path, root: Path) -> KnowledgeArtifact | None:
    parts = target.relative_to(root).parts
    if len(parts) not in {2, 3} or parts[0] != "artifacts":
        return None
    if len(parts) == 3 and parts[2] != "index.html":
        return None
    slug = parts[1]
    try:
        index = resolve_artifact_index(root, slug)
    except HTTPException:
        return None
    return KnowledgeArtifact(slug=slug, title=artifact_title(index) or slug)


def listed_skill_dirs(root: Path) -> tuple[dict[Path, str], str | None]:
    """Directory -> name of each local skill skills/flake.nix lists, or why the repo has no skills."""
    try:
        listed = read_skills_flake(root / "skills")
    except SkillsFlakeError as exc:
        return {}, str(exc)
    # Resolved, as the entries they are matched against are.
    skills = root / "skills"
    return {(skills / skill.directory).resolve(): skill.name for skill in listed if skill.directory is not None}, None


def build_entry(child: Path, root: Path, skill_dirs: dict[Path, str]) -> KnowledgeEntry:
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
    if resolved in skill_dirs:
        return KnowledgeEntry(name=child.name, type="dir", kind="skill")
    return KnowledgeEntry(name=child.name, type="dir")


def find_readme(target: Path, entries: list[KnowledgeEntry], root: Path) -> Path | None:
    """Pick the directory's README, matched case-insensitively against the listing."""
    for entry in entries:
        if entry.type == "file" and entry.name.lower() in README_NAMES:
            return contained_target(target / entry.name, root)
    return None


def inline_doc(
    target: Path, entries: list[KnowledgeEntry], listing: KnowledgeDirListing, root: Path, skill: str | None
) -> None:
    """Attach the directory's defining document, so the browser needs no second request.

    A listed skill's SKILL.md gets its frontmatter split out; any other directory falls back to its README.
    """
    if skill is not None:
        listing.kind = "skill"
        # Named by its attribute in skills/flake.nix, whatever the frontmatter says.
        listing.skill = KnowledgeSkill(name=skill)
        skill_doc = contained_target(target / SKILL_DOC, root)
        raw = read_text_content(skill_doc, skill_doc.stat().st_size) if skill_doc and skill_doc.is_file() else None
        if raw is None:
            listing.skill.error = f"{SKILL_DOC} is missing or not text"
            return
        listing.doc_name = SKILL_DOC
        try:
            document = parse_skill_document(raw, fallback_name=skill)
        except SkillDocumentError as exc:
            listing.doc = raw
            listing.skill.error = str(exc)
            return
        listing.doc = document.body
        listing.skill.description = document.description
        try:
            listing.skill.carapace = document.carapace_config()
        except SkillDocumentError as exc:
            listing.skill.error = str(exc)
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
    skill_dirs, skills_error = listed_skill_dirs(root)
    entries = [build_entry(child, root, skill_dirs) for child in target.iterdir() if child.name != ".git"]
    entries.sort(key=lambda e: (e.type != "dir", e.name.casefold()))
    rel = target.relative_to(root)
    artifact = artifact_info(target, root)
    listing = KnowledgeDirListing(
        path="" if rel == Path() else rel.as_posix(),
        entries=entries,
        artifact=artifact,
        kind="artifact" if artifact else None,
    )
    if artifact is None:
        inline_doc(target, entries, listing, root, skill_dirs.get(target))
    if rel in (Path(), Path("skills")):
        listing.skills_error = skills_error
    return listing


async def attach_commits(git_store: GitStore, listing: KnowledgeDirListing) -> None:
    """Fill in each entry's newest commit. Silent no-op on a repo without commits."""
    commits = await git_store.last_commits(listing.path)
    if not commits:
        return
    for entry in listing.entries:
        entry.commit = commits.get(entry.name)


def artifact_session(session_id: str, session_mgr: SessionManager, owner: str) -> ArtifactSession:
    reference = ArtifactSession(session_id=session_id)
    try:
        owned = session_mgr.is_owned_by(session_id, owner)
    except FileNotFoundError:
        return reference
    if owned:
        state = session_mgr.load_state(session_id)
        reference.title = state.title if state is not None else None
    return reference


async def attach_artifact_sessions(
    artifact: KnowledgeArtifact, git_store: GitStore, session_mgr: SessionManager, owner: str
) -> None:
    history = await git_store.session_history(f"artifacts/{artifact.slug}/index.html")
    if history is None:
        return
    created, updated = history
    artifact.created_in = artifact_session(created, session_mgr, owner)
    if updated != created:
        artifact.updated_in = artifact_session(updated, session_mgr, owner)


async def skill_build(builds: SkillBuilds, repo_dir: Path, name: str) -> KnowledgeSkillBuild | None:
    """The build of skill *name* at HEAD; looking starts the build of a tree that has no result yet."""
    build = next((build for build in await builds.ensure_built(repo_dir) if build.skill == name), None)
    if build is None:
        return None
    return KnowledgeSkillBuild(state=build.state, key=build.key, commands=build.commands, log_tail=build.detail)


@router.post("/knowledge/skills/{name}/build/retry")
async def retry_skill_build(
    user: Annotated[UserIdentity, Depends(require(Scope.knowledge, Access.write))],
    name: str,
) -> KnowledgeSkillBuild:
    root = server._knowledge_repo_registry.get_for_user(user.username).knowledge_dir.resolve()
    try:
        await server._skill_builds.retry(root, name)
    except RetryRefusedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    build = await skill_build(server._skill_builds, root, name)
    assert build is not None, "retry() accepted a skill that ensure_built() does not list"
    return build


async def skill_sources(updates: SkillUpdates, repo_dir: Path) -> KnowledgeSkillSources:
    head = await skills_flake_at_head(repo_dir)
    check = updates.latest(repo_dir)
    results = check.skills if check is not None else {}
    skills = [
        KnowledgeSkillSource(
            name=skill.name,
            path=f"skills/{skill.directory}" if skill.directory is not None else None,
            origin=skill.origin,
            locked_rev=skill.locked_rev,
            locked_at=skill.locked_at,
            update=KnowledgeSkillUpdate(**asdict(results[skill.name])) if skill.name in results else None,
        )
        for skill in (head.skills if head is not None else [])
    ]
    return KnowledgeSkillSources(
        skills=skills,
        checked_at=check.checked_at if check is not None else None,
        checking=updates.running(repo_dir),
        check_error=(check.error or None) if check is not None else None,
    )


@router.get("/knowledge/skills")
async def list_skill_sources(
    user: Annotated[UserIdentity, Depends(require(Scope.knowledge, Access.read))],
) -> KnowledgeSkillSources:
    root = server._knowledge_repo_registry.get_for_user(user.username).knowledge_dir.resolve()
    return await skill_sources(server._skill_builds.updates, root)


@router.post("/knowledge/skills/updates/check")
async def check_skill_updates(
    user: Annotated[UserIdentity, Depends(require(Scope.knowledge, Access.write))],
) -> KnowledgeSkillSources:
    """Start an update check of the user's skills; poll `GET /knowledge/skills` until `checking` is false."""
    root = server._knowledge_repo_registry.get_for_user(user.username).knowledge_dir.resolve()
    server._skill_builds.updates.start(root)
    return await skill_sources(server._skill_builds.updates, root)


def _commit_author(user: UserIdentity) -> str:
    """The user as a commit author. Without `<` and `>`, which would turn --author into a search pattern."""
    name = re.sub("[<>]", "", user.display_name or user.username)
    email = re.sub("[<>]", "", user.email or f"{user.username}@carapace")
    return f"{name} <{email}>"


@router.post("/knowledge/skills/{name}/update")
async def update_skill(
    name: str,
    user: Annotated[UserIdentity, Depends(require(Scope.knowledge, Access.write))],
) -> KnowledgeSkillSources:
    """Commit the update the last check found for skill *name*, then push and build as after a sandbox push.

    The user acts, so the commit is theirs and skips the sentinel.
    """
    handle = server._knowledge_repo_registry.get_for_user(user.username)
    root = handle.knowledge_dir.resolve()
    try:
        pending = await server._skill_builds.updates.pending_update(root, name)
        await handle.git_store.commit_replacing(
            "skills/flake.lock",
            pending.lock_text,
            unchanged={"skills": pending.base_tree},
            message=pending.message,
            author=_commit_author(user),
        )
    except (UpdateRefusedError, ConcurrentChangeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await server._after_push(user.username)
    return await skill_sources(server._skill_builds.updates, root)


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
        if listing.artifact is not None:
            await attach_artifact_sessions(
                listing.artifact, handle.git_store, server._engine.session_mgr, user.username
            )
        else:
            await attach_commits(handle.git_store, listing)
        if any(entry.kind == "artifact" for entry in listing.entries):
            shared = server._artifact_share_store.shared_slugs(user.username)
            for entry in listing.entries:
                entry.shared = entry.kind == "artifact" and entry.name in shared
        if listing.skill is not None:
            listing.build = await skill_build(server._skill_builds, root, listing.skill.name)
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
    artifact = artifact_info(target, root)
    if artifact is not None:
        await attach_artifact_sessions(artifact, handle.git_store, server._engine.session_mgr, user.username)
    return KnowledgeFileInfo(
        path=rel,
        name=target.name,
        size=size,
        mime=mime,
        # Only the types the client renders as an <img> skip their contents; anything
        # else it cannot display (an SVG, say) is still worth showing as source.
        content=None if mime in INLINE_MIME_TYPES else read_text_content(target, size),
        artifact=artifact,
    )


@router.get("/artifacts/{slug}")
async def render_artifact(
    user: Annotated[UserIdentity, Depends(require(Scope.knowledge, Access.read))],
    slug: str,
) -> FileResponse:
    handle = server._knowledge_repo_registry.get_for_user(user.username)
    target = resolve_artifact_index(handle.knowledge_dir.resolve(), slug)
    # Chat references reload this route after every push; revalidating keeps them on the current version.
    headers = {**artifact_headers(), "Cache-Control": "no-cache"}
    return FileResponse(target, media_type="text/html", headers=headers)
