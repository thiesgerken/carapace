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
    ("CORE.md", "memory/CORE.md"),
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
yarn-debug.log*
yarn-error.log*
.yarn/cache/
.yarn/unplugged/
.yarn/build-state.yml
.yarn/install-state.gz

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
"""


def _reset_assets() -> bool:
    return os.environ.get("CARAPACE_RESET_ASSETS", "").lower() in ("1", "true", "yes")


def _copy_asset(asset_path: str, target: Path) -> None:
    source = _ASSETS.joinpath(*asset_path.split("/"))
    with as_file(source) as src:
        logger.debug(f"Copying asset {asset_path} to {target}")
        shutil.copy2(src, target)


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


def _sync_bundled_skills(knowledge_dir: Path, reset: bool, created: list[str]) -> None:
    """Copy each ``carapace.assets/skills/<name>/`` tree into *knowledge_dir* when missing.

    When *reset* is true, overwrite files for every bundled skill (same as critical
    knowledge files).
    """
    skills_assets = _ASSETS.joinpath("skills")
    if not skills_assets.is_dir():
        return
    skills_out = knowledge_dir / "skills"
    for skill_root in sorted(skills_assets.iterdir(), key=lambda p: p.name):
        if not skill_root.is_dir():
            continue
        name = skill_root.name
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
