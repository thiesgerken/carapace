from __future__ import annotations

import asyncio

import pytest
from pydantic_ai.exceptions import UsageLimitExceeded

from carapace.security import evaluate_domain_with
from carapace.security.context import SentinelVerdict, SessionSecurity, UserEscalationDecision


class StubSentinel:
    def __init__(
        self,
        *,
        verdicts: list[SentinelVerdict] | None = None,
        batch_verdicts: list[SentinelVerdict] | None = None,
        single_side_effects: list[SentinelVerdict | Exception] | None = None,
        batch_side_effects: list[SentinelVerdict | Exception] | None = None,
        batch_blocker: asyncio.Event | None = None,
    ) -> None:
        self._single_side_effects = single_side_effects or list(verdicts or [])
        self._batch_side_effects = batch_side_effects or list(batch_verdicts or [])
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
        if len(self.calls) > len(self._single_side_effects):
            raise AssertionError("Unexpected extra sentinel domain review")
        effect = self._single_side_effects[len(self.calls) - 1]
        if isinstance(effect, Exception):
            raise effect
        return effect

    async def evaluate_domain_access_batch(
        self,
        session: SessionSecurity,
        domain_commands: dict[str, str],
        *,
        usage_tracker: object | None = None,
        assert_llm_budget_available: object | None = None,
        usage_limits: object | None = None,
    ) -> SentinelVerdict:
        del session, usage_tracker, assert_llm_budget_available, usage_limits
        self.batch_calls.append(dict(domain_commands))
        if self._batch_blocker is not None and len(self.batch_calls) == 1:
            await self._batch_blocker.wait()
        if len(self.batch_calls) > len(self._batch_side_effects):
            raise AssertionError("Unexpected extra batched sentinel domain review")
        effect = self._batch_side_effects[len(self.batch_calls) - 1]
        if isinstance(effect, Exception):
            raise effect
        return effect


@pytest.mark.anyio
async def test_duplicate_pending_domain_request_does_not_restart_debounce_generation() -> None:
    session = SessionSecurity("session-1", sentinel_domain_batch_window_ms=100)
    session.current_parent_tool_id = "tool-1"

    async def worker() -> None:
        return None

    await session.get_or_enqueue_domain_approval(
        "api.example.com",
        "curl https://api.example.com",
        lambda: asyncio.create_task(worker()),
    )
    first_generation = session._domain_scope_pending_generation

    await session.get_or_enqueue_domain_approval(
        "api.example.com",
        "curl https://api.example.com --retry 2",
        lambda: asyncio.create_task(worker()),
    )

    assert session._domain_scope_pending_generation == first_generation


@pytest.mark.anyio
async def test_reuses_sentinel_domain_approval_within_tool_call() -> None:
    session = SessionSecurity("session-1", sentinel_domain_batch_window_ms=0)
    session.current_parent_tool_id = "tool-1"
    sentinel = StubSentinel(batch_verdicts=[SentinelVerdict(decision="allow", explanation="looks fine")])

    first = await evaluate_domain_with(session, sentinel, "api.example.com", "curl https://api.example.com")
    second = await evaluate_domain_with(session, sentinel, "api.example.com", "curl https://api.example.com")

    assert first is True
    assert second is True
    assert sentinel.batch_calls == [{"api.example.com": "curl https://api.example.com"}]


@pytest.mark.anyio
async def test_reused_allowed_domain_reports_auto_source() -> None:
    session = SessionSecurity("session-1", sentinel_domain_batch_window_ms=0)
    session.current_parent_tool_id = "tool-1"
    domain_updates: list[tuple[str, str, str | None, str | None, str | None]] = []
    sentinel = StubSentinel(batch_verdicts=[SentinelVerdict(decision="allow", explanation="looks fine")])

    session.set_domain_info_callback(
        lambda domain, detail, source, verdict, explanation: domain_updates.append(
            (domain, detail, source, verdict, explanation)
        )
    )

    assert await evaluate_domain_with(session, sentinel, "api.example.com", "curl https://api.example.com") is True
    assert await evaluate_domain_with(session, sentinel, "api.example.com", "curl https://api.example.com") is True

    assert domain_updates[-1] == (
        "api.example.com",
        "[cached safe-list: allow] reused earlier decision",
        "safe-list",
        "allow",
        "looks fine",
    )


@pytest.mark.anyio
async def test_scope_change_before_enqueue_falls_back_to_single_domain_review() -> None:
    session = SessionSecurity("session-1", sentinel_domain_batch_window_ms=0)
    session.current_parent_tool_id = "tool-1"
    sentinel = StubSentinel(single_side_effects=[SentinelVerdict(decision="allow", explanation="fallback")])

    async def simulate_scope_change(
        domain: str,
        command: str,
        worker_factory: object,
    ) -> tuple[None, None, bool]:
        del domain, command, worker_factory
        session.current_parent_tool_id = None
        return None, None, False

    session.get_or_enqueue_domain_approval = simulate_scope_change  # type: ignore[method-assign]

    allowed = await evaluate_domain_with(session, sentinel, "api.example.com", "curl https://api.example.com")

    assert allowed is True
    assert sentinel.calls == [("api.example.com", "curl https://api.example.com")]
    assert sentinel.batch_calls == []


@pytest.mark.anyio
async def test_reuses_user_domain_approval_within_tool_call() -> None:
    session = SessionSecurity("session-1", sentinel_domain_batch_window_ms=0)
    session.current_parent_tool_id = "tool-1"
    user_calls: list[tuple[str, dict[str, object]]] = []

    async def approve(subject: str, context: dict[str, object]) -> UserEscalationDecision:
        user_calls.append((subject, context))
        return UserEscalationDecision(allowed=True, message="approved")

    session.set_user_escalation_callback(lambda _sid, subject, context: approve(subject, context))
    sentinel = StubSentinel(batch_verdicts=[SentinelVerdict(decision="escalate", explanation="needs confirmation")])

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
            SentinelVerdict(decision="allow", explanation="first batch"),
            SentinelVerdict(decision="allow", explanation="second batch"),
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
            SentinelVerdict(decision="allow", explanation="tool one"),
            SentinelVerdict(decision="allow", explanation="tool two"),
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
    sentinel = StubSentinel(batch_verdicts=[SentinelVerdict(decision="allow", explanation="shared")])

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
    sentinel = StubSentinel(batch_verdicts=[SentinelVerdict(decision="allow", explanation="batch allow")])

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
            SentinelVerdict(decision="allow", explanation="first wave"),
            SentinelVerdict(decision="allow", explanation="second wave"),
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


@pytest.mark.anyio
async def test_single_domain_usage_limit_falls_back_to_user_approval() -> None:
    session = SessionSecurity("session-1")
    user_calls: list[tuple[str, dict[str, object]]] = []

    async def approve(subject: str, context: dict[str, object]) -> UserEscalationDecision:
        user_calls.append((subject, context))
        return UserEscalationDecision(allowed=True)

    session.set_user_escalation_callback(lambda _sid, subject, context: approve(subject, context))
    sentinel = StubSentinel(
        single_side_effects=[UsageLimitExceeded("The next request would exceed the request_limit of 5")]
    )

    allowed = await evaluate_domain_with(session, sentinel, "solo.example.com", "curl https://solo.example.com")

    assert allowed is True
    assert user_calls == [
        (
            "solo.example.com",
            {
                "command": "curl https://solo.example.com",
                "explanation": (
                    "Automatic sentinel review hit its internal request limit and could not finish. "
                    + "Please approve or deny this domain manually."
                ),
                "kind": "domain_access",
            },
        )
    ]


@pytest.mark.anyio
async def test_pending_requests_fail_when_worker_errors() -> None:
    session = SessionSecurity("session-1", sentinel_domain_batch_window_ms=0)
    session.current_parent_tool_id = "tool-1"
    blocker = asyncio.Event()
    sentinel = StubSentinel(
        batch_side_effects=[RuntimeError("sentinel batch blew up")],
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
    await asyncio.sleep(0)
    blocker.set()

    first = await asyncio.gather(first_task, return_exceptions=True)
    second = await asyncio.gather(second_task, return_exceptions=True)

    assert isinstance(first[0], RuntimeError)
    assert str(first[0]) == "sentinel batch blew up"
    assert isinstance(second[0], RuntimeError)
    assert str(second[0]) == "sentinel batch blew up"


@pytest.mark.anyio
async def test_failed_batch_does_not_consume_review_budget() -> None:
    session = SessionSecurity("session-1", max_sentinel_calls_per_tool_call=1, sentinel_domain_batch_window_ms=0)
    session.current_parent_tool_id = "tool-1"
    user_calls: list[tuple[str, dict[str, object]]] = []
    sentinel = StubSentinel(
        batch_side_effects=[RuntimeError("sentinel batch blew up"), SentinelVerdict(decision="allow", explanation="ok")]
    )

    async def approve(subject: str, context: dict[str, object]) -> UserEscalationDecision:
        user_calls.append((subject, context))
        return UserEscalationDecision(allowed=True)

    session.set_user_escalation_callback(lambda _sid, subject, context: approve(subject, context))

    first = await asyncio.gather(
        evaluate_domain_with(session, sentinel, "a.example.com", "curl https://a.example.com"),
        return_exceptions=True,
    )
    second = await evaluate_domain_with(session, sentinel, "b.example.com", "curl https://b.example.com")

    assert isinstance(first[0], RuntimeError)
    assert str(first[0]) == "sentinel batch blew up"
    assert second is True
    assert sentinel.batch_calls == [
        {"a.example.com": "curl https://a.example.com"},
        {"b.example.com": "curl https://b.example.com"},
    ]
    assert user_calls == []
