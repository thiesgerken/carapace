"""Parallel tool calls: a result and an exec's boundary decision land on the card of their own call."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import patch

from carapace.models.tooling import ToolResult
from carapace.sandbox.exec_scope import RunningExec
from tests.session_helpers import _FakeSubscriber, _make_engine, _patch_sentinel


def test_overlapping_calls_keep_their_own_tool_ids(tmp_path: Path, db_factory: Any) -> None:
    async def _run() -> None:
        engine = _make_engine(tmp_path, session_factory=db_factory)
        sid = engine.session_mgr.create_session(user="thies").session_id
        active = engine.get_or_activate(sid)
        sub = _FakeSubscriber()
        engine.subscribe(sid, sub)

        async def _parallel_turn(_user_input: str, deps: Any, *_args: Any, **_kwargs: Any) -> tuple[Any, ...]:
            # read_skill starts first and waits; the exec starts after it, asks for a domain and returns first.
            deps.tool_call_callback("read_skill", {"skill_name": "ferret"}, "", None, None, None, "call-skill", None)
            deps.tool_call_callback("exec", {"command": "curl example.com"}, "", None, None, None, "call-exec", None)
            engine.sandbox_mgr.running_exec.return_value = RunningExec(
                session_id=sid, command="curl example.com", domains=set(), credentials=set(), tool_call_id="call-exec"
            )
            deps.security.notify_domain_decision("example.com", "allowed")
            engine.sandbox_mgr.running_exec.return_value = None
            deps.tool_result_callback(ToolResult(tool="exec", output="ok", model_tool_call_id="call-exec"))
            deps.tool_result_callback(ToolResult(tool="read_skill", output="docs", model_tool_call_id="call-skill"))
            return [], "done", "", None

        with patch("carapace.session.engine.run_agent_turn", new=_parallel_turn):
            await engine.submit_message(sid, "hello")
            async with asyncio.timeout(5):
                while active.agent_task is not None:
                    await asyncio.sleep(0.01)

        events = engine.session_mgr.load_events(sid)
        call_ids = {e["tool"]: e["tool_id"] for e in events if e["role"] == "tool_call"}
        result_ids = {e["tool"]: e["tool_id"] for e in events if e["role"] == "tool_result"}
        assert result_ids == {"exec": call_ids["exec"], "read_skill": call_ids["read_skill"]}
        assert {r.tool: r.tool_id for r in sub.tool_results} == result_ids
        [domain_event] = [e for e in events if e["role"] == "tool_call" and e["tool"] == "proxy_domain"]
        assert domain_event["parent_tool_id"] == call_ids["exec"]

    with _patch_sentinel():
        asyncio.run(_run())
