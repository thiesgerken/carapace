from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic_ai.models.test import TestModel

from carapace.security.context import AgentResponseEntry, ApprovalEntry, SentinelVerdict, SessionSecurity, ToolCallEntry
from carapace.security.sentinel import Sentinel, _format_entry
from tests.fake_skill_builds import FakeSkillBuilds, fake_skill_builds


def _make_sentinel(tmp_path: Path, *, timeout: timedelta | None = None) -> tuple[Sentinel, FakeSkillBuilds]:
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    skill_builds, fake = fake_skill_builds("moneydb", {"SKILL.md": "# MoneyDB\n"})
    sentinel = Sentinel(
        model="test:model",
        user="thies",
        knowledge_dir=knowledge_dir,
        skill_builds=skill_builds,
        llm_slots=None,
        timeout=timeout,
        model_factory=lambda _name, *, user: TestModel(),
    )
    return sentinel, fake


@pytest.mark.asyncio
async def test_read_skill_file_cached_reuses_unchanged_content(tmp_path: Path) -> None:
    sentinel, _builds = _make_sentinel(tmp_path)

    first = await sentinel._read_skill_file_cached("moneydb", "SKILL.md")
    second = await sentinel._read_skill_file_cached("moneydb", "SKILL.md")

    assert first == "# MoneyDB\n"
    assert "already provided earlier in this sentinel conversation" in second
    assert "SKILL.md" in second
    assert "moneydb" in second


@pytest.mark.asyncio
async def test_read_skill_file_cached_reloads_changed_file(tmp_path: Path) -> None:
    sentinel, builds = _make_sentinel(tmp_path)

    assert await sentinel._read_skill_file_cached("moneydb", "SKILL.md") == "# MoneyDB\n"

    builds.change("SKILL.md", "version-2\n")

    assert await sentinel._read_skill_file_cached("moneydb", "SKILL.md") == "version-2\n"


@pytest.mark.asyncio
async def test_skill_files_come_from_the_build(tmp_path: Path) -> None:
    sentinel, builds = _make_sentinel(tmp_path)
    builds.change("scripts/run.sh", "echo hi\n")

    assert await sentinel._read_skill_file_cached("moneydb", "scripts/run.sh") == "echo hi\n"
    assert await sentinel._read_skill_file_cached("moneydb", "missing.md") == "File not found: missing.md"
    assert await sentinel._read_skill_file_cached("other", "SKILL.md") == "Skill 'other' not found."


@pytest.mark.asyncio
async def test_set_policy_preserves_skill_cache(tmp_path: Path) -> None:
    sentinel, _builds = _make_sentinel(tmp_path)

    await sentinel._read_skill_file_cached("moneydb", "SKILL.md")

    sentinel.set_policy(ask_mode=True)

    cached = await sentinel._read_skill_file_cached("moneydb", "SKILL.md")
    assert "already provided earlier in this sentinel conversation" in cached


def test_eval_tool_logging_includes_context(tmp_path: Path, monkeypatch) -> None:
    sentinel, _builds = _make_sentinel(tmp_path)
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
async def test_evaluation_timeout_returns_deny_verdict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel, _builds = _make_sentinel(tmp_path, timeout=timedelta(seconds=0.01))
    session = SessionSecurity("session-1")

    async def _hang(*_args, **_kwargs):
        # A skill read inside the evaluation that then times out.
        await sentinel._read_skill_file_cached("moneydb", "SKILL.md")
        await asyncio.sleep(1)

    monkeypatch.setattr(sentinel._agent, "run", _hang)

    verdict = await sentinel.evaluate_domain_access(session, ["example.com"], "echo hi", follow_up=False)

    assert verdict.decision == "deny"
    assert verdict.risk_level == "high"
    assert verdict.explanation == (
        "Automatic sentinel review timed out after 0.01s. "
        "The request was blocked so the agent can decide whether to retry."
    )
    assert session.sentinel_eval_count == 1
    assert session.sentinel_messages == []
    assert await sentinel._read_skill_file_cached("moneydb", "SKILL.md") == "# MoneyDB\n"


@pytest.mark.parametrize(
    ("diff", "touches_artifacts"),
    [
        ("--- /dev/null\n+++ b/artifacts/report/index.html\n+report", True),
        ("--- a/artifacts/report/index.html\n+++ /dev/null\n-report", True),
        ("diff --git a/artifacts/report/chart.png b/artifacts/report/chart.png\nBinary files differ", True),
        ('diff --git "a/artifacts/quarterly report/chart.png" "b/artifacts/quarterly report/chart.png"', True),
        ("diff --git a/notes/report.html b/artifacts/report/index.html\nrename to artifacts/report/index.html", True),
        ("x" * 9000 + "\n--- a/artifacts/report/index.html\n+++ /dev/null", True),
        ("--- a/notes/report.md\n+++ b/notes/report.md\n+artifacts/report/index.html", False),
        ("--- a/notes/artifacts/index.html\n+++ b/notes/artifacts/index.html", False),
    ],
)
async def test_push_context_warns_only_for_touched_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, diff: str, touches_artifacts: bool
) -> None:
    sentinel, _builds = _make_sentinel(tmp_path)
    prompts: list[str] = []

    async def capture(_session: SessionSecurity, prompt: str, **_kwargs: object) -> SentinelVerdict:
        prompts.append(prompt)
        return SentinelVerdict(decision="allow", explanation="ok", risk_level="low")

    monkeypatch.setattr(sentinel, "_run_evaluation", capture)
    await sentinel.evaluate_push(
        SessionSecurity("session-1"),
        "refs/heads/main",
        True,
        "Update report",
        diff,
        shared_artifacts=set(),
        flake_input_changes=[],
    )
    assert ("Artifact security notice:" in prompts[0]) is touches_artifacts
    if touches_artifacts:
        assert "outside the sandbox egress proxy" in prompts[0]
        assert "private data as exfiltration" in prompts[0]
        assert "does not prevent self-navigation" in prompts[0]


@pytest.mark.parametrize(
    ("diff", "shared", "is_public"),
    [
        ("--- /dev/null\n+++ b/artifacts/report/index.html", {"report"}, True),
        ("--- a/artifacts/report/index.html\n+++ /dev/null", {"report"}, True),
        ("rename from artifacts/report/index.html\nrename to notes/report.html", {"report"}, True),
        ("--- a/artifacts/report/index.html\n+++ b/artifacts/report/index.html", set(), False),
        ("--- a/artifacts/private/index.html\n+++ b/artifacts/private/index.html", {"report"}, False),
        ("--- a/artifacts/reporting/index.html\n+++ b/artifacts/reporting/index.html", {"report"}, False),
        ("--- a/notes/report.html\n+++ b/notes/report.html", {"report"}, False),
    ],
)
async def test_push_context_marks_only_touched_shared_artifacts_as_publications(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, diff: str, shared: set[str], is_public: bool
) -> None:
    sentinel, _builds = _make_sentinel(tmp_path)
    prompts: list[str] = []

    async def capture(_session: SessionSecurity, prompt: str, **_kwargs: object) -> SentinelVerdict:
        prompts.append(prompt)
        return SentinelVerdict(decision="allow", explanation="ok", risk_level="low")

    monkeypatch.setattr(sentinel, "_run_evaluation", capture)
    await sentinel.evaluate_push(
        SessionSecurity("session-1"),
        "refs/heads/main",
        True,
        "Update report",
        diff,
        shared_artifacts=shared,
        flake_input_changes=[],
    )
    assert ("Publicly shared artifacts touched: report." in prompts[0]) is is_public
    assert ("this push is a publication." in prompts[0]) is is_public


def test_user_decision_entry_names_the_approved_command() -> None:
    line = _format_entry(ApprovalEntry(tool="exec", args={"command": "git push"}, decision="approved"))

    assert line == "[user_decision]: user approved exec(command='git push')"


def test_agent_messages_reach_the_sentinel_in_full() -> None:
    text = "I found two bugs:\n1. the query\n2. the docs\nShall I fix both?"

    assert _format_entry(AgentResponseEntry(text=text)) == f"[agent]: {text!r}"


def test_history_shows_tool_call_args_in_full() -> None:
    command = "git -C /workspace/knowledge commit -am 'fix moneta query' && git push && " + "echo done " * 20

    line = _format_entry(ToolCallEntry(tool="exec", args={"command": command}, decision="allowed"))

    assert line == f"[tool]: exec(command={command!r}) → allowed"
