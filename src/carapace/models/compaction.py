"""Compaction summary tree persisted alongside a session's history.

The model history (``SessionHistoryRow``) holds the compacted *cut*: folded turns are
replaced by a single marked synthetic user message, and large tool returns are
replaced by shorter summaries stamped on ``ToolReturnPart.metadata``. This module stores
the human/debug-facing summary nodes so the UI can render the folded turns' margin rail.

Folds roll: each node's summary covers every turn folded so far, and the model history holds
only the newest one. Earlier nodes stay so a rewind into the folded region can fall back to the
summary that was current at that point. Originals are never stored here — they remain in the
events transcript and git archive.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# Marker prefix on the synthetic assistant text that stands in for folded turns. Lets us
# detect (and never re-fold) a summary message in the model history without extra state.
FOLD_MARKER = "⟦compacted⟧"


class CompactionNode(BaseModel):
    """One fold summary: everything folded up to this fold, condensed for the model."""

    id: str
    summary: str
    # Originals behind the summary, including those behind the earlier summary it rolled up.
    orig_tokens: int = 0
    summary_tokens: int = 0
    created_at: datetime | None = None


class CompactionReport(BaseModel):
    """Outcome of one compaction: a `/compact` run (returned to the client) or an automatic one (``auto``).

    Token counts are local estimates without thinking parts.
    """

    mode: Literal["manual", "auto"]
    before_tokens: int = 0
    after_tokens: int = 0
    thinking_dropped: int = 0
    turns_folded: int = 0
    # Model responses folded; a fold inside a running turn folds steps without starting a new turn.
    steps_folded: int = 0
    tool_returns_compacted: int = 0
    message: str = ""

    @property
    def nothing_compacted(self) -> bool:
        return not (self.thinking_dropped or self.steps_folded or self.turns_folded or self.tool_returns_compacted)

    @property
    def saved_tokens(self) -> int:
        return max(0, self.before_tokens - self.after_tokens)


class CompactionPreviewToolOutput(BaseModel):
    tool_name: str
    tokens: int


class CompactionPreview(BaseModel):
    """Dry run of `/compact` from the pure planners: what it would compact, before any summary call.

    ``context_tokens`` is the provider-reported input of the last agent request, what the threshold is
    compared against; None before the first measured request or when it predates the last compaction.
    The other token counts are local estimates without thinking parts, like ``CompactionReport``. The
    summaries' sizes are unknown until they are written, so the estimate leaves them out.
    """

    context_tokens: int | None
    threshold_tokens: int
    context_window_tokens: int
    thinking_dropped: int
    turns_folded: int
    fold_tokens: int
    tool_outputs: list[CompactionPreviewToolOutput]
    estimated_tokens_without_summaries: int


class SessionCompaction(BaseModel):
    """The full compaction tree for a session (ordered oldest-first)."""

    nodes: list[CompactionNode] = Field(default_factory=list)

    def node(self, node_id: str) -> CompactionNode | None:
        return next((n for n in self.nodes if n.id == node_id), None)

    @property
    def total_orig_tokens(self) -> int:
        return sum(n.orig_tokens for n in self.nodes)

    @property
    def total_summary_tokens(self) -> int:
        return sum(n.summary_tokens for n in self.nodes)
