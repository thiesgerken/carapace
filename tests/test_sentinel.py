from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic_ai.models.test import TestModel

from carapace.security.context import SessionSecurity
from carapace.security.sentinel import Sentinel


def _make_sentinel(tmp_path: Path, *, timeout: timedelta = timedelta(seconds=60)) -> tuple[Sentinel, Path]:
    knowledge_dir = tmp_path / "knowledge"
    skills_dir = tmp_path / "skills"
    knowledge_dir.mkdir()
    skills_dir.mkdir()
    sentinel = Sentinel(
        model="test:model",
        knowledge_dir=knowledge_dir,
        skills_dir=skills_dir,
        timeout=timeout,
        model_factory=lambda _name: TestModel(),
    )
    return sentinel, skills_dir


def test_read_skill_file_cached_reuses_unchanged_content(tmp_path: Path) -> None:
    sentinel, skills_dir = _make_sentinel(tmp_path)
    skill_dir = skills_dir / "moneydb"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# MoneyDB\n")

    first = sentinel._read_skill_file_cached(skills_dir, "moneydb", "SKILL.md")
    second = sentinel._read_skill_file_cached(skills_dir, "moneydb", "SKILL.md")

    assert first == "# MoneyDB\n"
    assert "already provided earlier in this sentinel conversation" in second
    assert "SKILL.md" in second
    assert "moneydb" in second


def test_read_skill_file_cached_reloads_changed_file(tmp_path: Path) -> None:
    sentinel, skills_dir = _make_sentinel(tmp_path)
    skill_dir = skills_dir / "moneydb"
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text("version-1\n")

    assert sentinel._read_skill_file_cached(skills_dir, "moneydb", "SKILL.md") == "version-1\n"

    skill_file.write_text("version-2\n")

    assert sentinel._read_skill_file_cached(skills_dir, "moneydb", "SKILL.md") == "version-2\n"


def test_reset_clears_skill_file_cache(tmp_path: Path) -> None:
    sentinel, skills_dir = _make_sentinel(tmp_path)
    skill_dir = skills_dir / "moneydb"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# MoneyDB\n")

    sentinel._read_skill_file_cached(skills_dir, "moneydb", "SKILL.md")
    cached = sentinel._read_skill_file_cached(skills_dir, "moneydb", "SKILL.md")
    assert "already provided earlier in this sentinel conversation" in cached

    session = SessionSecurity("session-1")
    session.sentinel_eval_count = 1
    sentinel._reset(session)

    assert sentinel._read_skill_file_cached(skills_dir, "moneydb", "SKILL.md") == "# MoneyDB\n"


def test_eval_tool_logging_includes_context(tmp_path: Path, monkeypatch) -> None:
    sentinel, _skills_dir = _make_sentinel(tmp_path)
    messages: list[str] = []
    monkeypatch.setattr("carapace.security.sentinel.logger.info", messages.append)

    sentinel._begin_eval_logging("session-1", 7)
    tool_seq = sentinel._log_tool_call("read_skill_file", skill_name="moneydb", path="SKILL.md")
    sentinel._log_tool_result("read_skill_file", tool_seq, "cache_hit=true reuse_previous_result=true")

    assert messages == [
        "Sentinel tool call session=session-1 eval=7 step=1 tool=read_skill_file "
        + "args=skill_name='moneydb', path='SKILL.md'",
        "Sentinel tool result session=session-1 eval=7 step=1 tool=read_skill_file "
        + "summary=cache_hit=true reuse_previous_result=true",
    ]


@pytest.mark.asyncio
async def test_evaluate_tool_call_timeout_returns_deny_verdict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel, _skills_dir = _make_sentinel(tmp_path, timeout=timedelta(seconds=0.01))
    session = SessionSecurity("session-1")

    async def _hang(*_args, **_kwargs):
        await asyncio.sleep(1)

    monkeypatch.setattr(sentinel._agent, "run", _hang)

    verdict = await sentinel.evaluate_tool_call(session, "exec", {"command": "echo hi"})

    assert verdict.decision == "deny"
    assert verdict.risk_level == "high"
    assert verdict.explanation == (
        "Automatic sentinel review timed out after 0.01s. "
        "The tool call was blocked so the agent can decide whether to retry."
    )
    assert session.sentinel_eval_count == 1
