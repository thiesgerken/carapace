from __future__ import annotations

import asyncio

import pytest

from carapace.security import evaluate_domain_with
from carapace.security.context import SentinelVerdict, SessionSecurity, UserEscalationDecision


class StubSentinel:
    def __init__(
        self,
        *,
        verdicts: list[SentinelVerdict] | None = None,
        batch_verdicts: list[dict[str, SentinelVerdict]] | None = None,
        batch_blocker: asyncio.Event | None = None,
    ) -> None:
        self._verdicts = verdicts or []
        self._batch_verdicts = batch_verdicts or []
        self._batch_blocker = batch_blocker
        self.calls: list[tuple[str, str]] = []
        self.batch_calls: list[dict[str, str]] = []

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

    async def evaluate_domain_access_batch(
        self,
        session: SessionSecurity,
        domain_commands: dict[str, str],
        *,
        usage_tracker: object | None = None,
        assert_llm_budget_available: object | None = None,
        usage_limits: object | None = None,
    ) -> dict[str, SentinelVerdict]:
        del session, usage_tracker, assert_llm_budget_available, usage_limits
        self.batch_calls.append(dict(domain_commands))
        if self._batch_blocker is not None and len(self.batch_calls) == 1:
            await self._batch_blocker.wait()
        if len(self.batch_calls) > len(self._batch_verdicts):
            raise AssertionError("Unexpected extra batched sentinel domain review")
        return self._batch_verdicts[len(self.batch_calls) - 1]


@pytest.mark.anyio
async def test_reuses_sentinel_domain_approval_within_tool_call() -> None:
    session = SessionSecurity("session-1", sentinel_domain_batch_window_ms=0)
    session.current_parent_tool_id = "tool-1"
    sentinel = StubSentinel(
        batch_verdicts=[{"api.example.com": SentinelVerdict(decision="allow", explanation="looks fine")}]
    )

    first = await evaluate_domain_with(session, sentinel, "api.example.com", "curl https://api.example.com")
    second = await evaluate_domain_with(session, sentinel, "api.example.com", "curl https://api.example.com")

    assert first is True
    assert second is True
    assert sentinel.batch_calls == [{"api.example.com": "curl https://api.example.com"}]


@pytest.mark.anyio
async def test_reuses_user_domain_approval_within_tool_call() -> None:
    session = SessionSecurity("session-1", sentinel_domain_batch_window_ms=0)
    session.current_parent_tool_id = "tool-1"
    user_calls: list[tuple[str, dict[str, object]]] = []

    async def approve(subject: str, context: dict[str, object]) -> UserEscalationDecision:
        user_calls.append((subject, context))
        return UserEscalationDecision(allowed=True, message="approved")

    session.set_user_escalation_callback(lambda _sid, subject, context: approve(subject, context))
    sentinel = StubSentinel(
        batch_verdicts=[{"api.example.com": SentinelVerdict(decision="escalate", explanation="needs confirmation")}]
    )

    first = await evaluate_domain_with(session, sentinel, "api.example.com", "curl https://api.example.com")
    second = await evaluate_domain_with(session, sentinel, "api.example.com", "curl https://api.example.com")

    assert first is True
    assert second is True
    assert len(sentinel.batch_calls) == 1
    assert len(user_calls) == 1


@pytest.mark.anyio
async def test_domain_review_limit_falls_back_to_user_approval() -> None:
    session = SessionSecurity("session-1", max_sentinel_calls_per_tool_call=2, sentinel_domain_batch_window_ms=0)
    session.current_parent_tool_id = "tool-1"
    user_calls: list[tuple[str, dict[str, object]]] = []

    async def approve(subject: str, context: dict[str, object]) -> UserEscalationDecision:
        user_calls.append((subject, context))
        return UserEscalationDecision(allowed=True)

    session.set_user_escalation_callback(lambda _sid, subject, context: approve(subject, context))
    sentinel = StubSentinel(
        batch_verdicts=[
            {"a.example.com": SentinelVerdict(decision="allow", explanation="first")},
            {"b.example.com": SentinelVerdict(decision="allow", explanation="second")},
        ]
    )

    assert await evaluate_domain_with(session, sentinel, "a.example.com", "curl https://a.example.com") is True
    assert await evaluate_domain_with(session, sentinel, "b.example.com", "curl https://b.example.com") is True
    assert await evaluate_domain_with(session, sentinel, "c.example.com", "curl https://c.example.com") is True

    assert sentinel.batch_calls == [
        {"a.example.com": "curl https://a.example.com"},
        {"b.example.com": "curl https://b.example.com"},
    ]
    assert len(user_calls) == 1
    assert user_calls[0][0] == "c.example.com"
    assert "limit" in str(user_calls[0][1]["explanation"])


@pytest.mark.anyio
async def test_domain_approval_cache_resets_for_new_tool_call() -> None:
    session = SessionSecurity("session-1", sentinel_domain_batch_window_ms=0)
    sentinel = StubSentinel(
        batch_verdicts=[
            {"api.example.com": SentinelVerdict(decision="allow", explanation="tool one")},
            {"api.example.com": SentinelVerdict(decision="allow", explanation="tool two")},
        ]
    )

    session.current_parent_tool_id = "tool-1"
    assert await evaluate_domain_with(session, sentinel, "api.example.com", "curl https://api.example.com") is True

    session.current_parent_tool_id = "tool-2"
    assert await evaluate_domain_with(session, sentinel, "api.example.com", "curl https://api.example.com") is True

    assert len(sentinel.batch_calls) == 2


@pytest.mark.anyio
async def test_parallel_same_domain_requests_share_one_batch() -> None:
    session = SessionSecurity("session-1", sentinel_domain_batch_window_ms=10)
    session.current_parent_tool_id = "tool-1"
    sentinel = StubSentinel(
        batch_verdicts=[{"api.example.com": SentinelVerdict(decision="allow", explanation="shared")}]
    )

    first, second = await asyncio.gather(
        evaluate_domain_with(session, sentinel, "api.example.com", "curl https://api.example.com"),
        evaluate_domain_with(session, sentinel, "api.example.com", "curl https://api.example.com"),
    )

    assert first is True
    assert second is True
    assert sentinel.batch_calls == [{"api.example.com": "curl https://api.example.com"}]


@pytest.mark.anyio
async def test_parallel_distinct_domains_share_one_batch() -> None:
    session = SessionSecurity("session-1", sentinel_domain_batch_window_ms=10)
    session.current_parent_tool_id = "tool-1"
    sentinel = StubSentinel(
        batch_verdicts=[
            {
                "a.example.com": SentinelVerdict(decision="allow", explanation="a"),
                "b.example.com": SentinelVerdict(decision="allow", explanation="b"),
                "c.example.com": SentinelVerdict(decision="allow", explanation="c"),
            }
        ]
    )

    results = await asyncio.gather(
        evaluate_domain_with(session, sentinel, "a.example.com", "curl https://a.example.com"),
        evaluate_domain_with(session, sentinel, "b.example.com", "curl https://b.example.com"),
        evaluate_domain_with(session, sentinel, "c.example.com", "curl https://c.example.com"),
    )

    assert results == [True, True, True]
    assert list(sorted(sentinel.batch_calls[0])) == ["a.example.com", "b.example.com", "c.example.com"]


@pytest.mark.anyio
async def test_new_domain_wave_after_submission_forms_second_batch() -> None:
    session = SessionSecurity("session-1", sentinel_domain_batch_window_ms=0)
    session.current_parent_tool_id = "tool-1"
    blocker = asyncio.Event()
    sentinel = StubSentinel(
        batch_verdicts=[
            {"a.example.com": SentinelVerdict(decision="allow", explanation="first wave")},
            {"b.example.com": SentinelVerdict(decision="allow", explanation="second wave")},
        ],
        batch_blocker=blocker,
    )

    first_task = asyncio.create_task(
        evaluate_domain_with(session, sentinel, "a.example.com", "curl https://a.example.com")
    )
    for _ in range(50):
        if sentinel.batch_calls:
            break
        await asyncio.sleep(0)

    second_task = asyncio.create_task(
        evaluate_domain_with(session, sentinel, "b.example.com", "curl https://b.example.com")
    )
    blocker.set()

    first, second = await asyncio.gather(first_task, second_task)

    assert first is True
    assert second is True
    assert sentinel.batch_calls == [
        {"a.example.com": "curl https://a.example.com"},
        {"b.example.com": "curl https://b.example.com"},
    ]
