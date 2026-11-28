from __future__ import annotations

import json
import posixpath
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlencode


class SkillsFlakeError(ValueError):
    """`skills/flake.nix` or its lock is missing or unreadable, so the repo has no skills."""


# The inputs of skills/flake.nix that every skill follows; all other inputs are skills.
_SHARED_INPUTS = frozenset({"nixpkgs", "carapace"})
_FIX = "List the skills in skills/flake.nix and run `nix flake lock ./skills` (docs/skill-flakes.md)."


@dataclass(frozen=True, slots=True)
class ListedSkill:
    """An input of skills/flake.nix: a skill, named by its attribute."""

    name: str
    # Below skills/, for a `path:` input; None for a flake from elsewhere.
    directory: PurePosixPath | None
    # Where it comes from: `./<dir>` for a local skill, the flake reference it was written as otherwise.
    origin: str
    # The commit and its time the lock pins; None for a local skill, which the lock does not pin.
    locked_rev: str | None
    locked_at: datetime | None


def parse_skills_lock(text: str) -> list[ListedSkill]:
    """The skills `skills/flake.lock` lists, sorted by name.

    The lock and not the flake: the server never evaluates Nix, and the lock holds every input the builder builds.
    """
    try:
        lock = json.loads(text)
        nodes = lock["nodes"]
        inputs = nodes[lock["root"]].get("inputs", {})
        for node_id, node in nodes.items():
            if node_id != lock["root"]:
                _refuse_builder_local(node_id, node)
                _refuse_without_nar_hash(node_id, node)
        skills = [
            _listed_skill(name, nodes[node]) for name, node in sorted(inputs.items()) if name not in _SHARED_INPUTS
        ]
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise SkillsFlakeError(f"skills/flake.lock is not a flake lock file ({exc}). {_FIX}") from exc
    return skills


def _listed_skill(name: str, node: dict[str, Any]) -> ListedSkill:
    locked = node["locked"]
    directory = _local_directory(name, node)
    modified = locked.get("lastModified")
    return ListedSkill(
        name=name,
        directory=directory,
        origin=f"./{directory}" if directory is not None else flake_ref(node.get("original", locked)),
        locked_rev=locked.get("rev"),
        locked_at=datetime.fromtimestamp(modified, UTC) if modified is not None else None,
    )


def flake_ref(attributes: dict[str, Any]) -> str:
    """The flake reference a lock entry's attributes stand for, e.g. `github:owner/repo/ref?dir=sub`."""
    kind = attributes["type"]
    query = {key: attributes[key] for key in ("dir",) if key in attributes}
    match kind:
        case "github" | "gitlab" | "sourcehut":
            ref = attributes.get("ref") or attributes.get("rev")
            base = f"{kind}:{attributes['owner']}/{attributes['repo']}" + (f"/{ref}" if ref else "")
        case "git":
            base = f"git+{attributes['url']}"
            query = {key: attributes[key] for key in ("ref", "rev") if key in attributes} | query
        case "path":
            base = f"path:{attributes['path']}"
        case "indirect":
            base = attributes["id"]
        case _:
            # tarball, file, mercurial: their URL says it.
            base = attributes.get("url", kind)
    return f"{base}?{urlencode(query, safe='/')}" if query else base


def _refuse_builder_local(node_id: str, node: dict[str, Any]) -> None:
    """Any node, nested ones and nixpkgs included: a path on the builder's own disk would read the builder,
    not this repo, and land in the shared store the binary cache serves."""
    for attributes in (node["locked"], node.get("original") or {}):
        if (
            (attributes.get("type") == "path" and str(attributes.get("path", "")).startswith("/"))
            or attributes.get("type") == "file"
            or str(attributes.get("url", "")).startswith("file:")
        ):
            raise SkillsFlakeError(
                f"input {node_id}: an absolute path, file: or git+file: input reads the builder's disk; "
                "use path:./<dir> for a skill in this repo or a remote flake reference"
            )


def _refuse_without_nar_hash(node_id: str, node: dict[str, Any]) -> None:
    """Any node but a local skill's, nested ones included: a `rev` alone counts as locked, and the builder's
    fetcher cache serves a commit another user's token fetched without asking the forge. With the `narHash`
    required, using a private input takes reading a lock that uses it. `nix flake lock` always writes one;
    a local skill's `path:./<dir>` node has none and comes from this repo anyway."""
    locked = node["locked"]
    if locked["type"] != "path" and "narHash" not in locked:
        raise SkillsFlakeError(f"input {node_id}: its lock entry has no narHash; lock it again with nix flake lock")


def _local_directory(name: str, node: dict[str, Any]) -> PurePosixPath | None:
    locked = node["locked"]
    if locked["type"] != "path":
        return None
    directory = posixpath.normpath(locked["path"])
    if directory == "." or directory.startswith(".."):
        raise SkillsFlakeError(f"skill {name}: a local skill is a directory below skills/, not {locked['path']!r}")
    return PurePosixPath(directory)


def read_skills_flake(skills_dir: Path) -> list[ListedSkill]:
    """The skills of *skills_dir*'s flake. Without `flake.nix` a repo has no skills: there is no other discovery."""
    if not (skills_dir / "flake.nix").is_file():
        raise SkillsFlakeError(f"skills/flake.nix is missing, so this knowledge repo has no skills. {_FIX}")
    lock = skills_dir / "flake.lock"
    if not lock.is_file():
        raise SkillsFlakeError(f"skills/flake.lock is missing. {_FIX}")
    return parse_skills_lock(lock.read_text())
