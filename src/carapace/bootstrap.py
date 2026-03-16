from __future__ import annotations

import os
from importlib.resources import as_file, files
from pathlib import Path

_ASSETS = files("carapace.assets")

# Files that are never overwritten by CARAPACE_RESET_ASSETS (user-owned).
_USER_FILES: list[tuple[str, str]] = [
    ("SOUL.md", "SOUL.md"),
    ("USER.md", "USER.md"),
    ("config.yaml", "config.yaml"),
]

# Files that are overwritten when CARAPACE_RESET_ASSETS is set.
_CRITICAL_FILES: list[tuple[str, str]] = [
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


def _reset_assets() -> bool:
    return os.environ.get("CARAPACE_RESET_ASSETS", "").lower() in ("1", "true", "yes")


def _copy_asset(asset_path: str, target: Path) -> None:
    source = _ASSETS.joinpath(*asset_path.split("/"))
    with as_file(source) as src:
        target.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")


def ensure_data_dir(data_dir: Path) -> list[str]:
    """Ensure data dir exists with all critical files.

    When ``CARAPACE_RESET_ASSETS`` is set to a truthy value (``1``, ``true``,
    ``yes``), existing files are overwritten with the bundled versions.

    Returns the list of file paths (relative to *data_dir*) that were created
    or overwritten.
    """
    reset = _reset_assets()
    created: list[str] = []
    data_dir.mkdir(parents=True, exist_ok=True)

    # User-owned files: only seed, never overwrite on reset.
    for asset_name, target_rel in _USER_FILES:
        target = data_dir / target_rel
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            _copy_asset(asset_name, target)
            created.append(target_rel)

    for asset_name, target_rel in _CRITICAL_FILES:
        target = data_dir / target_rel
        if reset or not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            _copy_asset(asset_name, target)
            created.append(target_rel)

    # Seed skills directory when it doesn't exist at all (or reset is requested)
    skills_dir = data_dir / "skills"
    if reset or not skills_dir.exists():
        for asset_name, target_rel in _SEED_SKILLS:
            target = data_dir / target_rel
            target.parent.mkdir(parents=True, exist_ok=True)
            _copy_asset(asset_name, target)
            created.append(target_rel)

    return created
