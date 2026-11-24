"""A domain approval holds for the exec it was given to, and not for the next one under the same tool call."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from carapace.sandbox.exec_flow import SandboxExecCoordinator, SandboxExecState
from carapace.sandbox.skill_profile import SkillProfileSync
from carapace.security.context import SentinelVerdict, SessionSecurity
from carapace.security.sentinel import Sentinel
from tests.runtime_mocks import make_runtime_mock
from tests.session_helpers import _make_engine, _patch_sentinel


def _coordinator(domain_cb: Any) -> SandboxExecCoordinator:
    state = SandboxExecState(
        sessions={},
        allowed_domains={},
        exec_temp_domains={},
        session_current_command={},
        domain_approval_cbs={"s1": domain_cb},
        domain_notify_cbs={},
        exec_locks={},
        exec_notified_domains={},
        exec_notified_credentials={},
        running_execs={},
    )
    return SandboxExecCoordinator(
        runtime=make_runtime_mock(), state=state, profile_sync=SkillProfileSync(make_runtime_mock())
    )


def test_parallel_execs_under_one_tool_call_are_each_reviewed(tmp_path: Path, db_factory: Any) -> None:
    async def _run() -> None:
        engine = _make_engine(tmp_path, session_factory=db_factory)
        sid = engine.session_mgr.create_session(user="thies").session_id
        active = engine.get_or_activate(sid)
        security = SessionSecurity("s1", sentinel_domain_batch_window_ms=0)
        # Parallel tool calls: both execs ran under the id of the last gated call.
        security.current_parent_tool_id = "tool-2"
        sentinel = MagicMock(spec=Sentinel)
        sentinel.evaluate_domain_access = AsyncMock(return_value=SentinelVerdict(decision="allow", explanation="fits"))
        coordinator = _coordinator(engine._make_domain_eval_cb(security, sentinel, active))

        for command in ("curl https://api.example.com/a", "curl https://api.example.com/b"):
            coordinator._grant_exec_scope("s1", command)
            assert (await coordinator.request_domain_approval("s1", "api.example.com")).allowed
            coordinator._revoke_exec_scope("s1")

        assert sentinel.evaluate_domain_access.await_count == 2

    with _patch_sentinel():
        asyncio.run(_run())
