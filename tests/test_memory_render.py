from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

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
from carapace.memory.render import README, render_mirror


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


SESSION_MD = """\
---
kind: session
session_id: s-talos
week_key: 2026-W36
month_key: 2026-09
provenance:
  carapace_version: 0.158.7
  model: anthropic:claude-haiku-4-5
  prompt_version: a1b2c3d4e5f6
  input_format_version: 1
  input_hash: ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff
  input_tokens: 1200
  output_tokens: 300
  cost_usd: '0.0042'
  duration_ms: 2100
  task_id: 7
  created_at: '2026-09-08T07:12:00Z'
created_at: '2026-09-08T07:12:00Z'
---

# Session s-talos

The user planned the Talos upgrade of the home cluster.

## Outcomes

- Decided to upgrade the control plane first.

## Open loops

- Back up etcd before the upgrade.

## On my mind

- upgrading the home cluster to Talos 1.11

## Facts

### You

- The user prefers upgrading on weekends. _(user_said · medium confidence · durable · #2 · #9)_

### Surroundings

- **home cluster**: The home cluster runs Talos 1.10. _(observed · high confidence · dated until 2026-10-01 · #4)_

## Tags

`homelab` `talos`
"""

WEEK_MD = """\
---
kind: week
period_key: 2026-W36
coverage:
- source_id: s-talos
  source_hash: abc
- source_id: s-trip
  source_hash: def
coverage_hash: c0ffee
provenance:
  carapace_version: 0.158.7
  model: anthropic:claude-haiku-4-5
  prompt_version: a1b2c3d4e5f6
  input_format_version: 1
  input_hash: ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff
  input_tokens: 1200
  output_tokens: 300
  cost_usd: '0.0042'
  duration_ms: 2100
  task_id: 9
  created_at: '2026-09-08T07:12:00Z'
created_at: '2026-09-08T08:00:00Z'
---

# Week 2026-W36 (2026-08-31 to 2026-09-06)

Mostly homelab work.

## On my mind

- Talos upgrade ([s-talos](../sessions/2026/09/s-talos.md), s-trip)

## Open loops

- Back up etcd.

## Learned

### People

- **Anna**: Anna is the user's sister. _(user_said · high confidence · durable · s-trip)_
"""


def test_mirror_paths() -> None:
    files = render_mirror([EXTRACTION], [WEEK, MONTH])

    assert sorted(files) == [
        "memory/README.md",
        "memory/months/2026-09.md",
        "memory/sessions/2026/09/s-talos.md",
        "memory/weeks/2026-W36.md",
    ]
    assert files["memory/README.md"] == README


def test_session_file() -> None:
    assert render_mirror([EXTRACTION], [])["memory/sessions/2026/09/s-talos.md"] == SESSION_MD


def test_week_file_links_known_sessions_only() -> None:
    assert render_mirror([EXTRACTION], [WEEK])["memory/weeks/2026-W36.md"] == WEEK_MD


def test_month_file_links_weeks_and_omits_empty_sections() -> None:
    month = render_mirror([], [WEEK, MONTH])["memory/months/2026-09.md"]
    body = month.split("---\n\n", 1)[1]

    assert body == (
        "# Month 2026-09\n\n"
        "A homelab month.\n\n"
        "## On my mind\n\n"
        "- Talos upgrade ([2026-W36](../weeks/2026-W36.md))\n\n"
        "## Highlights\n\n"
        "- Upgraded the cluster.\n"
    )
    assert "kind: month\nperiod_key: 2026-09\n" in month


def test_week_title_crosses_year_boundary() -> None:
    week53 = WEEK.model_copy(update={"period_key": "2026-W53"})

    assert "# Week 2026-W53 (2026-12-28 to 2027-01-03)" in render_mirror([], [week53])["memory/weeks/2026-W53.md"]


def test_session_path_follows_month_key_not_extraction_date() -> None:
    # Extracted in September, but the session's week (and so its month) is in August.
    record = EXTRACTION.model_copy(update={"session_id": "s-aug", "week_key": "2026-W35", "month_key": "2026-08"})

    assert "memory/sessions/2026/08/s-aug.md" in render_mirror([record], [])


def test_rendering_is_deterministic() -> None:
    assert render_mirror([EXTRACTION], [WEEK, MONTH]) == render_mirror([EXTRACTION], [WEEK, MONTH])


def test_rejects_records_that_are_not_current() -> None:
    old = EXTRACTION.model_copy(update={"is_current": False})
    old_week = WEEK.model_copy(update={"is_current": False})

    with pytest.raises(ValueError, match="extraction 1, digest 3"):
        render_mirror([old], [old_week])
