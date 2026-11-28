"""The screenshot demo seed (scripts/seed_demo.py) hand-writes session events; keep it in step with the schema."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from carapace.config import resolve_user_knowledge_dir
from carapace.database.engine import create_engine_and_factory
from carapace.memory.store import MemoryStore
from carapace.models.config import DatabaseConfig
from carapace.server.history import HistoryMessage
from carapace.session.manager import SessionManager
from carapace.session.transcript import completed_event_turns, rebuild_model_history_from_events
from carapace.usage import CostSplit

_SEED_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "seed_demo.py"


def _load_seed_demo(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("CARAPACE_DATABASE_URL", raising=False)
    spec = importlib.util.spec_from_file_location("seed_demo", _SEED_SCRIPT)
    assert spec is not None and spec.loader is not None
    seed_demo = importlib.util.module_from_spec(spec)
    # Dataclasses resolve their string annotations through the module's sys.modules entry.
    monkeypatch.setitem(sys.modules, spec.name, seed_demo)
    spec.loader.exec_module(seed_demo)
    return seed_demo


def test_seed_refuses_a_data_dir_outside_the_temp_directory_unless_it_is_a_dev_stacks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_demo = _load_seed_demo(monkeypatch)
    (tmp_path / "tmp").mkdir()
    data_dir = (tmp_path / "data").resolve()
    data_dir.mkdir()
    monkeypatch.setattr(seed_demo.tempfile, "gettempdir", lambda: str(tmp_path / "tmp"))
    now = datetime(2026, 11, 9, 8, 0, tzinfo=UTC)

    with pytest.raises(SystemExit, match="must be inside"):
        seed_demo.seed(data_dir, now)
    seed_demo.seed(data_dir, now, dev_stack=True)

    _engine, session_factory = create_engine_and_factory(DatabaseConfig(), data_dir)
    assert SessionManager(session_factory, data_dir).list_sessions(user=seed_demo.DEMO_USER)


def test_seeded_demo_sessions_load_like_real_sessions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seed_demo = _load_seed_demo(monkeypatch)
    data_dir = tmp_path.resolve()
    now = datetime(2026, 11, 9, 8, 0, tzinfo=UTC)

    seed_demo.seed(data_dir, now)

    _engine, session_factory = create_engine_and_factory(DatabaseConfig(), data_dir)
    session_mgr = SessionManager(session_factory, data_dir)
    expected_ids = [demo.session_id for demo in seed_demo.demo_sessions(now)]
    assert sorted(session_mgr.list_sessions(user=seed_demo.DEMO_USER)) == sorted(expected_ids)
    for session_id in expected_ids:
        assert session_mgr.load_state(session_id) is not None
        events = session_mgr.load_events(session_id)
        for index, event in enumerate(events):
            HistoryMessage.model_validate({**event, "event_index": index})
        assert rebuild_model_history_from_events(events)
        # Every demo session ends a turn, except the two waiting on an open approval or escalation.
        if events[-1]["role"] not in ("approval_request", "credential_approval"):
            assert completed_event_turns(events)

    # The pancake turn's timeline joins the session's own requests: each once, nested in its span.
    records = session_mgr.load_llm_request_log("demo-pancake-recipe").records
    assert len({record.request_id for record in records}) == len(records)
    spans = {
        span.span_id: span for span in session_mgr.load_turn_spans("demo-pancake-recipe", seed_demo.PANCAKE_TURN_ID)
    }
    for record in records:
        if record.turn_id is not None:
            parent = spans[record.span_id]
            assert parent.started_at <= record.started_at and parent.ended_at >= record.completed_at

    # The memory demo bills one extraction on a paid model and one on the subscription.
    spend = MemoryStore(session_factory).spend(seed_demo.DEMO_USER, now)
    assert spend.cost == CostSplit(actual=Decimal("0.0214"), equivalent=Decimal("0.0600"))

    # The knowledge repo is set up like one the server bootstraps, so server-side commits work in it.
    repo = resolve_user_knowledge_dir(data_dir, seed_demo.DEMO_USER)
    assert (repo / "skills" / "flake.nix").is_file()
    identity = subprocess.run(["git", "config", "--local", "user.email"], cwd=repo, capture_output=True, text=True)
    assert identity.stdout.strip()
