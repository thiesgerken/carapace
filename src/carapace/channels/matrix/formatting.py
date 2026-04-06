"""Message formatting helpers for the Matrix channel."""

from __future__ import annotations

import json

import markdown as md

from carapace.ws_models import ApprovalRequest, CommandResult


def _credential_name(credential: object) -> str:
    if isinstance(credential, dict):
        name = credential.get("name")
        return str(name) if name else str(credential)

    name = getattr(credential, "name", None)
    return str(name) if name else str(credential)


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
            creds: list[object] = data.get("approved_credentials") or []
            creds_str = ", ".join(_credential_name(c) for c in creds) if creds else "(none)"
            domain_entries: list[dict[str, str]] = data.get("allowed_domains") or []
            if domain_entries:
                domains_str = "\n" + "\n".join(f"  - `{e['domain']}` ({e['scope']})" for e in domain_entries)
            else:
                domains_str = " (none)"
            lines = [
                f"**Session:** `{data.get('session_id', '?')}`",
                f"**Channel:** {data.get('channel_type', '?')}",
                f"**Approved credentials:** {creds_str}",
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
            models: dict[str, dict] = data.get("models", {})
            categories: dict[str, dict] = data.get("categories", {})
            costs: dict[str, str] = data.get("costs", {})
            category_costs: dict[str, str] = data.get("category_costs", {})
            total_input = data.get("total_input", 0)
            total_output = data.get("total_output", 0)
            total_cost = float(costs.get("total", 0))

            if not models and not categories:
                return "No token usage recorded yet."

            has_cache = any(
                b.get("cache_read_tokens") or b.get("cache_write_tokens")
                for b in [*models.values(), *categories.values()]
            )

            has_costs = any(v != "0" for k, v in costs.items() if k != "total")

            def _table(
                title: str,
                rows: dict[str, dict],
                *,
                show_cost: bool = False,
                row_costs: dict[str, str] | None = None,
            ) -> str:
                hdr = "| | Input | Output |"
                sep = "|---|---:|---:|"
                if has_cache:
                    hdr += " Cache R | Cache W |"
                    sep += "---:|---:|"
                hdr += " Req |"
                sep += "---:|"
                if show_cost and has_costs:
                    hdr += " Cost |"
                    sep += "---:|"

                lines = [f"**{title}**\n", hdr, sep]
                lookup = row_costs if row_costs is not None else costs
                for name, b in rows.items():
                    row = f"| {name} | {b.get('input_tokens', 0):,} | {b.get('output_tokens', 0):,} |"
                    if has_cache:
                        row += f" {b.get('cache_read_tokens', 0):,} | {b.get('cache_write_tokens', 0):,} |"
                    row += f" {b.get('requests', 0)} |"
                    if show_cost and has_costs:
                        c = lookup.get(name, "0")
                        row += f" ${float(c):.4f} |" if c != "0" else " - |"
                    lines.append(row)
                return "\n".join(lines)

            parts: list[str] = []
            total_tokens = total_input + total_output
            cost_str = f" | ${total_cost:.4f}" if total_cost else ""
            parts.append(
                f"**Total:** {total_tokens:,} tokens ({total_input:,} in + {total_output:,} out){cost_str}",
            )
            if models:
                parts.append(_table("By Model", models, show_cost=True))
            if categories:
                parts.append(
                    _table(
                        "By Category",
                        categories,
                        show_cost=True,
                        row_costs=category_costs,
                    ),
                )

            def _fmt_pct_cell(v: object) -> str:
                if v is None:
                    return "—"
                if isinstance(v, bool):
                    return str(v)
                if isinstance(v, int | float):
                    return f"{float(v):.1f}%"
                return "—"

            last_rows: list[tuple[str, dict]] = []
            for key, src in (("last_llm_agent", "agent"), ("last_llm_sentinel", "sentinel")):
                row = data.get(key)
                if isinstance(row, dict) and int(row.get("context_size", 0) or 0) > 0:
                    last_rows.append((src, row))

            if last_rows:
                show_other = False
                for _, row in last_rows:
                    b = row.get("breakdown_pct") if isinstance(row.get("breakdown_pct"), dict) else {}
                    o = b.get("other")
                    if isinstance(o, int | float) and float(o) > 0:
                        show_other = True
                        break

                if show_other:
                    hdr = (
                        "| Source | Tokens | sys% | usr% | asst% | tool calls % | tool outputs % | oth% |\n"
                        "|---|---:|---:|---:|---:|---:|---:|---:|"
                    )
                else:
                    hdr = (
                        "| Source | Tokens | sys% | usr% | asst% | tool calls % | tool outputs % |\n"
                        "|---|---:|---:|---:|---:|---:|---:|"
                    )
                lines = ["**Context**", hdr]
                for src, row in last_rows:
                    b = row.get("breakdown_pct") if isinstance(row.get("breakdown_pct"), dict) else {}
                    core = (
                        f"| {src} | {int(row.get('context_size', 0)):,} | "
                        f"{_fmt_pct_cell(b.get('system'))} | {_fmt_pct_cell(b.get('user'))} | "
                        f"{_fmt_pct_cell(b.get('assistant'))} | {_fmt_pct_cell(b.get('tool_calls'))} | "
                        f"{_fmt_pct_cell(b.get('tool_returns'))}"
                    )
                    lines.append(f"{core} | {_fmt_pct_cell(b.get('other'))} |" if show_other else f"{core} |")
                parts.append("\n".join(lines))

            return "\n\n".join(parts)

        case "models":
            if "models" in data:
                lines = []
                for model_type, info in data["models"].items():
                    line = f"**{model_type}:** `{info['current']}`"
                    if info["current"] != info["default"]:
                        line += f" (default: `{info['default']}`)"
                    lines.append(line)
                if data.get("available"):
                    lines.append("")
                    lines.append("**Available:** " + ", ".join(f"`{m}`" for m in data["available"]))
                return "\n".join(lines)
            return str(data)

        case "model" | "model-sentinel" | "model-title":
            if "error" in data:
                return f"❌ {data['error']}"
            if "message" in data:
                return data["message"]
            reply = f"**Current model:** `{data['current']}`"
            if data.get("default") and data["default"] != data["current"]:
                reply += f"\n**Default:** `{data['default']}`"
            return reply

        case _:
            return f"Command result: {json.dumps(data, indent=2, default=str)}"


def format_domain_escalation(domain: str, command: str, explanation: str) -> str:
    """Format a sentinel-escalated domain access request as a Matrix message."""
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
