from __future__ import annotations

import pytest

from carapace.security import evaluate_domain_with
from carapace.security.context import SentinelVerdict, SessionSecurity, UserEscalationDecision


class StubSentinel:
    def __init__(self, verdicts: list[SentinelVerdict]) -> None:
        self._verdicts = verdicts
        self.calls: list[tuple[str, str]] = []

    async def evaluate_domain_access(
        self,
        session: SessionSecurity,
        domain: str,
        command: str,
        *,
        usage_tracker: object | None = None,
        assert_llm_budget_available: object | None = None,
        usage_limits: object | None = None,
    ) -> SentinelVerdict:
        del session, usage_tracker, assert_llm_budget_available, usage_limits
        self.calls.append((domain, command))
        if len(self.calls) > len(self._verdicts):
            raise AssertionError("Unexpected extra sentinel domain review")
        return self._verdicts[len(self.calls) - 1]


@pytest.mark.anyio
async def test_reuses_sentinel_domain_approval_within_tool_call() -> None:
    session = SessionSecurity("session-1")
    session.current_parent_tool_id = "tool-1"
    sentinel = StubSentinel([SentinelVerdict(decision="allow", explanation="looks fine")])

    first = await evaluate_domain_with(session, sentinel, "api.example.com", "curl https://api.example.com")
    second = await evaluate_domain_with(session, sentinel, "api.example.com", "curl https://api.example.com")

    assert first is True
    assert second is True
    assert sentinel.calls == [("api.example.com", "curl https://api.example.com")]


@pytest.mark.anyio
async def test_reuses_user_domain_approval_within_tool_call() -> None:
    session = SessionSecurity("session-1")
    session.current_parent_tool_id = "tool-1"
    user_calls: list[tuple[str, dict[str, object]]] = []

    async def approve(subject: str, context: dict[str, object]) -> UserEscalationDecision:
        user_calls.append((subject, context))
        return UserEscalationDecision(allowed=True, message="approved")

    session.set_user_escalation_callback(lambda _sid, subject, context: approve(subject, context))
    sentinel = StubSentinel([SentinelVerdict(decision="escalate", explanation="needs confirmation")])

    first = await evaluate_domain_with(session, sentinel, "api.example.com", "curl https://api.example.com")
    second = await evaluate_domain_with(session, sentinel, "api.example.com", "curl https://api.example.com")

    assert first is True
    assert second is True
    assert len(sentinel.calls) == 1
    assert len(user_calls) == 1


@pytest.mark.anyio
async def test_domain_review_limit_falls_back_to_user_approval() -> None:
    session = SessionSecurity("session-1", max_sentinel_calls_per_tool_call=2)
    session.current_parent_tool_id = "tool-1"
    user_calls: list[tuple[str, dict[str, object]]] = []

    async def approve(subject: str, context: dict[str, object]) -> UserEscalationDecision:
        user_calls.append((subject, context))
        return UserEscalationDecision(allowed=True)

    session.set_user_escalation_callback(lambda _sid, subject, context: approve(subject, context))
    sentinel = StubSentinel(
        [
            SentinelVerdict(decision="allow", explanation="first"),
            SentinelVerdict(decision="allow", explanation="second"),
        ]
    )

    assert await evaluate_domain_with(session, sentinel, "a.example.com", "curl https://a.example.com") is True
    assert await evaluate_domain_with(session, sentinel, "b.example.com", "curl https://b.example.com") is True
    assert await evaluate_domain_with(session, sentinel, "c.example.com", "curl https://c.example.com") is True

    assert [domain for domain, _command in sentinel.calls] == ["a.example.com", "b.example.com"]
    assert len(user_calls) == 1
    assert user_calls[0][0] == "c.example.com"
    assert "limit" in str(user_calls[0][1]["explanation"])


@pytest.mark.anyio
async def test_domain_approval_cache_resets_for_new_tool_call() -> None:
    session = SessionSecurity("session-1")
    sentinel = StubSentinel(
        [
            SentinelVerdict(decision="allow", explanation="tool one"),
            SentinelVerdict(decision="allow", explanation="tool two"),
        ]
    )

    session.current_parent_tool_id = "tool-1"
    assert await evaluate_domain_with(session, sentinel, "api.example.com", "curl https://api.example.com") is True

    session.current_parent_tool_id = "tool-2"
    assert await evaluate_domain_with(session, sentinel, "api.example.com", "curl https://api.example.com") is True

    assert len(sentinel.calls) == 2
