"""Public session engine and cross-cutting session orchestration.

This module owns the long-lived SessionEngine that wires together session
state, security, sandbox integration, subscriber broadcasting, slash-command
handling, and model selection. Turn execution itself lives in session.turns;
 this file remains the integration point that provides the concrete host
 behavior for that turn runner.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import secrets
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

from loguru import logger
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, UserPromptPart
from pydantic_ai.models import Model, infer_model
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import UsageLimits

import carapace.security as security_mod
from carapace.agent.loop import run_agent_turn as _run_agent_turn
from carapace.git.store import GitStore
from carapace.llm import model_settings_for_config
from carapace.memory import MemoryStore
from carapace.models import (
    AvailableModelEntry,
    Config,
    CredentialRegistryProtocol,
    Deps,
    SessionState,
    SkillInfo,
    ToolCallCallback,
    ToolResult,
    agent_available_model_entries,
    context_grants_session_summary,
)
from carapace.sandbox.manager import SandboxManager
from carapace.sandbox.runtime import SkillActivationInputs, SkillFileCredential
from carapace.security.context import (
    ApprovalSource,
    ApprovalVerdict,
    SessionSecurity,
    UserEscalationDecision,
    UserVouchedEntry,
    normalize_optional_message,
)
from carapace.security.sentinel import Sentinel
from carapace.session.manager import SessionManager
from carapace.session.titler import generate_title
from carapace.session.turns import SessionTurnMixin
from carapace.session.types import ActiveSession, SessionSubscriber
from carapace.skills import SkillRegistry
from carapace.usage import (
    BudgetGauge,
    LlmRequestRecord,
    LlmRequestState,
    LlmSource,
    SessionBudgetExceededError,
    gauge_breakdown_pct_dict,
    last_record_for_source,
    llm_request_sink_scope,
    usage_budget_exceeded_error,
    usage_budget_gauges,
    usage_last_request_row,
    usage_limits_for_remaining_budget,
)
from carapace.usage import (
    note_llm_request_text as _note_llm_request_text,
)
from carapace.usage import (
    note_llm_request_thinking as _note_llm_request_thinking,
)
from carapace.ws_models import (
    SLASH_COMMANDS,
    ApprovalResponse,
    EscalationResponse,
    TurnUsage,
    TurnUsageBreakdownPct,
)

ModelType = Literal["agent", "sentinel", "title"]

_DEFAULT_CONTEXT_CAP_TOKENS = 200_000


# Compatibility shims for tests that patch helpers on carapace.session.engine.
def run_agent_turn(*args: Any, **kwargs: Any) -> Any:
    return _run_agent_turn(*args, **kwargs)


def note_llm_request_text() -> LlmRequestState | None:
    return _note_llm_request_text()


def note_llm_request_thinking() -> LlmRequestState | None:
    return _note_llm_request_thinking()


# security_mod is still imported for evaluate_domain_with (used in domain approval callback)


@dataclass(frozen=True, slots=True)
class CompletedEventTurn:
    start_event_index: int
    end_event_index: int
    user_content: str


class SessionEngine(SessionTurnMixin):
    """Central session lifecycle manager.

    Owns all in-memory session state, security sessions, and agent execution.
    Channels (WebSocket, Matrix, …) subscribe to events and submit messages
        through this class. Agent turns survive transport disconnects, and LLM
        concurrency is bounded by a shared semaphore.

        Responsibility split:
        - session.types: shared session datatypes and subscriber protocol
        - session.turns: turn execution flow and failure/finalization helpers
        - this module: dependency wiring, lifecycle, approvals, broadcasts, and
            public session APIs
    """

    def __init__(
        self,
        *,
        config: Config,
        data_dir: Path,
        knowledge_dir: Path,
        git_store: GitStore,
        session_mgr: SessionManager,
        skill_catalog: list[SkillInfo],
        agent_model: Model | None,
        sandbox_mgr: SandboxManager,
        credential_registry: CredentialRegistryProtocol,
        model_factory: Callable[[str], Model] | None = None,
    ) -> None:
        self._config = config
        self._data_dir = data_dir
        self._knowledge_dir = knowledge_dir
        self._git_store = git_store
        self._session_mgr = session_mgr
        self._skill_catalog = skill_catalog
        self._agent_model = agent_model
        self._sandbox_mgr = sandbox_mgr
        self._model_factory = model_factory
        self._credential_registry = credential_registry
        self._active: dict[str, ActiveSession] = {}
        self._llm_semaphore = asyncio.Semaphore(config.agent.max_parallel_llm)

        # Let SandboxManager retrieve activated skills so automatic setup can rerun on recreation
        sandbox_mgr.set_activated_skills_callback(self._get_activated_skills)
        sandbox_mgr.set_skill_activation_inputs_callback(self._skill_activation_inputs)
        sandbox_mgr.set_skill_command_aliases_callback(self._skill_command_aliases)

    # -- public access to file I/O manager --

    @property
    def session_mgr(self) -> SessionManager:
        return self._session_mgr

    @property
    def config(self) -> Config:
        return self._config

    @property
    def data_dir(self) -> Path:
        return self._data_dir

    @property
    def skill_catalog(self) -> list[SkillInfo]:
        return self._skill_catalog

    @property
    def sandbox_mgr(self) -> SandboxManager:
        return self._sandbox_mgr

    @property
    def agent_model(self) -> Model | None:
        return self._agent_model

    @property
    def available_models(self) -> list[str]:
        return [e.model_id for e in self.available_model_entries]

    @property
    def available_model_entries(self) -> list[AvailableModelEntry]:
        """Deduplicated ``agent.available_models`` (last row per ``model_id``), sorted by id."""
        return agent_available_model_entries(self._config.agent)

    def _max_input_tokens_for_model_id(self, model_id: str) -> int | None:
        for e in self.available_model_entries:
            if e.model_id == model_id:
                return e.max_input_tokens
        return None

    def _usage_last_llm_payload_row(self, active: ActiveSession, source: LlmSource) -> dict[str, Any] | None:
        """``usage_last_request_row`` plus ``context_cap_tokens`` and ``context_used_pct`` for the UI."""
        rec = last_record_for_source(active.llm_request_log, source)
        row = usage_last_request_row(rec)
        if row is None:
            return None
        mid = (
            active.agent_model_name or self._config.agent.model
            if source == "agent"
            else active.sentinel_model_name or self._config.agent.sentinel_model
        )
        cap = self._max_input_tokens_for_model_id(mid)
        if cap is None:
            cap = _DEFAULT_CONTEXT_CAP_TOKENS
        cs = row["context_size"]
        pct = min(100.0, (100.0 * cs / cap)) if cap > 0 else 0.0
        out: dict[str, Any] = dict(row)
        out["context_cap_tokens"] = cap
        out["context_used_pct"] = round(pct, 1)
        return out

    def agent_model_id_for_gauge(self, active: ActiveSession) -> str:
        """Canonical Carapace model id (``provider:name``) for UI gauge / config lookup.

        Do not use the provider's raw ``model_name`` from the LLM log — it is often a short
        id without the ``provider:`` prefix, so it would not match ``available_models`` entries.
        """
        return active.agent_model_name or self._config.agent.model

    def agent_context_cap_for_gauge(self, active: ActiveSession) -> int:
        model_id = self.agent_model_id_for_gauge(active)
        return self._max_input_tokens_for_model_id(model_id) or _DEFAULT_CONTEXT_CAP_TOKENS

    def _budget_gauges(self, active: ActiveSession) -> list[BudgetGauge]:
        budget = active.state.budget
        return usage_budget_gauges(
            active.usage_tracker,
            input_tokens_limit=budget.input_tokens,
            output_tokens_limit=budget.output_tokens,
            total_cost_limit=budget.cost_usd,
        )

    def _budget_exceeded_error(self, active: ActiveSession) -> SessionBudgetExceededError | None:
        budget = active.state.budget
        return usage_budget_exceeded_error(
            active.usage_tracker,
            input_tokens_limit=budget.input_tokens,
            output_tokens_limit=budget.output_tokens,
            total_cost_limit=budget.cost_usd,
        )

    def _assert_llm_budget_available(self, active: ActiveSession) -> None:
        error = self._budget_exceeded_error(active)
        if error is not None:
            raise error

    def _remaining_usage_limits(self, active: ActiveSession) -> UsageLimits | None:
        return usage_limits_for_remaining_budget(
            active.usage_tracker,
            output_tokens_limit=active.state.budget.output_tokens,
        )

    def _remaining_aux_usage_limits(self, active: ActiveSession) -> UsageLimits | None:
        return usage_limits_for_remaining_budget(
            active.usage_tracker,
            output_tokens_limit=active.state.budget.output_tokens,
            request_limit=10,
        )

    def _turn_usage_payload(self, active: ActiveSession) -> TurnUsage | None:
        rec_agent = last_record_for_source(active.llm_request_log, "agent")
        budget_gauges = self._budget_gauges(active)
        if rec_agent is None and not budget_gauges:
            return None
        row = usage_last_request_row(rec_agent) if rec_agent else None
        bd = gauge_breakdown_pct_dict(rec_agent)
        return TurnUsage(
            input_tokens=rec_agent.input_tokens if rec_agent else 0,
            output_tokens=rec_agent.output_tokens if rec_agent else 0,
            breakdown_pct=TurnUsageBreakdownPct.model_validate(bd) if bd else None,
            model=self.agent_model_id_for_gauge(active),
            context_cap_tokens=self.agent_context_cap_for_gauge(active),
            ttft_ms=row["ttft_ms"] if row else None,
            total_duration_ms=row["total_duration_ms"] if row else None,
            reasoning_duration_ms=row["reasoning_duration_ms"] if row else None,
            reasoning_tokens=row["reasoning_tokens"] if row else None,
            started_at=rec_agent.started_at if rec_agent else None,
            first_thinking_at=rec_agent.first_thinking_at if rec_agent else None,
            last_thinking_at=rec_agent.last_thinking_at if rec_agent else None,
            first_text_at=rec_agent.first_text_at if rec_agent else None,
            completed_at=rec_agent.completed_at if rec_agent else None,
            budget_gauges=budget_gauges,
        )

    async def _set_llm_request_state(self, active: ActiveSession, state: LlmRequestState) -> None:
        active.llm_request_state = state.model_copy(deep=True)
        self._session_mgr.save_llm_request_state(active.state.session_id, active.llm_request_state)
        await self._broadcast(active, "on_llm_activity", active.llm_request_state.model_copy(deep=True))

    async def _clear_llm_request_state(self, active: ActiveSession) -> None:
        if active.llm_request_state is None:
            self._session_mgr.clear_llm_request_state(active.state.session_id)
            return
        active.llm_request_state = None
        self._session_mgr.clear_llm_request_state(active.state.session_id)
        await self._broadcast(active, "on_llm_activity", None)

    async def _maybe_promote_llm_request_state(self, active: ActiveSession, state: LlmRequestState | None) -> None:
        if state is None:
            return
        current = active.llm_request_state
        if current is not None and current.phase == state.phase and current.first_text_at == state.first_text_at:
            return
        await self._set_llm_request_state(active, state)

    def _budget_command_payload(self, active: ActiveSession, *, message: str | None = None) -> dict[str, Any]:
        gauges = self._budget_gauges(active)
        usage_hint = "Set budgets with /budget input N, /budget output N, or /budget cost N. Use 0 to clear a limit."
        payload: dict[str, Any] = {
            "gauges": [g.model_dump(mode="json") for g in gauges],
            "usage_hint": usage_hint,
        }
        if message is not None:
            payload["message"] = message
        if not gauges and message is None:
            payload["message"] = "No session budgets configured."
        return payload

    def _parse_budget_limit_value(self, metric: Literal["input", "output", "cost"], raw: str) -> int | Decimal:
        cleaned = raw.replace(",", "").replace("_", "")
        if metric in ("input", "output"):
            lowered = cleaned.lower()
            multiplier = 1
            if lowered.endswith("k"):
                multiplier = 1_000
                lowered = lowered[:-1]
            elif lowered.endswith("m"):
                multiplier = 1_000_000
                lowered = lowered[:-1]

            if not lowered:
                raise ValueError(f"Invalid token budget: {raw}")

            try:
                scaled = Decimal(lowered) * multiplier
            except InvalidOperation as exc:
                raise ValueError(f"Invalid token budget: {raw}") from exc

            if scaled != scaled.to_integral_value():
                raise ValueError(f"Invalid token budget: {raw}")

            value = int(scaled)
            if value < 0:
                raise ValueError("Budget value must be >= 0")
            return value
        try:
            value = Decimal(cleaned)
        except InvalidOperation as exc:
            raise ValueError(f"Invalid cost budget: {raw}") from exc
        if value < 0:
            raise ValueError("Budget value must be >= 0")
        return value

    def _set_budget_metric(
        self,
        active: ActiveSession,
        metric: Literal["input", "output", "cost"],
        value: int | Decimal,
    ) -> str:
        budget = active.state.budget.model_copy(deep=True)
        if metric == "input":
            budget.input_tokens = int(value)
            if budget.input_tokens == 0:
                budget.input_tokens = None
            active.state.budget = budget
            self._session_mgr.save_state(active.state)
            if budget.input_tokens is None:
                return "Cleared input token budget."
            return f"Set input token budget to {budget.input_tokens:,} tokens."
        if metric == "output":
            budget.output_tokens = int(value)
            if budget.output_tokens == 0:
                budget.output_tokens = None
            active.state.budget = budget
            self._session_mgr.save_state(active.state)
            if budget.output_tokens is None:
                return "Cleared output token budget."
            return f"Set output token budget to {budget.output_tokens:,} tokens."
        budget.cost_usd = Decimal(value)
        if budget.cost_usd == 0:
            budget.cost_usd = None
        active.state.budget = budget
        self._session_mgr.save_state(active.state)
        if budget.cost_usd is None:
            return "Cleared cost budget."
        return f"Set cost budget to ${budget.cost_usd:.4f}."

    def _resolve_model(self, name: str) -> Model:
        """Create a Model from a name, using the model_factory if available."""
        return self._model_factory(name) if self._model_factory else infer_model(name)

    def _resolve_model_settings(self, name: str) -> ModelSettings | None:
        """Build per-model request settings from the configured catalog."""
        return model_settings_for_config(self._config, name, default_thinking=True)

    # -- session lifecycle --

    def _ensure_active(self, session_id: str) -> ActiveSession:
        """Return or create the in-memory ``ActiveSession`` for *session_id*."""
        if session_id in self._active:
            return self._active[session_id]

        state = self._session_mgr.resume_session(session_id)
        if state is None:
            raise KeyError(f"Session {session_id} not found on disk")

        audit_dir = self._data_dir / "sessions" / session_id
        security = SessionSecurity(
            session_id,
            audit_dir=audit_dir,
            max_sentinel_calls_per_tool_call=self._config.agent.max_sentinel_calls_per_tool_call,
        )
        sentinel = Sentinel(
            model=self._config.agent.sentinel_model,
            knowledge_dir=self._knowledge_dir,
            skills_dir=self._knowledge_dir / "skills",
            model_factory=self._model_factory,
            model_settings_resolver=self._resolve_model_settings,
        )
        usage_tracker = self._session_mgr.load_usage(session_id)
        llm_log = self._session_mgr.load_llm_request_log(session_id)
        stale_llm_state = self._session_mgr.load_llm_request_state(session_id)
        if stale_llm_state is not None:
            logger.warning(f"Clearing stale in-flight LLM activity for session {session_id}")
            self._session_mgr.clear_llm_request_state(session_id)

        active = ActiveSession(
            state=state,
            security=security,
            sentinel=sentinel,
            usage_tracker=usage_tracker,
            llm_request_log=llm_log,
        )
        self._active[session_id] = active

        # Wire security callbacks so domain escalation / info works
        # even outside an agent turn (e.g. during sandbox setup).
        security.set_user_escalation_callback(self._make_escalation_cb(active))
        security.set_domain_info_callback(self._make_domain_info_cb(active))
        security.set_push_info_callback(self._make_push_info_cb(active))
        security.set_credential_info_callback(self._make_credential_info_cb(active))
        security.set_credential_notify_suppress(
            lambda vp: self._sandbox_mgr.mark_credential_notified(state.session_id, vp),
        )

        # Register a domain-approval callback so the sandbox proxy can
        # evaluate domain requests through the per-session sentinel.
        self._sandbox_mgr.set_domain_approval_callback(
            session_id,
            self._make_domain_eval_cb(security, sentinel, active),
        )
        # Register a domain-notify callback so skill-granted and bypass
        # domain accesses also emit UI events.
        self._sandbox_mgr.set_domain_notify_callback(
            session_id,
            self._make_domain_info_cb(active),
        )

        return active

    def _get_activated_skills(self, session_id: str) -> list[str]:
        """Return activated skills for a session (from in-memory state or disk)."""
        active = self._active.get(session_id)
        if active:
            return list(active.state.activated_skills)
        state = self._session_mgr.load_state(session_id)
        if state:
            return list(state.activated_skills)
        return []

    async def _skill_activation_inputs(self, session_id: str, skill_name: str) -> SkillActivationInputs:
        """Return approved env/file inputs for automatic skill activation providers."""
        registry = SkillRegistry(self._knowledge_dir / "skills")
        carapace_cfg = registry.get_carapace_config(skill_name)
        if not carapace_cfg or not carapace_cfg.credentials:
            return SkillActivationInputs()

        approved_paths = self._credential_vault_paths_for_skill(session_id, skill_name)
        env: dict[str, str] = {}
        file_credentials: list[SkillFileCredential] = []
        for decl in carapace_cfg.credentials:
            if decl.vault_path not in approved_paths or not (decl.env_var or decl.file):
                continue

            value = self._sandbox_mgr.get_cached_credential(session_id, decl.vault_path)
            if not isinstance(value, str):
                value = None
            try:
                if value is None:
                    value = await self._credential_registry.fetch(decl.vault_path)
                    self._sandbox_mgr.cache_credential(session_id, decl.vault_path, value)
            except KeyError:
                logger.warning(f"Credential {decl.vault_path} not found in vault during re-injection")
                continue
            if decl.base64:
                value = base64.b64decode(value).decode()
            if decl.env_var:
                env[decl.env_var] = value
            if decl.file:
                file_credentials.append(SkillFileCredential(path=decl.file, value=value))
        return SkillActivationInputs(environment=env, file_credentials=file_credentials)

    def _skill_command_aliases(self, skill_name: str) -> list[tuple[str, str]]:
        """Return validated command aliases declared by a skill."""
        registry = SkillRegistry(self._knowledge_dir / "skills")
        carapace_cfg = registry.get_carapace_config(skill_name)
        if not carapace_cfg:
            return []
        return [(command.name, command.command) for command in carapace_cfg.commands]

    def _credential_vault_paths_for_skill(self, session_id: str, skill_name: str) -> set[str]:
        """Vault paths allowed for file re-injection: that skill's context grant (from ``use_skill``)."""
        active = self._active.get(session_id)
        state = active.state if active else self._session_mgr.load_state(session_id)
        if not state:
            return set()
        grant = state.context_grants.get(skill_name)
        return grant.vault_paths if grant else set()

    def get_active(self, session_id: str) -> ActiveSession | None:
        """Return the ``ActiveSession`` if loaded, else ``None``."""
        return self._active.get(session_id)

    def update_active_state(self, session_id: str, **changes: Any) -> None:
        """Apply explicit field updates to the in-memory state for a loaded session."""
        active = self._active.get(session_id)
        if active is not None:
            for field_name, value in changes.items():
                if field_name not in SessionState.model_fields:
                    raise AttributeError(f"Unknown SessionState field: {field_name}")
                setattr(active.state, field_name, value)

    def is_agent_running(self, session_id: str) -> bool:
        active = self._active.get(session_id)
        return active is not None and active.agent_task is not None and not active.agent_task.done()

    def get_or_activate(self, session_id: str) -> ActiveSession:
        """Return (or load) the ``ActiveSession``."""
        return self._ensure_active(session_id)

    def deactivate(self, session_id: str) -> None:
        """Remove in-memory state when a session is no longer needed."""
        active = self._active.pop(session_id, None)
        if active and active.agent_task and not active.agent_task.done():
            active.agent_task.cancel()
        self._sandbox_mgr.set_domain_approval_callback(session_id, None)
        self._sandbox_mgr.set_domain_notify_callback(session_id, None)

    # -- subscribers --

    def subscribe(self, session_id: str, sub: SessionSubscriber) -> ActiveSession:
        """Attach a subscriber and return the ``ActiveSession``."""
        active = self._ensure_active(session_id)
        if sub not in active.subscribers:
            active.subscribers.append(sub)
        return active

    @contextlib.contextmanager
    def llm_request_recording(self, active: ActiveSession):
        engine = self
        session_id = active.state.session_id

        class Sink:
            async def on_request_started(self, state: LlmRequestState) -> None:
                active.llm_request_thinking.pop(state.request_id, None)
                await engine._set_llm_request_state(active, state)

            async def on_request_completed(self, record: LlmRequestRecord) -> None:
                thinking_content = active.llm_request_thinking.pop(record.request_id or "", "")
                if thinking_content:
                    thinking_event: dict[str, Any] = {
                        "role": "thinking",
                        "content": thinking_content,
                    }
                    if record.request_id:
                        thinking_event["request_id"] = record.request_id
                    row = usage_last_request_row(record)
                    if row is not None and row["reasoning_duration_ms"] is not None:
                        thinking_event["reasoning_duration_ms"] = row["reasoning_duration_ms"]
                    if row is not None and row["reasoning_tokens"] is not None:
                        thinking_event["reasoning_tokens"] = row["reasoning_tokens"]
                    engine._session_mgr.append_events(session_id, [thinking_event])
                active.llm_request_log.records.append(record)
                engine._session_mgr.save_llm_request_log(session_id, active.llm_request_log)
                await engine._clear_llm_request_state(active)

        with llm_request_sink_scope(Sink()):
            yield

    def unsubscribe(self, session_id: str, sub: SessionSubscriber) -> None:
        """Detach a subscriber.  Does NOT cancel agent work or destroy security."""
        active = self._active.get(session_id)
        if active:
            with contextlib.suppress(ValueError):
                active.subscribers.remove(sub)
            # When all subscribers disconnect and no task is running we can
            # flush usage to disk, but keep the active session alive.
            if not active.subscribers and (active.agent_task is None or active.agent_task.done()):
                self._session_mgr.save_usage(session_id, active.usage_tracker)
                self._session_mgr.save_llm_request_log(session_id, active.llm_request_log)
                if active.llm_request_state is not None:
                    self._session_mgr.save_llm_request_state(session_id, active.llm_request_state)

    # -- broadcasting helpers --

    async def _broadcast(
        self,
        active: ActiveSession,
        method: str,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        for sub in list(active.subscribers):
            try:
                await getattr(sub, method)(*args, **kwargs)
            except Exception as exc:
                logger.warning(f"Subscriber broadcast {method} failed: {exc}")

    # -- agent execution --

    def _build_deps(
        self,
        active: ActiveSession,
        *,
        tool_call_callback: ToolCallCallback | None = None,
        tool_result_callback: Callable[[ToolResult], None] | None = None,
    ) -> Deps:
        assert active.security is not None and active.sentinel is not None
        session_id = active.state.session_id

        def _append_session_events(events: list[dict[str, Any]]) -> None:
            self._session_mgr.append_events(session_id, events)

        return Deps(
            config=self._config,
            data_dir=self._data_dir,
            knowledge_dir=self._knowledge_dir,
            session_state=active.state,
            security=active.security,
            sentinel=active.sentinel,
            git_store=self._git_store,
            skill_catalog=self._skill_catalog,
            agent_model=active.agent_model or self._agent_model or self._resolve_model(self._config.agent.model),
            agent_model_id=active.agent_model_name or self._config.agent.model,
            verbose=active.verbose,
            tool_call_callback=tool_call_callback,
            tool_result_callback=tool_result_callback,
            append_session_events=_append_session_events,
            usage_tracker=active.usage_tracker,
            assert_llm_budget_available=lambda: self._assert_llm_budget_available(active),
            llm_usage_limits=lambda: self._remaining_aux_usage_limits(active),
            sandbox=self._sandbox_mgr,
            activated_skills=[],
            credential_registry=self._credential_registry,
        )

    async def submit_message(
        self,
        session_id: str,
        content: str,
        *,
        origin: SessionSubscriber | None = None,
    ) -> None:
        """Start an agent turn.  Safe to call from any channel."""
        active = self._ensure_active(session_id)

        if active.agent_task and not active.agent_task.done():
            await self._broadcast(active, "on_error", "Agent is busy — cancel first")
            return

        # Drain leftover approval responses
        while not active.tool_approval_queue.empty():
            active.tool_approval_queue.get_nowait()
        while not active.escalation_queue.empty():
            active.escalation_queue.get_nowait()

        active.agent_task = asyncio.create_task(
            self._run_turn(active, content, origin=origin),
            name=f"agent-turn-{session_id}",
        )

    async def retry_latest_turn(
        self,
        session_id: str,
        *,
        origin: SessionSubscriber | None = None,
    ) -> None:
        active = self._ensure_active(session_id)
        if active.agent_task and not active.agent_task.done():
            await self._broadcast(active, "on_error", "Agent is busy — cancel first")
            return

        events = self._truncate_incomplete_events(self._session_mgr.load_events(session_id))
        turns = self._completed_event_turns(events)
        if not turns:
            await self._broadcast(active, "on_error", "No completed turn available to retry")
            return

        target = turns[-1]
        self._rewrite_session_transcript(session_id, events[: target.start_event_index])
        await self.submit_message(session_id, target.user_content, origin=origin)

    async def reset_to_turn(self, session_id: str, event_index: int) -> bool:
        active = self._ensure_active(session_id)
        if active.agent_task and not active.agent_task.done():
            await self._broadcast(active, "on_error", "Agent is busy — cancel first")
            return False

        events = self._truncate_incomplete_events(self._session_mgr.load_events(session_id))
        turns = self._completed_event_turns(events)
        target = next((turn for turn in turns if turn.end_event_index == event_index), None)
        if target is None:
            await self._broadcast(active, "on_error", "Unknown reset target")
            return False

        self._rewrite_session_transcript(session_id, events[: target.end_event_index + 1])
        return True

    def fork_session(
        self,
        session_id: str,
        *,
        event_index: int,
        channel_type: str,
        channel_ref: str = "",
    ) -> SessionState:
        active = self._ensure_active(session_id)
        if active.agent_task and not active.agent_task.done():
            msg = "Agent is busy — cancel first"
            raise RuntimeError(msg)

        source_state = active.state.model_copy(deep=True)
        events = self._truncate_incomplete_events(self._session_mgr.load_events(session_id))
        turns = self._completed_event_turns(events)
        target = next((turn for turn in turns if turn.end_event_index == event_index), None)
        if target is None:
            msg = "Unknown fork target"
            raise ValueError(msg)

        forked_events = events[: target.end_event_index + 1]
        turn_count = len(self._completed_event_turns(forked_events))
        history = self._truncate_incomplete_model_history(self._session_mgr.load_history(session_id))
        forked_history = self._history_for_completed_turn_count(history, turn_count)

        now = datetime.now(tz=UTC)
        forked_session_id = f"{now:%Y-%m-%d-%H-%M}-{secrets.token_hex(4)}"
        forked_state = source_state.model_copy(
            deep=True,
            update={
                "session_id": forked_session_id,
                "channel_type": channel_type,
                "channel_ref": channel_ref or None,
                "title": f"{source_state.title} (Copy)" if source_state.title else None,
                "created_at": now,
                "last_active": now,
                "knowledge_last_committed_at": None,
                "knowledge_last_archive_path": None,
                "knowledge_last_export_hash": None,
                "knowledge_last_commit_trigger": None,
            },
        )

        self._session_mgr.save_state(forked_state)
        self._session_mgr.save_events(forked_session_id, forked_events)
        self._session_mgr.save_history(forked_session_id, forked_history)
        self._session_mgr.clear_llm_request_state(forked_session_id)
        self._session_mgr.clear_sandbox_snapshot(forked_session_id)
        return forked_state

    async def submit_cancel(self, session_id: str) -> None:
        """Cancel the running agent turn for *session_id*."""
        active = self._active.get(session_id)
        if not active:
            return
        if active.agent_task and not active.agent_task.done():
            active.agent_task.cancel()
            active.tool_approval_queue.put_nowait(None)
            active.escalation_queue.put_nowait(None)
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await active.agent_task
            active.agent_task = None

    async def submit_approval(
        self,
        session_id: str,
        response: ApprovalResponse | EscalationResponse,
    ) -> None:
        """Forward an approval / escalation response to the running turn."""
        active = self._active.get(session_id)
        if active:
            if isinstance(response, ApprovalResponse):
                active.tool_approval_queue.put_nowait(response)
            else:
                active.escalation_queue.put_nowait(response)

    # -- slash commands --

    async def handle_slash_command(self, session_id: str, command: str) -> dict[str, Any] | None:
        """Process a slash command, return structured data or ``None``."""
        active = self._active.get(session_id)
        if not active:
            return None

        parts = command.strip().split(maxsplit=1)
        cmd = parts[0].lower()

        if cmd == "/help":
            return {"command": "help", "data": {"commands": SLASH_COMMANDS}}

        if cmd == "/security":
            security_path = self._knowledge_dir / "SECURITY.md"
            policy = security_path.read_text() if security_path.exists() else "(no SECURITY.md loaded)"
            log_count = len(active.security.action_log) if active.security else 0
            eval_count = active.security.sentinel_eval_count if active.security else 0
            return {
                "command": "security",
                "data": {
                    "policy_preview": policy[:500] + ("..." if len(policy) > 500 else ""),
                    "action_log_entries": log_count,
                    "sentinel_evaluations": eval_count,
                },
            }

        if cmd == "/approve-context":
            if active.security:
                active.security.append(UserVouchedEntry())
            return {
                "command": "approve-context",
                "data": {"message": "Recorded: you vouch for the current agent context as trustworthy."},
            }

        if cmd == "/session":
            grants_summary = context_grants_session_summary(
                session_id,
                active.state.context_grants,
                self._sandbox_mgr.get_cached_credential,
            )
            return {
                "command": "session",
                "data": {
                    "session_id": session_id,
                    "channel_type": active.state.channel_type,
                    "context_grants": grants_summary,
                    "allowed_domains": self._sandbox_mgr.get_domain_info(session_id),
                },
            }

        if cmd == "/skills":
            skills = [{"name": s.name, "description": s.description.strip()} for s in self._skill_catalog]
            return {"command": "skills", "data": skills}

        if cmd == "/memory":
            store = MemoryStore(self._knowledge_dir)
            files = store.list_files()
            return {"command": "memory", "data": files}

        if cmd == "/retitle":
            arg = parts[1].strip() if len(parts) > 1 else ""
            if arg:
                active.state.title = arg
                self._session_mgr.save_state(active.state)
                await self._broadcast(active, "on_title_update", arg)
                return {"command": "retitle", "data": {"message": f"Title set to: {arg}"}}
            events = list(self._session_mgr.load_events(session_id))
            new_title = await self._generate_title(active, events)
            if not new_title:
                return {
                    "command": "retitle",
                    "data": {"message": "Could not generate a title (no eligible messages yet, or generation failed)."},
                }
            return {"command": "retitle", "data": {"message": f"Title: {new_title}"}}

        if cmd == "/models":
            return self._handle_models_command(active)

        if cmd == "/model":
            return self._handle_model_all_command(
                active,
                parts[1].strip() if len(parts) > 1 else "",
            )

        if cmd in ("/model-agent", "/model-sentinel", "/model-title"):
            model_map: dict[str, ModelType] = {
                "/model-agent": "agent",
                "/model-sentinel": "sentinel",
                "/model-title": "title",
            }
            model_type = model_map[cmd]
            return await self._handle_model_command(
                active,
                model_type,
                parts[1].strip() if len(parts) > 1 else "",
                slash_line=command.strip(),
            )

        if cmd == "/usage":
            tracker = active.usage_tracker
            costs = tracker.estimated_cost()
            cat_costs = tracker.estimated_category_cost()
            return {
                "command": "usage",
                "data": {
                    "models": {k: v.model_dump() for k, v in tracker.models.items()},
                    "categories": {k: v.model_dump() for k, v in tracker.categories.items()},
                    "total_input": tracker.total_input,
                    "total_output": tracker.total_output,
                    "costs": {k: str(v) for k, v in costs.items()},
                    "category_costs": {k: str(v) for k, v in cat_costs.items()},
                    "budget_gauges": [g.model_dump(mode="json") for g in self._budget_gauges(active)],
                    "last_llm_agent": self._usage_last_llm_payload_row(active, "agent"),
                    "last_llm_sentinel": self._usage_last_llm_payload_row(active, "sentinel"),
                },
            }

        if cmd == "/budget":
            if len(parts) == 1:
                return {"command": "budget", "data": self._budget_command_payload(active)}

            args = parts[1].strip().split(maxsplit=1)
            if len(args) != 2 or args[0] not in ("input", "output", "cost"):
                return {
                    "command": "budget",
                    "data": {
                        **self._budget_command_payload(active),
                        "error": "Usage: /budget, /budget input N, /budget output N, or /budget cost N",
                    },
                }

            metric = args[0]
            try:
                value = self._parse_budget_limit_value(metric, args[1].strip())
            except ValueError as exc:
                return {
                    "command": "budget",
                    "data": {**self._budget_command_payload(active), "error": str(exc)},
                }
            message = self._set_budget_metric(active, metric, value)
            return {
                "command": "budget",
                "data": self._budget_command_payload(active, message=message),
            }

        if cmd == "/pull":
            return await self._handle_pull_command()

        if cmd == "/push":
            return await self._handle_push_command()

        if cmd == "/reload":
            return await self._handle_reload_command(session_id)

        return None

    # -- pull / push from/to remote --

    async def _handle_push_command(self) -> dict[str, Any]:
        """Handle the ``/push`` slash command — push to external remote."""
        if not self._config.git.remote:
            return {"command": "push", "data": {"message": "No external remote configured."}}
        try:
            await self._git_store.push_to_remote()
            return {"command": "push", "data": {"message": "Pushed to external remote."}}
        except Exception as exc:
            return {"command": "push", "data": {"message": f"Push failed: {exc}"}}

    async def _handle_pull_command(self) -> dict[str, Any]:
        """Handle the ``/pull`` slash command — pull from external remote."""
        if not self._config.git.remote:
            return {"command": "pull", "data": {"message": "No external remote configured."}}
        try:
            summary = await self._git_store.pull_from_remote()
            # Re-scan skills after pull
            registry = SkillRegistry(self._knowledge_dir / "skills")
            self._skill_catalog = registry.scan()
            return {"command": "pull", "data": {"message": summary}}
        except RuntimeError as exc:
            return {"command": "pull", "data": {"message": f"Pull failed: {exc}"}}

    async def _handle_reload_command(self, session_id: str) -> dict[str, Any]:
        """Handle the ``/reload`` slash command — reset the sandbox completely."""
        try:
            await self._sandbox_mgr.reset_session(session_id)
            return {
                "command": "reload",
                "data": {
                    "message": ("Sandbox reset. A fresh workspace will be created from Git on the next command."),
                },
            }
        except Exception as exc:
            return {"command": "reload", "data": {"message": f"Reload failed: {exc}"}}

    # -- model switching --

    _MODEL_TYPES: tuple[ModelType, ...] = ("agent", "sentinel", "title")

    def _handle_models_command(self, active: ActiveSession) -> dict[str, Any]:
        """Show all model types with their current and default values."""
        models = self._models_slash_view(active)
        available = [e.model_dump(mode="json", by_alias=True) for e in self.available_model_entries]
        return {"command": "models", "data": {"models": models, "available": available}}

    def _models_slash_view(self, active: ActiveSession) -> dict[str, dict[str, str]]:
        defaults = {
            "agent": self._config.agent.model,
            "sentinel": self._config.agent.sentinel_model,
            "title": self._config.agent.title_model,
        }
        overrides = {
            "agent": active.agent_model_name,
            "sentinel": active.sentinel_model_name,
            "title": active.title_model_name,
        }
        return {t: {"current": overrides[t] or defaults[t], "default": defaults[t]} for t in self._MODEL_TYPES}

    def _handle_model_all_command(self, active: ActiveSession, arg: str) -> dict[str, Any]:
        """Process ``/model [MODEL | reset]`` — show or set all three model roles at once."""
        defaults = {
            "agent": self._config.agent.model,
            "sentinel": self._config.agent.sentinel_model,
            "title": self._config.agent.title_model,
        }
        models_view = self._models_slash_view(active)

        if not arg:
            return {"command": "model", "data": {"models": models_view}}

        if arg == "reset":
            for mt in self._MODEL_TYPES:
                self._apply_model_override(active, mt, None, None)
            reset_view = {t: {"current": defaults[t], "default": defaults[t]} for t in self._MODEL_TYPES}
            return {
                "command": "model",
                "data": {"models": reset_view, "message": "Reset all models to defaults."},
            }

        try:
            new_model = self._resolve_model(arg)
        except Exception as exc:
            return {"command": "model", "data": {"models": models_view, "error": str(exc)}}

        self._apply_model_override(active, "agent", arg, new_model)
        self._apply_model_override(active, "sentinel", arg, None)
        self._apply_model_override(active, "title", arg, None)
        switched = {t: {"current": arg, "default": defaults[t]} for t in self._MODEL_TYPES}
        return {
            "command": "model",
            "data": {
                "models": switched,
                "message": f"Switched agent, sentinel, and title to: {arg}",
            },
        }

    async def _handle_model_command(
        self, active: ActiveSession, model_type: ModelType, arg: str, *, slash_line: str
    ) -> dict[str, Any]:
        """Process ``/model-(agent|sentinel|title) [MODEL | reset]``."""
        cmd_name = {"agent": "model-agent", "sentinel": "model-sentinel", "title": "model-title"}[model_type]
        defaults = {
            "agent": self._config.agent.model,
            "sentinel": self._config.agent.sentinel_model,
            "title": self._config.agent.title_model,
        }
        overrides = {
            "agent": active.agent_model_name,
            "sentinel": active.sentinel_model_name,
            "title": active.title_model_name,
        }
        default = defaults[model_type]
        current = overrides[model_type] or default

        # No argument — show current
        if not arg:
            return {"command": cmd_name, "data": {"current": current, "default": default}}

        # Reset
        if arg == "reset":
            self._apply_model_override(active, model_type, None, None)
            if model_type == "title":
                await self._regenerate_title(active, pending_user_line=slash_line)
            return {
                "command": cmd_name,
                "data": {"current": default, "default": default, "message": f"Reset to default: {default}"},
            }

        # Switch
        try:
            new_model = self._resolve_model(arg)
        except Exception as exc:
            return {"command": cmd_name, "data": {"current": current, "default": default, "error": str(exc)}}

        self._apply_model_override(active, model_type, arg, new_model if model_type == "agent" else None)
        if model_type == "title":
            await self._regenerate_title(active, pending_user_line=slash_line)
        return {
            "command": cmd_name,
            "data": {"current": arg, "default": default, "message": f"Switched to: {arg}"},
        }

    def _apply_model_override(
        self, active: ActiveSession, model_type: ModelType, name: str | None, model_obj: Model | None = None
    ) -> None:
        if model_type == "agent":
            active.agent_model = model_obj
            active.agent_model_name = name
        elif model_type == "sentinel":
            active.sentinel_model_name = name
            if active.sentinel:
                active.sentinel.set_model(name or self._config.agent.sentinel_model)
        elif model_type == "title":
            active.title_model_name = name

    async def _regenerate_title(self, active: ActiveSession, *, pending_user_line: str | None = None) -> None:
        """Regenerate the session title using the current title model.

        *pending_user_line* is the slash command line not yet persisted to events (e.g. first
        ``/model-title`` in a session).
        """
        session_id = active.state.session_id
        events = list(self._session_mgr.load_events(session_id))
        if pending_user_line:
            events.append({"role": "user", "content": pending_user_line})
        if events:
            await self._generate_title(active, events)

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
    ) -> str:
        contexts_raw = args.get("contexts")
        matching_args = match_args if match_args is not None else args
        event: dict[str, Any] = {
            "role": "tool_call",
            "tool": tool,
            "args": args,
            "detail": detail,
            "approval_source": approval_source,
            "approval_verdict": approval_verdict,
            "approval_explanation": approval_explanation,
        }
        if parent_tool_id is not None:
            event["parent_tool_id"] = parent_tool_id
        if isinstance(contexts_raw, list):
            event["contexts"] = list(contexts_raw)

        should_update_existing = approval_verdict is not None and approval_source in {"sentinel", "user"}

        def _mutate(events: list[dict[str, Any]]) -> str:
            if should_update_existing:
                for index in range(len(events) - 1, -1, -1):
                    existing = events[index]
                    if existing.get("role") != "tool_call":
                        continue
                    if existing.get("tool") != tool:
                        continue
                    if existing.get("parent_tool_id") != parent_tool_id:
                        continue
                    if existing.get("approval_source") != "sentinel":
                        continue
                    if existing.get("approval_verdict") not in (None, "escalate"):
                        continue
                    existing_args = existing.get("args")
                    if not isinstance(existing_args, dict):
                        continue
                    if any(existing_args.get(key) != value for key, value in matching_args.items()):
                        continue

                    tool_id = str(existing.get("tool_id") or uuid.uuid4())
                    events[index] = {**existing, **event, "tool_id": tool_id}
                    return tool_id

            tool_id = str(uuid.uuid4())
            events.append({**event, "tool_id": tool_id})
            return tool_id

        return self._session_mgr.update_events(session_id, _mutate)

    def _completed_event_turns(self, events: list[dict[str, Any]]) -> list[CompletedEventTurn]:
        turns: list[CompletedEventTurn] = []
        start_event_index: int | None = None
        user_content: str | None = None

        for index, event in enumerate(events):
            role = event.get("role")
            if role == "user" and isinstance(content := event.get("content"), str) and not content.startswith("/"):
                start_event_index = index
                user_content = content
            elif role == "assistant" and start_event_index is not None and user_content is not None:
                turns.append(
                    CompletedEventTurn(
                        start_event_index=start_event_index,
                        end_event_index=index,
                        user_content=user_content,
                    )
                )
                start_event_index = None
                user_content = None

        return turns

    def _completed_model_turn_end_indexes(self, messages: list[ModelMessage]) -> list[int]:
        turn_end_indexes: list[int] = []
        current_turn_start: int | None = None

        for index, message in enumerate(messages):
            has_user_prompt = isinstance(message, ModelRequest) and any(
                isinstance(part, UserPromptPart) and isinstance(part.content, str) for part in message.parts
            )
            if not has_user_prompt:
                continue
            if (
                current_turn_start is not None
                and index - 1 > current_turn_start
                and isinstance(messages[index - 1], ModelResponse)
            ):
                turn_end_indexes.append(index - 1)
            current_turn_start = index

        if (
            current_turn_start is not None
            and len(messages) - 1 > current_turn_start
            and isinstance(messages[-1], ModelResponse)
        ):
            turn_end_indexes.append(len(messages) - 1)

        return turn_end_indexes

    def _history_for_completed_turn_count(self, messages: list[ModelMessage], turn_count: int) -> list[ModelMessage]:
        if turn_count <= 0:
            return []

        turn_end_indexes = self._completed_model_turn_end_indexes(messages)
        if not turn_end_indexes:
            return []

        capped_turn_count = min(turn_count, len(turn_end_indexes))
        return messages[: turn_end_indexes[capped_turn_count - 1] + 1]

    def _rewrite_session_transcript(self, session_id: str, events: list[dict[str, Any]]) -> None:
        truncated_events = self._truncate_incomplete_events(events)
        turn_count = len(self._completed_event_turns(truncated_events))
        history = self._truncate_incomplete_model_history(self._session_mgr.load_history(session_id))
        truncated_history = self._history_for_completed_turn_count(history, turn_count)

        self._session_mgr.save_events(session_id, truncated_events)
        self._session_mgr.save_history(session_id, truncated_history)
        self._session_mgr.clear_llm_request_state(session_id)

        active = self._active.get(session_id)
        if active is not None:
            active.llm_request_state = None
            active.llm_request_thinking.clear()

    async def _generate_title(self, active: ActiveSession, events: list[dict[str, Any]]) -> str:
        session_id = active.state.session_id
        try:
            async with self._llm_semaphore:
                with self.llm_request_recording(active):
                    self._assert_llm_budget_available(active)
                    title = await generate_title(
                        events,
                        model=active.title_model_name or self._config.agent.title_model,
                        usage_tracker=active.usage_tracker,
                        before_llm_call=lambda: self._assert_llm_budget_available(active),
                        model_factory=self._model_factory,
                        model_settings=self._resolve_model_settings(
                            active.title_model_name or self._config.agent.title_model
                        ),
                        usage_limits=self._remaining_aux_usage_limits(active),
                    )
            if title:
                active.state.title = title
                self._session_mgr.save_state(active.state)
                self._session_mgr.save_usage(session_id, active.usage_tracker)
                await self._broadcast(active, "on_title_update", title, self._turn_usage_payload(active))
                return title
        except Exception as exc:
            logger.warning(f"Title generation failed for {session_id}: {exc}")
        return ""

    def _make_escalation_cb(
        self,
        active: ActiveSession,
    ) -> Callable[[str, str, dict[str, Any]], Awaitable[UserEscalationDecision]]:
        """Build a callback that broadcasts sentinel escalations (proxy domain or git push) to subscribers."""

        async def _escalate(session_id: str, subject: str, context: dict[str, Any]) -> UserEscalationDecision:
            request_id = secrets.token_hex(8)
            cmd = context.get("command", "")
            kind = context.get("kind", "domain_access")

            # Auto-deny stale pending escalations of the same kind+key.
            # This happens when an exec timeout killed git push but the old
            # escalation callback is still blocked on the queue.
            match_key = {"git_push": "ref", "credential_access": "vault_path"}.get(kind, "domain")
            match_val = context.get(match_key, subject)
            for old in list(active.pending_escalations):
                if old.get("kind") == kind and old.get(match_key) == match_val:
                    logger.info(f"Superseding stale {kind} escalation {old['request_id']} for {match_val}")
                    active.escalation_queue.put_nowait(
                        EscalationResponse(request_id=old["request_id"], decision="deny")
                    )

            if kind == "git_push":
                ref = context.get("ref", subject)
                explanation = context.get("explanation", "")
                changed_files: list[str] = context.get("changed_files", [])
                self._session_mgr.append_events(
                    session_id,
                    [
                        {
                            "role": "git_push_approval",
                            "request_id": request_id,
                            "ref": ref,
                            "explanation": explanation,
                            "changed_files": changed_files,
                        }
                    ],
                )
                active.pending_escalations.append(
                    {
                        "request_id": request_id,
                        "kind": "git_push",
                        "ref": ref,
                        "explanation": explanation,
                        "changed_files": changed_files,
                    }
                )
                await self._broadcast(
                    active, "on_git_push_approval_request", request_id, ref, explanation, changed_files
                )
            elif kind == "credential_access":
                vault_path = context.get("vault_path", subject)
                cred_name = context.get("name", vault_path)
                cred_desc = context.get("description", "")
                explanation = context.get("explanation", "")
                self._session_mgr.append_events(
                    session_id,
                    [
                        {
                            "role": "credential_approval",
                            "request_id": request_id,
                            "vault_paths": [vault_path],
                            "names": [cred_name],
                            "descriptions": [cred_desc],
                            "explanation": explanation,
                        }
                    ],
                )
                active.pending_escalations.append(
                    {
                        "request_id": request_id,
                        "kind": "credential_access",
                        "vault_path": vault_path,
                        "vault_paths": [vault_path],
                        "names": [cred_name],
                        "descriptions": [cred_desc],
                        "explanation": explanation,
                    }
                )
                await self._broadcast(
                    active,
                    "on_credential_approval_request",
                    request_id,
                    [vault_path],
                    [cred_name],
                    [cred_desc],
                    None,
                    explanation,
                )
            else:
                self._session_mgr.append_events(
                    session_id,
                    [{"role": "domain_access_approval", "request_id": request_id, "domain": subject, "command": cmd}],
                )
                active.pending_escalations.append(
                    {"request_id": request_id, "kind": "domain_access", "domain": subject, "command": cmd}
                )
                await self._broadcast(active, "on_domain_access_approval_request", request_id, subject, cmd)
            # Block until a subscriber responds
            while True:
                msg = await active.escalation_queue.get()
                if msg is None:
                    active.pending_escalations.clear()
                    return UserEscalationDecision(allowed=False)
                if msg.request_id == request_id:
                    decision = msg.decision
                    message = normalize_optional_message(msg.message)
                    event_roles = {
                        "git_push": "git_push_approval",
                        "credential_access": "credential_approval",
                    }
                    event_role = event_roles.get(kind, "domain_access_approval")
                    if kind == "credential_access":
                        vp = context.get("vault_path", subject)
                        response_event: dict[str, Any] = {
                            "role": event_role,
                            "request_id": request_id,
                            "vault_paths": [vp],
                            "decision": decision,
                            "decision_source": "user",
                            "message": message,
                        }
                    else:
                        response_event = {
                            "role": event_role,
                            "request_id": request_id,
                            "domain": subject,
                            "command": cmd,
                            "decision": decision,
                            "decision_source": "user",
                            "message": message,
                        }
                    self._session_mgr.append_events(session_id, [response_event])
                    active.pending_escalations = [
                        p for p in active.pending_escalations if p["request_id"] != request_id
                    ]
                    return UserEscalationDecision(allowed=decision != "deny", message=message)

        return _escalate

    def _make_domain_info_cb(
        self,
        active: ActiveSession,
    ) -> Callable[
        [
            str,
            str,
            ApprovalSource | None,
            ApprovalVerdict | None,
            str | None,
        ],
        None,
    ]:
        """Build a callback that broadcasts domain access decisions to subscribers."""
        session_id = active.state.session_id

        def _notify(
            domain: str,
            detail: str,
            approval_source: ApprovalSource | None = None,
            approval_verdict: ApprovalVerdict | None = None,
            approval_explanation: str | None = None,
        ) -> None:
            parent_id = active.security.current_parent_tool_id if active.security else None
            tool_id = self._record_tool_call_event(
                session_id,
                tool="proxy_domain",
                args={"domain": domain},
                detail=detail,
                approval_source=approval_source,
                approval_verdict=approval_verdict,
                approval_explanation=approval_explanation,
                parent_tool_id=parent_id,
            )
            task = asyncio.ensure_future(
                self._broadcast(
                    active,
                    "on_domain_info",
                    domain,
                    detail,
                    approval_source,
                    approval_verdict,
                    approval_explanation,
                    tool_id,
                    parent_id,
                )
            )
            active._pending_sends.add(task)
            task.add_done_callback(active._pending_sends.discard)

        return _notify

    def _make_push_info_cb(
        self,
        active: ActiveSession,
    ) -> Callable[
        [
            str,
            str,
            str,
            ApprovalSource | None,
            ApprovalVerdict | None,
            str | None,
        ],
        Awaitable[None],
    ]:
        """Build a callback that broadcasts git push decisions to subscribers."""
        session_id = active.state.session_id

        async def _notify(
            ref: str,
            decision: str,
            detail: str,
            approval_source: ApprovalSource | None = None,
            approval_verdict: ApprovalVerdict | None = None,
            approval_explanation: str | None = None,
        ) -> None:
            parent_id = active.security.current_parent_tool_id if active.security else None
            tool_id = self._record_tool_call_event(
                session_id,
                tool="git_push",
                args={"ref": ref, "decision": decision},
                detail=detail,
                approval_source=approval_source,
                approval_verdict=approval_verdict,
                approval_explanation=approval_explanation,
                parent_tool_id=parent_id,
                match_args={"ref": ref},
            )
            await self._broadcast(
                active,
                "on_git_push_info",
                ref,
                decision,
                detail,
                approval_source,
                approval_verdict,
                approval_explanation,
                tool_id,
                parent_id,
            )

        return _notify

    def _make_credential_info_cb(
        self,
        active: ActiveSession,
    ) -> Callable[
        [
            str,
            str,
            str,
            ApprovalSource | None,
            ApprovalVerdict | None,
            str | None,
        ],
        None,
    ]:
        """Build a callback that broadcasts credential access decisions to subscribers."""
        session_id = active.state.session_id

        def _notify(
            vault_path: str,
            name: str,
            detail: str,
            approval_source: ApprovalSource | None = None,
            approval_verdict: ApprovalVerdict | None = None,
            approval_explanation: str | None = None,
        ) -> None:
            parent_id = active.security.current_parent_tool_id if active.security else None
            tool_id = self._record_tool_call_event(
                session_id,
                tool="credential_access",
                args={"vault_path": vault_path, "name": name},
                detail=detail,
                approval_source=approval_source,
                approval_verdict=approval_verdict,
                approval_explanation=approval_explanation,
                parent_tool_id=parent_id,
                match_args={"vault_path": vault_path},
            )
            task = asyncio.ensure_future(
                self._broadcast(
                    active,
                    "on_credential_info",
                    vault_path,
                    name,
                    detail,
                    approval_source,
                    approval_verdict,
                    approval_explanation,
                    tool_id,
                    parent_id,
                )
            )
            active._pending_sends.add(task)
            task.add_done_callback(active._pending_sends.discard)

        return _notify

    def _make_domain_eval_cb(
        self,
        security: SessionSecurity,
        sentinel: Sentinel,
        active: ActiveSession,
    ) -> Callable[[str, str], Awaitable[bool]]:
        """Build a callback for SandboxManager.request_domain_approval."""

        async def _eval(domain: str, command: str) -> bool:
            with self.llm_request_recording(active):
                try:
                    return await security_mod.evaluate_domain_with(
                        security,
                        sentinel,
                        domain,
                        command,
                        usage_tracker=active.usage_tracker,
                        assert_llm_budget_available=lambda: self._assert_llm_budget_available(active),
                        usage_limits=self._remaining_aux_usage_limits(active),
                    )
                except SessionBudgetExceededError as exc:
                    logger.info(f"Session budget blocked domain evaluation for {active.state.session_id}: {exc}")
                    return False
                except UsageLimitExceeded as exc:
                    logger.info(f"Usage limits blocked domain evaluation for {active.state.session_id}: {exc}")
                    return False

        return _eval
