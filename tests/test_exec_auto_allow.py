from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from carapace.security import evaluate_domain_with, evaluate_with
from carapace.security.context import SentinelVerdict, SessionSecurity, ToolCallEntry
from carapace.security.sentinel import Sentinel


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("command", "expected_label"),
    [
        ("ls -la .", "ls"),
        ("cat README.md docs/quickstart.md", "cat"),
        ("grep -nF -- sentinel README.md", "grep"),
        ("rg -nF -- session src tests", "rg"),
        ("head -n 20 /workspace/README.md", "head"),
        ("tail -n 20 /workspace/README.md", "tail"),
        ("wc -l README.md", "wc"),
        ("file -b README.md", "file"),
    ],
)
async def test_exec_auto_allow_skips_sentinel_for_read_only_commands(
    tmp_path,
    command: str,
    expected_label: str,
) -> None:
    session = SessionSecurity("test-session", audit_dir=tmp_path)
    sentinel = MagicMock(spec=Sentinel)
    sentinel.evaluate_tool_call = AsyncMock(
        return_value=SentinelVerdict(decision="deny", explanation="should not be used")
    )
    callback_calls: list[tuple[str, dict[str, object], str, str | None, str | None, str | None]] = []

    await evaluate_with(
        session,
        sentinel,
        "exec",
        {"command": command},
        tool_call_callback=lambda tool, args, detail, source, verdict, explanation: callback_calls.append(
            (tool, args, detail, source, verdict, explanation)
        ),
    )

    sentinel.evaluate_tool_call.assert_not_awaited()
    entry = session.action_log[-1]
    assert isinstance(entry, ToolCallEntry)
    assert entry.tool == "exec"
    assert entry.decision == "auto_allowed"
    assert entry.explanation == f"Auto-allowed by read-only exec heuristic ({expected_label})."

    assert callback_calls == [
        (
            "exec",
            {"command": command},
            f"[safe-list] auto-allowed read-only exec heuristic ({expected_label})",
            "safe-list",
            "allow",
            f"Auto-allowed by read-only exec heuristic ({expected_label}).",
        )
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "command,args",
    [
        ("cat README.md && rm -f data.txt", {"command": "cat README.md && rm -f data.txt"}),
        ("grep sentinel README.md", {"command": "grep sentinel README.md"}),
        ("grep -nF -- #include src/main.c", {"command": "grep -nF -- #include src/main.c"}),
        ("cat ../secrets.env", {"command": "cat ../secrets.env"}),
        ("rg -nF --pre=python README.md", {"command": "rg -nF --pre=python README.md"}),
        ("grep -nF --color=always README.md", {"command": "grep -nF --color=always README.md"}),
        ("tail -f /workspace/app/server.log", {"command": "tail -f /workspace/app/server.log"}),
        ("grep -n -- -F README.md", {"command": "grep -n -- -F README.md"}),
        ("rg -nF -- token src", {"command": "rg -nF -- token src", "contexts": ["moneydb"]}),
    ],
)
async def test_exec_auto_allow_falls_back_to_sentinel_for_non_matching_commands(
    tmp_path,
    command: str,
    args: dict[str, object],
) -> None:
    session = SessionSecurity("test-session", audit_dir=tmp_path)
    sentinel = MagicMock(spec=Sentinel)
    sentinel.evaluate_tool_call = AsyncMock(
        return_value=SentinelVerdict(decision="allow", explanation="allowed by sentinel")
    )

    await evaluate_with(session, sentinel, "exec", args)

    sentinel.evaluate_tool_call.assert_awaited_once_with(
        session,
        "exec",
        args,
        usage_tracker=None,
        assert_llm_budget_available=None,
        usage_limits=None,
    )
    entry = session.action_log[-1]
    assert isinstance(entry, ToolCallEntry)
    assert entry.tool == "exec"
    assert entry.decision == "allowed"
    assert entry.explanation == "allowed by sentinel"


@pytest.mark.asyncio
async def test_allowed_tool_can_auto_approve_one_domain_for_same_tool_call(tmp_path) -> None:
    session = SessionSecurity("test-session", audit_dir=tmp_path, sentinel_domain_batch_window_ms=0)
    sentinel = MagicMock(spec=Sentinel)
    callback_calls: list[tuple[str, dict[str, object], str, str | None, str | None, str | None]] = []
    sentinel.evaluate_tool_call = AsyncMock(
        return_value=SentinelVerdict(
            decision="allow",
            explanation="curl target is clear",
            auto_approve_domain="https://google.de/search?q=test",
        )
    )
    sentinel.evaluate_domain_access = AsyncMock(
        side_effect=AssertionError("tool-call auto approval should skip single-domain sentinel review")
    )
    sentinel.evaluate_domain_access_batch = AsyncMock(
        side_effect=AssertionError("tool-call auto approval should skip batched sentinel review")
    )

    def record_tool_call(
        tool: str,
        args: dict[str, object],
        detail: str,
        source: str | None,
        verdict: str | None,
        explanation: str | None,
    ) -> None:
        callback_calls.append((tool, args, detail, source, verdict, explanation))
        session.current_parent_tool_id = "tool-1"

    await evaluate_with(
        session,
        sentinel,
        "exec",
        {"command": "curl https://google.de/search?q=test"},
        tool_call_callback=record_tool_call,
    )

    allowed = await evaluate_domain_with(session, sentinel, "google.de", "curl https://google.de/search?q=test")

    assert allowed is True
    sentinel.evaluate_tool_call.assert_awaited_once()
    sentinel.evaluate_domain_access.assert_not_awaited()
    sentinel.evaluate_domain_access_batch.assert_not_awaited()
    entry = session.action_log[-1]
    assert isinstance(entry, ToolCallEntry)
    assert entry.explanation == "curl target is clear Auto-approved domain for this tool call: google.de."
    assert callback_calls == [
        (
            "exec",
            {"command": "curl https://google.de/search?q=test"},
            "[sentinel: allow] curl target is clear Auto-approved domain for this tool call: google.de.",
            "sentinel",
            "allow",
            "curl target is clear Auto-approved domain for this tool call: google.de.",
        )
    ]


@pytest.mark.asyncio
async def test_auto_approved_domain_emits_log_line(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    session = SessionSecurity("test-session", audit_dir=tmp_path)
    sentinel = MagicMock(spec=Sentinel)
    sentinel.evaluate_tool_call = AsyncMock(
        return_value=SentinelVerdict(
            decision="allow",
            explanation="curl target is clear",
            auto_approve_domain="google.de",
        )
    )
    messages: list[str] = []
    monkeypatch.setattr("carapace.security.logger.info", messages.append)

    await evaluate_with(
        session,
        sentinel,
        "exec",
        {"command": "curl google.de"},
        verbose=False,
    )

    assert messages == ["Sentinel auto-approved domain for tool call tool=exec domain=google.de"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "auto_approve_domain",
    [
        "https://google.de/path with spaces",
        "*.google.de",
        "google",
        "google.de,example.com",
        "user@google.de",
    ],
)
async def test_invalid_auto_approved_domain_is_ignored(tmp_path, auto_approve_domain: str) -> None:
    session = SessionSecurity("test-session", audit_dir=tmp_path, sentinel_domain_batch_window_ms=0)
    sentinel = MagicMock(spec=Sentinel)
    sentinel.evaluate_tool_call = AsyncMock(
        return_value=SentinelVerdict(
            decision="allow",
            explanation="allowed by sentinel",
            auto_approve_domain=auto_approve_domain,
        )
    )
    sentinel.evaluate_domain_access_batch = AsyncMock(
        return_value=SentinelVerdict(decision="allow", explanation="needs normal proxy path")
    )

    def record_tool_call(
        tool: str,
        args: dict[str, object],
        detail: str,
        source: str | None,
        verdict: str | None,
        explanation: str | None,
    ) -> None:
        del tool, args, detail, source, verdict, explanation
        session.current_parent_tool_id = "tool-1"

    await evaluate_with(
        session,
        sentinel,
        "exec",
        {"command": "curl https://google.de"},
        tool_call_callback=record_tool_call,
    )

    allowed = await evaluate_domain_with(session, sentinel, "google.de", "curl https://google.de")

    assert allowed is True
    sentinel.evaluate_domain_access_batch.assert_awaited_once_with(
        session,
        {"google.de": "curl https://google.de"},
        usage_tracker=None,
        assert_llm_budget_available=None,
        usage_limits=None,
    )
