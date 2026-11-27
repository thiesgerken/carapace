from __future__ import annotations

import os
import shutil
from importlib.resources import as_file, files
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


def _seed_skills_flake(knowledge_dir: Path, created: list[str]) -> None:
    """Give a new repo the bundled ``skills/flake.nix``, its lock and ``skills/config.json``.

    The flake lists the bundled skills as inputs on carapace's main branch, and config.json turns off the ones
    that need setting up first. An existing repo keeps its own, even on reset.
    """
    skills_out = knowledge_dir / "skills"
    if skills_out.exists():
        return
    skills_out.mkdir(parents=True)
    for name in ("flake.nix", "flake.lock", "config.json"):
        _copy_asset(f"skills/{name}", skills_out / name)
        created.append(f"skills/{name}")


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

    _seed_skills_flake(knowledge_dir, created)

    return created
