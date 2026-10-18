from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from carapace import prompt_preview
from carapace.git.store import GitStore
from carapace.knowledge import KnowledgeRepoHandle
from carapace.memory.prompt_block import MemoryBlock
from carapace.models.config import Config
from carapace.models.user import UserConfig
from carapace.prompt_preview import PreviewInputs, PromptDriftError, PromptPreview, PromptRole, preview_prompt
from carapace.sandbox.manager import SandboxManager
from carapace.skills import SkillRegistry

MEMORY = MemoryBlock(
    text="# Memory\n\n<memory>\n## Session s1 (week 2026-W41)\nAbstract: Upgraded.\n</memory>", tokens=42
)


def preview(role: PromptRole, tmp_path: Path) -> PromptPreview:
    (tmp_path / "USER.md").write_text("The user is Thies.")
    (tmp_path / "SECURITY.md").write_text("Never push to main.")
    inputs = PreviewInputs(
        config=Config(),
        user="thies",
        user_config=UserConfig(),
        data_dir=tmp_path,
        repo=KnowledgeRepoHandle(
            owner="thies",
            knowledge_dir=tmp_path,
            git_store=MagicMock(spec=GitStore),
            skill_registry=SkillRegistry(tmp_path / "skills"),
        ),
        sandbox=MagicMock(spec=SandboxManager),
        memory_block=lambda _user, _session_id: MEMORY,
        now=datetime(2026, 10, 9, 12, 0, tzinfo=UTC),
    )
    return asyncio.run(preview_prompt(role, inputs))


def keys(result: PromptPreview) -> list[str]:
    return [section.key for section in result.sections]


def tool_names(result: PromptPreview) -> str:
    return next(section.text for section in result.sections if section.key == "tools")


@pytest.mark.parametrize("role", list(PromptRole))
def test_every_role_previews_its_real_prompt(role: PromptRole, tmp_path: Path) -> None:
    result = preview(role, tmp_path)

    assert result.role is role
    assert result.model
    assert result.total_tokens == sum(section.tokens for section in result.sections) > 0
    assert all(section.tokens == 0 or section.text for section in result.sections)
    if role is not PromptRole.agent:
        assert result.memory_budget_tokens is None and result.memory_used_tokens is None


def test_agent_previews_a_fresh_session_with_its_memory_block(tmp_path: Path) -> None:
    result = preview(PromptRole.agent, tmp_path)

    assert keys(result) == ["tools", "shared_prefix", "role_instructions", "memory", "volatile"]
    assert result.cacheable_until == 3  # tools, prefix and instructions and memory are cached, session info is not
    memory = result.sections[3]
    assert memory.text == MEMORY.text
    assert memory.title == "Memory"
    assert (result.memory_budget_tokens, result.memory_used_tokens) == (4000, 42)
    assert "The user is Thies." in result.sections[1].text
    assert '"name": "exec"' in tool_names(result)
    assert "Session ID: prompt-preview" in result.sections[4].text


@pytest.mark.parametrize("role", [PromptRole.agent, PromptRole.compaction, PromptRole.session_extract])
def test_disabled_skill_is_excluded_from_prompt_preview(role: PromptRole, tmp_path: Path) -> None:
    directory = tmp_path / "skills" / "private-search"
    directory.mkdir(parents=True)
    skill_md = directory / "SKILL.md"
    text = (
        "---\nname: private-search\ndescription: Unique private coverage\n"
        "metadata:\n  carapace:\n    disabled: true\n---\nInstructions.\n"
    )
    skill_md.write_text(text)

    assert "Unique private coverage" not in "\n".join(section.text for section in preview(role, tmp_path).sections)

    skill_md.write_text(text.replace("disabled: true", "disabled: false"))

    assert "Unique private coverage" in "\n".join(section.text for section in preview(role, tmp_path).sections)


def test_sentinel_and_titler_set_no_cache_breakpoint(tmp_path: Path) -> None:
    sentinel = preview(PromptRole.sentinel, tmp_path)
    titler = preview(PromptRole.titler, tmp_path)

    assert keys(sentinel) == ["tools", "role_instructions", "security_md"]
    assert sentinel.sections[2].text == "Never push to main."
    assert '"name": "judge"' in tool_names(sentinel)
    assert keys(titler) == ["role_instructions"]
    assert sentinel.cacheable_until is None and titler.cacheable_until is None


@pytest.mark.parametrize("role", [PromptRole.session_extract, PromptRole.week_digest, PromptRole.month_digest])
def test_memory_tasks_cache_their_system_prompt_and_label_placeholder_material(
    role: PromptRole, tmp_path: Path
) -> None:
    result = preview(role, tmp_path)

    assert keys(result) == ["tools", "shared_prefix", "role_instructions", "user_prompt"]
    assert result.cacheable_until == 2
    assert '"name": "final_result"' in tool_names(result)
    user_prompt = result.sections[3]
    assert "placeholder" in user_prompt.title
    assert "[Placeholder material for the preview." in user_prompt.text


def test_compaction_caches_prefix_and_instructions(tmp_path: Path) -> None:
    result = preview(PromptRole.compaction, tmp_path)

    assert keys(result) == ["shared_prefix", "role_instructions"]
    assert result.cacheable_until == 1


def test_a_section_that_drifted_from_the_real_prompt_fails_loudly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(prompt_preview, "agent_instructions", lambda: "# Instructions the agent never gets")

    with pytest.raises(PromptDriftError):
        preview(PromptRole.agent, tmp_path)
