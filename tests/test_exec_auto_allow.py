from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from carapace.security import evaluate_with
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
