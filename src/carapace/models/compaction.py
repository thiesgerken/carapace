"""Compaction summary tree persisted alongside a session's history.

The model history (``SessionHistoryRow``) holds the compacted *cut*: folded turns are
replaced by a single marked synthetic user message, and large tool returns are
replaced by shorter summaries stamped on ``ToolReturnPart.metadata``. This module stores
the human/debug-facing summary nodes so the UI can render the folded turns' margin rail.

Originals are never stored here — they remain in the events transcript and git archive.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# Marker prefix on the synthetic assistant text that stands in for folded turns. Lets us
# detect (and never re-fold) a summary message in the model history without extra state.
FOLD_MARKER = "⟦compacted⟧"


class CompactionNode(BaseModel):
    """One fold summary: a contiguous run of original turns condensed for the model."""

    id: str
    summary: str
    orig_tokens: int = 0
    summary_tokens: int = 0
    # First/last completed-turn indexes (in the pre-fold model history) this node covers.
    source_turn_start: int = 0
    source_turn_end: int = 0
    created_at: datetime | None = None


class CompactionReport(BaseModel):
    """Outcome of one `/compact` run, returned to the client."""

    mode: Literal["all", "fold", "tools"]
    before_tokens: int = 0
    after_tokens: int = 0
    thinking_dropped: int = 0
    turns_folded: int = 0
    tool_returns_compacted: int = 0
    message: str = ""

    @property
    def saved_tokens(self) -> int:
        return max(0, self.before_tokens - self.after_tokens)


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
