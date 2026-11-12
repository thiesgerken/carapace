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
from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, ToolReturnPart
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import UsageLimits

from ..llm import with_prompt_cache
from ..models.compaction import (
    CompactionNode,
    CompactionPreview,
    CompactionPreviewToolOutput,
    CompactionReport,
    SessionCompaction,
)
from ..models.skills import SkillInfo
from ..prompt_prefix import shared_prompt_prefix
from ..usage import count_message_tokens, count_text_tokens
from .compaction import (
    AppliedToolReturn,
    FoldPlan,
    LadderPlan,
    ToolReturnCandidate,
    apply_fold,
    apply_thinking_drop,
    apply_tool_return_compaction,
    find_tool_return_candidates,
    fold_render_text,
    last_request_input_tokens,
    plan_fold,
    plan_ladder,
    plan_step_fold,
    sentinel_fold_render_text,
    split_merged_requests,
    strip_thinking,
    tool_return_compaction_region,
    user_prompt_count,
)
from .compaction_summarizer import (
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
    from ..models.config import Config


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
        def agent_context_cap_for_gauge(self, active: ActiveSession) -> int: ...
        def llm_request_recording(
            self, active: ActiveSession, *, track_activity: bool = True
        ) -> AbstractContextManager[Any, bool | None]: ...

    def _compaction_model(self, active: ActiveSession) -> str:
        return active.compaction_model_name or self._config.agent.compaction_model or self._config.agent.title_model

    def _plan_ladder(self, active: ActiveSession, history: list[ModelMessage], model_name: str) -> LadderPlan:
        cfg = self._config.agent.compaction
        return plan_ladder(
            history,
            keep_turns=cfg.keep_turns,
            verbatim_turns=cfg.verbatim_tool_turns,
            floor_tokens=cfg.tool_output_floor_tokens,
            model_name=model_name,
        )

    def preview_compaction(self, active: ActiveSession) -> CompactionPreview:
        """What `/compact` would do right now, from the pure planners (no LLM call)."""
        model_name = self.agent_model_id_for_gauge(active)
        history = self._session_mgr.load_history(active.state.session_id)
        plan = self._plan_ladder(active, history, model_name)
        folded = apply_fold(plan.fold, "") if plan.fold is not None else plan.history
        candidate_tokens = sum(c.tokens for c in plan.tool_candidates)
        return CompactionPreview(
            context_tokens=_tokens(history, model_name),
            threshold_tokens=self.compaction_threshold_for_model_id(model_name),
            context_window_tokens=self.agent_context_cap_for_gauge(active),
            thinking_dropped=plan.thinking_dropped,
            turns_folded=user_prompt_count(plan.fold.foldable) if plan.fold is not None else 0,
            fold_tokens=plan.fold.orig_tokens if plan.fold is not None else 0,
            tool_outputs=[
                CompactionPreviewToolOutput(tool_name=c.tool_name, tokens=c.tokens) for c in plan.tool_candidates
            ],
            estimated_tokens_without_summaries=max(0, _tokens(folded, model_name) - candidate_tokens),
        )

    async def run_compaction(self, active: ActiveSession, *, focus: str | None = None) -> CompactionReport:
        """`/compact`: thinking-drop, fold, then tool outputs, with *focus* added to every summary request.

        Unlike the automatic ladder it folds before it summarizes tool outputs: it runs every rung
        anyway, and this way it never pays for summaries the fold would discard.
        """
        session_id = active.state.session_id
        model_name = self.agent_model_id_for_gauge(active)
        history = self._session_mgr.load_history(session_id)
        before = _tokens(history, model_name)
        report = CompactionReport(mode="manual", before_tokens=before, after_tokens=before)
        plan = self._plan_ladder(active, history, model_name)
        history, report.thinking_dropped = plan.history, plan.thinking_dropped
        fold: _Fold | None = None
        if plan.fold is not None:
            fold = await self._summarize_fold(active, plan.fold, focus=focus)
            history = apply_fold(plan.fold, fold.summary)
        applied = await self._summarize_candidates(active, plan.tool_candidates, model_name=model_name, focus=focus)
        history = apply_tool_return_compaction(history, applied)

        report.after_tokens = _tokens(history, model_name)
        self._record_ladder(report, fold, applied)
        if not report.nothing_compacted:
            self._persist_compaction(active, fold=fold, applied=applied, model_name=model_name)
            self._session_mgr.save_history(session_id, history)
            await self._broadcast(active, "on_compaction", report)
        logger.info(f"Compaction session={session_id} mode=manual focus={bool(focus)} {report.message}")
        return report

    async def compact_during_run(
        self, active: ActiveSession, messages: list[ModelMessage]
    ) -> list[ModelMessage] | None:
        """The run's history compacted down to the target, or None while it stays below the threshold.

        Triggered by the provider-reported input tokens of the run's last request, against the agent
        model's compaction threshold. The ladder (thinking-drop, then tool outputs outside the hot zone,
        then a fold that may cut inside the running turn) stops once the local estimate is below the
        target, half the threshold. The caller persists the returned history with the turn; the tree and
        the event annotations are persisted here. Raises ``CompactionError`` when the history is above
        the threshold and nothing can be compacted: the turn must not continue past it silently.
        """
        session_id = active.state.session_id
        model_name = self.agent_model_id_for_gauge(active)
        threshold = self.compaction_threshold_for_model_id(model_name)
        if last_request_input_tokens(messages) <= threshold:
            return None
        target = threshold // 2
        history = split_merged_requests(messages)
        before = _tokens(history, model_name)
        if before <= target:
            # The last request was measured before an earlier compaction (e.g. a `/compact` between turns).
            return None

        report = CompactionReport(mode="auto", before_tokens=before, after_tokens=before)
        fold: _Fold | None = None
        history, report.thinking_dropped = apply_thinking_drop(history)
        applied = await self._summarize_tool_returns(
            active, history, verbatim=self._config.agent.compaction.verbatim_tool_turns, model_name=model_name
        )
        history = apply_tool_return_compaction(history, applied)
        if _tokens(history, model_name) > target and (
            plan := plan_step_fold(history, keep_tokens=target // 2, model_name=model_name)
        ):
            fold = await self._summarize_fold(active, plan)
            history = apply_fold(plan, fold.summary)

        report.after_tokens = _tokens(history, model_name)
        self._record_ladder(report, fold, applied)
        if fold is None and not applied:
            raise CompactionError(
                f"Compaction failed: the last request used {last_request_input_tokens(messages):,} input tokens "
                f"(threshold {threshold:,}) and nothing is left to compact"
            )
        self._persist_compaction(active, fold=fold, applied=applied, model_name=model_name)
        await self._broadcast(active, "on_compaction", report)
        logger.info(f"Compaction session={session_id} mode=auto threshold={threshold} {report.message}")
        return history

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
        # The rewritten history breaks the conversation cache anyway, so the next turn
        # refreshes the frozen memory block at no extra cost.
        active.state.memory = None
        self._session_mgr.save_state(active.state)
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

    async def _summarize_fold(self, active: ActiveSession, plan: FoldPlan, *, focus: str | None = None) -> _Fold:
        text = fold_render_text([*plan.lead_folds, *plan.foldable])
        return _Fold(plan=plan, summary=await self._summarize(active, partial(summarize_fold, text, focus=focus)))

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
        return await self._summarize_candidates(active, candidates, model_name=model_name)

    async def _summarize_candidates(
        self,
        active: ActiveSession,
        candidates: list[ToolReturnCandidate],
        *,
        model_name: str,
        focus: str | None = None,
    ) -> dict[str, AppliedToolReturn]:
        summaries = await _gather_cache_warm(
            [
                partial(
                    self._summarize, active, partial(summarize_tool_output, c.tool_name, _text(c.content), focus=focus)
                )
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
        if last_request_input_tokens(messages) <= threshold:
            return None
        before = count_message_tokens(messages, model_name=model_name)

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

        after = count_message_tokens(compacted, model_name=model_name)
        logger.info(
            f"Sentinel compaction session={session_id} tokens={before}->{after} threshold={threshold} "
            + f"folded={plan is not None} tool_returns={len(candidates)} thinking_dropped={thinking_dropped}"
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


def _tokens(messages: list[ModelMessage], model_name: str) -> int:
    """Local token estimate without thinking: providers strip old thinking themselves, so counting it
    would overstate both the history and what dropping it saves."""
    return count_message_tokens(strip_thinking(messages), model_name=model_name)


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
