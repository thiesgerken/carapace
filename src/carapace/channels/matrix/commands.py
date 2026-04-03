"""Slash command processing for the Matrix channel."""

from __future__ import annotations

from carapace.memory import MemoryStore
from carapace.models import Deps
from carapace.security.context import UserVouchedEntry
from carapace.ws_models import CommandResult


def handle_matrix_slash_command(
    command: str,
    deps: Deps,
    security_md: str,
    slash_commands: list[dict[str, str]],
) -> CommandResult | None:
    """Process a slash command inline for the Matrix channel.

    This mirrors the logic that used to live in ``server._handle_slash_command``
    but works without depending on server-module globals.
    """
    parts = command.strip().split(maxsplit=1)
    cmd = parts[0].lower()

    if cmd == "/help":
        return CommandResult(command="help", data={"commands": slash_commands})

    if cmd == "/security":
        policy = security_md or "(no SECURITY.md loaded)"
        log_count = len(deps.security.action_log)
        eval_count = deps.security.sentinel_eval_count
        return CommandResult(
            command="security",
            data={
                "policy_preview": policy[:500] + ("..." if len(policy) > 500 else ""),
                "action_log_entries": log_count,
                "sentinel_evaluations": eval_count,
            },
        )

    if cmd == "/approve-context":
        deps.security.append(UserVouchedEntry())
        return CommandResult(
            command="approve-context",
            data={"message": "Recorded: you vouch for the current agent context as trustworthy."},
        )

    if cmd == "/session":
        session_id = deps.session_state.session_id
        return CommandResult(
            command="session",
            data={
                "session_id": session_id,
                "channel_type": deps.session_state.channel_type,
                "approved_credentials": deps.session_state.approved_credentials,
                "allowed_domains": deps.sandbox.get_domain_info(session_id),
            },
        )

    if cmd == "/skills":
        skills = [{"name": s.name, "description": s.description.strip()} for s in deps.skill_catalog]
        return CommandResult(command="skills", data=skills)

    if cmd == "/memory":
        store = MemoryStore(deps.data_dir)
        files = store.list_files()
        return CommandResult(command="memory", data=files)

    if cmd == "/usage":
        tracker = deps.usage_tracker
        costs = tracker.estimated_cost()
        cat_costs = tracker.estimated_category_cost()
        return CommandResult(
            command="usage",
            data={
                "models": {k: v.model_dump() for k, v in tracker.models.items()},
                "categories": {k: v.model_dump() for k, v in tracker.categories.items()},
                "total_input": tracker.total_input,
                "total_output": tracker.total_output,
                "costs": {k: str(v) for k, v in costs.items()},
                "category_costs": {k: str(v) for k, v in cat_costs.items()},
            },
        )

    return None
