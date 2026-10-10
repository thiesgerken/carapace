"""Which source records a digest consumed, and the hash that tells when that set changed.

Coverage names exact records (by id), not their content or rendering: a re-extraction produces a
new record even for identical input, and a digest input format bump must not make digests stale.
"""

from __future__ import annotations

import hashlib
import json

from .models import CoverageEntry, DigestRecord, ExtractionRecord


def week_coverage(extractions: list[ExtractionRecord]) -> list[CoverageEntry]:
    return [CoverageEntry(source_id=e.session_id, source_hash=str(e.id)) for e in extractions]


def month_coverage(week_digests: list[DigestRecord]) -> list[CoverageEntry]:
    return [CoverageEntry(source_id=d.period_key, source_hash=str(d.id)) for d in week_digests]


def coverage_hash(entries: list[CoverageEntry]) -> str:
    ordered = sorted((e.source_id, e.source_hash) for e in entries)
    return hashlib.sha256(json.dumps(ordered).encode()).hexdigest()
