from __future__ import annotations

from typing import Any

from loguru import logger
from pydantic_ai import Agent, DeferredToolRequests, RunContext, ToolDenied

import carapace.security as security
from carapace.config import load_workspace_file
from carapace.credentials import CredentialRegistry
from carapace.memory import MemoryStore
from carapace.models import CredentialMetadata, Deps, SkillCredentialDecl, ToolResult
from carapace.sandbox.runtime import SkillVenvError
from carapace.security.context import CredentialAccessEntry, SkillActivatedEntry, ToolResultEntry
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


def _notify_result(ctx: RunContext[Deps], tool_name: str, result: str, exit_code: int = 0) -> None:
    if ctx.deps.tool_result_callback:
        ctx.deps.tool_result_callback(ToolResult(tool=tool_name, output=result[:2000], exit_code=exit_code))


async def _inject_skill_credentials(
    ctx: RunContext[Deps],
    cred_decls: list[SkillCredentialDecl],
    skill_name: str,
) -> str:
    """Fetch and inject declared skill credentials into the sandbox.

    Returns a human-readable summary for the agent (never includes values).
    """
    if not cred_decls:
        return ""

    cred_registry: CredentialRegistry | None = ctx.deps.credential_registry
    if cred_registry is None:
        return ""

    approved_paths = {c.vault_path for c in ctx.deps.session_state.approved_credentials}

    # Filter to credentials not yet approved
    needed = [c for c in cred_decls if c.vault_path not in approved_paths]
    if not needed:
        # All already approved — re-inject in case container was recreated
        return await _do_inject(ctx, cred_decls, cred_registry, skill_name)

    # Fetch metadata for all needed credentials
    metas: list[CredentialMetadata] = []
    for decl in needed:
        try:
            meta = await cred_registry.fetch_metadata(decl.vault_path)
        except KeyError:
            meta = CredentialMetadata(vault_path=decl.vault_path, name=decl.vault_path, description=decl.description)
        metas.append(meta)

    ctx.deps.security.append(CredentialAccessEntry(vault_paths=[m.vault_path for m in metas], decision="approved"))

    # Record approvals in session state
    for meta in metas:
        if not any(c.vault_path == meta.vault_path for c in ctx.deps.session_state.approved_credentials):
            ctx.deps.session_state.approved_credentials.append(meta)

    return await _do_inject(ctx, cred_decls, cred_registry, skill_name)


async def _do_inject(
    ctx: RunContext[Deps],
    cred_decls: list[SkillCredentialDecl],
    cred_registry: CredentialRegistry,
    skill_name: str,
) -> str:
    """Fetch credential values and inject them into the sandbox."""
    session_id = ctx.deps.session_state.session_id
    injected_env = 0
    injected_file = 0
    errors: list[str] = []

    for decl in cred_decls:
        try:
            value = await cred_registry.fetch(decl.vault_path)
        except KeyError:
            errors.append(f"Credential {decl.vault_path} not found in vault")
            continue

        if decl.env_var:
            ctx.deps.sandbox.set_session_env(session_id, {decl.env_var: value})
            injected_env += 1

        if decl.file:
            skill_dir = f"/workspace/skills/{skill_name}"
            result = await ctx.deps.sandbox.file_write(session_id, decl.file, value, mode=0o400, workdir=skill_dir)
            if result.startswith("Error"):
                errors.append(f"Failed to write {decl.file}: {result}")
            else:
                injected_file += 1

    parts: list[str] = []
    total = injected_env + injected_file
    if total:
        parts.append(f"{total} credential(s) injected for skill '{skill_name}'.")
    if errors:
        parts.append("Credential errors: " + "; ".join(errors))
    return " ".join(parts)


def build_system_prompt(deps: Deps) -> str:
    parts: list[str] = []

    agents_md = load_workspace_file(deps.knowledge_dir, "AGENTS.md")
    if agents_md:
        parts.append(agents_md)

    soul_md = load_workspace_file(deps.knowledge_dir, "SOUL.md")
    if soul_md:
        parts.append(soul_md)

    user_md = load_workspace_file(deps.knowledge_dir, "USER.md")
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
        "`/workspace/` is a Git repository cloned from the server. "
        "All changes to memory, skills, and other user files must be committed and pushed "
        "(`git add`, `git commit`, `git push`) — this is the only way to persist changes. "
        "Every push is evaluated by the security sentinel via a pre-receive hook.\n\n"
        "## Workspace layout\n"
        "- `/workspace/SOUL.md`, `/workspace/USER.md`, `/workspace/SECURITY.md` "
        "— personality and security policy files\n"
        "- `/workspace/memory/` — memory files\n"
        "- `/workspace/skills/` — activated skills (populated by `use_skill`)\n"
        "Call `use_skill(skill_name)` to activate a skill before running its scripts.\n"
        "`uv` is pre-installed; skill dependencies are managed via `pyproject.toml` + `uv.lock`.\n"
        "Run skill scripts with `uv run --directory /workspace/skills/<name> scripts/<script>.py`.\n\n"
        "## Network Access\n"
        "The sandbox has internet access. Outgoing requests are allowed but subject to "
        "security review by the sentinel — like all tool calls, network activity is evaluated "
        "and may be denied if it violates the security policy. "
        "Skills can declare specific domains they need; those are granted when the skill is activated."
    )

    parts.append(f"# Session Info\nSession ID: {deps.session_state.session_id}")

    return "\n\n---\n\n".join(parts)


def create_agent(deps: Deps) -> Agent[Deps, str | DeferredToolRequests]:
    system_prompt = build_system_prompt(deps)

    agent: Agent[Deps, str | DeferredToolRequests] = Agent(
        deps.agent_model,
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
        registry = SkillRegistry(ctx.deps.knowledge_dir / "skills")

        carapace_cfg = registry.get_carapace_config(skill_name)
        requested_domains = carapace_cfg.network.domains if carapace_cfg else []
        requested_creds = carapace_cfg.credentials if carapace_cfg else []

        if not ctx.tool_call_approved:
            gate_args: dict[str, Any] = {"skill_name": skill_name}
            if requested_domains:
                gate_args["network_domains"] = requested_domains
            if requested_creds:
                gate_args["credentials"] = [c.vault_path for c in requested_creds]
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

        # Credential auto-injection
        cred_msg = await _inject_skill_credentials(ctx, requested_creds, skill_name)

        ctx.deps.activated_skills.append(skill_name)
        if skill_name not in ctx.deps.session_state.activated_skills:
            ctx.deps.session_state.activated_skills.append(skill_name)

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
        if cred_msg:
            parts.append(cred_msg)
        parts.append(f"Instructions:\n\n{instructions}")
        result = "\n".join(parts)
        _notify_result(ctx, "use_skill", result)
        return result

    # --- Filesystem (sandboxed — runs inside the Docker container) ---

    @agent.tool
    async def read(ctx: RunContext[Deps], path: str) -> str | ToolDenied:
        """Read a file or list a directory inside the sandbox.

        Use container paths (e.g. /workspace/skills/foo.py).
        """
        if not ctx.tool_call_approved and (denied := await _gate(ctx, "read", {"path": path})):
            return denied

        session_id = ctx.deps.session_state.session_id
        exit_code = 0
        try:
            result = await ctx.deps.sandbox.file_read(session_id, path)
        except Exception as exc:
            result = f"Error: {exc}"
            exit_code = -1
        _notify_result(ctx, "read", result, exit_code)
        return result

    @agent.tool
    async def write(ctx: RunContext[Deps], path: str, content: str) -> str | ToolDenied:
        """Write content to a file in the sandbox. Creates parent directories as needed."""
        if not ctx.tool_call_approved and (
            denied := await _gate(ctx, "write", {"path": path, "content": content[:200]})
        ):
            return denied

        session_id = ctx.deps.session_state.session_id
        exit_code = 0
        try:
            result = await ctx.deps.sandbox.file_write(session_id, path, content)
        except Exception as exc:
            result = f"Error: {exc}"
            exit_code = -1
        _notify_result(ctx, "write", result, exit_code)
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
        exit_code = 0
        try:
            result = await ctx.deps.sandbox.file_edit(session_id, path, old_string, new_string)
        except Exception as exc:
            result = f"Error: {exc}"
            exit_code = -1
        _notify_result(ctx, "edit", result, exit_code)
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
        exit_code = 0
        try:
            result = await ctx.deps.sandbox.file_apply_patch(session_id, changes)
        except Exception as exc:
            result = f"Error: {exc}"
            exit_code = -1
        _notify_result(ctx, "apply_patch", result, exit_code)
        return result

    # --- Runtime ---

    @agent.tool
    async def exec(ctx: RunContext[Deps], command: str) -> str | ToolDenied:
        """Run a shell command (typically bash) and return its output. Runs in a Docker sandbox."""
        if not ctx.tool_call_approved:
            if denied := await _gate(ctx, "exec", {"command": command}):
                return denied
        else:
            _notify_approved_start(ctx, "exec", {"command": command})

        session_id = ctx.deps.session_state.session_id
        try:
            exec_result = await ctx.deps.sandbox.exec_command(session_id, command)
            result = exec_result.output
            exit_code = exec_result.exit_code
        except Exception as exc:
            result = f"Error: {exc}"
            exit_code = -1

        ctx.deps.security.append(
            ToolResultEntry(tool="exec", status="error" if exit_code != 0 else "success"),
        )

        _notify_result(ctx, "exec", result, exit_code)
        return result

    # --- Memory ---

    @agent.tool
    async def read_memory(ctx: RunContext[Deps], file_path: str = "", query: str = "") -> str:
        """Read memory files or search memory. Provide file_path to read a specific file, or query to search."""
        store = MemoryStore(ctx.deps.knowledge_dir)
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

    return agent
