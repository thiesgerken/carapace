"""Message formatting helpers for the Matrix channel."""

from __future__ import annotations

import json

import markdown as md

from carapace.payloads import dict_of_dicts, dict_or_empty, list_of_dicts, string_dict
from carapace.ws_models import ApprovalRequest, CommandResult


def md_to_html(text: str) -> str:
    """Convert markdown text to HTML for Matrix rich-text messages."""
    return md.markdown(text, extensions=["fenced_code", "tables"])


def format_command_result_text(result: CommandResult) -> str:
    """Render a CommandResult as plain text suitable for a Matrix message."""
    data = dict_or_empty(result.data)

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
            grants = dict_of_dicts(data.get("context_grants"))
            if grants:
                grant_lines: list[str] = []
                for skill, info in grants.items():
                    parts_g = [f"- **{skill}**"]
                    domains_list = info.get("domains")
                    if isinstance(domains_list, list) and domains_list:
                        parts_g.append(f"  domains: {', '.join(str(d) for d in domains_list)}")
                    vps = info.get("vault_paths")
                    cached = info.get("cached_credentials", 0)
                    if isinstance(vps, list) and vps:
                        parts_g.append(f"  credentials: {len(vps)} declared, {cached} cached")
                    grant_lines.append("\n".join(parts_g))
                grants_str = "\n" + "\n".join(grant_lines)
            else:
                grants_str = " (none)"
            domain_entries = list_of_dicts(data.get("allowed_domains"))
            if domain_entries:
                domains_str = "\n" + "\n".join(
                    f"  - `{e.get('domain', '?')}` ({e.get('scope', '?')})" for e in domain_entries
                )
            else:
                domains_str = " (none)"
            lines = [
                f"**Session:** `{data.get('session_id', '?')}`",
                f"**Channel:** {data.get('channel_type', '?')}",
                f"**Context grants:**{grants_str}",
                f"**Allowed domains:**{domains_str}",
            ]
            return "\n".join(lines)

        case "skills":
            skills = list_of_dicts(result.data)
            if not skills:
                return "No skills available."
            lines = ["**Skills:**\n"]
            for skill in skills:
                lines.append(f"- **{skill.get('name', '?')}** — {skill.get('description', '')}")
            return "\n".join(lines)

        case "memory":
            if not data:
                return "No memory files."
            lines = ["**Memory files:**\n"]
            for f in data:
                lines.append(f"- {f}")
            return "\n".join(lines)

        case "retitle":
            return data.get("message", "")

        case "usage":
            models = dict_of_dicts(data.get("models"))
            categories = dict_of_dicts(data.get("categories"))
            costs = string_dict(data.get("costs"))
            category_costs = string_dict(data.get("category_costs"))
            budget_gauges = list_of_dicts(data.get("budget_gauges"))
            total_input = data.get("total_input", 0)
            total_output = data.get("total_output", 0)
            total_tool_calls = int(data.get("total_tool_calls", 0) or 0)
            total_cost = float(costs.get("total", 0))

            if not models and not categories and not budget_gauges and total_tool_calls == 0:
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
            parts.append(f"**Tool Calls:** {total_tool_calls:,}")
            if budget_gauges:
                lines = [
                    "**Session Budgets**\n",
                    "| Metric | Current | Limit | Remaining | Used |",
                    "|---|---:|---:|---:|---:|",
                ]
                for gauge in budget_gauges:
                    used = "blocked" if gauge.get("unavailable_reason") else f"{float(gauge.get('fill_pct', 0)):.1f}%"
                    lines.append(
                        "| "
                        + " | ".join(
                            [
                                str(gauge.get("label", "?")),
                                str(gauge.get("current_value", "-")),
                                str(gauge.get("limit_value", "-")),
                                str(gauge.get("remaining_value") or "—"),
                                used,
                            ]
                        )
                        + " |"
                    )
                parts.append("\n".join(lines))
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

            last_rows: list[tuple[str, dict[str, object]]] = []
            for key, src in (("last_llm_agent", "agent"), ("last_llm_sentinel", "sentinel")):
                row = dict_or_empty(data.get(key))
                if int(row.get("context_size", 0) or 0) > 0:
                    last_rows.append((src, row))

            if last_rows:
                show_other = False
                for _, row in last_rows:
                    b = dict_or_empty(row.get("breakdown_pct"))
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
                lines = ["**Context**\n", hdr]
                for src, row in last_rows:
                    b = dict_or_empty(row.get("breakdown_pct"))
                    context_size = row.get("context_size", 0)
                    context_tokens = int(context_size) if isinstance(context_size, int | float | str) else 0
                    core = (
                        f"| {src} | {context_tokens:,} | "
                        f"{_fmt_pct_cell(b.get('system'))} | {_fmt_pct_cell(b.get('user'))} | "
                        f"{_fmt_pct_cell(b.get('assistant'))} | {_fmt_pct_cell(b.get('tool_calls'))} | "
                        f"{_fmt_pct_cell(b.get('tool_returns'))}"
                    )
                    lines.append(f"{core} | {_fmt_pct_cell(b.get('other'))} |" if show_other else f"{core} |")
                parts.append("\n".join(lines))

            return "\n\n".join(parts)

        case "budget":
            if data.get("error"):
                return f"Error: {data['error']}"
            gauges: list[dict] = data.get("gauges", [])
            message = data.get("message")
            usage_hint = data.get("usage_hint")
            if not gauges:
                parts = [message or "No session budgets configured."]
                if usage_hint:
                    parts.append(usage_hint)
                return "\n".join(parts)
            lines = []
            if message:
                lines.append(message)
            if usage_hint:
                lines.append(usage_hint)
            lines.extend(
                [
                    "**Session Budgets**\n",
                    "| Metric | Current | Limit | Remaining | Used |",
                    "|---|---:|---:|---:|---:|",
                ]
            )
            for gauge in gauges:
                used = "blocked" if gauge.get("unavailable_reason") else f"{float(gauge.get('fill_pct', 0)):.1f}%"
                lines.append(
                    "| "
                    + " | ".join(
                        [
                            str(gauge.get("label", "?")),
                            str(gauge.get("current_value", "-")),
                            str(gauge.get("limit_value", "-")),
                            str(gauge.get("remaining_value") or "—"),
                            used,
                        ]
                    )
                    + " |"
                )
            return "\n".join(lines)

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

        case "model":
            if "models" in data:
                lines = []
                for model_type, info in data["models"].items():
                    line = f"**{model_type}:** `{info['current']}`"
                    if info["current"] != info["default"]:
                        line += f" (default: `{info['default']}`)"
                    lines.append(line)
                body = "\n".join(lines)
                if data.get("error"):
                    return f"❌ {data['error']}\n\n{body}"
                if data.get("message"):
                    return f"{body}\n\n{data['message']}"
                return body
            if "error" in data:
                return f"❌ {data['error']}"
            if "message" in data:
                return data["message"]
            reply = f"**Current model:** `{data['current']}`"
            if data.get("default") and data["default"] != data["current"]:
                reply += f"\n**Default:** `{data['default']}`"
            return reply

        case "model-agent" | "model-sentinel" | "model-title":
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
