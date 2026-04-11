from __future__ import annotations

import secrets
from pathlib import Path, PurePosixPath
from typing import Annotated, Any

import httpx
from loguru import logger
from pydantic import Field
from pydantic_ai import Agent, DeferredToolRequests, RunContext, ToolDenied

import carapace.security as security
from carapace.config import load_workspace_file
from carapace.models import (
    ContextGrant,
    CredentialMetadata,
    Deps,
    SkillCredentialDecl,
    ToolResult,
)
from carapace.sandbox.manager import READ_TOOL_MAX_LINE_WINDOW
from carapace.sandbox.runtime import SkillVenvError
from carapace.security.context import (
    ContextGrantEntry,
    CredentialAccessEntry,
    SkillActivatedEntry,
    ToolResultEntry,
)
from carapace.skills import SkillRegistry
from carapace.usage import LlmRequestLogCapability

_WORKSPACE_ROOT = PurePosixPath("/workspace")
_SKILLS_ROOT = PurePosixPath("skills")


def _normalize_workspace_path(path: str) -> PurePosixPath:
    raw = PurePosixPath(path)
    if raw.is_absolute():
        if raw == _WORKSPACE_ROOT:
            return PurePosixPath(".")
        try:
            return raw.relative_to(_WORKSPACE_ROOT)
        except ValueError:
            return raw
    return raw


def _extract_skill_path(path: str) -> tuple[str, PurePosixPath] | None:
    normalized = _normalize_workspace_path(path)
    parts = normalized.parts
    if ".." in parts or len(parts) < 2 or parts[0] != _SKILLS_ROOT.as_posix():
        return None
    return parts[1], normalized


def _skill_file_exists_in_backend_knowledge(knowledge_dir: Path, relative_path: PurePosixPath) -> bool:
    parts = relative_path.parts
    if relative_path.is_absolute() or len(parts) < 2 or parts[0] != _SKILLS_ROOT.as_posix():
        return False
    return (knowledge_dir / relative_path).exists()


def _read_skill_access_denial(path: str, knowledge_dir: Path, activated_skills: list[str]) -> str | None:
    skill_path = _extract_skill_path(path)
    if not skill_path:
        return None
    skill_name, rel_path = skill_path
    if skill_name in activated_skills:
        return None
    if not _skill_file_exists_in_backend_knowledge(knowledge_dir, rel_path):
        return None
    return f"Please activate the {skill_name} skill using the use_skill tool before accessing the skill's files"


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
        ctx.deps.tool_call_callback(
            tool_name,
            args,
            "[user approved]",
            "user",
            "allow",
            "user approved",
        )


def _notify_result(ctx: RunContext[Deps], tool_name: str, result: str, exit_code: int = 0) -> None:
    if ctx.deps.tool_result_callback:
        ctx.deps.tool_result_callback(ToolResult(tool=tool_name, output=result, exit_code=exit_code))


def _log_sandbox_tool_exception(tool: str, session_id: str) -> None:
    """Log full traceback for sandbox tool failures (must run inside ``except``)."""
    logger.exception(f"Sandbox tool {tool!r} failed (session {session_id})")


async def _cache_skill_credentials(
    ctx: RunContext[Deps],
    cred_decls: list[SkillCredentialDecl],
    skill_name: str,
) -> str:
    """Fetch declared skill credentials and cache them for per-exec injection.

    Values are stored in ``SandboxManager._credential_cache`` — **not** in
    ``session_env``.  They will be injected (env vars) or written (files) only
    for ``exec`` calls that carry a matching context.

    Returns a human-readable summary for the agent (never includes values).
    """
    if not cred_decls:
        return ""

    cred_registry = ctx.deps.credential_registry
    session_id = ctx.deps.session_state.session_id

    # Fetch metadata for UI / action-log
    meta_errors: list[str] = []
    failed_vault_paths: set[str] = set()
    metas: list[CredentialMetadata] = []
    for decl in cred_decls:
        try:
            meta = await cred_registry.fetch_metadata(decl.vault_path)
        except KeyError:
            meta = CredentialMetadata(vault_path=decl.vault_path, name=decl.vault_path, description=decl.description)
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            logger.warning(f"Credential metadata fetch failed for {decl.vault_path!r} (skill {skill_name!r}): {exc}")
            meta_errors.append(f"{decl.vault_path}: vault unreachable or error ({type(exc).__name__})")
            failed_vault_paths.add(decl.vault_path)
            continue
        metas.append(meta)

    # Append action-log entry so the sentinel is aware
    if metas:
        ctx.deps.security.append(CredentialAccessEntry(vault_paths=[m.vault_path for m in metas], decision="approved"))
        if ctx.deps.append_session_events:
            request_id = secrets.token_hex(8)
            vault_paths = [m.vault_path for m in metas]
            names = [m.name for m in metas]
            descriptions = [m.description for m in metas]
            explanation = (
                f"Credential access for skill {skill_name!r} approved implicitly with use_skill "
                "(paths were listed in the skill activation tool approval)."
            )
            ctx.deps.append_session_events(
                [
                    {
                        "role": "credential_approval",
                        "request_id": request_id,
                        "vault_paths": vault_paths,
                        "names": names,
                        "descriptions": descriptions,
                        "skill_name": skill_name,
                        "explanation": explanation,
                    },
                    {
                        "role": "credential_approval",
                        "request_id": request_id,
                        "vault_paths": vault_paths,
                        "decision": "allow",
                    },
                ]
            )

    # Fetch values and cache (not inject)
    cached = 0
    fetch_errors: list[str] = []
    for decl in cred_decls:
        if decl.vault_path in failed_vault_paths:
            continue  # skip if metadata fetch already failed
        try:
            value = await cred_registry.fetch(decl.vault_path)
        except KeyError:
            fetch_errors.append(f"Credential {decl.vault_path} not found in vault")
            continue
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            logger.warning(
                f"Credential fetch failed for {decl.vault_path!r} (session {session_id}, skill {skill_name!r}): {exc}"
            )
            fetch_errors.append(f"Credential {decl.vault_path}: vault request failed ({type(exc).__name__})")
            continue
        ctx.deps.sandbox.cache_credential(session_id, decl.vault_path, value)
        cached += 1

    parts: list[str] = []
    if cached:
        parts.append(f"{cached} credential(s) cached for skill '{skill_name}' (injected per-exec via contexts).")
    if meta_errors:
        parts.append("Credential vault unavailable for some declarations (not cached): " + "; ".join(meta_errors))
    if fetch_errors:
        parts.append("Credential errors: " + "; ".join(fetch_errors))
    return "\n".join(parts)


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

    parts.append(
        "# Response format\n"
        "Format your replies using Markdown (headings, lists, emphasis, links) when it helps readability.\n"
        "When you use fenced code blocks and the language is clear, add it after the opening fence "
        "(e.g. ```python, ```yaml, ```bash) so the client can syntax-highlight; "
        "omit the language tag only when unknown.\n"
        "For LaTeX math, use $...$ inline and $$...$$ on their own lines for display equations."
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
        capabilities=[LlmRequestLogCapability(source="agent")],
        retries=1,
        output_retries=3,
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
        requested_creds_payload = [decl.model_dump(mode="json") for decl in requested_creds]

        if not ctx.tool_call_approved:
            gate_args: dict[str, Any] = {
                "skill_name": skill_name,
                "requested_creds": requested_creds_payload,
                "requested_domains": requested_domains,
            }

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

        # Register context grant (replaces permanent allow_domains + session env injection)
        grant = ContextGrant(
            skill_name=skill_name,
            domains=set(requested_domains),
            credential_decls=list(requested_creds),
        )
        ctx.deps.session_state.context_grants[skill_name] = grant
        ctx.deps.security.append(
            ContextGrantEntry(
                skill_name=skill_name,
                domains=requested_domains,
                vault_paths=[c.vault_path for c in requested_creds],
            ),
        )

        # Cache credential values for per-exec injection
        cred_msg = await _cache_skill_credentials(ctx, requested_creds, skill_name)

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

        status_lines: list[str] = []
        if sandbox_msg:
            status_lines.append(sandbox_msg)
        else:
            status_lines.append(f"Skill '{skill_name}' activated.")
        if requested_domains:
            status_lines.append(f"Network access granted for: {', '.join(requested_domains)}")
        if cred_msg:
            status_lines.append(cred_msg)

        result = "\n".join(f"- {line}" for line in status_lines)
        result += f"\n\nInstructions:\n\n{instructions}"
        _notify_result(ctx, "use_skill", result)
        return result

    # --- Filesystem (sandboxed — runs inside the Docker container) ---

    @agent.tool
    async def read(
        ctx: RunContext[Deps],
        path: str,
        offset: Annotated[int, Field(ge=0)] = 0,
        limit: Annotated[int, Field(ge=1, le=READ_TOOL_MAX_LINE_WINDOW)] = 100,
    ) -> str | ToolDenied:
        """Read a path under `/workspace` (or list a directory).

        Relative ``path`` values are resolved from ``/workspace``. Absolute paths are used as-is.

        **Files:** You get a short header, a line of dashes, then the text. The header
        says total lines, which lines you received (1-based, like an editor), and whether
        output was cut short. If you need more, call again with a higher ``offset``:
        that is how many lines to skip from the start. Each call returns at most
        ``limit`` lines (default 100, max 1000) and about 64k characters of body text—if
        you hit either cap, read the header and continue with a larger ``offset``.

        **Binaries:** You do not get file bytes, only size and a brief ``file``-style type.
        Use ``exec`` if you need something else (e.g. ``hexdump``, ``xxd``).

        **Directories:** Lists entry names; ``offset``/``limit`` do not apply to listings.
        """
        if denied_message := _read_skill_access_denial(
            path,
            ctx.deps.knowledge_dir,
            ctx.deps.session_state.activated_skills,
        ):
            if ctx.deps.tool_call_callback:
                ctx.deps.tool_call_callback(
                    "read",
                    {"path": path, "offset": offset, "limit": limit},
                    "[blocked: skill not activated]",
                )
            _notify_result(ctx, "read", denied_message, exit_code=1)
            return denied_message

        if not ctx.tool_call_approved and (
            denied := await _gate(ctx, "read", {"path": path, "offset": offset, "limit": limit})
        ):
            return denied

        session_id = ctx.deps.session_state.session_id
        exit_code = 0
        try:
            result = await ctx.deps.sandbox.file_read(session_id, path, offset=offset, limit=limit)
        except Exception as exc:
            _log_sandbox_tool_exception("read", session_id)
            result = f"Error: {exc}"
            exit_code = -1
        _notify_result(ctx, "read", result, exit_code)
        return result

    @agent.tool
    async def write(ctx: RunContext[Deps], path: str, content: str) -> str | ToolDenied:
        """Write content to a file in the sandbox. Creates parent directories as needed."""
        if not ctx.tool_call_approved and (denied := await _gate(ctx, "write", {"path": path, "content": content})):
            return denied

        session_id = ctx.deps.session_state.session_id
        exit_code = 0
        try:
            exec_result = await ctx.deps.sandbox.file_write(session_id, path, content)
            result = exec_result.output
            exit_code = exec_result.exit_code
        except Exception as exc:
            _log_sandbox_tool_exception("write", session_id)
            result = f"Error: {exc}"
            exit_code = -1
        _notify_result(ctx, "write", result, exit_code)
        return result

    @agent.tool
    async def str_replace(
        ctx: RunContext[Deps],
        path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> str | ToolDenied:
        """Replace text in a file.

        Use ``replace_all=False`` (default) to require exactly one match.
        Use ``replace_all=True`` to replace all matches.
        Returns a compact status string including match count and original line number(s).
        """
        if not ctx.tool_call_approved and (
            denied := await _gate(
                ctx,
                "str_replace",
                {
                    "path": path,
                    "old_string": old_string,
                    "new_string": new_string,
                    "replace_all": replace_all,
                },
            )
        ):
            return denied

        session_id = ctx.deps.session_state.session_id
        exit_code = 0
        try:
            exec_result = await ctx.deps.sandbox.file_str_replace(
                session_id,
                path,
                old_string,
                new_string,
                replace_all=replace_all,
            )
            result = exec_result.output
            exit_code = exec_result.exit_code
        except Exception as exc:
            _log_sandbox_tool_exception("str_replace", session_id)
            result = f"Error: {exc}"
            exit_code = -1
        _notify_result(ctx, "str_replace", result, exit_code)
        return result

    # --- Runtime ---

    @agent.tool
    async def exec(
        ctx: RunContext[Deps],
        command: str,
        title: str | None = None,
        contexts: list[str] | None = None,
    ) -> str | ToolDenied:
        """Run a shell command (typically bash) and return its output. Runs in a Docker sandbox.

        Args:
            command: The shell command to execute.
            title: Optional short label (a few words) describing the purpose of this command,
                e.g. "clean up temp files and commit".
            contexts: Optional list of activated skill names whose declared network domains
                and credentials should be available for this command. Each entry must match
                an activated skill; unknown names are rejected.
        """
        contexts = contexts or []

        # Validate contexts against activated skills
        grants = ctx.deps.session_state.context_grants
        invalid = [c for c in contexts if c not in grants]
        if invalid:
            return f"Unknown contexts: {', '.join(invalid)}. If these are skills, please activate them first."

        args: dict[str, Any] = {"command": command}
        if title is not None:
            args["title"] = title
        if contexts:
            args["contexts"] = contexts
        if not ctx.tool_call_approved:
            if denied := await _gate(ctx, "exec", args):
                return denied
        else:
            _notify_approved_start(ctx, "exec", args)

        session_id = ctx.deps.session_state.session_id

        # Build per-exec injection data from matching context grants
        extra_env: dict[str, str] = {}
        context_domains: set[str] = set()
        context_file_creds: list[tuple[str, str, str]] = []  # (skill_name, file_path, vault_path)
        missing_cached: list[tuple[str, str]] = []
        injected_creds: list[tuple[str, str]] = []  # (ctx_name, vault_path)
        for ctx_name in contexts:
            grant = grants[ctx_name]
            context_domains.update(grant.domains)
            for decl in grant.credential_decls:
                if not (decl.env_var or decl.file):
                    continue
                cached = ctx.deps.sandbox.get_cached_credential(session_id, decl.vault_path)
                if cached is None:
                    missing_cached.append((ctx_name, decl.vault_path))
                    continue
                injected_creds.append((ctx_name, decl.vault_path))
                if decl.env_var:
                    extra_env[decl.env_var] = cached
                if decl.file:
                    context_file_creds.append((ctx_name, decl.file, decl.vault_path))

        try:
            exec_result = await ctx.deps.sandbox.exec_command(
                session_id,
                command,
                contexts=contexts,
                extra_env=extra_env or None,
                context_domains=context_domains or None,
                context_file_creds=context_file_creds or None,
            )
            result = exec_result.output
            exit_code = exec_result.exit_code
        except Exception as exc:
            _log_sandbox_tool_exception("exec", session_id)
            result = f"Error: {exc}"
            exit_code = -1

        if missing_cached:
            lines = "\n".join(f"  - skill {name!r}, vault path {vp!r}" for name, vp in dict.fromkeys(missing_cached))
            result = (
                "Warning: these credentials are not in the session cache and were not injected "
                "(re-run use_skill for the skill if you need them):\n"
                f"{lines}\n\n"
            ) + result

        # Notify credential injection for each context-scoped credential
        for ctx_name, vp in injected_creds:
            ctx.deps.security.notify_credential_decision(
                vp,
                f"[skill] {vp}",
                approval_source="skill",
                approval_verdict="allow",
                approval_explanation=f"skill-declared credential ({ctx_name})",
            )

        ctx.deps.security.append(
            ToolResultEntry(tool="exec", status="error" if exit_code != 0 else "success"),
        )

        _notify_result(ctx, "exec", result, exit_code)
        return result

    return agent
