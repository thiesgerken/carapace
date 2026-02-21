from __future__ import annotations

from importlib.resources import as_file, files
from pathlib import Path

_ASSETS = files("carapace.assets")

_CRITICAL_FILES: list[tuple[str, str]] = [
    ("SOUL.md", "SOUL.md"),
    ("USER.md", "USER.md"),
    ("config.yaml", "config.yaml"),
    ("rules.yaml", "rules.yaml"),
    ("CORE.md", "memory/CORE.md"),
]

_SEED_SKILLS: list[tuple[str, str]] = [
    ("example-skill/SKILL.md", "skills/example/SKILL.md"),
    ("example-skill/pyproject.toml", "skills/example/pyproject.toml"),
    ("example-skill/uv.lock", "skills/example/uv.lock"),
    ("example-skill/scripts/hello.py", "skills/example/scripts/hello.py"),
    ("create-skill/SKILL.md", "skills/create-skill/SKILL.md"),
]


def _copy_asset(asset_path: str, target: Path) -> None:
    source = _ASSETS.joinpath(*asset_path.split("/"))
    with as_file(source) as src:
        target.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")


def ensure_data_dir(data_dir: Path) -> list[str]:
    """Ensure data dir exists with all critical files.

    Returns the list of file paths (relative to *data_dir*) that were created.
    """
    created: list[str] = []
    data_dir.mkdir(parents=True, exist_ok=True)

    for asset_name, target_rel in _CRITICAL_FILES:
        target = data_dir / target_rel
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            _copy_asset(asset_name, target)
            created.append(target_rel)

    # Seed skills directory when it doesn't exist at all
    skills_dir = data_dir / "skills"
    if not skills_dir.exists():
        for asset_name, target_rel in _SEED_SKILLS:
            target = data_dir / target_rel
            target.parent.mkdir(parents=True, exist_ok=True)
            _copy_asset(asset_name, target)
            created.append(target_rel)

    return created
