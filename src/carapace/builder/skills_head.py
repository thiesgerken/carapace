"""skills/ of a knowledge repo at HEAD, read from Git objects for builds and update checks."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from ..skills import ListedSkill, SkillsFlakeError, parse_skills_lock


@dataclass(frozen=True, slots=True)
class SkillsFlakeAtHead:
    """skills/ at HEAD, read from Git objects: Git and not the working tree, so everything describes HEAD."""

    tree: str
    flake: str
    lock: str
    # skills/config.json, the values of the skills' settings; empty without one.
    config: str
    lock_text: str
    skills: list[ListedSkill]
    # What is wrong with config.json that no skill's manifest reports, or None.
    config_error: str | None


async def skills_flake_at_head(repo_dir: Path) -> SkillsFlakeAtHead | None:
    """None without a usable skills/flake.nix and lock at HEAD; the knowledge view says why."""
    tree = await object_id(repo_dir, "HEAD:skills")
    flake = await object_id(repo_dir, "HEAD:skills/flake.nix")
    lock = await object_id(repo_dir, "HEAD:skills/flake.lock")
    if not (tree and flake and lock):
        return None
    config = await object_id(repo_dir, "HEAD:skills/config.json")
    try:
        lock_text = (await _git(repo_dir, "cat-file", "blob", lock)).decode()
        skills = parse_skills_lock(lock_text)
    except (SkillsFlakeError, UnicodeDecodeError):
        return None
    config_error = unlisted_config_entries(await _git(repo_dir, "cat-file", "blob", config), skills) if config else None
    return SkillsFlakeAtHead(
        tree=tree, flake=flake, lock=lock, config=config, lock_text=lock_text, skills=skills, config_error=config_error
    )


def unlisted_config_entries(config: bytes, skills: list[ListedSkill]) -> str | None:
    """Entries of config.json for skills that skills/flake.nix does not list, as a message, or None.

    skillsFlake ignores them so that a skill dropped from the flake does not fail every other one; they are
    still a mistake, so the server says so.
    """
    try:
        values = json.loads(config)
    except (json.JSONDecodeError, UnicodeDecodeError):
        # Every skill's manifest fails on it, with Nix's message.
        return None
    if not isinstance(values, dict):
        return None
    unlisted = sorted(set(values) - {skill.name for skill in skills})
    if not unlisted:
        return None
    return (
        f"skills/config.json has entries for {', '.join(unlisted)}, which skills/flake.nix does not list: "
        "remove them, or list the skills again."
    )


async def archive_skills(repo_dir: Path, tree: str, *paths: str) -> bytes:
    """The skills/ tree *tree*, or only *paths* of it, as the tar archive the builder takes."""
    # Literal: a directory name like `*` would otherwise glob in more than the key covers.
    return await _git(repo_dir, "--literal-pathspecs", "archive", tree, "--", *paths)


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
