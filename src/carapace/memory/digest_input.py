"""Render the sources of a week or month digest into the text the digest model reads.

Each source starts with a header line (``=== session <id> ===``, ``=== week <key> ===``) whose id
is the ref the digest cites. Every text field is collapsed to one line, so model output from the
level below cannot forge a header and smuggle in a source that does not exist.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from ..usage import count_text_tokens
from .models import DigestFact, DigestRecord, ExtractionRecord, Fact

# Bump whenever the rendered digest material changes for the same sources. Like the extraction
# input version, a bump marks digests outdated; it must never make them stale (the coverage hash
# depends only on which source records a digest consumed, not on how they were rendered).
DIGEST_INPUT_FORMAT_VERSION = 1


class DigestInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    input_hash: str
    token_estimate: int
    input_format_version: int


def render_week_input(extractions: Sequence[ExtractionRecord]) -> DigestInput:
    """Render a week's current extractions, in the given (chronological session) order."""
    return _digest_input([_session_block(record) for record in extractions])


def render_month_input(week_digests: Sequence[DigestRecord]) -> DigestInput:
    """Render a month's current week digests, in the given (chronological) order."""
    return _digest_input([_week_block(record) for record in week_digests])


def _session_block(record: ExtractionRecord) -> str:
    extraction = record.extraction
    return _block(
        f"=== session {record.session_id} ===",
        [
            f"Abstract: {_one_line(extraction.abstract)}",
            _list("Outcomes", extraction.outcomes),
            _list("Open loops", extraction.open_loops),
            _list("On my mind", extraction.on_my_mind),
            _list("Facts", [_fact_line(fact) for fact in extraction.facts]),
            f"Tags: {', '.join(_one_line(tag) for tag in extraction.tags)}" if extraction.tags else "",
        ],
    )


def _week_block(record: DigestRecord) -> str:
    digest = record.digest
    return _block(
        f"=== week {record.period_key} ===",
        [
            f"Summary: {_one_line(digest.summary)}",
            # Theme refs point at sessions, which the month level never sees.
            _list("On my mind", [theme.theme for theme in digest.on_my_mind]),
            _list("Highlights", digest.highlights),
            _list("Open loops", digest.open_loops),
            _list("Learned", [_fact_line(fact) for fact in digest.learned]),
        ],
    )


def _fact_line(fact: Fact | DigestFact) -> str:
    # Only enum values go inside the brackets: free text there could close them early and forge
    # a `user_said` meta line for an observed fact.
    durability = f"dated until {fact.valid_until.isoformat()}" if fact.valid_until else fact.durability.value
    meta = [fact.category.value, fact.source_kind.value, f"{fact.confidence.value} confidence", durability]
    statement = f"{fact.subject}: {fact.statement}" if fact.subject else fact.statement
    return f"[{' · '.join(meta)}] {statement}"


def _list(title: str, items: Sequence[str]) -> str:
    return f"{title}:\n" + "\n".join(f"- {_one_line(item)}" for item in items) if items else ""


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _block(header: str, parts: list[str]) -> str:
    return "\n".join([header, *(part for part in parts if part)])


def _digest_input(blocks: list[str]) -> DigestInput:
    text = "\n\n".join(blocks)
    return DigestInput(
        text=text,
        input_hash=hashlib.sha256(text.encode()).hexdigest(),
        token_estimate=count_text_tokens(text),
        input_format_version=DIGEST_INPUT_FORMAT_VERSION,
    )
