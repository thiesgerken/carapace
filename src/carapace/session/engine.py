from __future__ import annotations

import asyncio
import base64
import contextlib
import secrets
import traceback
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

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
from pydantic_ai.models import Model, infer_model

import carapace.security as security_mod
from carapace.agent.loop import run_agent_turn
from carapace.git.store import GitStore
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
    format_denial_message,
    normalize_optional_message,
)
from carapace.security.sentinel import Sentinel
from carapace.session.manager import SessionManager
from carapace.session.titler import generate_title
from carapace.skills import SkillRegistry
from carapace.usage import (
    BudgetGauge,
    LlmRequestLog,
    LlmRequestRecord,
    LlmSource,
    SessionBudgetExceededError,
    UsageTracker,
    gauge_breakdown_pct_dict,
    last_record_for_source,
    llm_request_sink_scope,
    usage_budget_exceeded_error,
    usage_budget_gauges,
    usage_last_request_row,
)
from carapace.ws_models import (
    SLASH_COMMANDS,
    ApprovalRequest,
    ApprovalResponse,
    EscalationResponse,
    TurnUsage,
    TurnUsageBreakdownPct,
)

ModelType = Literal["agent", "sentinel", "title"]

_DEFAULT_CONTEXT_CAP_TOKENS = 200_000


def _non_slash_user_message_count(events: list[dict[str, Any]]) -> int:
    """Count user lines that are not slash commands (matches server slash-command routing)."""
    return sum(
        1
        for e in events
        if e.get("role") == "user" and isinstance(c := e.get("content"), str) and not c.startswith("/")
    )


def _truncate_for_log(text: str, limit: int = 160) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 3] + "..."


def _summarize_tool_args_for_log(args: dict[str, Any]) -> str:
    parts: list[str] = []
    for idx, key in enumerate(sorted(args)):
        if idx >= 4:
            parts.append("...")
            break
        value = args[key]
        if key == "command" and isinstance(value, str):
            parts.append(f"command={_truncate_for_log(value, 100)}")
        elif key == "contexts" and isinstance(value, list):
            parts.append(f"contexts={','.join(str(v) for v in value[:4])}")
        else:
            parts.append(f"{key}={_truncate_for_log(str(value), 60)}")
    return ", ".join(parts) if parts else "-"


def _summarize_tool_result_for_log(result: ToolResult) -> str:
    if not result.output:
        return "(no output)"
    output = result.output if isinstance(result.output, str) else str(result.output)
    first_line = output.splitlines()[0] if output.splitlines() else output
    return _truncate_for_log(first_line, 140)


# security_mod is still imported for evaluate_domain_with (used in domain approval callback)

# ---------------------------------------------------------------------------
# Subscriber protocol — channels (WebSocket, Matrix, …) implement this
# ---------------------------------------------------------------------------


@runtime_checkable
class SessionSubscriber(Protocol):
    async def on_user_message(self, content: str, *, from_self: bool) -> None: ...
    async def on_tool_call(
        self,
        tool: str,
        args: dict[str, Any],
        detail: str,
        approval_source: ApprovalSource | None = None,
        approval_verdict: ApprovalVerdict | None = None,
        approval_explanation: str | None = None,
        tool_id: str | None = None,
        parent_tool_id: str | None = None,
    ) -> None: ...
    async def on_tool_result(self, result: ToolResult) -> None: ...
    async def on_token(self, content: str) -> None: ...
    async def on_thinking_token(self, content: str) -> None: ...
    async def on_done(self, content: str, usage: TurnUsage, *, thinking: str | None = None) -> None: ...
    async def on_error(self, detail: str) -> None: ...
    async def on_cancelled(self) -> None: ...
    async def on_approval_request(self, req: ApprovalRequest) -> None: ...
    async def on_domain_access_approval_request(self, request_id: str, domain: str, command: str) -> None: ...
    async def on_git_push_approval_request(
        self, request_id: str, ref: str, explanation: str, changed_files: list[str]
    ) -> None: ...
    async def on_title_update(self, title: str, usage: TurnUsage | None = None) -> None: ...
    async def on_domain_info(
        self,
        domain: str,
        detail: str,
        approval_source: ApprovalSource | None = None,
        approval_verdict: ApprovalVerdict | None = None,
        approval_explanation: str | None = None,
        tool_id: str | None = None,
        parent_tool_id: str | None = None,
    ) -> None: ...
    async def on_git_push_info(
        self,
        ref: str,
        decision: str,
        detail: str,
        approval_source: ApprovalSource | None = None,
        approval_verdict: ApprovalVerdict | None = None,
        approval_explanation: str | None = None,
        tool_id: str | None = None,
        parent_tool_id: str | None = None,
    ) -> None: ...
    async def on_credential_info(
        self,
        vault_path: str,
        name: str,
        detail: str,
        approval_source: ApprovalSource | None = None,
        approval_verdict: ApprovalVerdict | None = None,
        approval_explanation: str | None = None,
        tool_id: str | None = None,
        parent_tool_id: str | None = None,
    ) -> None: ...
    async def on_credential_approval_request(
        self,
        request_id: str,
        vault_paths: list[str],
        names: list[str],
        descriptions: list[str],
        skill_name: str | None,
        explanation: str,
    ) -> None: ...


# ---------------------------------------------------------------------------
# ActiveSession — in-memory state for a session that is currently loaded
# ---------------------------------------------------------------------------


@dataclass
class ActiveSession:
    state: SessionState
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    security: SessionSecurity | None = None
    sentinel: Sentinel | None = None
    agent_task: asyncio.Task[None] | None = None
    subscribers: list[SessionSubscriber] = field(default_factory=list)
    tool_approval_queue: asyncio.Queue[ApprovalResponse | None] = field(default_factory=asyncio.Queue)
    escalation_queue: asyncio.Queue[EscalationResponse | None] = field(default_factory=asyncio.Queue)
    usage_tracker: UsageTracker = field(default_factory=UsageTracker)
    llm_request_log: LlmRequestLog = field(default_factory=LlmRequestLog)
    verbose: bool = True
    agent_model: Model | None = None
    agent_model_name: str | None = None
    sentinel_model_name: str | None = None
    title_model_name: str | None = None
    pending_approval_requests: list[dict[str, Any]] = field(default_factory=list)
    pending_escalations: list[dict[str, Any]] = field(default_factory=list)
    _pending_sends: set[asyncio.Task[Any]] = field(default_factory=set)


# ---------------------------------------------------------------------------
# SessionEngine — central owner of session lifecycle and agent execution
# ---------------------------------------------------------------------------


class SessionEngine:
    """Central session lifecycle manager.

    Owns all in-memory session state, security sessions, and agent execution.
    Channels (WebSocket, Matrix, …) subscribe to events and submit messages
    through this class.  Agent turns survive transport disconnects, and LLM
    concurrency is bounded by a shared semaphore.
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

    def _turn_usage_payload(self, active: ActiveSession) -> TurnUsage | None:
        rec_agent = last_record_for_source(active.llm_request_log, "agent")
        budget_gauges = self._budget_gauges(active)
        if rec_agent is None and not budget_gauges:
            return None
        bd = gauge_breakdown_pct_dict(rec_agent)
        return TurnUsage(
            input_tokens=rec_agent.input_tokens if rec_agent else 0,
            output_tokens=rec_agent.output_tokens if rec_agent else 0,
            breakdown_pct=TurnUsageBreakdownPct.model_validate(bd) if bd else None,
            model=self.agent_model_id_for_gauge(active),
            context_cap_tokens=self.agent_context_cap_for_gauge(active),
            budget_gauges=budget_gauges,
        )

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

    # -- session lifecycle --

    def _ensure_active(self, session_id: str) -> ActiveSession:
        """Return or create the in-memory ``ActiveSession`` for *session_id*."""
        if session_id in self._active:
            return self._active[session_id]

        state = self._session_mgr.resume_session(session_id)
        if state is None:
            raise KeyError(f"Session {session_id} not found on disk")

        audit_dir = self._data_dir / "sessions" / session_id
        security = SessionSecurity(session_id, audit_dir=audit_dir)
        sentinel = Sentinel(
            model=self._config.agent.sentinel_model,
            knowledge_dir=self._knowledge_dir,
            skills_dir=self._knowledge_dir / "skills",
            model_factory=self._model_factory,
        )
        usage_tracker = self._session_mgr.load_usage(session_id)
        llm_log = self._session_mgr.load_llm_request_log(session_id)

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
        session_id = active.state.session_id

        def sink(rec: LlmRequestRecord) -> None:
            active.llm_request_log.records.append(rec)
            self._session_mgr.save_llm_request_log(session_id, active.llm_request_log)

        with llm_request_sink_scope(sink):
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
    ) -> str:
        contexts_raw = args.get("contexts")
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

        should_update_pending = approval_source == "sentinel" and approval_verdict is not None
        if should_update_pending:
            events = self._session_mgr.load_events(session_id)
            for index in range(len(events) - 1, -1, -1):
                existing = events[index]
                if existing.get("role") != "tool_call":
                    continue
                if existing.get("tool") != tool or existing.get("args") != args:
                    continue
                if existing.get("parent_tool_id") != parent_tool_id:
                    continue
                if existing.get("approval_source") != "sentinel" or existing.get("approval_verdict") is not None:
                    continue

                tool_id = str(existing.get("tool_id") or uuid.uuid4())
                events[index] = {**existing, **event, "tool_id": tool_id}
                self._session_mgr.save_events(session_id, events)
                return tool_id

        tool_id = str(uuid.uuid4())
        self._session_mgr.append_events(session_id, [{**event, "tool_id": tool_id}])
        return tool_id

    # -- internal turn runner --

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
            latest_messages = [m for m in snapshot if isinstance(m, (ModelRequest, ModelResponse))]

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
                # Refresh state from disk (other channels may have updated it)
                fresh = self._session_mgr.resume_session(session_id)
                if fresh:
                    active.state = fresh

                deps = self._build_deps(
                    active,
                    tool_call_callback=_tool_call_cb,
                    tool_result_callback=_tool_result_cb,
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

                async def _send_approval(req: ApprovalRequest) -> None:
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

                async def _collect_approvals(
                    pending: set[str],
                ) -> dict[str, bool | ToolDenied]:
                    results: dict[str, bool | ToolDenied] = {}
                    responses: dict[str, ApprovalResponse] = {}
                    remaining = set(pending)
                    while remaining:
                        msg = await active.tool_approval_queue.get()
                        if msg is None:
                            for tid in remaining:
                                results[tid] = ToolDenied("Agent cancelled.")
                            break
                        if msg.tool_call_id in remaining:
                            responses[msg.tool_call_id] = msg
                            results[msg.tool_call_id] = (
                                True if msg.approved else ToolDenied(format_denial_message("user", msg.message))
                            )
                            remaining.discard(msg.tool_call_id)
                    # Store approval decisions in events for history reconstruction
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
                                    "message": normalize_optional_message(response.message)
                                    if response is not None
                                    else None,
                                }
                            ],
                        )
                    active.pending_approval_requests.clear()
                    return results

                async def _on_token(chunk: str) -> None:
                    await self._broadcast(active, "on_token", chunk)

                async def _on_thinking_token(chunk: str) -> None:
                    await self._broadcast(active, "on_thinking_token", chunk)

                async with self._llm_semaphore:
                    with self.llm_request_recording(active):
                        self._assert_llm_budget_available(active)
                        messages, output, thinking = await run_agent_turn(
                            user_input,
                            deps,
                            message_history,
                            send_approval_request=_send_approval,
                            collect_approvals=_collect_approvals,
                            on_token=_on_token,
                            on_thinking_token=_on_thinking_token,
                            on_messages_snapshot=lambda snapshot: _set_latest_messages(snapshot),
                            before_llm_call=lambda: self._assert_llm_budget_available(active),
                        )

                self._session_mgr.save_history(session_id, messages)
                self._session_mgr.save_state(active.state)
                self._session_mgr.save_usage(session_id, active.usage_tracker)
                self._session_mgr.save_llm_request_log(session_id, active.llm_request_log)
                events_to_append: list[dict[str, Any]] = []
                if thinking:
                    events_to_append.append({"role": "thinking", "content": thinking})
                events_to_append.append({"role": "assistant", "content": output})
                self._session_mgr.append_events(session_id, events_to_append)

                if output.startswith("Unexpected agent output type:"):
                    await self._broadcast(active, "on_error", output)
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

                # Generate a title after the 1st and 3rd non-slash user message
                events = self._session_mgr.load_events(session_id)
                if _non_slash_user_message_count(events) in (1, 3):
                    t = asyncio.create_task(
                        self._generate_title(active, events),
                        name=f"title-{session_id}",
                    )
                    active._pending_sends.add(t)
                    t.add_done_callback(active._pending_sends.discard)

        except asyncio.CancelledError:
            logger.info(f"Agent turn cancelled for session {session_id}")
            self._session_mgr.save_usage(session_id, active.usage_tracker)
            self._session_mgr.save_llm_request_log(session_id, active.llm_request_log)
            self._save_user_message_on_failure(
                session_id,
                user_input,
                latest_messages=latest_messages,
                terminal_message="The previous turn was interrupted before completion.",
            )
            await self._broadcast(active, "on_cancelled")
        except SessionBudgetExceededError as exc:
            logger.info(f"Session budget blocked LLM call for {session_id}: {exc}")
            self._session_mgr.save_usage(session_id, active.usage_tracker)
            self._session_mgr.save_llm_request_log(session_id, active.llm_request_log)
            self._save_user_message_on_failure(
                session_id,
                user_input,
                latest_messages=latest_messages,
                terminal_message=str(exc),
            )
            await self._broadcast(active, "on_error", str(exc))
        except UsageLimitExceeded as exc:
            sentinel_evals = active.security.sentinel_eval_count if active.security else 0
            logger.error(
                f"Turn usage-limit failure session={session_id} error={exc} "
                + f"llm_requests={len(active.llm_request_log.records)} "
                + f"sentinel_evals={sentinel_evals} prompt={_truncate_for_log(user_input)}"
            )
            self._save_user_message_on_failure(
                session_id,
                user_input,
                latest_messages=latest_messages,
                terminal_message="The previous turn failed before completion.",
            )
            await self._broadcast(active, "on_error", str(exc))
        except Exception:
            logger.exception(f"Agent error session={session_id} prompt={_truncate_for_log(user_input)}")
            self._save_user_message_on_failure(
                session_id,
                user_input,
                latest_messages=latest_messages,
                terminal_message="The previous turn failed before completion.",
            )
            await self._broadcast(active, "on_error", traceback.format_exc())
        finally:
            active.agent_task = None

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
            events.append({"role": "assistant", "content": terminal_message})
        self._session_mgr.save_events(session_id, events)

    def _truncate_incomplete_model_history(self, messages: list[ModelMessage]) -> list[ModelMessage]:
        pending_tool_calls: set[str] = set()
        safe_prefix_end = 0

        for idx, message in enumerate(messages):
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
                safe_prefix_end = idx + 1

        return messages[:safe_prefix_end]

    def _truncate_incomplete_events(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        tools_with_results = {
            e.get("tool") for e in events if e.get("role") == "tool_result" and isinstance(e.get("tool"), str)
        }
        pending_by_tool: dict[str, int] = {}
        safe_prefix_end = 0

        for idx, event in enumerate(events):
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
                safe_prefix_end = idx + 1

        return events[:safe_prefix_end]

    async def _generate_title(self, active: ActiveSession, events: list[dict[str, Any]]) -> str:
        session_id = active.state.session_id
        try:
            async with self._llm_semaphore:
                self._assert_llm_budget_available(active)
                title = await generate_title(
                    events,
                    model=active.title_model_name or self._config.agent.title_model,
                    usage_tracker=active.usage_tracker,
                    before_llm_call=lambda: self._assert_llm_budget_available(active),
                    model_factory=self._model_factory,
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
                    )
                except SessionBudgetExceededError as exc:
                    logger.info(f"Session budget blocked domain evaluation for {active.state.session_id}: {exc}")
                    return False

        return _eval
