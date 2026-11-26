"""skills/ of a knowledge repo at HEAD, read from Git objects for builds and update checks."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from ..skills import ListedSkill, SkillsFlakeError, parse_skills_lock


@dataclass(frozen=True, slots=True)
class SkillsFlakeAtHead:
    """skills/ at HEAD, read from Git objects: Git and not the working tree, so everything describes HEAD."""

    tree: str
    flake: str
    lock: str
    lock_text: str
    skills: list[ListedSkill]


async def skills_flake_at_head(repo_dir: Path) -> SkillsFlakeAtHead | None:
    """None without a usable skills/flake.nix and lock at HEAD; the knowledge view says why."""
    tree = await object_id(repo_dir, "HEAD:skills")
    flake = await object_id(repo_dir, "HEAD:skills/flake.nix")
    lock = await object_id(repo_dir, "HEAD:skills/flake.lock")
    if not (tree and flake and lock):
        return None
    try:
        lock_text = (await _git(repo_dir, "cat-file", "blob", lock)).decode()
        skills = parse_skills_lock(lock_text)
    except (SkillsFlakeError, UnicodeDecodeError):
        return None
    return SkillsFlakeAtHead(tree=tree, flake=flake, lock=lock, lock_text=lock_text, skills=skills)


async def archive_skills(repo_dir: Path, tree: str) -> bytes:
    """The skills/ tree *tree* as the tar archive the builder takes."""
    return await _git(repo_dir, "archive", tree)


async def object_id(repo_dir: Path, spec: str) -> str:
    """The Git object *spec* names, or empty when it does not exist."""
    process = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        str(repo_dir),
        "rev-parse",
        "--verify",
        "--quiet",
        spec,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await process.communicate()
    return stdout.decode().strip() if process.returncode == 0 else ""


async def _git(repo_dir: Path, *args: str) -> bytes:
    process = await asyncio.create_subprocess_exec(
        "git", "-C", str(repo_dir), *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed in {repo_dir}: {stderr.decode(errors='replace').strip()}")
    return stdout
