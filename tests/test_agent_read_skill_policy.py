from __future__ import annotations

from pathlib import Path

import pytest

from carapace.agent.tools import _exec_skill_access_warning, _read_skill_access_denial


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


@pytest.mark.parametrize(
    "command",
    [
        "uv run --directory /workspace/skills/demo demo",
        "npm --prefix /workspace/skills/demo run build",
        "pnpm --dir /workspace/skills/demo install",
        "cd /workspace/skills/demo && pnpm install",
        "bash /workspace/skills/demo/setup.sh",
        "/workspace/skills/demo/bin/demo-tool --help",
        "cat /workspace/skills/demo/setup.sh",
        "echo /workspace/skills/demo",
    ],
)
def test_warns_when_skill_is_not_activated(tmp_path: Path, command: str) -> None:
    skill_file = tmp_path / "skills" / "demo" / "SKILL.md"
    skill_file.parent.mkdir(parents=True, exist_ok=True)
    skill_file.write_text("# Demo")

    result = _exec_skill_access_warning(command, tmp_path, activated_skills=[], contexts=[])

    assert result == (
        "Warning: this command references skill directories without the matching skill context:\n"
        "- `demo` is referenced in this command but is not activated. Use `use_skill('demo')` first, then rerun "
        "`exec` with `contexts=['demo']` if you need that skill's context."
    )


@pytest.mark.parametrize(
    "command",
    [
        "uv run --directory /workspace/skills/demo demo",
        "pnpm --dir /workspace/skills/demo install",
        "cd /workspace/skills/demo && bash setup.sh",
        "/workspace/skills/demo/bin/demo-tool --help",
        "cat /workspace/skills/demo/setup.sh",
    ],
)
def test_warns_when_context_missing(tmp_path: Path, command: str) -> None:
    skill_file = tmp_path / "skills" / "demo" / "SKILL.md"
    skill_file.parent.mkdir(parents=True, exist_ok=True)
    skill_file.write_text("# Demo")

    result = _exec_skill_access_warning(command, tmp_path, activated_skills=["demo"], contexts=[])

    assert result == (
        "Warning: this command references skill directories without the matching skill context:\n"
        "- `demo` is referenced in this command but missing from `contexts`. Rerun `exec` with "
        "`contexts=['demo']` if you need that skill's injected credentials, tunnels, or domains."
    )


def test_no_warning_when_skill_activated_and_context_present(tmp_path: Path) -> None:
    skill_file = tmp_path / "skills" / "demo" / "SKILL.md"
    skill_file.parent.mkdir(parents=True, exist_ok=True)
    skill_file.write_text("# Demo")

    result = _exec_skill_access_warning(
        "uv run --directory /workspace/skills/demo demo",
        tmp_path,
        activated_skills=["demo"],
        contexts=["demo"],
    )

    assert result is None


def test_ignores_non_backend_skill_path_mentions(tmp_path: Path) -> None:
    skill_file = tmp_path / "skills" / "demo" / "SKILL.md"
    skill_file.parent.mkdir(parents=True, exist_ok=True)
    skill_file.write_text("# Demo")

    result = _exec_skill_access_warning(
        "cat /workspace/skills/new-skill/setup.sh",
        tmp_path,
        activated_skills=[],
        contexts=[],
    )

    assert result is None
