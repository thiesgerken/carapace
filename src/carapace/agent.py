from __future__ import annotations

from typing import Any

from loguru import logger
from pydantic_ai import Agent, DeferredToolRequests, RunContext, ToolDenied

import carapace.security as security
from carapace.config import load_workspace_file
from carapace.memory import MemoryStore
from carapace.models import Deps
from carapace.sandbox.runtime import SkillVenvError
from carapace.security.context import SkillActivatedEntry, ToolResultEntry
from carapace.skills import SkillRegistry


async def _gate(ctx: RunContext[Deps], tool_name: str, args: dict[str, Any]) -> ToolDenied | None:
    """Delegate to the security module for tool call evaluation.

    Returns ``ToolDenied`` when the sentinel denies the call (the caller must
    return it to pydantic-ai), or ``None`` when the call is allowed.
    """
    try:
        await security.evaluate_with(
            ctx.deps.security,
            ctx.deps.sentinel,
            tool_name,
            args,
            usage_tracker=ctx.deps.usage_tracker,
            verbose=ctx.deps.verbose,
            tool_call_callback=ctx.deps.tool_call_callback,
        )
    except security.SecurityDeniedError as exc:
        return ToolDenied(str(exc))
    return None


def _notify_approved_start(ctx: RunContext[Deps], tool_name: str, args: dict[str, Any]) -> None:
    """For previously-escalated tools, send a ToolCallInfo before execution."""
    if ctx.deps.tool_call_callback:
        ctx.deps.tool_call_callback(tool_name, args, "[user approved]")


def _notify_result(ctx: RunContext[Deps], tool_name: str, result: str) -> None:
    if ctx.deps.tool_result_callback:
        ctx.deps.tool_result_callback(tool_name, result[:2000])


def build_system_prompt(deps: Deps) -> str:
    parts: list[str] = []

    agents_md = load_workspace_file(deps.data_dir, "AGENTS.md")
    if agents_md:
        parts.append(agents_md)

    soul_md = load_workspace_file(deps.data_dir, "SOUL.md")
    if soul_md:
        parts.append(soul_md)

    user_md = load_workspace_file(deps.data_dir, "USER.md")
    if user_md:
        parts.append(user_md)

    if deps.skill_catalog:
        catalog_lines = ["# Available Skills", ""]
        for skill in deps.skill_catalog:
            catalog_lines.append(f"- **{skill.name}**: {skill.description.strip()}")
        catalog_lines.append("")
        catalog_lines.append(
            "Use `use_skill` to activate a skill before using it. "
            + "That will copy the skill to your sandbox environment and if needed setup a virtual environment for it."
        )
        parts.append("\n".join(catalog_lines))

    parts.append(
        "# Sandbox Environment\n"
        "Commands run inside a Docker sandbox container.\n"
        "- `/workspace/AGENTS.md`, `/workspace/SOUL.md`, `/workspace/USER.md` — read-only reference files\n"
        "- `/workspace/memory/` — read-only memory files\n"
        "- `/workspace/skills/` — activated skills (populated by `use_skill`)\n"
        "- `/workspace/tmp/` — writable scratch space\n"
        "Call `use_skill(skill_name)` to activate a skill before running its scripts.\n"
        "Call `save_skill(skill_name)` to persist edits back to the master skill directory."
    )

    parts.append(f"# Session Info\nSession ID: {deps.session_state.session_id}")

    return "\n\n---\n\n".join(parts)


def create_agent(deps: Deps) -> Agent[Deps, str | DeferredToolRequests]:
    system_prompt = build_system_prompt(deps)

    model = deps.agent_model or deps.config.agent.model

    agent: Agent[Deps, str | DeferredToolRequests] = Agent(
        model,
        deps_type=Deps,
        output_type=[str, DeferredToolRequests],  # type: ignore[arg-type]
        instructions=system_prompt,
    )

    # --- Skills ---

    @agent.tool
    async def list_skills(ctx: RunContext[Deps]) -> str:
        """List all available skills (names and descriptions)."""
        catalog = ctx.deps.skill_catalog
        if not catalog:
            return "No skills available."
        lines = [f"- {s.name}: {s.description.strip()}" for s in catalog]
        result = "Available skills:\n" + "\n".join(lines)
        _notify_result(ctx, "list_skills", result)
        return result

    @agent.tool
    async def use_skill(ctx: RunContext[Deps], skill_name: str) -> str | ToolDenied:
        """Activate a skill: copies it to the sandbox, builds its venv, and loads instructions.

        Call before using a skill.
        """
        registry = SkillRegistry(ctx.deps.data_dir / "skills")

        carapace_cfg = registry.get_carapace_config(skill_name)
        requested_domains = carapace_cfg.network.domains if carapace_cfg else []

        if not ctx.tool_call_approved:
            gate_args: dict[str, Any] = {"skill_name": skill_name}
            if requested_domains:
                gate_args["network_domains"] = requested_domains
            if denied := await _gate(ctx, "use_skill", gate_args):
                return denied
        else:
            _notify_approved_start(ctx, "use_skill", {"skill_name": skill_name})

        instructions = registry.get_full_instructions(skill_name)
        if instructions is None:
            return f"Skill '{skill_name}' not found."

        sandbox_msg = ""
        try:
            sandbox_msg = await ctx.deps.sandbox.activate_skill(
                ctx.deps.session_state.session_id,
                skill_name,
            )
        except SkillVenvError as exc:
            logger.exception(f"Error activating skill {skill_name}: {exc}")
            sandbox_msg = f"ERROR: {exc}"

        if requested_domains:
            ctx.deps.sandbox.allow_domains(
                ctx.deps.session_state.session_id,
                set(requested_domains),
            )

        ctx.deps.activated_skills.append(skill_name)

        skill_info = next((s for s in ctx.deps.skill_catalog if s.name == skill_name), None)
        ctx.deps.security.append(
            SkillActivatedEntry(
                skill_name=skill_name,
                description=skill_info.description if skill_info else "",
                declared_domains=requested_domains,
            ),
        )

        parts = [f"Skill '{skill_name}' activated."]
        if sandbox_msg:
            parts.append(sandbox_msg)
        if requested_domains:
            parts.append(f"Network access granted for: {', '.join(requested_domains)}")
        parts.append(f"Instructions:\n\n{instructions}")
        result = "\n".join(parts)
        _notify_result(ctx, "use_skill", result)
        return result

    @agent.tool
    async def save_skill(ctx: RunContext[Deps], skill_name: str) -> str | ToolDenied:
        """Save an activated skill back to the master skills directory. Persists edits made in the sandbox."""
        if not ctx.tool_call_approved:
            if denied := await _gate(ctx, "save_skill", {"skill_name": skill_name}):
                return denied
        else:
            _notify_approved_start(ctx, "save_skill", {"skill_name": skill_name})

        result = await ctx.deps.sandbox.save_skill(
            ctx.deps.session_state.session_id,
            skill_name,
        )
        ctx.deps.security.append(
            ToolResultEntry(tool="save_skill", status="success"),
        )
        _notify_result(ctx, "save_skill", result)
        return result

    # --- Filesystem (sandboxed — runs inside the Docker container) ---

    @agent.tool
    async def read(ctx: RunContext[Deps], path: str) -> str | ToolDenied:
        """Read a file or list a directory inside the sandbox. Use container paths (e.g. /workspace/skills/foo.py)."""
        if not ctx.tool_call_approved and (denied := await _gate(ctx, "read", {"path": path})):
            return denied

        session_id = ctx.deps.session_state.session_id
        result = await ctx.deps.sandbox.file_read(session_id, path)
        _notify_result(ctx, "read", result)
        return result

    @agent.tool
    async def write(ctx: RunContext[Deps], path: str, content: str) -> str | ToolDenied:
        """Write content to a file in the sandbox. Creates parent directories as needed."""
        if not ctx.tool_call_approved and (
            denied := await _gate(ctx, "write", {"path": path, "content": content[:200]})
        ):
            return denied

        session_id = ctx.deps.session_state.session_id
        result = await ctx.deps.sandbox.file_write(session_id, path, content)
        _notify_result(ctx, "write", result)
        return result

    @agent.tool
    async def edit(
        ctx: RunContext[Deps],
        path: str,
        old_string: str,
        new_string: str,
    ) -> str | ToolDenied:
        """Edit a file in the sandbox by replacing old_string with new_string.
        The old_string must appear exactly once."""
        if not ctx.tool_call_approved and (
            denied := await _gate(
                ctx,
                "edit",
                {
                    "path": path,
                    "old_string": old_string[:100],
                    "new_string": new_string[:100],
                },
            )
        ):
            return denied

        session_id = ctx.deps.session_state.session_id
        result = await ctx.deps.sandbox.file_edit(session_id, path, old_string, new_string)
        _notify_result(ctx, "edit", result)
        return result

    @agent.tool
    async def apply_patch(ctx: RunContext[Deps], changes: list[dict[str, str]]) -> str | ToolDenied:
        """Apply structured edits across one or more files in the sandbox.

        Each change is a dict with 'path', 'old_string', and 'new_string'.
        If old_string is empty, the file is created with new_string as content.
        """
        paths_summary = [c.get("path", "?") for c in changes]
        if not ctx.tool_call_approved and (
            denied := await _gate(
                ctx,
                "apply_patch",
                {"files": paths_summary, "num_changes": len(changes)},
            )
        ):
            return denied

        session_id = ctx.deps.session_state.session_id
        result = await ctx.deps.sandbox.file_apply_patch(session_id, changes)
        _notify_result(ctx, "apply_patch", result)
        return result

    # --- Runtime ---

    @agent.tool
    async def exec(ctx: RunContext[Deps], command: str, timeout: int = 30) -> str | ToolDenied:
        """Run a shell command (typically bash) and return its output. Runs in a Docker sandbox."""
        if not ctx.tool_call_approved:
            if denied := await _gate(ctx, "exec", {"command": command}):
                return denied
        else:
            _notify_approved_start(ctx, "exec", {"command": command})

        session_id = ctx.deps.session_state.session_id
        result = await ctx.deps.sandbox.exec_command(session_id, command, timeout)

        ctx.deps.security.append(
            ToolResultEntry(tool="exec", status="error" if result.startswith("Error") else "success"),
        )

        _notify_result(ctx, "exec", result)
        return result

    # --- Memory ---

    @agent.tool
    async def read_memory(ctx: RunContext[Deps], file_path: str = "", query: str = "") -> str:
        """Read memory files or search memory. Provide file_path to read a specific file, or query to search."""
        store = MemoryStore(ctx.deps.data_dir)
        if file_path:
            content = store.read(file_path)
            if content is None:
                result = f"Memory file not found: {file_path}"
                _notify_result(ctx, "read_memory", result)
                return result
            _notify_result(ctx, "read_memory", content)
            return content
        if query:
            results = store.search(query)
            if not results:
                result = f"No memory matches for '{query}'"
                _notify_result(ctx, "read_memory", result)
                return result
            lines = [f"- {r['file']}: {r['matches']}" for r in results]
            result = "Memory search results:\n" + "\n".join(lines)
            _notify_result(ctx, "read_memory", result)
            return result
        files = store.list_files()
        if not files:
            result = "No memory files."
            _notify_result(ctx, "read_memory", result)
            return result
        result = "Memory files:\n" + "\n".join(f"- {f}" for f in files)
        _notify_result(ctx, "read_memory", result)
        return result

    @agent.tool
    async def write_memory(ctx: RunContext[Deps], file_path: str, content: str) -> str | ToolDenied:
        """Write or update a memory file."""
        if not ctx.tool_call_approved:
            if denied := await _gate(ctx, "write_memory", {"file_path": file_path, "content": content[:200]}):
                return denied
        else:
            _notify_approved_start(ctx, "write_memory", {"file_path": file_path})

        store = MemoryStore(ctx.deps.data_dir)
        result = store.write(file_path, content)
        ctx.deps.security.append(
            ToolResultEntry(tool="write_memory", status="success"),
        )
        _notify_result(ctx, "write_memory", result)
        return result

    return agent
