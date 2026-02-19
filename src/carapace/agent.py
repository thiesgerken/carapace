from __future__ import annotations

import difflib
import subprocess
from pathlib import Path
from typing import Any

from pydantic_ai import Agent, ApprovalRequired, DeferredToolRequests, RunContext

from carapace.config import load_workspace_file
from carapace.memory import MemoryStore
from carapace.models import Deps, OperationClassification, RuleCheckResult
from carapace.security.classifier import classify_operation
from carapace.security.engine import check_rules
from carapace.skills import SkillRegistry


async def _gate(
    ctx: RunContext[Deps],
    tool_name: str,
    args: dict[str, Any],
    context: str = "",
) -> tuple[OperationClassification, RuleCheckResult]:
    """Classify an operation and check rules. Raises ApprovalRequired if needed."""
    classification = await classify_operation(ctx.deps.classifier_model, tool_name, args, context)
    result = await check_rules(
        ctx.deps.classifier_model,
        ctx.deps.rules,
        ctx.deps.session_state,
        classification,
    )
    if ctx.deps.verbose:
        args_parts = []
        for k, v in args.items():
            v_str = repr(v) if isinstance(v, str) else str(v)
            if len(v_str) > 60:
                v_str = v_str[:57] + "..."
            args_parts.append(f"{k}={v_str}")
        args_str = ", ".join(args_parts)
        if len(args_str) > 200:
            args_str = args_str[:197] + "..."
        cats = ", ".join(classification.categories) if classification.categories else ""
        rules_str = ", ".join(result.triggered_rules) if result.triggered_rules else ""
        detail = f"[{classification.operation_type}]" if classification.operation_type else ""
        if cats:
            detail += f" ({cats})"
        if rules_str:
            detail += f" rules: {rules_str}"
        if result.needs_approval:
            detail += " -> approval required"

        if ctx.deps.tool_call_callback:
            ctx.deps.tool_call_callback(tool_name, args, detail)
        else:
            print(f"  \033[2m{tool_name}({args_str}) {detail}\033[0m")

    if result.needs_approval:
        raise ApprovalRequired(
            metadata={
                "tool": tool_name,
                "args": args,
                "classification": classification.model_dump(),
                "triggered_rules": result.triggered_rules,
                "descriptions": result.descriptions,
            }
        )
    return classification, result


def _resolve_path(data_dir, path: str) -> tuple[str | None, Path]:
    """Resolve a path within data_dir. Returns (error, resolved_path)."""

    full_path = (data_dir / path).resolve()
    if not str(full_path).startswith(str(data_dir.resolve())):
        return "Error: path escapes data directory", full_path
    return None, full_path


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
        catalog_lines.append("Use `activate_skill` to load full instructions before using a skill.")
        parts.append("\n".join(catalog_lines))

    parts.append(
        "# Session Info\n"
        f"Session ID: {deps.session_state.session_id}\n"
        f"Activated rules: {deps.session_state.activated_rules or '(none)'}\n"
        f"Disabled rules: {deps.session_state.disabled_rules or '(none)'}"
    )

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
        return "Available skills:\n" + "\n".join(lines)

    @agent.tool
    async def activate_skill(ctx: RunContext[Deps], skill_name: str) -> str:
        """Load the full instructions for a skill. Call this before using a skill."""
        if not ctx.tool_call_approved:
            await _gate(
                ctx,
                "activate_skill",
                {"skill_name": skill_name},
                context="Loading full skill instructions into agent context",
            )

        registry = SkillRegistry(ctx.deps.data_dir / "skills")
        instructions = registry.get_full_instructions(skill_name)
        if instructions is None:
            return f"Skill '{skill_name}' not found."
        ctx.deps.activated_skills.append(skill_name)
        return f"Skill '{skill_name}' activated. Instructions:\n\n{instructions}"

    # --- Filesystem (group:fs) ---

    @agent.tool
    async def read(ctx: RunContext[Deps], path: str) -> str:
        """Read a file from the data directory. Returns the file content."""
        if not ctx.tool_call_approved:
            await _gate(ctx, "read", {"path": path})

        err, full_path = _resolve_path(ctx.deps.data_dir, path)
        if err:
            return err
        if not full_path.exists():
            return f"File not found: {path}"
        if full_path.is_dir():
            entries = sorted(full_path.iterdir())
            lines = []
            for e in entries:
                suffix = "/" if e.is_dir() else ""
                lines.append(f"  {e.name}{suffix}")
            return f"Directory listing of {path}/:\n" + "\n".join(lines)
        return full_path.read_text()

    @agent.tool
    async def write(ctx: RunContext[Deps], path: str, content: str) -> str:
        """Write content to a file in the data directory. Creates parent directories as needed."""
        if not ctx.tool_call_approved:
            await _gate(ctx, "write", {"path": path, "content": content[:200]})

        err, full_path = _resolve_path(ctx.deps.data_dir, path)
        if err:
            return err
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content)
        return f"Written to {path}"

    @agent.tool
    async def edit(
        ctx: RunContext[Deps],
        path: str,
        old_string: str,
        new_string: str,
    ) -> str:
        """Edit a file by replacing old_string with new_string. The old_string must appear exactly once in the file."""
        if not ctx.tool_call_approved:
            await _gate(
                ctx,
                "edit",
                {
                    "path": path,
                    "old_string": old_string[:100],
                    "new_string": new_string[:100],
                },
            )

        err, full_path = _resolve_path(ctx.deps.data_dir, path)
        if err:
            return err
        if not full_path.exists():
            return f"File not found: {path}"

        original = full_path.read_text()
        count = original.count(old_string)
        if count == 0:
            return f"Error: old_string not found in {path}"
        if count > 1:
            return f"Error: old_string appears {count} times in {path} (must be unique)"

        updated = original.replace(old_string, new_string, 1)
        full_path.write_text(updated)

        diff = difflib.unified_diff(
            original.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            n=3,
        )
        diff_text = "".join(diff)
        return f"Edited {path}:\n```diff\n{diff_text}```"

    @agent.tool
    async def apply_patch(ctx: RunContext[Deps], changes: list[dict[str, str]]) -> str:
        """Apply structured edits across one or more files.

        Each change is a dict with 'path', 'old_string', and 'new_string'.
        If old_string is empty, the file is created with new_string as content.
        """
        paths_summary = [c.get("path", "?") for c in changes]
        if not ctx.tool_call_approved:
            await _gate(
                ctx,
                "apply_patch",
                {"files": paths_summary, "num_changes": len(changes)},
            )

        results: list[str] = []
        for i, change in enumerate(changes):
            p = change.get("path", "")
            old = change.get("old_string", "")
            new = change.get("new_string", "")

            if not p:
                results.append(f"Change {i + 1}: missing path")
                continue

            err, full_path = _resolve_path(ctx.deps.data_dir, p)
            if err:
                results.append(f"Change {i + 1} ({p}): {err}")
                continue

            if not old:
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(new)
                results.append(f"Change {i + 1}: created {p}")
                continue

            if not full_path.exists():
                results.append(f"Change {i + 1}: file not found: {p}")
                continue

            original = full_path.read_text()
            count = original.count(old)
            if count == 0:
                results.append(f"Change {i + 1} ({p}): old_string not found")
                continue
            if count > 1:
                results.append(f"Change {i + 1} ({p}): old_string appears {count} times (must be unique)")
                continue

            full_path.write_text(original.replace(old, new, 1))
            results.append(f"Change {i + 1}: edited {p}")

        return "\n".join(results)

    # --- Runtime (group:runtime) ---

    @agent.tool
    async def exec(ctx: RunContext[Deps], command: str, timeout: int = 30) -> str:
        """Run a shell command in the data directory and return its output."""
        if not ctx.tool_call_approved:
            await _gate(ctx, "exec", {"command": command})

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(ctx.deps.data_dir),
            )
            output = result.stdout
            if result.stderr:
                output += f"\n[stderr] {result.stderr}"
            if result.returncode != 0:
                output += f"\n[exit code: {result.returncode}]"
            return output or "(no output)"
        except subprocess.TimeoutExpired:
            return f"Error: command timed out ({timeout}s)"
        except Exception as e:
            return f"Error: {e}"

    @agent.tool
    async def bash(ctx: RunContext[Deps], command: str, timeout: int = 30) -> str:
        """Run a command explicitly in bash. Use for bash-specific syntax (pipes, redirects, etc.)."""
        if not ctx.tool_call_approved:
            await _gate(ctx, "bash", {"command": command})

        try:
            result = subprocess.run(
                ["bash", "-c", command],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(ctx.deps.data_dir),
            )
            output = result.stdout
            if result.stderr:
                output += f"\n[stderr] {result.stderr}"
            if result.returncode != 0:
                output += f"\n[exit code: {result.returncode}]"
            return output or "(no output)"
        except subprocess.TimeoutExpired:
            return f"Error: command timed out ({timeout}s)"
        except Exception as e:
            return f"Error: {e}"

    # --- Memory ---

    @agent.tool
    async def read_memory(ctx: RunContext[Deps], file_path: str = "", query: str = "") -> str:
        """Read memory files or search memory. Provide file_path to read a specific file, or query to search."""
        store = MemoryStore(ctx.deps.data_dir)
        if file_path:
            content = store.read(file_path)
            if content is None:
                return f"Memory file not found: {file_path}"
            return content
        if query:
            results = store.search(query)
            if not results:
                return f"No memory matches for '{query}'"
            lines = [f"- {r['file']}: {r['matches']}" for r in results]
            return "Memory search results:\n" + "\n".join(lines)
        files = store.list_files()
        if not files:
            return "No memory files."
        return "Memory files:\n" + "\n".join(f"- {f}" for f in files)

    @agent.tool
    async def write_memory(ctx: RunContext[Deps], file_path: str, content: str) -> str:
        """Write or update a memory file."""
        if not ctx.tool_call_approved:
            await _gate(ctx, "write_memory", {"file_path": file_path, "content": content[:200]})

        store = MemoryStore(ctx.deps.data_dir)
        return store.write(file_path, content)

    return agent
