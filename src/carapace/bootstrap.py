from __future__ import annotations

import os
from importlib.resources import as_file, files
from pathlib import Path

_ASSETS = files("carapace.assets")

# --- Data dir files (stay in data/) ---

# Files that are never overwritten by CARAPACE_RESET_ASSETS (user-owned).
_USER_FILES: list[tuple[str, str]] = [
    ("config.yaml", "config.yaml"),
]

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

_SEED_SKILLS: list[tuple[str, str]] = [
    ("example-skill/SKILL.md", "skills/example/SKILL.md"),
    ("example-skill/pyproject.toml", "skills/example/pyproject.toml"),
    ("example-skill/uv.lock", "skills/example/uv.lock"),
    ("example-skill/scripts/hello.py", "skills/example/scripts/hello.py"),
    ("create-skill/SKILL.md", "skills/create-skill/SKILL.md"),
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
        target.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")


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

    # Seed skills directory
    skills_dir = knowledge_dir / "skills"
    if reset or not skills_dir.exists():
        for asset_name, target_rel in _SEED_SKILLS:
            target = knowledge_dir / target_rel
            target.parent.mkdir(parents=True, exist_ok=True)
            _copy_asset(asset_name, target)
            created.append(target_rel)

    return created
