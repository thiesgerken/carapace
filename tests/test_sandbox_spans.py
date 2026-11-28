"""Sandbox spans: startup steps, exec and file calls, and the proxy's domain checks."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai import RunContext
from pydantic_ai.models import Model
from pydantic_ai.usage import RunUsage

from carapace.agent.autonomy import AutonomyStreak
from carapace.agent.deps import Deps
from carapace.agent.tools import create_agent
from carapace.builder.skill_builds import SkillBuilds
from carapace.builder.skill_updates import no_fetch_credentials
from carapace.credentials import CredentialRegistry
from carapace.git.store import GitStore
from carapace.knowledge import KnowledgeRepoHandle
from carapace.models.config import Config
from carapace.models.session import SessionState
from carapace.sandbox.exec_flow import SandboxExecCoordinator, SandboxExecState
from carapace.sandbox.manager import SandboxManager
from carapace.sandbox.proxy import ProxyServer
from carapace.sandbox.runtime import ExecResult
from carapace.sandbox.skill_profile import SkillProfileSync
from carapace.security.context import BoundaryEvaluation, SessionSecurity
from carapace.session.manager import SessionManager, SessionMeta
from carapace.span_names import EXEC_LOCK_WAIT_SPAN
from carapace.spans import Span, TurnTrace, attach, attach_sandbox_call, current_span_ref, span
from carapace.usage import UsageTracker
from carapace.ws_models import EscalationResponse
from tests.runtime_mocks import make_runtime_mock
from tests.session_helpers import _make_engine, _patch_sentinel


def _trace() -> tuple[TurnTrace, Span]:
    trace = TurnTrace("t1", on_change=lambda _span: None)
    return trace, trace.start("turn", "turn", parent_id=None, attrs={})


def _by_name(trace: TurnTrace) -> dict[str, Span]:
    return {s.name: s for s in trace.spans.values()}


def test_a_sandbox_call_nests_under_the_newest_running_exec_or_file_span() -> None:
    trace, root = _trace()
    done = trace.start("exec", "done", parent_id=root.span_id, attrs={})
    trace.end(done, "ok")
    write = trace.start("file", "write", parent_id=root.span_id, attrs={})
    trace.start("sandbox", "ensure", parent_id=write.span_id, attrs={})
    newest = trace.start("exec", "exec", parent_id=root.span_id, attrs={})

    assert trace.sandbox_call_parent() == newest.span_id
    trace.end(newest, "ok")
    assert trace.sandbox_call_parent() == write.span_id
    trace.end(write, "ok")
    assert trace.sandbox_call_parent() == root.span_id


def test_a_sandbox_call_outside_a_turn_records_nothing() -> None:
    with attach_sandbox_call(None), span("domain", "pypi.org") as check:
        assert current_span_ref() is None
    assert check.parent_id is None


@pytest.mark.asyncio
async def test_the_proxys_domain_check_nests_under_the_exec_that_made_it() -> None:
    trace, root = _trace()
    exec_span = trace.start("exec", "exec", parent_id=root.span_id, attrs={})
    proxy = ProxyServer(
        verify_session_token=lambda _sid, _tok: True,
        get_allowed_domains=lambda _sid: {"pypi.org"},
        attach_sandbox_call=lambda _sid: attach_sandbox_call(trace),
    )

    assert (await proxy._authorize_domain("s1", "pypi.org")).allowed
    assert not (await proxy._authorize_domain("s1", "evil.example")).allowed

    checks = {s.name: s for s in trace.spans.values() if s.kind == "domain"}
    assert checks["pypi.org"].parent_id == exec_span.span_id
    assert checks["pypi.org"].attrs == {"domain": "pypi.org", "allowed": True}
    assert checks["evil.example"].attrs["allowed"] is False
    assert {s.status for s in checks.values()} == {"ok"}


def test_a_domain_decision_waiting_on_the_user_is_a_wait_inside_the_domain_check(tmp_path: Path, db_factory) -> None:
    async def _run() -> None:
        engine = _make_engine(tmp_path, session_factory=db_factory)
        sid = engine.session_mgr.create_session(user="thies").session_id
        active = engine.get_or_activate(sid)
        trace, root = _trace()
        exec_span = trace.start("exec", "exec", parent_id=root.span_id, attrs={})
        active.turn_trace = trace
        escalate = engine._make_escalation_cb(active)

        async def _ask_user(session_id: str, domain: str) -> BoundaryEvaluation:
            decision = await escalate(session_id, domain, {"kind": "domain_access", "command": "curl"})
            return BoundaryEvaluation(allowed=decision.allowed, rejection="")

        proxy = ProxyServer(
            verify_session_token=lambda _sid, _tok: True,
            get_allowed_domains=lambda _sid: set(),
            attach_sandbox_call=engine.attach_sandbox_call,
            request_approval=_ask_user,
        )
        # Like the proxy's connection handler: its own task, outside the turn's context.
        check = asyncio.create_task(proxy._authorize_domain(sid, "pypi.org"))
        await asyncio.sleep(0.01)
        (pending,) = active.pending_escalations
        await engine.submit_approval(sid, EscalationResponse(request_id=pending["request_id"], decision="allow"))
        assert (await asyncio.wait_for(check, timeout=1)).allowed

        domain = next(s for s in trace.spans.values() if s.kind == "domain")
        wait = next(s for s in trace.spans.values() if s.kind == "wait")
        assert (domain.parent_id, domain.attrs) == (exec_span.span_id, {"domain": "pypi.org", "allowed": True})
        assert (wait.parent_id, wait.name, wait.attrs) == (domain.span_id, "pypi.org", {"reason": "domain"})

    with _patch_sentinel():
        asyncio.run(_run())


def _deps(tmp_path: Path, sandbox: SandboxManager) -> Deps:
    return Deps(
        skill_builds=SkillBuilds(None, no_fetch_credentials),
        config=Config.model_validate({}),
        data_dir=tmp_path,
        knowledge_dir=tmp_path,
        session_state=SessionState.now(session_id="s1", unattended=False),
        sandbox=sandbox,
        security=SessionSecurity("s1", unattended=False),
        git_store=MagicMock(spec=GitStore),
        agent_model=MagicMock(spec=Model),
        agent_model_id="anthropic:claude-sonnet-4-6",
        usage_tracker=UsageTracker(),
        autonomy=AutonomyStreak(),
        credential_registry=CredentialRegistry(),
        load_session_events=list,
    )


@pytest.mark.asyncio
async def test_exec_tool_records_its_command_and_exit_code(tmp_path: Path) -> None:
    sandbox = MagicMock(spec=SandboxManager)
    sandbox.exec_command = AsyncMock(return_value=ExecResult(stdout="", exit_code=3, output="nope"))
    deps = _deps(tmp_path, sandbox)
    tool = create_agent(deps)._function_toolset.tools["exec"]
    ctx = RunContext(deps=deps, model=MagicMock(spec=Model), usage=RunUsage(), tool_call_approved=True)
    trace, root = _trace()

    with attach(trace, root.span_id):
        await tool.function(ctx, command="x" * 300)

    [call] = [s for s in trace.spans.values() if s.kind == "exec"]
    assert call.parent_id == root.span_id
    assert call.attrs == {"command": "x" * 200, "exit_code": 3}


def _manager(tmp_path: Path, db_factory) -> SandboxManager:
    SessionManager(db_factory, tmp_path).save_meta("s1", SessionMeta(user="thies"))
    runtime = make_runtime_mock()
    runtime.logs = AsyncMock(return_value="carapace sandbox ready")
    handle = KnowledgeRepoHandle(
        owner="thies",
        knowledge_dir=tmp_path,
        git_store=GitStore(tmp_path),
    )
    mgr = SandboxManager(
        runtime=runtime,
        server_host="172.18.0.1",
        network_name="carapace-sandbox-default",
        data_dir=tmp_path,
        knowledge_repo_for_session=lambda _session_id: handle,
        session_factory=db_factory,
    )
    return mgr


@pytest.mark.asyncio
async def test_a_sandbox_start_records_its_steps_and_a_running_one_records_nothing(tmp_path: Path, db_factory) -> None:
    mgr = _manager(tmp_path, db_factory)
    trace, root = _trace()

    with attach(trace, root.span_id):
        await mgr.ensure_session("s1")
        started = len(trace.spans)
        await mgr.ensure_session("s1")

    assert len(trace.spans) == started
    steps = _by_name(trace)
    ensure = steps["ensure"]
    assert ensure.parent_id == root.span_id
    for step in ("create", "wait_for_ready", "knowledge clone", "git identity"):
        assert steps[step].parent_id == ensure.span_id, step
    assert steps["wait_for_ready"].attrs == {"ready": True}
    assert steps["hooks"].parent_id == steps["knowledge clone"].span_id
    assert {s.status for s in trace.spans.values() if s.kind == "sandbox"} == {"ok"}


@pytest.mark.asyncio
async def test_a_warm_pool_refill_scheduled_in_a_turn_records_nothing_in_it(tmp_path: Path, db_factory) -> None:
    mgr = _manager(tmp_path, db_factory)
    lifecycle = mgr._session_lifecycle
    lifecycle._runtime.runtime_kind = "kubernetes"
    seen: list[tuple[str, str] | None] = []

    async def _refill(_size: int) -> int:
        seen.append(current_span_ref())
        return 0

    lifecycle.ensure_warm_pool = _refill
    trace, root = _trace()
    with attach(trace, root.span_id):
        lifecycle.schedule_warm_pool_refill()
    await asyncio.gather(*lifecycle._warm_refill_tasks)

    assert seen == [None]


@pytest.mark.asyncio
async def test_a_sandbox_controlled_domain_is_capped() -> None:
    trace, _root = _trace()
    proxy = ProxyServer(
        verify_session_token=lambda _sid, _tok: True,
        get_allowed_domains=lambda _sid: set(),
        attach_sandbox_call=lambda _sid: attach_sandbox_call(trace),
    )

    await proxy._authorize_domain("s1", "a" * 5000)

    (check,) = [s for s in trace.spans.values() if s.kind == "domain"]
    assert check.name == check.attrs["domain"] == "a" * 200


def _exec_coordinator() -> SandboxExecCoordinator:
    runtime = make_runtime_mock()
    state = SandboxExecState(
        sessions={},
        exec_temp_domains={},
        session_current_command={},
        domain_approval_cbs={},
        domain_notify_cbs={},
        exec_locks={},
        exec_notified_domains={},
        exec_notified_credentials={},
        running_execs={},
    )
    return SandboxExecCoordinator(runtime=runtime, state=state, profile_sync=SkillProfileSync(runtime))


@pytest.mark.anyio
async def test_waiting_for_the_exec_lock_is_a_wait_span_only_when_it_is_held() -> None:
    coordinator = _exec_coordinator()
    trace, root = _trace()

    with attach(trace, root.span_id):
        async with coordinator.hold_exec_lock("s1"):
            pass
    assert list(trace.spans) == [root.span_id]

    async def queued() -> None:
        with attach(trace, root.span_id):
            async with coordinator.hold_exec_lock("s1"):
                pass

    async with coordinator.hold_exec_lock("s1"):
        waiter = asyncio.create_task(queued())
        await asyncio.sleep(0)
        wait = _by_name(trace)[EXEC_LOCK_WAIT_SPAN]
        assert (wait.kind, wait.parent_id, wait.status) == ("wait", root.span_id, "running")
    await waiter

    assert wait.status == "ok"
