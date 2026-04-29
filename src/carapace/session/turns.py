"""Agent-turn execution helpers for SessionEngine.

This module contains the mechanics of running a single turn: approval flow,
token/thinking streaming, turn finalization, and history truncation after
failures. It does not own the full session lifecycle; instead it operates
against the host surface provided by session.engine.
"""

from __future__ import annotations

import asyncio
import sys
import traceback
from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from functools import partial
from typing import Any, Protocol

from loguru import logger
from pydantic_ai import ToolDenied
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import (
    BuiltinToolCallPart,
    BuiltinToolReturnPart,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.usage import UsageLimits

from carapace.models import Config, Deps, ToolCallCallback, ToolResult
from carapace.sandbox.manager import SandboxManager
from carapace.security.context import ApprovalSource, ApprovalVerdict, format_denial_message, normalize_optional_message
from carapace.session.manager import SessionManager
from carapace.session.types import ActiveSession, SessionSubscriber, TurnExecutionResult
from carapace.usage import LlmRequestState, SessionBudgetExceededError
from carapace.ws_models import ApprovalRequest, ApprovalResponse, TurnUsage


def _non_slash_user_message_count(events: list[dict[str, Any]]) -> int:
    """Count user lines that are not slash commands (matches server slash-command routing)."""
    return sum(
        1
        for event in events
        if event.get("role") == "user"
        and isinstance(content := event.get("content"), str)
        and not content.startswith("/")
    )


def _truncate_for_log(text: str, limit: int = 160) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 3] + "..."


def _summarize_tool_args_for_log(args: dict[str, Any]) -> str:
    parts: list[str] = []
    for index, key in enumerate(sorted(args)):
        if index >= 4:
            parts.append("...")
            break
        value = args[key]
        if key == "command" and isinstance(value, str):
            parts.append(f"command={_truncate_for_log(value, 100)}")
        elif key == "contexts" and isinstance(value, list):
            parts.append(f"contexts={','.join(str(entry) for entry in value[:4])}")
        else:
            parts.append(f"{key}={_truncate_for_log(str(value), 60)}")
    return ", ".join(parts) if parts else "-"


def _summarize_tool_result_for_log(result: ToolResult) -> str:
    if not result.output:
        return "(no output)"
    output = result.output if isinstance(result.output, str) else str(result.output)
    first_line = output.splitlines()[0] if output.splitlines() else output
    return _truncate_for_log(first_line, 140)


def _engine_module() -> Any:
    module = sys.modules.get("carapace.session.engine")
    if module is None:
        raise RuntimeError("carapace.session.engine is not loaded")
    return module


class SessionTurnHost(Protocol):
    """Minimal engine surface required by SessionTurnMixin.

    Kept in this module on purpose so the turn-runner contract stays close to
    the code that consumes it, without introducing another session submodule.
    """

    _config: Config
    _session_mgr: SessionManager
    _sandbox_mgr: SandboxManager
    _llm_semaphore: asyncio.Semaphore

    async def _broadcast(
        self,
        active: ActiveSession,
        method: str,
        *args: Any,
        **kwargs: Any,
    ) -> None: ...

    def _build_deps(
        self,
        active: ActiveSession,
        *,
        tool_call_callback: ToolCallCallback | None = None,
        tool_result_callback: Callable[[ToolResult], None] | None = None,
    ) -> Deps: ...

    def _record_tool_call_event(
        self,
        session_id: str,
        *,
        tool: str,
        args: dict[str, Any],
        detail: str,
        approval_source: ApprovalSource | None = None,
        approval_verdict: ApprovalVerdict | None = None,
        approval_explanation: str | None = None,
        parent_tool_id: str | None = None,
        match_args: dict[str, Any] | None = None,
    ) -> str: ...

    def llm_request_recording(self, active: ActiveSession) -> AbstractContextManager[Any, bool | None]: ...

    def _assert_llm_budget_available(self, active: ActiveSession) -> None: ...

    def _remaining_usage_limits(self, active: ActiveSession) -> UsageLimits | None: ...

    async def _maybe_promote_llm_request_state(
        self,
        active: ActiveSession,
        state: LlmRequestState | None,
    ) -> None: ...

    def _turn_usage_payload(self, active: ActiveSession) -> TurnUsage | None: ...

    async def _clear_llm_request_state(self, active: ActiveSession) -> None: ...

    async def _generate_title(self, active: ActiveSession, events: list[dict[str, Any]]) -> str: ...


class SessionTurnMixin(SessionTurnHost):
    """Turn runner mixed into SessionEngine.

    The mixin keeps the turn lifecycle cohesive in one place while delegating
    storage, sandbox, and broadcast concerns back to the engine host.
    """

    async def _run_turn(
        self,
        active: ActiveSession,
        user_input: str,
        *,
        origin: SessionSubscriber | None = None,
    ) -> None:
        """Execute a single agent turn with semaphore-bounded LLM access."""
        session_id = active.state.session_id
        latest_messages: list[ModelMessage] | None = None

        def _set_latest_messages(snapshot: list[Any]) -> None:
            nonlocal latest_messages
            latest_messages = [message for message in snapshot if isinstance(message, (ModelRequest, ModelResponse))]

        def _tool_call_cb(
            tool: str,
            args: dict[str, Any],
            detail: str,
            approval_source: ApprovalSource | None = None,
            approval_verdict: ApprovalVerdict | None = None,
            approval_explanation: str | None = None,
        ) -> None:
            tool_id = self._record_tool_call_event(
                session_id,
                tool=tool,
                args=args,
                detail=detail,
                approval_source=approval_source,
                approval_verdict=approval_verdict,
                approval_explanation=approval_explanation,
            )
            if active.security:
                active.security.current_parent_tool_id = tool_id
            logger.info(
                f"Tool call session={session_id} tool={tool} "
                + f"approval={approval_source or '-'}:{approval_verdict or '-'} "
                + f"args={_summarize_tool_args_for_log(args)}"
            )
            task = asyncio.ensure_future(
                self._broadcast(
                    active,
                    "on_tool_call",
                    tool,
                    args,
                    detail,
                    approval_source,
                    approval_verdict,
                    approval_explanation,
                    tool_id,
                )
            )
            active._pending_sends.add(task)
            task.add_done_callback(active._pending_sends.discard)

        def _tool_result_cb(tr: ToolResult) -> None:
            self._session_mgr.append_events(
                session_id,
                [
                    {
                        "role": "tool_result",
                        "tool": tr.tool,
                        "result": tr.output,
                        "exit_code": tr.exit_code,
                        "tool_id": tr.tool_id,
                    }
                ],
            )
            logger.info(
                f"Tool result session={session_id} tool={tr.tool} exit_code={tr.exit_code} "
                + f"summary={_summarize_tool_result_for_log(tr)}"
            )
            task = asyncio.ensure_future(self._broadcast(active, "on_tool_result", tr))
            active._pending_sends.add(task)
            task.add_done_callback(active._pending_sends.discard)

        try:
            async with active.lock:
                deps, message_history = await self._prepare_turn_execution(
                    active,
                    session_id,
                    user_input,
                    origin=origin,
                    tool_call_callback=_tool_call_cb,
                    tool_result_callback=_tool_result_cb,
                )

                async def _send_approval(req: ApprovalRequest) -> None:
                    await self._send_approval_request(active, session_id, req)

                async def _collect_approvals(
                    pending: set[str],
                ) -> dict[str, bool | ToolDenied]:
                    return await self._collect_approval_results(active, session_id, pending)

                turn_result = await self._execute_agent_turn(
                    active,
                    user_input,
                    deps,
                    message_history,
                    send_approval_request=_send_approval,
                    collect_approvals=_collect_approvals,
                    on_messages_snapshot=_set_latest_messages,
                )

                await self._finalize_successful_turn(
                    active,
                    session_id,
                    turn_result.messages,
                    turn_result.output,
                    turn_result.thinking,
                )

        except asyncio.CancelledError:
            logger.info(f"Agent turn cancelled for session {session_id}")
            await self._finalize_failed_turn(
                active,
                session_id,
                user_input,
                latest_messages=latest_messages,
                terminal_message="The previous turn was interrupted before completion.",
                save_progress=True,
            )
            await self._broadcast(active, "on_cancelled")
        except SessionBudgetExceededError as exc:
            logger.info(f"Session budget blocked LLM call for {session_id}: {exc}")
            await self._finalize_failed_turn(
                active,
                session_id,
                user_input,
                latest_messages=latest_messages,
                terminal_message=str(exc),
                save_progress=True,
            )
            await self._broadcast(active, "on_error", str(exc), turn_terminal=True)
        except UsageLimitExceeded as exc:
            sentinel_evals = active.security.sentinel_eval_count if active.security else 0
            logger.error(
                f"Turn usage-limit failure session={session_id} error={exc} "
                + f"llm_requests={len(active.llm_request_log.records)} "
                + f"sentinel_evals={sentinel_evals} prompt={_truncate_for_log(user_input)}"
            )
            await self._finalize_failed_turn(
                active,
                session_id,
                user_input,
                latest_messages=latest_messages,
                terminal_message="The previous turn failed before completion.",
            )
            await self._broadcast(active, "on_error", str(exc), turn_terminal=True)
        except Exception:
            logger.exception(f"Agent error session={session_id} prompt={_truncate_for_log(user_input)}")
            await self._finalize_failed_turn(
                active,
                session_id,
                user_input,
                latest_messages=latest_messages,
                terminal_message="The previous turn failed before completion.",
            )
            await self._broadcast(active, "on_error", traceback.format_exc(), turn_terminal=True)
        finally:
            active.agent_task = None

    def _save_turn_progress(self, session_id: str, active: ActiveSession) -> None:
        self._session_mgr.save_usage(session_id, active.usage_tracker)
        self._session_mgr.save_llm_request_log(session_id, active.llm_request_log)

    async def _prepare_turn_execution(
        self,
        active: ActiveSession,
        session_id: str,
        user_input: str,
        *,
        origin: SessionSubscriber | None,
        tool_call_callback: ToolCallCallback,
        tool_result_callback: Callable[[ToolResult], None],
    ) -> tuple[Deps, list[ModelMessage]]:
        fresh = self._session_mgr.resume_session(session_id)
        if fresh:
            active.state = fresh

        deps = self._build_deps(
            active,
            tool_call_callback=tool_call_callback,
            tool_result_callback=tool_result_callback,
        )
        self._session_mgr.append_events(session_id, [{"role": "user", "content": user_input}])
        for sub in list(active.subscribers):
            try:
                await sub.on_user_message(user_input, from_self=(sub is origin))
            except Exception as exc:
                logger.warning(f"Subscriber on_user_message failed: {exc}")

        message_history = self._session_mgr.load_history(session_id)
        logger.info(
            f"Turn start session={session_id} model={active.agent_model_name or self._config.agent.model} "
            + f"history_messages={len(message_history)} prompt={_truncate_for_log(user_input)}"
        )
        return deps, message_history

    async def _send_approval_request(
        self,
        active: ActiveSession,
        session_id: str,
        req: ApprovalRequest,
    ) -> None:
        self._session_mgr.append_events(
            session_id,
            [
                {
                    "role": "approval_request",
                    "tool_call_id": req.tool_call_id,
                    "tool": req.tool,
                    "args": req.args,
                    "explanation": req.explanation,
                    "risk_level": req.risk_level,
                }
            ],
        )
        active.pending_approval_requests.append(req.model_dump())
        await self._broadcast(active, "on_approval_request", req)

    def _append_approval_response_events(
        self,
        session_id: str,
        results: dict[str, bool | ToolDenied],
        responses: dict[str, ApprovalResponse],
    ) -> None:
        for tool_call_id, decision in results.items():
            response = responses.get(tool_call_id)
            user_decision = "approved" if decision is True else "denied"
            self._session_mgr.append_events(
                session_id,
                [
                    {
                        "role": "approval_response",
                        "tool_call_id": tool_call_id,
                        "decision": user_decision,
                        "decision_source": "user",
                        "message": normalize_optional_message(response.message) if response is not None else None,
                    }
                ],
            )

    async def _collect_approval_results(
        self,
        active: ActiveSession,
        session_id: str,
        pending: set[str],
    ) -> dict[str, bool | ToolDenied]:
        results: dict[str, bool | ToolDenied] = {}
        responses: dict[str, ApprovalResponse] = {}
        remaining = set(pending)
        while remaining:
            msg = await active.tool_approval_queue.get()
            if msg is None:
                for tool_call_id in remaining:
                    results[tool_call_id] = ToolDenied("Agent cancelled.")
                break
            if msg.tool_call_id in remaining:
                responses[msg.tool_call_id] = msg
                results[msg.tool_call_id] = (
                    True if msg.approved else ToolDenied(format_denial_message("user", msg.message))
                )
                remaining.discard(msg.tool_call_id)
        self._append_approval_response_events(session_id, results, responses)
        active.pending_approval_requests.clear()
        return results

    async def _refresh_sandbox_snapshot_after_turn(self, session_id: str) -> None:
        try:
            await self._sandbox_mgr.refresh_sandbox_snapshot(session_id, measure_usage=True)
        except Exception:
            logger.exception(f"Failed to refresh sandbox snapshot after completed turn for session {session_id}")

    async def _execute_agent_turn(
        self,
        active: ActiveSession,
        user_input: str,
        deps: Deps,
        message_history: list[ModelMessage],
        *,
        send_approval_request: Callable[[ApprovalRequest], Awaitable[None]],
        collect_approvals: Callable[[set[str]], Awaitable[dict[str, bool | ToolDenied]]],
        on_messages_snapshot: Callable[[list[Any]], None],
    ) -> TurnExecutionResult:
        async with self._llm_semaphore:
            with self.llm_request_recording(active):
                self._assert_llm_budget_available(active)
                messages, output, thinking = await _engine_module().run_agent_turn(
                    user_input,
                    deps,
                    message_history,
                    send_approval_request=send_approval_request,
                    collect_approvals=collect_approvals,
                    on_token=partial(self._handle_token_chunk, active),
                    on_thinking_token=partial(self._handle_thinking_token_chunk, active),
                    on_messages_snapshot=lambda snapshot: on_messages_snapshot(snapshot),
                    before_llm_call=lambda: self._assert_llm_budget_available(active),
                    get_usage_limits=lambda: self._remaining_usage_limits(active),
                )
        return TurnExecutionResult(messages=messages, output=output, thinking=thinking)

    async def _handle_token_chunk(self, active: ActiveSession, chunk: str) -> None:
        await self._maybe_promote_llm_request_state(active, _engine_module().note_llm_request_text())
        await self._broadcast(active, "on_token", chunk)

    async def _handle_thinking_token_chunk(self, active: ActiveSession, chunk: str) -> None:
        state = _engine_module().note_llm_request_thinking()
        if state is not None:
            active.llm_request_thinking[state.request_id] = (
                active.llm_request_thinking.get(state.request_id, "") + chunk
            )
        await self._maybe_promote_llm_request_state(active, state)
        await self._broadcast(active, "on_thinking_token", chunk)

    def _schedule_title_generation_if_needed(
        self,
        active: ActiveSession,
        session_id: str,
        events: list[dict[str, Any]],
    ) -> None:
        if _non_slash_user_message_count(events) not in (1, 3):
            return
        task = asyncio.create_task(
            self._generate_title(active, events),
            name=f"title-{session_id}",
        )
        active._pending_sends.add(task)
        task.add_done_callback(active._pending_sends.discard)

    async def _finalize_successful_turn(
        self,
        active: ActiveSession,
        session_id: str,
        messages: list[ModelMessage],
        output: str,
        thinking: str,
    ) -> None:
        self._session_mgr.save_history(session_id, messages)
        self._session_mgr.save_state(active.state)
        self._save_turn_progress(session_id, active)
        await self._refresh_sandbox_snapshot_after_turn(session_id)
        self._session_mgr.append_events(session_id, [{"role": "assistant", "content": output}])

        if output.startswith("Unexpected agent output type:"):
            await self._broadcast(active, "on_error", output, turn_terminal=True)
        else:
            usage_payload = self._turn_usage_payload(active) or TurnUsage()
            logger.info(
                f"Turn done session={session_id} "
                + f"model={usage_payload.model or active.agent_model_name or self._config.agent.model} "
                + f"input_tokens={usage_payload.input_tokens} output_tokens={usage_payload.output_tokens} "
                + f"thinking_chars={len(thinking)} output_chars={len(output)}"
            )
            await self._broadcast(
                active,
                "on_done",
                output,
                usage_payload,
                thinking=thinking or None,
            )

        self._schedule_title_generation_if_needed(active, session_id, self._session_mgr.load_events(session_id))

    async def _finalize_failed_turn(
        self,
        active: ActiveSession,
        session_id: str,
        user_input: str,
        *,
        latest_messages: list[ModelMessage] | None = None,
        terminal_message: str | None = None,
        save_progress: bool = False,
    ) -> None:
        active.llm_request_thinking.clear()
        if save_progress:
            self._save_turn_progress(session_id, active)
        await self._clear_llm_request_state(active)
        self._save_user_message_on_failure(
            session_id,
            user_input,
            latest_messages=latest_messages,
            terminal_message=terminal_message,
        )

    def _save_user_message_on_failure(
        self,
        session_id: str,
        user_input: str,
        *,
        latest_messages: list[ModelMessage] | None = None,
        terminal_message: str | None = None,
    ) -> None:
        """Persist the user message to history even when the agent turn fails.

        Without this the next turn would load stale history and the agent would
        have no memory of what the user said before the error.
        """
        if latest_messages is not None:
            history = list(latest_messages)
        else:
            history = self._session_mgr.load_history(session_id)
            history.append(ModelRequest(parts=[UserPromptPart(content=user_input)]))
        history = self._truncate_incomplete_model_history(history)
        if terminal_message:
            history.append(ModelResponse(parts=[TextPart(content=terminal_message)]))
        self._session_mgr.save_history(session_id, history)

        events = self._truncate_incomplete_events(self._session_mgr.load_events(session_id))
        if terminal_message:
            events.append(
                {
                    "role": "assistant",
                    "content": terminal_message,
                    "timestamp": datetime.now(tz=UTC).isoformat(),
                }
            )
        self._session_mgr.save_events(session_id, events)

    def _truncate_incomplete_model_history(self, messages: list[ModelMessage]) -> list[ModelMessage]:
        pending_tool_calls: set[str] = set()
        safe_prefix_end = 0

        for index, message in enumerate(messages):
            if isinstance(message, ModelResponse):
                for part in message.parts:
                    if isinstance(part, ToolCallPart | BuiltinToolCallPart):
                        tool_call_id = getattr(part, "tool_call_id", None)
                        if isinstance(tool_call_id, str) and tool_call_id:
                            pending_tool_calls.add(tool_call_id)
            elif isinstance(message, ModelRequest):
                for part in message.parts:
                    if isinstance(part, ToolReturnPart | BuiltinToolReturnPart):
                        tool_call_id = getattr(part, "tool_call_id", None)
                        if isinstance(tool_call_id, str) and tool_call_id in pending_tool_calls:
                            pending_tool_calls.remove(tool_call_id)

            if not pending_tool_calls:
                safe_prefix_end = index + 1

        return messages[:safe_prefix_end]

    def _truncate_incomplete_events(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        tools_with_results = {
            event.get("tool")
            for event in events
            if event.get("role") == "tool_result" and isinstance(event.get("tool"), str)
        }
        pending_by_tool: dict[str, int] = {}
        safe_prefix_end = 0

        for index, event in enumerate(events):
            role = event.get("role")
            tool = event.get("tool")
            if not isinstance(tool, str):
                tool = ""

            if role == "tool_call" and tool in tools_with_results:
                pending_by_tool[tool] = pending_by_tool.get(tool, 0) + 1
            elif role == "tool_result" and tool in tools_with_results:
                outstanding = pending_by_tool.get(tool, 0)
                if outstanding > 0:
                    if outstanding == 1:
                        pending_by_tool.pop(tool, None)
                    else:
                        pending_by_tool[tool] = outstanding - 1

            if not pending_by_tool:
                safe_prefix_end = index + 1

        return events[:safe_prefix_end]
