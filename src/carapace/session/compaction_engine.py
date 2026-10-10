"""Engine mixin: orchestrate manual `/compact` over a session's model history.

Runs the pure strategies from ``compaction`` with the configured compaction model, persists
the rewritten history + summary tree, annotates the events transcript for the UI, and reports
token savings. v1 is manual only — there is no automatic trigger.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

from loguru import logger
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import UsageLimits

from ..models.compaction import CompactionNode, CompactionReport, SessionCompaction
from ..usage import count_message_tokens, count_text_tokens
from .compaction import (
    AppliedToolReturn,
    apply_fold,
    apply_thinking_drop,
    apply_tool_return_compaction,
    find_tool_return_candidates,
    fold_render_text,
    plan_fold,
    split_lead_folds,
)
from .compaction_summarizer import summarize_fold, summarize_tool_output
from .manager import SessionManager
from .transcript import completed_event_turns, completed_model_turn_end_indexes, rebuild_model_history_from_events
from .types import ActiveSession

if TYPE_CHECKING:
    from ..models.config import Config

CompactionMode = Literal["all", "fold", "tools"]


class SessionCompactionMixin:
    _config: Config
    _session_mgr: SessionManager
    _model_factory: Any
    _llm_semaphore: asyncio.Semaphore

    if TYPE_CHECKING:

        async def _broadcast(self, active: ActiveSession, method: str, *args: Any, **kwargs: Any) -> None: ...
        def _assert_llm_budget_available(self, active: ActiveSession) -> None: ...
        def _resolve_model_settings(self, name: str) -> ModelSettings | None: ...
        def _remaining_aux_usage_limits(self, active: ActiveSession) -> UsageLimits | None: ...
        def agent_model_id_for_gauge(self, active: ActiveSession) -> str: ...
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

        history = self._session_mgr.load_history(session_id)
        tree = self._session_mgr.load_compaction(session_id)
        events = list(self._session_mgr.load_events(session_id))
        before = count_message_tokens(history, model_name=model_name)

        report = CompactionReport(mode=mode, before_tokens=before, after_tokens=before)

        if mode == "all":
            history, report.thinking_dropped = apply_thinking_drop(history)

        if mode in ("all", "fold"):
            history = await self._do_fold(
                active, history, tree, events, keep=keep, model_name=model_name, report=report
            )

        if mode in ("all", "tools"):
            history = await self._do_tool_returns(
                active, history, events, model_name=model_name, report=report, verbatim_tool_turns=verbatim_tool_turns
            )

        report.after_tokens = count_message_tokens(history, model_name=model_name)

        nothing = report.thinking_dropped == 0 and report.turns_folded == 0 and report.tool_returns_compacted == 0
        report.message = (
            "Nothing to compact."
            if nothing
            else (
                f"Compacted {report.before_tokens:,}→{report.after_tokens:,} tokens "
                f"(folded {report.turns_folded} turns, summarized {report.tool_returns_compacted} tool outputs"
                f"{f', dropped {report.thinking_dropped} thinking parts' if report.thinking_dropped else ''})."
            )
        )

        if not nothing:
            self._session_mgr.save_history(session_id, history)
            self._session_mgr.save_compaction(session_id, tree)
            self._session_mgr.save_events(session_id, events)
            self._session_mgr.save_usage(session_id, active.usage_tracker)
            await self._broadcast(active, "on_compaction", report)

        logger.info(f"Compaction session={session_id} mode={mode} {report.message}")
        return report

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

    async def _do_fold(
        self,
        active: ActiveSession,
        history: list[Any],
        tree: SessionCompaction,
        events: list[dict[str, Any]],
        *,
        keep: int,
        model_name: str,
        report: CompactionReport,
    ) -> list[Any]:
        plan = plan_fold(history, keep_turns=keep, model_name=model_name)
        if plan is None or plan.is_empty:
            return history
        summary = await self._summarize(active, lambda **kw: summarize_fold(fold_render_text(plan.foldable), **kw))
        if not summary:
            logger.warning("Fold aborted: empty summary")
            return history
        folded_turns = len(completed_model_turn_end_indexes(plan.foldable))
        node = CompactionNode(
            id=uuid.uuid4().hex[:12],
            kind="fold",
            summary=summary,
            method="summarize",
            orig_tokens=plan.orig_tokens,
            summary_tokens=count_text_tokens(summary, model_name=model_name),
            source_turn_start=plan.source_turn_start,
            source_turn_end=plan.source_turn_end,
            created_at=datetime.now(UTC),
        )
        tree.nodes.append(node)
        report.turns_folded = folded_turns
        _annotate_folded_events(events, folded_turns, node.id)
        return apply_fold(plan, summary)

    async def _do_tool_returns(
        self,
        active: ActiveSession,
        history: list[Any],
        events: list[dict[str, Any]],
        *,
        model_name: str,
        report: CompactionReport,
        verbatim_tool_turns: int | None = None,
    ) -> list[Any]:
        # Only compact tool returns in the kept region, never inside a fold block, and never inside
        # the verbatim hot zone (the newest `verbatim_tool_turns` completed turns). The hot-zone size
        # comes from the config unless the caller overrides it (e.g. `/compact tools N`).
        cfg = self._config.agent.compaction
        verbatim = cfg.verbatim_tool_turns if verbatim_tool_turns is None else max(0, verbatim_tool_turns)
        _lead, rest = split_lead_folds(history)
        rest_offset = len(history) - len(rest)
        turn_ends = completed_model_turn_end_indexes(rest)
        if verbatim <= 0:
            cut = len(rest)
        elif len(turn_ends) <= verbatim:
            return history  # the entire kept region is within the verbatim hot zone
        else:
            cut = turn_ends[len(turn_ends) - verbatim - 1] + 1
        eligible_indexes = set(range(rest_offset, rest_offset + cut))
        candidates = find_tool_return_candidates(
            history, floor_tokens=cfg.tool_output_floor_tokens, model_name=model_name, within_indexes=eligible_indexes
        )
        if not candidates:
            return history

        # Concurrency is bounded by the shared LLM semaphore acquired inside _summarize.
        async def _one(cand: Any) -> tuple[str, AppliedToolReturn] | None:
            summary = await self._summarize(
                active, lambda **kw: summarize_tool_output(cand.tool_name, _text(cand.content), **kw)
            )
            if not summary or cand.tool_call_id is None:
                return None
            return cand.tool_call_id, AppliedToolReturn(
                new_content=summary,
                method="summarize",
                orig_tokens=cand.tokens,
                summary_tokens=count_text_tokens(summary, model_name=model_name),
            )

        results = await asyncio.gather(*[_one(c) for c in candidates])
        applied = {tid: rep for r in results if r is not None for tid, rep in [r]}
        if not applied:
            return history
        report.tool_returns_compacted = len(applied)
        _annotate_tool_result_events(events, applied)
        return apply_tool_return_compaction(history, applied)

    async def _summarize(self, active: ActiveSession, call: Any) -> str:
        """Run one summarization under the shared LLM semaphore + request log + budget guard."""
        try:
            async with self._llm_semaphore:
                with self.llm_request_recording(active, track_activity=False):
                    self._assert_llm_budget_available(active)
                    model = self._compaction_model(active)
                    return await call(
                        model=model,
                        usage_tracker=active.usage_tracker,
                        before_llm_call=lambda: self._assert_llm_budget_available(active),
                        model_factory=self._model_factory,
                        user=active.owner,
                        model_settings=self._resolve_model_settings(model),
                        usage_limits=self._remaining_aux_usage_limits(active),
                    )
        except Exception as exc:
            logger.warning(f"Compaction summary failed: {exc}")
            return ""


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        return "\n".join(_text(i) for i in content)
    return "" if content is None else str(content)


def fold_survival_for_events(events: list[dict[str, Any]]) -> tuple[list[str], int]:
    """Return ``(ordered surviving fold-node ids, count of folded event-turns)`` for *events*.

    Drives fold-aware reset/fork slicing: the ids appear oldest-first (matching the order of the
    leading fold messages in the model history), and the count is how many completed event-turns
    are represented by a fold rather than a verbatim turn.
    """
    fold_ids: list[str] = []
    folded_turns = 0
    for turn in completed_event_turns(events):
        span = events[turn.start_event_index : turn.end_event_index + 1]
        node_id = next(
            (
                e["compaction"]["folded_into"]
                for e in span
                if isinstance(e.get("compaction"), dict) and "folded_into" in e["compaction"]
            ),
            None,
        )
        if node_id is None:
            continue
        folded_turns += 1
        if node_id not in fold_ids:
            fold_ids.append(node_id)
    return fold_ids, folded_turns


def trim_compaction_tree(tree: SessionCompaction, surviving_fold_ids: list[str]) -> SessionCompaction:
    """Drop fold nodes (and consolidate nodes orphaned by them) no longer present after a rewind."""
    keep = set(surviving_fold_ids)
    nodes = [n for n in tree.nodes if n.id in keep or (n.kind == "consolidate" and set(n.children) <= keep)]
    return SessionCompaction(nodes=nodes)


def _annotate_folded_events(events: list[dict[str, Any]], count: int, node_id: str) -> None:
    """Tag the oldest *count* not-yet-folded event-turns with the fold node id (for UI badges)."""
    if count <= 0:
        return
    annotated = 0
    for turn in completed_event_turns(events):
        span = events[turn.start_event_index : turn.end_event_index + 1]
        # Skip only turns already folded — a tool-output annotation (method) must not block folding.
        if any(isinstance(e.get("compaction"), dict) and "folded_into" in e["compaction"] for e in span):
            continue
        for e in span:
            ann = e.get("compaction")
            ann = dict(ann) if isinstance(ann, dict) else {}
            ann["folded_into"] = node_id
            e["compaction"] = ann
        annotated += 1
        if annotated >= count:
            break


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
            "method": rep.method,
            "orig_tokens": rep.orig_tokens,
            "summary_tokens": rep.summary_tokens,
        }
