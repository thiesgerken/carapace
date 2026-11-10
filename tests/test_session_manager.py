"""Tests for SessionManager persistence and small session helpers."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from carapace.models.session import SessionAttributes, SessionBudget
from carapace.models.skills import ContextGrant, SkillCredentialDecl
from carapace.sandbox.state import SessionSandboxSnapshot
from carapace.security.context import (
    SessionSecurity,
    UserEscalationDecision,
    format_denial_message,
    normalize_optional_message,
)
from carapace.session import SessionManager
from carapace.usage import LlmRequestState


def test_create_session(tmp_path: Path, db_factory):
    mgr = SessionManager(db_factory, tmp_path)
    state = mgr.create_session(user="thies")
    assert len(state.session_id) == 25  # 2026-03-08-10-22-abcd1234
    assert state.channel_type == "cli"
    assert state.attributes == SessionAttributes()


def test_create_session_persists_budget(tmp_path: Path, db_factory):
    mgr = SessionManager(db_factory, tmp_path)
    budget = SessionBudget(input_tokens=1_000, cost_usd=Decimal("5.00"), tool_calls=4)
    state = mgr.create_session(user="thies", budget=budget)

    resumed = mgr.resume_session(state.session_id)
    assert resumed is not None
    assert resumed.budget.input_tokens == 1_000
    assert resumed.budget.cost_usd == Decimal("5.00")
    assert resumed.budget.tool_calls == 4


def test_create_session_persists_private_attribute(tmp_path: Path, db_factory):
    mgr = SessionManager(db_factory, tmp_path)
    state = mgr.create_session(user="thies", private=True)

    resumed = mgr.resume_session(state.session_id)
    assert resumed is not None
    assert resumed.attributes.private is True


def test_create_session_persists_access_modes(tmp_path: Path, db_factory) -> None:
    mgr = SessionManager(db_factory, tmp_path)
    state = mgr.create_session(user="thies", ask_mode=True)

    resumed = mgr.resume_session(state.session_id)
    assert resumed is not None
    assert resumed.attributes.ask_mode is True
    assert resumed.attributes.yolo_mode is False


def test_resume_session(tmp_path: Path, db_factory):
    mgr = SessionManager(db_factory, tmp_path)
    state = mgr.create_session(user="thies")
    resumed = mgr.resume_session(state.session_id)
    assert resumed is not None
    assert resumed.session_id == state.session_id


def test_update_events_timestamps_inserted_and_replaced_entries(tmp_path: Path, db_factory):
    mgr = SessionManager(db_factory, tmp_path)
    state = mgr.create_session(user="thies")
    mgr.save_events(
        state.session_id,
        [
            {"role": "user", "content": "first", "timestamp": "2026-01-01T00:00:00+00:00"},
            {"role": "assistant", "content": "second", "timestamp": "2026-01-01T00:00:01+00:00"},
        ],
    )

    def _mutate(events: list[dict[str, object]]) -> None:
        events.insert(0, {"role": "thinking", "content": "inserted"})
        events[2] = {"role": "assistant", "content": "replaced"}

    mgr.update_events(state.session_id, _mutate)

    events = mgr.load_events(state.session_id)
    assert events[0]["role"] == "thinking"
    assert "timestamp" in events[0]
    assert events[1]["timestamp"] == "2026-01-01T00:00:00+00:00"
    assert events[2]["role"] == "assistant"
    assert events[2]["content"] == "replaced"
    assert "timestamp" in events[2]


def test_resume_nonexistent(tmp_path: Path, db_factory):
    mgr = SessionManager(db_factory, tmp_path)
    assert mgr.resume_session("doesnotexist") is None


def test_list_sessions(tmp_path: Path, db_factory):
    mgr = SessionManager(db_factory, tmp_path)
    s1 = mgr.create_session(user="thies")
    s2 = mgr.create_session(user="thies")
    sessions = mgr.list_sessions()
    assert s1.session_id in sessions
    assert s2.session_id in sessions


def test_list_sessions_filters_by_owner(tmp_path: Path, db_factory) -> None:
    mgr = SessionManager(db_factory, tmp_path)
    alice = mgr.create_session(user="alice")
    bob = mgr.create_session(user="bob")
    mgr.create_session(user="thies")

    assert mgr.list_sessions(user="alice") == [alice.session_id]
    assert mgr.list_sessions(user="bob") == [bob.session_id]


def test_list_sessions_filters_by_owner_skips_missing_meta(tmp_path: Path, db_factory) -> None:
    from carapace.database.models import SessionRow

    mgr = SessionManager(db_factory, tmp_path)
    alice = mgr.create_session(user="alice")
    legacy = mgr.create_session(user="alice")
    # Simulate a legacy session without owner metadata by clearing its user column.
    with db_factory.begin() as db:
        db.get(SessionRow, legacy.session_id).user = ""

    assert mgr.list_sessions(user="alice") == [alice.session_id]


def test_save_and_resume_state(tmp_path: Path, db_factory):
    mgr = SessionManager(db_factory, tmp_path)
    state = mgr.create_session(user="thies")
    state.context_grants["my-skill"] = ContextGrant(
        skill_name="my-skill",
        domains={"example.com"},
        credential_decls=[SkillCredentialDecl(vault_path="dev/test", description="test cred")],
    )
    mgr.save_state(state)

    resumed = mgr.resume_session(state.session_id)
    assert resumed is not None
    assert "my-skill" in resumed.context_grants
    assert "dev/test" in resumed.context_grants["my-skill"].vault_paths


def test_session_manager_calls_on_change_for_state_mutations(tmp_path: Path, db_factory) -> None:
    changed: list[str] = []
    mgr = SessionManager(db_factory, tmp_path, on_change=lambda: changed.append("changed"))

    state = mgr.create_session(user="thies")
    state.title = "Renamed"
    mgr.save_state(state)
    assert mgr.delete_session(state.session_id) is True

    # create_session inserts the row directly (not via the notifying save_state path),
    # so on_change fires for the save_state and delete_session mutations.
    assert changed == ["changed", "changed"]


def test_save_and_load_llm_request_state(tmp_path: Path, db_factory) -> None:
    mgr = SessionManager(db_factory, tmp_path)
    state = mgr.create_session(user="thies")
    activity = LlmRequestState(
        request_id="req-1",
        source="agent",
        model_name="anthropic:claude-haiku-4-5",
        started_at=datetime.now(tz=UTC),
        phase="processing_prompt",
    )

    mgr.save_llm_request_state(state.session_id, activity)

    reloaded = mgr.load_llm_request_state(state.session_id)
    assert reloaded is not None
    assert reloaded.request_id == "req-1"
    assert reloaded.phase == "processing_prompt"

    mgr.clear_llm_request_state(state.session_id)
    assert mgr.load_llm_request_state(state.session_id) is None


def test_save_and_load_sandbox_snapshot(tmp_path: Path, db_factory) -> None:
    mgr = SessionManager(db_factory, tmp_path)
    state = mgr.create_session(user="thies")
    snapshot = SessionSandboxSnapshot(
        exists=True,
        runtime="kubernetes",
        status="scaled_down",
        sandbox_id="warm-1",
        resource_id="carapace-sandbox-abc-0",
        resource_kind="statefulset",
        storage_present=True,
        provisioned_bytes=1_073_741_824,
        last_measured_used_bytes=123_456,
        last_measured_at=datetime.now(tz=UTC),
        updated_at=datetime.now(tz=UTC),
    )

    mgr.save_sandbox_snapshot(state.session_id, snapshot)

    reloaded = mgr.load_sandbox_snapshot(state.session_id)
    assert reloaded is not None
    assert reloaded.runtime == "kubernetes"
    assert reloaded.status == "scaled_down"
    assert reloaded.sandbox_id == "warm-1"
    assert reloaded.last_measured_used_bytes == 123_456

    mgr.clear_sandbox_snapshot(state.session_id)
    assert mgr.load_sandbox_snapshot(state.session_id) is None


def test_normalize_optional_message_strips_blank_values() -> None:
    assert normalize_optional_message(None) is None
    assert normalize_optional_message("   ") is None
    assert normalize_optional_message("  blocked by user  ") == "blocked by user"


def test_format_denial_message_includes_source_and_message() -> None:
    assert format_denial_message("sentinel", "dangerous command") == (
        "Sentinel denied this operation. dangerous command"
    )
    assert format_denial_message("user", None) == "User denied this operation."


def test_missing_user_escalation_callback_denies() -> None:
    security = SessionSecurity("session-1")
    result = asyncio.run(security.escalate_to_user("example.com", {"kind": "domain_access"}))
    assert result == UserEscalationDecision(allowed=False)


def _titled_session(mgr: SessionManager, title: str, *, user: str = "thies", events: list[dict] | None = None) -> str:
    state = mgr.create_session(user=user)
    state.title = title
    mgr.save_state(state)
    if events:
        mgr.append_events(state.session_id, events)
    return state.session_id


def _search(mgr: SessionManager, query: str, *, fulltext: bool = False, user: str = "thies") -> dict[str, str | None]:
    return {
        match.state.session_id: match.snippet
        for match in mgr.search_sessions(user=user, query=query, fulltext=fulltext, limit=50)
    }


def test_search_sessions_matches_title_case_insensitively(tmp_path: Path, db_factory):
    mgr = SessionManager(db_factory, tmp_path)
    pancakes = _titled_session(mgr, "Classic Fluffy Pancakes")
    _titled_session(mgr, "Refactoring Date Parsing")

    assert _search(mgr, "fluffy") == {pancakes: None}


def test_search_sessions_title_mode_ignores_message_text(tmp_path: Path, db_factory):
    mgr = SessionManager(db_factory, tmp_path)
    _titled_session(mgr, "Breakfast", events=[{"role": "user", "content": "How do I make pancakes?"}])

    assert _search(mgr, "pancakes") == {}


def test_search_sessions_fulltext_matches_messages_with_snippet(tmp_path: Path, db_factory):
    mgr = SessionManager(db_factory, tmp_path)
    long_intro = "Sure, here is a recipe that works every time and needs no special equipment at all. "
    sid = _titled_session(
        mgr,
        "Breakfast",
        events=[
            {"role": "user", "content": "What should I cook?"},
            {
                "role": "assistant",
                "content": long_intro + "Whisk the flour\nand Buttermilk until smooth, then rest it.",
            },
        ],
    )

    snippet = _search(mgr, "buttermilk", fulltext=True)[sid]

    assert snippet is not None
    assert snippet.startswith("…")
    assert "Whisk the flour and Buttermilk until smooth" in snippet


def test_search_sessions_fulltext_still_matches_titles(tmp_path: Path, db_factory):
    mgr = SessionManager(db_factory, tmp_path)
    sid = _titled_session(mgr, "Classic Fluffy Pancakes")

    assert _search(mgr, "fluffy", fulltext=True) == {sid: None}


def test_search_sessions_fulltext_skips_tool_calls_results_and_slash_commands(tmp_path: Path, db_factory):
    mgr = SessionManager(db_factory, tmp_path)
    _titled_session(
        mgr,
        "Sandbox tour",
        events=[
            {"role": "user", "content": "/budget zebra"},
            {"role": "tool_call", "tool": "exec", "tool_id": "t1", "args": {"command": "echo zebra"}},
            {"role": "tool_result", "tool": "exec", "tool_id": "t1", "result": "zebra"},
            {"role": "command", "command": "budget", "content": "zebra"},
            {"role": "thinking", "content": "zebra"},
        ],
    )

    assert _search(mgr, "zebra", fulltext=True) == {}


def test_search_sessions_includes_archived_and_excludes_other_users(tmp_path: Path, db_factory):
    mgr = SessionManager(db_factory, tmp_path)
    archived = _titled_session(mgr, "Old pancake notes")
    state = mgr.load_state(archived)
    assert state is not None
    state.attributes = state.attributes.model_copy(update={"archived": True})
    mgr.save_state(state)
    _titled_session(mgr, "Ada's pancake notes", user="ada")

    assert _search(mgr, "pancake") == {archived: None}


def test_search_sessions_orders_by_last_active_and_escapes_wildcards(tmp_path: Path, db_factory):
    mgr = SessionManager(db_factory, tmp_path)
    older = _titled_session(mgr, "Discount 100% off")
    newer = _titled_session(mgr, "Another 100% deal")
    _titled_session(mgr, "Discount 1000 off")
    state = mgr.load_state(older)
    assert state is not None
    state.last_active = datetime(2020, 1, 1, tzinfo=UTC)
    mgr.save_state(state)

    assert list(_search(mgr, "100%")) == [newer, older]
