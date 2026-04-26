from __future__ import annotations

from pathlib import Path

import pytest

from carapace.agent.tools import (
    _exec_skill_access_warning,
    _read_skill_access_denial,
    _resolve_exec_command_alias,
    _skill_command_alias_conflict,
)
from carapace.sandbox.skill_activation import SKILL_COMMAND_SHIM_DIR


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


def test_detects_command_alias_conflict_with_active_skill(tmp_path: Path) -> None:
    active_skill_dir = tmp_path / "skills" / "web"
    active_skill_dir.mkdir(parents=True, exist_ok=True)
    (active_skill_dir / "SKILL.md").write_text("# Web")
    (active_skill_dir / "carapace.yaml").write_text("commands:\n  - name: web\n    command: uv run web\n")

    new_skill_dir = tmp_path / "skills" / "web-plus"
    new_skill_dir.mkdir(parents=True, exist_ok=True)
    (new_skill_dir / "SKILL.md").write_text("# Web Plus")
    (new_skill_dir / "carapace.yaml").write_text("commands:\n  - name: web\n    command: uv run web-plus\n")

    result = _skill_command_alias_conflict("web-plus", tmp_path, activated_skills=["web"])

    assert result == (
        "Cannot activate skill 'web-plus' because these command aliases conflict with active skills: "
        "'web' (already registered by 'web')."
    )


def test_resolves_exec_alias_and_auto_adds_context(tmp_path: Path) -> None:
    skill_dir = tmp_path / "skills" / "web"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text("# Web")
    (skill_dir / "carapace.yaml").write_text("commands:\n  - name: web\n    command: uv run web\n")

    command, contexts, warning = _resolve_exec_command_alias(
        "web search docs/skills.md",
        tmp_path,
        activated_skills=["web"],
        contexts=[],
    )

    assert command == f"{SKILL_COMMAND_SHIM_DIR}/web search docs/skills.md"
    assert contexts == ["web"]
    assert warning == (
        "Warning: Carapace added a skill context automatically because this command starts with the registered "
        "alias `web` from skill `web`. Include `contexts=['web']` next time."
    )


def test_resolves_exec_alias_without_warning_when_context_present(tmp_path: Path) -> None:
    skill_dir = tmp_path / "skills" / "web"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text("# Web")
    (skill_dir / "carapace.yaml").write_text("commands:\n  - name: web\n    command: uv run web\n")

    command, contexts, warning = _resolve_exec_command_alias(
        f"{SKILL_COMMAND_SHIM_DIR}/web search docs/skills.md",
        tmp_path,
        activated_skills=["web"],
        contexts=["web"],
    )

    assert command == f"{SKILL_COMMAND_SHIM_DIR}/web search docs/skills.md"
    assert contexts == ["web"]
    assert warning is None
