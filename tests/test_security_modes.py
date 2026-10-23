from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from carapace.security import evaluate_push_with, evaluate_with
from carapace.security.context import GitPushEntry, SessionSecurity, ToolCallEntry
from carapace.security.sentinel import Sentinel


@pytest.mark.anyio
async def test_yolo_mode_bypasses_tool_sentinel_review(tmp_path) -> None:
    session = SessionSecurity("test-session", yolo_mode=True)
    sentinel = MagicMock(spec=Sentinel)
    sentinel.evaluate_tool_call = AsyncMock()

    await evaluate_with(session, sentinel, "use_skill", {"skill_name": "web"})

    sentinel.evaluate_tool_call.assert_not_awaited()
    entry = session.action_log[-1]
    assert isinstance(entry, ToolCallEntry)
    assert entry.decision == "allowed"
    assert entry.explanation == "YOLO mode bypassed sentinel."


@pytest.mark.anyio
async def test_ask_mode_denies_git_push_without_sentinel_review(tmp_path) -> None:
    session = SessionSecurity("test-session", ask_mode=True)
    sentinel = MagicMock(spec=Sentinel)
    sentinel.evaluate_push = AsyncMock()

    allowed = await evaluate_push_with(
        session,
        sentinel,
        "origin/main",
        True,
        "abc123 test commit",
        "diff --git a/README.md b/README.md",
        shared_artifacts=set(),
    )

    assert allowed is False
    sentinel.evaluate_push.assert_not_awaited()
    entry = session.action_log[-1]
    assert isinstance(entry, GitPushEntry)
    assert entry.decision == "denied"
    assert entry.explanation == "Ask mode blocks git push because it writes outside the sandbox."
