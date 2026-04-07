from __future__ import annotations

from pathlib import Path

from carapace.agent.tools import _read_skill_access_denial


def test_denies_read_for_backend_existing_skill_file_when_not_activated(tmp_path: Path) -> None:
    skill_file = tmp_path / "skills" / "demo" / "SKILL.md"
    skill_file.parent.mkdir(parents=True, exist_ok=True)
    skill_file.write_text("# Demo")

    result = _read_skill_access_denial(
        "skills/demo/SKILL.md",
        tmp_path,
        activated_skills=[],
    )

    assert result == "Please activate the demo skill using the use_skill tool before accessing the skill's files"


def test_allows_read_for_backend_existing_skill_file_when_activated(tmp_path: Path) -> None:
    skill_file = tmp_path / "skills" / "demo" / "SKILL.md"
    skill_file.parent.mkdir(parents=True, exist_ok=True)
    skill_file.write_text("# Demo")

    result = _read_skill_access_denial(
        "/workspace/skills/demo/SKILL.md",
        tmp_path,
        activated_skills=["demo"],
    )

    assert result is None


def test_allows_read_for_sandbox_only_skill_file_when_not_in_backend(tmp_path: Path) -> None:
    result = _read_skill_access_denial(
        "skills/new_skill/SKILL.md",
        tmp_path,
        activated_skills=[],
    )

    assert result is None
