from __future__ import annotations

import os
import shutil
from importlib.resources import as_file, files
from importlib.resources.abc import Traversable
from pathlib import Path

from loguru import logger

_ASSETS = files("carapace.assets")

# --- Data dir files (stay in data/) ---

# Files that are never overwritten by CARAPACE_RESET_ASSETS (user-owned).
_USER_FILES: list[tuple[str, str]] = []

# --- Knowledge dir files (move to knowledge/) ---

# User-owned knowledge files: seed once, never overwrite.
_KNOWLEDGE_USER_FILES: list[tuple[str, str]] = [
    ("SOUL.md", "SOUL.md"),
    ("USER.md", "USER.md"),
]

# Critical knowledge files: overwrite when CARAPACE_RESET_ASSETS is set.
_KNOWLEDGE_CRITICAL_FILES: list[tuple[str, str]] = [
    ("SECURITY.md", "SECURITY.md"),
]

_KNOWLEDGE_GITIGNORE = """\
# Python
__pycache__/
*.pyc
*.pyo
.venv/
venv/
*.egg-info/

# Node
node_modules/
.npm/
.pnpm-store/
pnpm-debug.log*
npm-debug.log*

# OS
.DS_Store
Thumbs.db

# Editor
*.swp
*.swo
*~
.idea/
.vscode/

# Skill build artifacts
skills/**/.venv/

# Session scratch space
tmp/
tmp/**

# Generated sandbox runtime state
.carapace/
.carapace/**
"""


def _reset_assets() -> bool:
    return os.environ.get("CARAPACE_RESET_ASSETS", "").lower() in ("1", "true", "yes")


def _copy_asset(asset_path: str, target: Path) -> None:
    source = _ASSETS.joinpath(*asset_path.split("/"))
    with as_file(source) as src:
        logger.debug(f"Copying asset {asset_path} to {target}")
        # Content only: from the Nix store, a copied mode would make the file read-only, and a reset could
        # not overwrite it. Earlier versions copied it, so a read-only copy is replaced rather than opened.
        target.unlink(missing_ok=True)
        shutil.copyfile(src, target)


def _skill_file_relpaths(skill_root: Traversable) -> list[str]:
    paths: list[str] = []

    def walk(node: Traversable, prefix: str) -> None:
        for child in sorted(node.iterdir(), key=lambda c: c.name):
            rel = f"{prefix}/{child.name}" if prefix else child.name
            if child.is_dir():
                walk(child, rel)
            elif child.is_file():
                paths.append(rel)

    walk(skill_root, "")
    return paths


# Bundled skills whose flake carries this instance's settings, so a repo gets its own copy. The other
# bundled skills come from carapace's main branch as inputs of the seeded skills/flake.nix.
LOCAL_BUNDLED_SKILLS = ("carapace", "ferret", "web")


def _sync_bundled_skills(knowledge_dir: Path, reset: bool, created: list[str]) -> None:
    """Copy each ``carapace.assets/skills/<name>/`` tree of `LOCAL_BUNDLED_SKILLS` into *knowledge_dir* when missing.

    When *reset* is true, overwrite their files (same as critical knowledge files). A new repo also gets
    the bundled ``skills/flake.nix`` and its lock, which list the skills, and an empty ``skills/config.json``
    for their settings, which turns ``carapace-cli`` off until it is configured; an existing repo keeps its
    own, even on reset.
    """
    skills_assets = _ASSETS.joinpath("skills")
    if not skills_assets.is_dir():
        return
    skills_out = knowledge_dir / "skills"
    if not skills_out.exists():
        skills_out.mkdir(parents=True)
        for name in ("flake.nix", "flake.lock", "config.json"):
            _copy_asset(f"skills/{name}", skills_out / name)
            created.append(f"skills/{name}")
    for name in LOCAL_BUNDLED_SKILLS:
        skill_root = skills_assets.joinpath(name)
        dest_root = skills_out / name
        if not reset and dest_root.exists():
            continue
        for rel in _skill_file_relpaths(skill_root):
            target_rel = f"skills/{name}/{rel}"
            target = knowledge_dir / target_rel
            target.parent.mkdir(parents=True, exist_ok=True)
            _copy_asset(f"skills/{name}/{rel}", target)
            created.append(target_rel)


def ensure_data_dir(data_dir: Path) -> list[str]:
    """Ensure data dir exists with config and session directories.

    Returns the list of file paths (relative to *data_dir*) that were created.
    """
    created: list[str] = []
    data_dir.mkdir(parents=True, exist_ok=True)

    for asset_name, target_rel in _USER_FILES:
        target = data_dir / target_rel
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            _copy_asset(asset_name, target)
            created.append(target_rel)

    return created


def ensure_knowledge_dir(knowledge_dir: Path) -> list[str]:
    """Ensure knowledge dir has all required files.

    Seeds user-owned files, critical files, skills, and ``.gitignore``.
    Returns the list of file paths (relative to *knowledge_dir*) that were
    created or overwritten.
    """
    reset = _reset_assets()
    created: list[str] = []
    knowledge_dir.mkdir(parents=True, exist_ok=True)

    # .gitignore — seed once as user-owned
    gitignore = knowledge_dir / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(_KNOWLEDGE_GITIGNORE, encoding="utf-8")
        created.append(".gitignore")

    # User-owned knowledge files: seed once, never overwrite
    for asset_name, target_rel in _KNOWLEDGE_USER_FILES:
        target = knowledge_dir / target_rel
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            _copy_asset(asset_name, target)
            created.append(target_rel)

    # Critical knowledge files: overwrite when reset is requested
    for asset_name, target_rel in _KNOWLEDGE_CRITICAL_FILES:
        target = knowledge_dir / target_rel
        if reset or not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            _copy_asset(asset_name, target)
            created.append(target_rel)

    _sync_bundled_skills(knowledge_dir, reset, created)

    return created
