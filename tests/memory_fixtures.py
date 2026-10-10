"""Memory records shared by the render and digest input tests."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from carapace.memory.models import (
    CoverageEntry,
    DigestFact,
    DigestLevel,
    DigestRecord,
    DigestTheme,
    ExtractionRecord,
    Fact,
    PeriodDigest,
    Provenance,
    SessionExtraction,
)


def provenance(task_id: int) -> Provenance:
    return Provenance(
        carapace_version="0.158.7",
        model="anthropic:claude-haiku-4-5",
        prompt_version="a1b2c3d4e5f6",
        input_format_version=1,
        input_hash="f" * 64,
        input_tokens=1200,
        output_tokens=300,
        cost_usd=Decimal("0.0042"),
        duration_ms=2100,
        task_id=task_id,
        created_at=datetime(2026, 9, 8, 7, 12, tzinfo=UTC),
    )


EXTRACTION = ExtractionRecord(
    id=1,
    session_id="s-talos",
    week_key="2026-W36",
    month_key="2026-09",
    is_current=True,
    input_hash="f" * 64,
    provenance=provenance(7),
    created_at=datetime(2026, 9, 8, 7, 12, tzinfo=UTC),
    extraction=SessionExtraction(
        abstract="The user planned the Talos upgrade of the home cluster.",
        outcomes=["Decided to upgrade the control plane first."],
        open_loops=["Back up etcd before the upgrade."],
        on_my_mind=["upgrading the home cluster to Talos 1.11"],
        facts=[
            Fact(
                category="surroundings",
                statement="The home cluster runs Talos 1.10.",
                subject="home cluster",
                source_seqs=[4],
                source_kind="observed",
                confidence="high",
                durability="dated",
                valid_until=date(2026, 10, 1),
            ),
            Fact(
                category="user",
                statement="The user prefers upgrading on weekends.",
                source_seqs=[2, 9],
                source_kind="user_said",
                confidence="medium",
                durability="durable",
            ),
        ],
        friction=[],
        tags=["homelab", "talos"],
    ),
)

WEEK = DigestRecord(
    id=3,
    level=DigestLevel.week,
    period_key="2026-W36",
    is_current=True,
    coverage=[
        CoverageEntry(source_id="s-talos", source_hash="abc"),
        CoverageEntry(source_id="s-trip", source_hash="def"),
    ],
    coverage_hash="c0ffee",
    provenance=provenance(9),
    created_at=datetime(2026, 9, 8, 8, 0, tzinfo=UTC),
    digest=PeriodDigest(
        summary="Mostly homelab work.",
        on_my_mind=[DigestTheme(theme="Talos upgrade", refs=["s-talos", "s-trip"])],
        highlights=[],
        open_loops=["Back up etcd."],
        learned=[
            DigestFact(
                category="social",
                statement="Anna is the user's sister.",
                subject="Anna",
                source_kind="user_said",
                confidence="high",
                durability="durable",
                refs=["s-trip"],
            ),
        ],
    ),
)

MONTH = DigestRecord(
    id=4,
    level=DigestLevel.month,
    period_key="2026-09",
    is_current=True,
    coverage=[CoverageEntry(source_id="2026-W36", source_hash="123")],
    coverage_hash="beef",
    provenance=provenance(11),
    created_at=datetime(2026, 10, 1, 6, 0, tzinfo=UTC),
    digest=PeriodDigest(
        summary="A homelab month.",
        on_my_mind=[DigestTheme(theme="Talos upgrade", refs=["2026-W36"])],
        highlights=["Upgraded the cluster."],
        open_loops=[],
        learned=[],
    ),
)
