"""Engine mixin: orchestrate manual `/compact` over a session's model history.

Runs the pure strategies from ``compaction`` with the configured compaction model, persists
the rewritten history + summary tree, annotates the events transcript for the UI, and reports
token savings. v1 is manual only — there is no automatic trigger.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from loguru import logger
from pydantic_ai.messages import ModelMessage
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import UsageLimits

from ..llm import with_prompt_cache
from ..models.compaction import CompactionNode, CompactionReport, SessionCompaction
from ..models.skills import SkillInfo
from ..prompt_prefix import shared_prompt_prefix
from ..usage import count_message_tokens, count_text_tokens
from .compaction import (
    AppliedToolReturn,
    apply_fold,
    apply_thinking_drop,
    apply_tool_return_compaction,
    find_tool_return_candidates,
    fold_render_text,
    make_fold_message,
    plan_fold,
    sentinel_fold_render_text,
    split_merged_requests,
    tool_return_compaction_region,
)
from .compaction_summarizer import (
    summarize_fold,
    summarize_sentinel_fold,
    summarize_sentinel_tool_output,
    summarize_tool_output,
)
from .manager import SessionManager
from .transcript import completed_event_turns, completed_model_turn_end_indexes, rebuild_model_history_from_events
from .types import ActiveSession

if TYPE_CHECKING:
    from ..models.config import Config

CompactionMode = Literal["all", "fold", "tools"]


class CompactionError(RuntimeError):
    """An agent compaction summary failed; the history stays as it was."""


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
        def sentinel_context_cap(self, active: ActiveSession) -> int: ...
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
            # The rewritten history breaks the conversation cache anyway, so the next turn
            # refreshes the frozen memory block at no extra cost.
            active.state.memory = None
            self._session_mgr.save_state(active.state)
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
        summary = await self._summarize(active, partial(summarize_fold, fold_render_text(plan.foldable)))
        folded_turns = len(completed_model_turn_end_indexes(plan.foldable))
        node = CompactionNode(
            id=uuid.uuid4().hex[:12],
            summary=summary,
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
        # The hot-zone size comes from the config unless the caller overrides it (e.g. `/compact tools N`).
        cfg = self._config.agent.compaction
        verbatim = cfg.verbatim_tool_turns if verbatim_tool_turns is None else max(0, verbatim_tool_turns)
        eligible_indexes = tool_return_compaction_region(history, verbatim_turns=verbatim)
        candidates = find_tool_return_candidates(
            history, floor_tokens=cfg.tool_output_floor_tokens, model_name=model_name, within_indexes=eligible_indexes
        )
        if not candidates:
            return history

        summaries = await _gather_cache_warm(
            [
                partial(self._summarize, active, partial(summarize_tool_output, c.tool_name, _text(c.content)))
                for c in candidates
            ]
        )
        applied = {
            c.tool_call_id: AppliedToolReturn(
                new_content=summary,
                orig_tokens=c.tokens,
                summary_tokens=count_text_tokens(summary, model_name=model_name),
            )
            for c, summary in zip(candidates, summaries, strict=True)
        }
        report.tool_returns_compacted = len(applied)
        _annotate_tool_result_events(events, applied)
        return apply_tool_return_compaction(history, applied)

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

        Same ladder and settings as the agent's `/compact`, with one sentinel evaluation as one turn.
        Summaries lead with the sentinel's *system_prompt* (incl. SECURITY.md) so they keep what
        matters for later verdicts. Every failure raises: the sentinel never evaluates uncompacted.
        """
        active = self._active[session_id]
        cfg = self._config.agent.compaction
        model_name = self.sentinel_model_id(active)
        before = count_message_tokens(messages, model_name=model_name)
        cap = self.sentinel_context_cap(active)
        if before * 100 < cap * cfg.sentinel_threshold_pct:
            return None

        compacted, thinking_dropped = apply_thinking_drop(split_merged_requests(messages))
        plan = plan_fold(compacted, keep_turns=cfg.keep_turns, model_name=model_name)
        if plan is not None:
            # Unlike agent folds, the earlier summary is folded again together with the newly folded
            # evaluations: one summary plus keep_turns evaluations is what bounds the conversation.
            summary = await self._run_summary_call(
                active,
                partial(summarize_sentinel_fold, sentinel_fold_render_text([*plan.lead_folds, *plan.foldable])),
                prompt_prefix=system_prompt,
            )
            compacted = [make_fold_message(summary), *plan.kept]

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
            f"Sentinel compaction session={session_id} tokens={before}->{after} cap={cap} "
            + f"folded={plan is not None} tool_returns={len(candidates)} thinking_dropped={thinking_dropped}"
        )
        return compacted


async def _gather_cache_warm(calls: list[Callable[[], Awaitable[str]]]) -> list[str]:
    """Run the first summary alone, then the rest concurrently.

    All summaries share one system prompt, so the first call writes the compaction model's prefix
    cache and the others read it instead of each paying their own cache write. Concurrency stays
    bounded by the shared LLM semaphore inside each call.
    """
    if not calls:
        return []
    first = await calls[0]()
    return [first, *await asyncio.gather(*(call() for call in calls[1:]))]


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
    """Drop fold nodes no longer present after a rewind."""
    keep = set(surviving_fold_ids)
    return SessionCompaction(nodes=[n for n in tree.nodes if n.id in keep])


def _annotate_folded_events(events: list[dict[str, Any]], count: int, node_id: str) -> None:
    """Tag the oldest *count* not-yet-folded event-turns with the fold node id (for UI badges)."""
    if count <= 0:
        return
    annotated = 0
    for turn in completed_event_turns(events):
        span = events[turn.start_event_index : turn.end_event_index + 1]
        # Skip only turns already folded — a tool-output annotation must not block folding.
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
            "orig_tokens": rep.orig_tokens,
            "summary_tokens": rep.summary_tokens,
        }
