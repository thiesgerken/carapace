"""Engine mixin: compact a session's model history, by `/compact` or automatically inside a run.

Runs the pure strategies from ``compaction`` with the configured compaction model, persists the
summary tree, annotates the events transcript for the UI, and reports token savings. `/compact`
also persists the rewritten history; inside a run the rewritten history is the run's own and is
persisted with the turn.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Coroutine
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from loguru import logger
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, ToolReturnPart, post_compaction_window
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import UsageLimits

from ..llm import ProviderCompaction, provider_compaction, with_prompt_cache
from ..models.compaction import CompactionNode, CompactionReport, SessionCompaction
from ..models.skills import SkillInfo
from ..prompt_prefix import shared_prompt_prefix
from ..usage import count_message_tokens, count_text_tokens
from .compaction import (
    AppliedToolReturn,
    FoldPlan,
    apply_fold,
    apply_thinking_drop,
    apply_tool_return_compaction,
    find_tool_return_candidates,
    fold_render_text,
    has_foreign_compaction,
    last_request_input_tokens,
    make_fold_message,
    newest_measured_response,
    plan_fold,
    plan_step_fold,
    sentinel_fold_render_text,
    split_merged_requests,
    strip_compaction_parts,
    strip_thinking,
    tool_return_compaction_region,
    user_prompt_count,
)
from .compaction_summarizer import (
    FOLD_INSTRUCTIONS,
    SENTINEL_FOLD_INSTRUCTIONS,
    summarize_fold,
    summarize_sentinel_fold,
    summarize_sentinel_tool_output,
    summarize_tool_output,
)
from .manager import SessionManager
from .transcript import (
    completed_event_turns,
    is_terminal_history_message,
    is_turn_prompt_event,
    is_turn_terminal_event,
    rebuild_model_history_from_events,
)
from .types import ActiveSession

if TYPE_CHECKING:
    from ..models.config import AvailableModelEntry, Config

CompactionMode = Literal["all", "fold", "tools"]


class CompactionError(RuntimeError):
    """Agent compaction failed; the history stays as it was."""


@dataclass(frozen=True, slots=True)
class _Fold:
    """A summarized fold, not yet persisted."""

    plan: FoldPlan
    summary: str


class SessionCompactionMixin:
    _active: dict[str, ActiveSession]
    _config: Config
    _session_mgr: SessionManager
    _model_factory: Any
    _llm_semaphore: asyncio.Semaphore

    if TYPE_CHECKING:

        async def _broadcast(self, active: ActiveSession, method: str, *args: Any, **kwargs: Any) -> None: ...
        def _assert_llm_budget_available(self, active: ActiveSession) -> None: ...
        def _knowledge_dir_for_session(self, session_id: str) -> Path: ...
        def _skill_catalog_for_session(self, session_id: str) -> list[SkillInfo]: ...
        def _resolve_model_settings(self, name: str) -> ModelSettings | None: ...
        def _remaining_aux_usage_limits(self, active: ActiveSession) -> UsageLimits | None: ...
        def agent_model_id_for_gauge(self, active: ActiveSession) -> str: ...
        def sentinel_model_id(self, active: ActiveSession) -> str: ...
        def compaction_threshold_for_model_id(self, model_id: str) -> int: ...
        def _model_entry(self, model_id: str) -> AvailableModelEntry | None: ...
        def llm_request_recording(
            self, active: ActiveSession, *, track_activity: bool = True
        ) -> AbstractContextManager[Any, bool | None]: ...

    def _compaction_model(self, active: ActiveSession) -> str:
        return active.compaction_model_name or self._config.agent.compaction_model or self._config.agent.title_model

    async def run_compaction(
        self,
        active: ActiveSession,
        *,
        mode: CompactionMode = "all",
        keep_turns: int | None = None,
        verbatim_tool_turns: int | None = None,
    ) -> CompactionReport:
        session_id = active.state.session_id
        cfg = self._config.agent.compaction
        keep = keep_turns if keep_turns is not None else cfg.keep_turns
        model_name = self.agent_model_id_for_gauge(active)

        verbatim = cfg.verbatim_tool_turns if verbatim_tool_turns is None else max(0, verbatim_tool_turns)

        history = self._session_mgr.load_history(session_id)
        before = _tokens(history, model_name)
        report = CompactionReport(mode=mode, before_tokens=before, after_tokens=before)
        fold: _Fold | None = None
        applied: dict[str, AppliedToolReturn] = {}

        if mode == "all":
            history, report.thinking_dropped = apply_thinking_drop(history)
        # Unlike the automatic ladder, `/compact` folds before it summarizes tool outputs: it runs
        # every rung anyway, and this way it never pays for summaries the fold would discard.
        if mode in ("all", "fold") and (plan := plan_fold(history, keep_turns=keep, model_name=model_name)):
            fold = await self._summarize_fold(active, plan)
            # The fold now covers what a provider compaction covered; the kept turns are originals.
            history = strip_compaction_parts(apply_fold(plan, fold.summary))
        if mode in ("all", "tools"):
            applied = await self._summarize_tool_returns(active, history, verbatim=verbatim, model_name=model_name)
            history = apply_tool_return_compaction(history, applied)

        report.after_tokens = _tokens(history, model_name)
        self._record_ladder(report, fold, applied)
        if not report.nothing_compacted:
            self._persist_compaction(active, fold=fold, applied=applied, model_name=model_name)
            self._session_mgr.save_history(session_id, history)
            if measured := newest_measured_response(history):
                active.state.compacted_through = measured.timestamp
            # The rewritten history misses the conversation cache on the next turn anyway, so that turn
            # refreshes the frozen memory block at no extra cost. Inside a run the miss happens right
            # away, and a refresh on the next turn would cost a second one.
            active.state.memory = None
            self._session_mgr.save_state(active.state)
            await self._broadcast(active, "on_compaction", report)
        logger.info(f"Compaction session={session_id} mode={mode} {report.message}")
        return report

    async def compact_during_run(
        self, active: ActiveSession, messages: list[ModelMessage]
    ) -> list[ModelMessage] | None:
        """The run's history compacted down to the target, or None while it stays below the threshold.

        Triggered by the provider-reported input tokens of the run's last measured request, against the
        agent model's compaction threshold, unless that measurement predates the last compaction. The
        ladder (thinking-drop, then tool outputs outside the hot zone, then a fold that may cut inside the
        running turn) stops once the history is below the target, half the threshold: the local estimate
        plus what the provider counted on top of it for the measured request. The caller persists the
        returned history with the turn; the tree and the event annotations are persisted here. Raises
        ``CompactionError`` when the history is above the threshold and nothing can be compacted: the
        turn must not continue past it silently.
        """
        session_id = active.state.session_id
        model_name = self.agent_model_id_for_gauge(active)
        threshold = self.compaction_threshold_for_model_id(model_name)
        measured = newest_measured_response(messages)
        if measured is None or measured.usage.input_tokens <= threshold:
            return None
        if active.state.compacted_through is not None and measured.timestamp <= active.state.compacted_through:
            return None  # measured before the last compaction (e.g. `/compact` between turns)

        # The provider counts what the local estimate cannot see: system prompt, tool definitions, its own
        # tokenizer. Carry that overhead into every target check, so a small window or a heavy prompt
        # cannot hide a history that is still too large.
        overhead = measured.usage.input_tokens - _sent_tokens(messages[: messages.index(measured)], model_name)
        history, report, fold, applied = await self._auto_ladder(
            active, split_merged_requests(messages), model_name=model_name, threshold=threshold, overhead=overhead
        )
        if report.nothing_compacted:
            raise CompactionError(
                f"Compaction failed: the last request used {measured.usage.input_tokens:,} input tokens "
                f"(threshold {threshold:,}) and nothing is left to compact"
            )
        self._persist_compaction(active, fold=fold, applied=applied, model_name=model_name)
        active.state.compacted_through = measured.timestamp
        self._session_mgr.save_state(active.state)
        await self._broadcast(active, "on_compaction", report)
        logger.info(f"Compaction session={session_id} mode=auto threshold={threshold} {report.message}")
        return history

    async def history_for_agent_model(self, active: ActiveSession, history: list[ModelMessage]) -> list[ModelMessage]:
        """*history* ready for the session's agent model, before a turn starts.

        A provider reads back only its own ``CompactionPart``s, and only when it compacts server-side.
        Any other part is stripped (lossless, the originals are still there) and the local ladder runs
        once, regardless of the trigger: the newest measurement came from the compacted context, so it
        would understate what the new model is about to receive. The result is persisted right away, so
        a turn that fails early still matches the tree and the event annotations.
        """
        model_name = self.agent_model_id_for_gauge(active)
        provider = self.agent_provider_compaction(active)
        keep_provider = provider.provider_name if provider is not None else None
        if not has_foreign_compaction(history, keep_provider=keep_provider):
            return history
        session_id = active.state.session_id
        history, report, fold, applied = await self._auto_ladder(
            active,
            strip_compaction_parts(history, keep_provider=keep_provider),
            model_name=model_name,
            threshold=self.compaction_threshold_for_model_id(model_name),
            overhead=0,
        )
        self._persist_compaction(active, fold=fold, applied=applied, model_name=model_name)
        self._session_mgr.save_history(session_id, history)
        if measured := newest_measured_response(history):
            active.state.compacted_through = measured.timestamp
            self._session_mgr.save_state(active.state)
        logger.info(f"Compaction session={session_id} mode=provider-switch {report.message}")
        return history

    def agent_provider_compaction(self, active: ActiveSession) -> ProviderCompaction | None:
        """Server-side compaction for the agent model; a model without a catalog row compacts locally."""
        entry = self._model_entry(self.agent_model_id_for_gauge(active))
        return provider_compaction(entry, instructions=FOLD_INSTRUCTIONS) if entry is not None else None

    def sentinel_provider_compaction(self, model_id: str) -> ProviderCompaction | None:
        entry = self._model_entry(model_id)
        return provider_compaction(entry, instructions=SENTINEL_FOLD_INSTRUCTIONS) if entry is not None else None

    async def _auto_ladder(
        self, active: ActiveSession, history: list[ModelMessage], *, model_name: str, threshold: int, overhead: int
    ) -> tuple[list[ModelMessage], CompactionReport, _Fold | None, dict[str, AppliedToolReturn]]:
        """The automatic ladder down to the target (half the *threshold*), measuring what is sent plus *overhead*."""

        def above_target(messages: list[ModelMessage]) -> bool:
            return _sent_tokens(messages, model_name) + overhead > threshold // 2

        before = _tokens(history, model_name)
        report = CompactionReport(mode="auto", before_tokens=before, after_tokens=before)
        fold: _Fold | None = None
        applied: dict[str, AppliedToolReturn] = {}
        history, report.thinking_dropped = apply_thinking_drop(history)
        if above_target(history):
            applied = await self._summarize_tool_returns(
                active, history, verbatim=self._config.agent.compaction.verbatim_tool_turns, model_name=model_name
            )
            history = apply_tool_return_compaction(history, applied)
        if above_target(history) and (
            plan := plan_step_fold(history, keep_tokens=threshold // 4, model_name=model_name)
        ):
            fold = await self._summarize_fold(active, plan)
            history = apply_fold(plan, fold.summary)
        report.after_tokens = _tokens(history, model_name)
        self._record_ladder(report, fold, applied)
        return history, report, fold, applied

    def _record_ladder(
        self, report: CompactionReport, fold: _Fold | None, applied: dict[str, AppliedToolReturn]
    ) -> None:
        if fold is not None:
            report.turns_folded = user_prompt_count(fold.plan.foldable)
            report.steps_folded = sum(isinstance(m, ModelResponse) for m in fold.plan.foldable)
        report.tool_returns_compacted = len(applied)
        report.message = (
            "Nothing to compact."
            if report.nothing_compacted
            else (
                f"Compacted {report.before_tokens:,}→{report.after_tokens:,} tokens "
                f"(folded {report.turns_folded} turns, summarized {report.tool_returns_compacted} tool outputs"
                f"{f', dropped {report.thinking_dropped} thinking parts' if report.thinking_dropped else ''})."
            )
        )

    def _persist_compaction(
        self,
        active: ActiveSession,
        *,
        fold: _Fold | None,
        applied: dict[str, AppliedToolReturn],
        model_name: str,
    ) -> None:
        """Persist the tree and the event annotations of one compaction.

        Events are loaded only now, after every summary call, and written back without an await in
        between: events appended while the summaries ran (inside a run, e.g. escalations) survive.
        """
        session_id = active.state.session_id
        events = list(self._session_mgr.load_events(session_id))
        tree = self._session_mgr.load_compaction(session_id)
        _annotate_tool_result_events(events, applied)
        if fold is not None:
            # A fold rolls the previous summary up, so its node covers the originals behind both.
            earlier_tokens = tree.nodes[-1].orig_tokens if fold.plan.lead_folds and tree.nodes else 0
            node = CompactionNode(
                id=uuid.uuid4().hex[:12],
                summary=fold.summary,
                orig_tokens=earlier_tokens + fold.plan.orig_tokens,
                summary_tokens=count_text_tokens(fold.summary, model_name=model_name),
                created_at=datetime.now(UTC),
            )
            tree.nodes.append(node)
            _annotate_folded_events(events, fold.plan.foldable, node.id)
        self._session_mgr.save_compaction(session_id, tree)
        self._session_mgr.save_events(session_id, events)
        self._session_mgr.save_usage(session_id, active.usage_tracker)

    async def run_uncompaction(self, active: ActiveSession) -> dict[str, Any]:
        """Debug aid: rebuild the uncompacted model history from events and drop all compaction state.

        Reverses every fold and tool-output compaction by reconstructing the history from the
        (complete, append-only) event transcript, then clears the compaction tree and per-event
        annotations. Lossy only on thinking parts (never recorded as events; compaction drops them).
        """
        session_id = active.state.session_id
        model_name = self.agent_model_id_for_gauge(active)
        events = list(self._session_mgr.load_events(session_id))
        tree = self._session_mgr.load_compaction(session_id)

        had_annotations = any(isinstance(e.get("compaction"), dict) for e in events)
        if not tree.nodes and not had_annotations:
            return {"restored": False, "message": "Nothing to uncompact — this session is not compacted."}

        before = count_message_tokens(self._session_mgr.load_history(session_id), model_name=model_name)
        rebuilt = rebuild_model_history_from_events(events)
        after = count_message_tokens(rebuilt, model_name=model_name)
        for e in events:
            e.pop("compaction", None)

        self._session_mgr.save_history(session_id, rebuilt)
        self._session_mgr.save_compaction(session_id, SessionCompaction())
        self._session_mgr.save_events(session_id, events)

        message = f"Uncompacted {before:,}→{after:,} tokens — restored {len(rebuilt)} messages from the transcript."
        logger.info(f"Uncompaction session={session_id} {message}")
        return {"restored": True, "before_tokens": before, "after_tokens": after, "message": message}

    async def _summarize_fold(self, active: ActiveSession, plan: FoldPlan) -> _Fold:
        text = fold_render_text([*plan.lead_folds, *plan.foldable])
        return _Fold(plan=plan, summary=await self._summarize(active, partial(summarize_fold, text)))

    async def _summarize_tool_returns(
        self, active: ActiveSession, history: list[ModelMessage], *, verbatim: int, model_name: str
    ) -> dict[str, AppliedToolReturn]:
        """Summaries of the large tool outputs outside the newest *verbatim* turns, by tool call id."""
        candidates = find_tool_return_candidates(
            history,
            floor_tokens=self._config.agent.compaction.tool_output_floor_tokens,
            model_name=model_name,
            within_indexes=tool_return_compaction_region(history, verbatim_turns=verbatim),
        )
        summaries = await _gather_cache_warm(
            [
                partial(self._summarize, active, partial(summarize_tool_output, c.tool_name, _text(c.content)))
                for c in candidates
            ]
        )
        return {
            c.tool_call_id: AppliedToolReturn(
                new_content=summary,
                orig_tokens=c.tokens,
                summary_tokens=count_text_tokens(summary, model_name=model_name),
            )
            for c, summary in zip(candidates, summaries, strict=True)
        }

    async def _summarize(self, active: ActiveSession, call: Any) -> str:
        """Agent compaction summary, led by the agent's shared prompt prefix. Raises ``CompactionError``."""
        session_id = active.state.session_id
        prompt_prefix = shared_prompt_prefix(
            self._knowledge_dir_for_session(session_id), self._skill_catalog_for_session(session_id)
        )
        try:
            return await self._run_summary_call(active, call, prompt_prefix=prompt_prefix)
        # Wrapped, not swallowed: provider, budget and size errors alike abort `/compact` with a visible
        # message instead of tearing down the caller's connection.
        except Exception as exc:
            raise CompactionError(f"Compaction failed: {exc}") from exc

    async def _run_summary_call(self, active: ActiveSession, call: Any, *, prompt_prefix: str) -> str:
        """Run one summarization under the shared LLM semaphore + request log + budget guard."""
        async with self._llm_semaphore:
            with self.llm_request_recording(active, track_activity=False):
                self._assert_llm_budget_available(active)
                model = self._compaction_model(active)
                return await call(
                    prompt_prefix=prompt_prefix,
                    model=model,
                    config=self._config,
                    usage_tracker=active.usage_tracker,
                    before_llm_call=lambda: self._assert_llm_budget_available(active),
                    model_factory=self._model_factory,
                    user=active.owner,
                    model_settings=with_prompt_cache(self._resolve_model_settings(model), conversation=False),
                    usage_limits=self._remaining_aux_usage_limits(active),
                )

    async def compact_sentinel_conversation(
        self, session_id: str, messages: list[ModelMessage], system_prompt: str
    ) -> list[ModelMessage] | None:
        """The compacted shadow conversation, or None while it stays below the threshold.

        Triggered like the agent's automatic compaction: by the provider-reported input tokens of the
        last evaluation, against the sentinel model's compaction threshold. Then the full ladder with the
        agent's settings, one sentinel evaluation as one turn. Summaries lead with the sentinel's
        *system_prompt* (incl. SECURITY.md) so they keep what matters for later verdicts. Every failure
        raises: the sentinel never evaluates uncompacted.
        """
        active = self._active[session_id]
        cfg = self._config.agent.compaction
        model_name = self.sentinel_model_id(active)
        threshold = self.compaction_threshold_for_model_id(model_name)
        provider = self.sentinel_provider_compaction(model_name)
        keep_provider = provider.provider_name if provider is not None else None
        # A model that compacts server-side needs the ladder only after a provider switch: the stripped
        # conversation is the uncompacted one, and the old measurement would understate it.
        switched = has_foreign_compaction(messages, keep_provider=keep_provider)
        if not switched and (provider is not None or last_request_input_tokens(messages) <= threshold):
            return None
        messages = strip_compaction_parts(messages, keep_provider=keep_provider)
        before = _sent_tokens(messages, model_name)

        compacted, thinking_dropped = apply_thinking_drop(split_merged_requests(messages))
        plan = plan_fold(compacted, keep_turns=cfg.keep_turns, model_name=model_name)
        if plan is not None:
            summary = await self._run_summary_call(
                active,
                partial(summarize_sentinel_fold, sentinel_fold_render_text([*plan.lead_folds, *plan.foldable])),
                prompt_prefix=system_prompt,
            )
            compacted = apply_fold(plan, summary)

        candidates = find_tool_return_candidates(
            compacted,
            floor_tokens=cfg.tool_output_floor_tokens,
            model_name=model_name,
            within_indexes=tool_return_compaction_region(compacted, verbatim_turns=cfg.verbatim_tool_turns),
        )
        summaries = await _gather_cache_warm(
            [
                partial(
                    self._run_summary_call,
                    active,
                    partial(summarize_sentinel_tool_output, c.tool_name, _text(c.content)),
                    prompt_prefix=system_prompt,
                )
                for c in candidates
            ]
        )
        compacted = apply_tool_return_compaction(
            compacted,
            {
                c.tool_call_id: AppliedToolReturn(
                    new_content=summary,
                    orig_tokens=c.tokens,
                    summary_tokens=count_text_tokens(summary, model_name=model_name),
                )
                for c, summary in zip(candidates, summaries, strict=True)
            },
        )

        after = _sent_tokens(compacted, model_name)
        logger.info(
            f"Sentinel compaction session={session_id} tokens={before}->{after} threshold={threshold} "
            + f"switched={switched} folded={plan is not None} tool_returns={len(candidates)} "
            + f"thinking_dropped={thinking_dropped}"
        )
        return compacted


async def _gather_cache_warm(calls: list[Callable[[], Coroutine[Any, Any, str]]]) -> list[str]:
    """Run the first summary alone, then the rest concurrently; the first failure cancels the others.

    All summaries share one system prompt, so the first call writes the compaction model's prefix
    cache and the others read it instead of each paying their own cache write. Concurrency stays
    bounded by the shared LLM semaphore inside each call.
    """
    if not calls:
        return []
    first = await calls[0]()
    try:
        async with asyncio.TaskGroup() as group:
            tasks = [group.create_task(call()) for call in calls[1:]]
    except ExceptionGroup as failed:
        # Callers handle the call's own error (``CompactionError`` on the agent path), not a group.
        raise failed.exceptions[0] from None
    return [first, *(task.result() for task in tasks)]


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        return "\n".join(_text(i) for i in content)
    return "" if content is None else str(content)


def _sent_tokens(messages: list[ModelMessage], model_name: str) -> int:
    """Local token estimate of what is actually sent: nothing before the latest provider compaction."""
    return count_message_tokens(post_compaction_window(messages), model_name=model_name)


def _tokens(messages: list[ModelMessage], model_name: str) -> int:
    """``_sent_tokens`` without thinking, for reports: providers strip old thinking themselves, so counting
    it would overstate both the history and what dropping it saves."""
    return _sent_tokens(strip_thinking(messages), model_name)


@dataclass(frozen=True, slots=True)
class FoldSurvival:
    """What of the folded history an event prefix keeps (drives fold-aware reset/fork slicing)."""

    # Oldest first, so the last one is the newest surviving summary.
    fold_ids: list[str]
    # Completed event-turns a fold represents rather than verbatim history.
    folded_turns: int
    # The last folded turn is one a step fold cut in two: its tail is still verbatim history.
    split_turn: bool


def fold_survival_for_events(events: list[dict[str, Any]]) -> FoldSurvival:
    fold_ids: list[str] = []
    folded_turns = 0
    split_turn = False
    for turn in completed_event_turns(events):
        span = [e for e in events[turn.start_event_index : turn.end_event_index + 1] if _annotatable(e)]
        node_ids = [e["compaction"]["folded_into"] for e in span if _is_folded(e)]
        if not node_ids:
            continue
        folded_turns += 1
        split_turn = len(node_ids) < len(span)
        fold_ids += [node_id for node_id in dict.fromkeys(node_ids) if node_id not in fold_ids]
    return FoldSurvival(fold_ids=fold_ids, folded_turns=folded_turns, split_turn=split_turn)


def history_for_folded_cut_turn(
    tree: SessionCompaction, head_events: list[dict[str, Any]], turn_events: list[dict[str, Any]]
) -> tuple[list[ModelMessage], SessionCompaction] | None:
    """History and tree for a cut inside a turn a step fold reached, or None when no fold reached it.

    Every turn before it is folded too, so the history is the newest summary among the kept events'
    folds, then the turn's events no fold reached, rebuilt up to the cut (none if the cut lies inside
    the folded part). The kept events' annotations then all point at surviving nodes.
    """
    turn_folds = [e["compaction"]["folded_into"] for e in turn_events if _is_folded(e)]
    if not turn_folds:
        return None
    kept = trim_compaction_tree(tree, [*fold_survival_for_events(head_events).fold_ids, *turn_folds])
    unfolded = rebuild_model_history_from_events([e for e in turn_events if not _is_folded(e)])
    return [make_fold_message(kept.nodes[-1].summary), *unfolded], kept


def trim_compaction_tree(tree: SessionCompaction, surviving_fold_ids: list[str]) -> SessionCompaction:
    """Drop fold nodes no longer present after a rewind."""
    keep = set(surviving_fold_ids)
    return SessionCompaction(nodes=[n for n in tree.nodes if n.id in keep])


def _annotate_folded_events(events: list[dict[str, Any]], foldable: list[ModelMessage], node_id: str) -> None:
    """Tag the events of the newly folded region with the fold node id (UI rail, rewind/fork survival).

    The not-yet-folded events line up with the verbatim history in order, so everything up to the
    region's last event belongs to it. Slash commands between turns are not part of any turn.
    """
    end = _fold_end_event_index(events, foldable)
    for e in events[: end + 1]:
        if _is_folded(e) or not _annotatable(e):
            continue
        ann = e.get("compaction")
        e["compaction"] = {**(ann if isinstance(ann, dict) else {}), "folded_into": node_id}


def _fold_end_event_index(events: list[dict[str, Any]], foldable: list[ModelMessage]) -> int:
    """Index of the last event the folded region covers: its last tool result, its last turn prompt, or,
    when the region ends a turn, that turn's terminal event."""
    unfolded = [i for i, e in enumerate(events) if not _is_folded(e)]
    returned = {
        p.tool_call_id
        for m in foldable
        if isinstance(m, ModelRequest)
        for p in m.parts
        if isinstance(p, ToolReturnPart)
    }
    end = max(
        (
            i
            for i in unfolded
            if events[i].get("role") == "tool_result"
            and (events[i].get("model_tool_call_id") or events[i].get("tool_id")) in returned
        ),
        default=-1,
    )
    prompt_events = [i for i in unfolded if is_turn_prompt_event(events[i])]
    if prompts := user_prompt_count(foldable):
        if len(prompt_events) < prompts:
            raise CompactionError(f"Compaction failed: {prompts} turns folded, but only {len(prompt_events)} in events")
        end = max(end, prompt_events[prompts - 1])
    if is_terminal_history_message(foldable[-1]):
        start = max(end, unfolded[0] if unfolded else len(events))
        end = next((i for i in range(start, len(events)) if is_turn_terminal_event(events[i])), -1)
        if end < 0:
            raise CompactionError("Compaction failed: the folded region ends a turn the events never end")
    return end


def _annotatable(event: dict[str, Any]) -> bool:
    """Whether a fold covers *event*: slash commands, even those typed during a turn, belong to no turn."""
    return event.get("role") != "command" and (event.get("role") != "user" or is_turn_prompt_event(event))


def _is_folded(event: dict[str, Any]) -> bool:
    return isinstance(ann := event.get("compaction"), dict) and "folded_into" in ann


def _annotate_tool_result_events(events: list[dict[str, Any]], applied: dict[str, AppliedToolReturn]) -> None:
    # ``applied`` is keyed by the model's provider tool_call_id. Match it to the event's
    # ``model_tool_call_id`` (recorded alongside the carapace UUID ``tool_id``); fall back to
    # ``tool_id`` for legacy events / tests where the two ids coincide.
    for e in events:
        if e.get("role") != "tool_result":
            continue
        key = e.get("model_tool_call_id") or e.get("tool_id")
        if not isinstance(key, str):
            continue
        rep = applied.get(key)
        if rep is None:
            continue
        e["compaction"] = {
            "orig_tokens": rep.orig_tokens,
            "summary_tokens": rep.summary_tokens,
        }
