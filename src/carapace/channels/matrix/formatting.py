"""Message formatting helpers for the Matrix channel."""

from __future__ import annotations

import json
import math

import markdown as md

from carapace.ws_models import ApprovalRequest, CommandResult


def md_to_html(text: str) -> str:
    """Convert markdown text to HTML for Matrix rich-text messages."""
    return md.markdown(text, extensions=["fenced_code", "tables"])


def format_command_result_text(result: CommandResult) -> str:
    """Render a CommandResult as plain text suitable for a Matrix message."""
    data = result.data

    match result.command:
        case "help":
            lines = ["**Available commands:**\n"]
            for entry in data.get("commands", []):
                lines.append(f"- `{entry['command']}` — {entry['description']}")
            return "\n".join(lines)

        case "security":
            lines = [
                "**Security Policy:**\n",
                data.get("policy_preview", "(none)"),
                f"\nAction log entries: {data.get('action_log_entries', 0)}",
                f"Sentinel evaluations: {data.get('sentinel_evaluations', 0)}",
            ]
            return "\n".join(lines)

        case "approve-context":
            return data.get("message", "Context approved.")

        case "session":
            creds = data.get("approved_credentials") or []
            domain_entries: list[dict[str, str]] = data.get("allowed_domains") or []
            if domain_entries:
                domains_str = "\n" + "\n".join(f"  - `{e['domain']}` ({e['scope']})" for e in domain_entries)
            else:
                domains_str = " (none)"
            lines = [
                f"**Session:** `{data.get('session_id', '?')}`",
                f"**Channel:** {data.get('channel_type', '?')}",
                f"**Approved credentials:** {', '.join(creds) if creds else '(none)'}",
                f"**Allowed domains:**{domains_str}",
            ]
            return "\n".join(lines)

        case "skills":
            if not data:
                return "No skills available."
            lines = ["**Skills:**\n"]
            for s in data:
                lines.append(f"- **{s['name']}** — {s['description']}")
            return "\n".join(lines)

        case "memory":
            if not data:
                return "No memory files."
            lines = ["**Memory files:**\n"]
            for f in data:
                lines.append(f"- {f}")
            return "\n".join(lines)

        case "usage":
            costs = data.get("costs", {})
            total = costs.get("total", math.nan)
            lines = [f"**Token usage** (est. total: {total:0.2f}$)\n"]
            for model, usage in data.get("models", {}).items():
                inp = usage.get("input_tokens", 0)
                out = usage.get("output_tokens", 0)
                lines.append(f"- `{model}`: {inp} in / {out} out")
            return "\n".join(lines)

        case _:
            return f"Command result: {json.dumps(data, indent=2, default=str)}"


def format_domain_escalation(domain: str, command: str, explanation: str) -> str:
    """Format a sentinel-escalated domain request as a Matrix message."""
    parts = [
        f"**🌐 Network Access Request** — domain: `{domain}`",
        f"**Command:** `{command}`",
    ]
    if explanation:
        parts.append(f"**Reason:** {explanation}")
    parts.append(
        "\nThe security sentinel escalated this domain request.\n"
        "React ✅ or type `/allow` / `/yes` to allow.\n"
        "React ❌ or type `/deny` / `/no` to deny."
    )
    return "\n".join(parts)


def format_approval_request(req: ApprovalRequest) -> str:
    """Format an approval request as a Matrix message."""
    args_text = json.dumps(req.args, indent=2, default=str)

    parts = [
        f"**⚠️ Approval Required** — tool: `{req.tool}`",
    ]
    if req.explanation:
        parts.append(f"**Reason:** {req.explanation}")
    if req.risk_level:
        parts.append(f"**Risk level:** {req.risk_level}")
    parts += [
        f"**Arguments:**\n```json\n{args_text}\n```",
        "",
        "React ✅ or type `/allow` / `/yes` to allow. React ❌ or type `/deny` / `/no` to deny.",
    ]
    return "\n".join(parts)
