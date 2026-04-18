from __future__ import annotations

import re
from asyncio.locks import Lock
from collections.abc import Awaitable, Callable
from pathlib import Path

from loguru import logger

from carapace.sandbox import file_ops
from carapace.sandbox.exec_flow import SandboxExecCoordinator, SandboxExecState
from carapace.sandbox.file_ops import SandboxFileOps
from carapace.sandbox.runtime import (
    ContainerRuntime,
    ExecResult,
    SkillActivationError,
    SkillActivationInputs,
)
from carapace.sandbox.session_lifecycle import (
    SandboxSessionLifecycle,
    SandboxSessionLifecycleState,
    SessionContainer,
)
from carapace.sandbox.skill_activation import SkillActivationRunner
from carapace.security.context import ApprovalSource, ApprovalVerdict

_SKILL_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
FILE_READ_SCRIPT = file_ops.FILE_READ_SCRIPT
MAX_READ_OUTPUT_CHARS = file_ops.MAX_READ_OUTPUT_CHARS
SANDBOX_READ_BODY_SEPARATOR = file_ops.SANDBOX_READ_BODY_SEPARATOR
READ_TOOL_MAX_LINE_WINDOW = file_ops.READ_TOOL_MAX_LINE_WINDOW


def _validate_skill_name(skill_name: str) -> str | None:
    """Return an error message if ``skill_name`` is not a safe directory name; ``None`` if valid.

    Must be nonempty, start with an alphanumeric character, and contain only
    alphanumerics, hyphens, underscores, or dots.
    """
    if not skill_name or not _SKILL_NAME_RE.match(skill_name):
        return f"Invalid skill name: {skill_name!r}"
    return None


class SandboxManager:
    def __init__(
        self,
        runtime: ContainerRuntime,
        data_dir: Path,
        knowledge_dir: Path,
        base_image: str = "carapace-sandbox:latest",
        network_name: str = "carapace-sandbox",
        idle_timeout_minutes: int = 15,
        proxy_port: int = 3128,
        sandbox_port: int = 8322,
        git_author: str = "Carapace <carapace@%h>",
    ) -> None:
        self._runtime = runtime
        self._data_dir = data_dir
        self._knowledge_dir = knowledge_dir
        self._git_author = git_author
        self._base_image = base_image
        self._network_name = network_name
        self._idle_timeout = idle_timeout_minutes * 60
        self._proxy_port = proxy_port
        self._sandbox_port = sandbox_port
        self._sessions: dict[str, SessionContainer] = {}
        self._token_to_session: dict[str, str] = {}
        self._session_tokens: dict[str, str] = {}
        self._allowed_domains: dict[str, set[str]] = {}
        self._exec_temp_domains: dict[str, set[str]] = {}  # session_id -> domains, cleared after each exec
        self._exec_context_skill_domains: dict[str, set[str]] = {}  # skill-sourced subset of exec_temp_domains
        self._session_current_command: dict[str, str] = {}
        self._domain_approval_cbs: dict[str, Callable[[str, str], Awaitable[bool]]] = {}
        self._domain_notify_cbs: dict[
            str,
            Callable[[str, str, ApprovalSource | None, ApprovalVerdict | None, str | None], None],
        ] = {}
        self._exec_locks: dict[str, Lock] = {}
        self._proxy_bypass_sessions: set[str] = set()
        self._stashed_session_env: dict[str, dict[str, str]] = {}
        self._credential_cache: dict[str, dict[str, str]] = {}  # session_id -> {vault_path: value}
        self._session_current_contexts: dict[str, list[str]] = {}
        self._exec_notified_domains: dict[str, set[str]] = {}  # dedupe silent-allow domain UI notifications
        self._exec_notified_credentials: dict[str, set[str]] = {}  # dedupe credential UI notifications
        self._get_activated_skills_cb: Callable[[str], list[str]] | None = None
        self._skill_activation_inputs_cb: Callable[[str, str], Awaitable[SkillActivationInputs]] | None = None
        self._session_lifecycle = SandboxSessionLifecycle(
            runtime=runtime,
            state=SandboxSessionLifecycleState(
                sessions=self._sessions,
                token_to_session=self._token_to_session,
                session_tokens=self._session_tokens,
                allowed_domains=self._allowed_domains,
                exec_temp_domains=self._exec_temp_domains,
                exec_context_skill_domains=self._exec_context_skill_domains,
                session_current_command=self._session_current_command,
                domain_approval_cbs=self._domain_approval_cbs,
                domain_notify_cbs=self._domain_notify_cbs,
                exec_locks=self._exec_locks,
                proxy_bypass_sessions=self._proxy_bypass_sessions,
                stashed_session_env=self._stashed_session_env,
                credential_cache=self._credential_cache,
                session_current_contexts=self._session_current_contexts,
                exec_notified_domains=self._exec_notified_domains,
                exec_notified_credentials=self._exec_notified_credentials,
            ),
            data_dir=data_dir,
            knowledge_dir=knowledge_dir,
            base_image=base_image,
            network_name=network_name,
            idle_timeout=self._idle_timeout,
            proxy_port=proxy_port,
            sandbox_port=sandbox_port,
            git_author=git_author,
        )
        self._exec_coordinator = SandboxExecCoordinator(
            runtime=runtime,
            state=SandboxExecState(
                sessions=self._sessions,
                allowed_domains=self._allowed_domains,
                exec_temp_domains=self._exec_temp_domains,
                exec_context_skill_domains=self._exec_context_skill_domains,
                session_current_command=self._session_current_command,
                domain_approval_cbs=self._domain_approval_cbs,
                domain_notify_cbs=self._domain_notify_cbs,
                exec_locks=self._exec_locks,
                proxy_bypass_sessions=self._proxy_bypass_sessions,
                session_current_contexts=self._session_current_contexts,
                exec_notified_domains=self._exec_notified_domains,
                exec_notified_credentials=self._exec_notified_credentials,
            ),
        )
        self._sandbox_file_ops = SandboxFileOps(
            exec_in_session=self._exec,
            exec_in_container=self._exec_in_container,
            get_session=self._sessions.get,
        )
        self._skill_activation_runner = SkillActivationRunner(
            knowledge_workdir=self._KNOWLEDGE_WORKDIR,
            get_activation_inputs=self._get_skill_activation_inputs,
            exec_in_session=self._exec,
            exec_in_container=self._exec_in_container,
            write_context_file_credentials=self._sandbox_file_ops.write_context_file_credentials,
            delete_context_file_credentials=self._sandbox_file_ops.delete_context_file_credentials,
        )
        logger.info(
            f"SandboxManager initialized (image={base_image}, "
            + f"network={network_name}, proxy_port={proxy_port}, idle_timeout={idle_timeout_minutes}m)"
        )

    def set_activated_skills_callback(self, cb: Callable[[str], list[str]]) -> None:
        """Register a callback to retrieve activated skills for a session (from persisted state)."""
        self._get_activated_skills_cb = cb

    def set_skill_activation_inputs_callback(
        self,
        cb: Callable[[str, str], Awaitable[SkillActivationInputs]],
    ) -> None:
        """Register a callback to retrieve activation inputs for a skill."""
        self._skill_activation_inputs_cb = cb

    async def _get_skill_activation_inputs(self, session_id: str, skill_name: str) -> SkillActivationInputs:
        if self._skill_activation_inputs_cb is None:
            return SkillActivationInputs()
        return await self._skill_activation_inputs_cb(session_id, skill_name)

    def _get_or_create_token(self, session_id: str) -> str:
        return self._session_lifecycle.get_or_create_token(session_id)

    async def _log_container_tail(self, container_id: str, session_id: str) -> None:
        await self._session_lifecycle.log_container_tail(container_id, session_id)

    def _get_exec_lock(self, session_id: str) -> Lock:
        return self._exec_coordinator.get_exec_lock(session_id)

    async def ensure_session(self, session_id: str) -> tuple[SessionContainer, bool]:
        return await self._session_lifecycle.ensure_session(session_id)

    def _sandbox_name(self, session_id: str) -> str:
        return self._session_lifecycle.sandbox_name(session_id)

    def _build_proxy_env(self, session_id: str, proxy_token: str, proxy_url: str) -> dict[str, str]:
        return self._session_lifecycle.build_proxy_env(session_id, proxy_token, proxy_url)

    async def _exec_in_container(
        self,
        sc: SessionContainer,
        command: str,
        timeout: int = 30,
        *,
        bypass_proxy: bool = False,
        workdir: str | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> ExecResult:
        return await self._exec_coordinator.exec_in_container(
            sc,
            command,
            timeout=timeout,
            bypass_proxy=bypass_proxy,
            workdir=workdir,
            extra_env=extra_env,
        )

    async def _exec(
        self,
        session_id: str,
        command: str,
        timeout: int = 30,
        *,
        bypass_proxy: bool = False,
        workdir: str | None = None,
        contexts: list[str] | None = None,
        extra_env: dict[str, str] | None = None,
        context_domains: set[str] | None = None,
        context_file_creds: list[tuple[str, str, str]] | None = None,
        after_exec_credential_notify: Callable[[], None] | None = None,
    ) -> ExecResult:
        return await self._exec_coordinator.exec(
            session_id,
            command,
            timeout=timeout,
            ensure_session=lambda sid: self.ensure_session(sid),
            rebuild_skill_venvs=lambda sid: self._rebuild_skill_venvs(sid),
            log_container_tail=lambda container_id, sid: self._log_container_tail(container_id, sid),
            prepare_session_recreate=lambda sid: self._prepare_session_recreate(sid),
            exec_in_container=lambda sc, cmd, cmd_timeout=30, **kwargs: self._exec_in_container(
                sc,
                cmd,
                timeout=cmd_timeout,
                **kwargs,
            ),
            write_context_file_credentials=lambda sc, creds: self._write_context_file_credentials(sc, creds),
            delete_context_file_credentials=lambda sid, written: self._delete_context_file_credentials(sid, written),
            bypass_proxy=bypass_proxy,
            workdir=workdir,
            contexts=contexts,
            extra_env=extra_env,
            context_domains=context_domains,
            context_file_creds=context_file_creds,
            after_exec_credential_notify=after_exec_credential_notify,
        )

    _KNOWLEDGE_WORKDIR = "/workspace"

    async def exec_command(
        self,
        session_id: str,
        command: str,
        timeout: int = 3600,
        *,
        contexts: list[str] | None = None,
        extra_env: dict[str, str] | None = None,
        context_domains: set[str] | None = None,
        context_file_creds: list[tuple[str, str, str]] | None = None,
        after_exec_credential_notify: Callable[[], None] | None = None,
    ) -> ExecResult:
        """Run a command in the sandbox and return the result.

        *contexts*: activated skill names active for this exec.
        *extra_env*: per-exec env vars (credential values) — merged on top of session env.
        *context_domains*: domains to add to exec-scoped temp allowlist.
        *context_file_creds*: ``(skill_name, file_path, value)`` tuples for file-based
            credentials to be written before exec and deleted after.
        *after_exec_credential_notify*: passed through to `_exec` (see there).
        """
        result = await self._exec(
            session_id,
            command,
            timeout=timeout,
            workdir=self._KNOWLEDGE_WORKDIR,
            contexts=contexts,
            extra_env=extra_env,
            context_domains=context_domains,
            context_file_creds=context_file_creds,
            after_exec_credential_notify=after_exec_credential_notify,
        )
        output = result.output
        if result.exit_code != 0 and f"[exit code: {result.exit_code}]" not in output:
            logger.debug(f"Command failed in session {session_id} (exit {result.exit_code}): {command}")
            output += f"\n[exit code: {result.exit_code}]"
        return ExecResult(exit_code=result.exit_code, output=output or "(no output)")

    # ------------------------------------------------------------------
    # File operations (executed inside the sandbox container via
    # shell commands and small inline Python snippets).
    # Data is passed as base64 CLI args to avoid shell-escaping issues.
    # ------------------------------------------------------------------

    async def file_read(self, session_id: str, path: str, *, offset: int = 0, limit: int = 100) -> str:
        return await self._sandbox_file_ops.file_read(session_id, path, offset=offset, limit=limit)

    async def file_write(
        self,
        session_id: str,
        path: str,
        content: str,
        *,
        mode: int | None = None,
        workdir: str | None = None,
        quote: bool = True,
    ) -> ExecResult:
        return await self._sandbox_file_ops.file_write(
            session_id,
            path,
            content,
            mode=mode,
            workdir=workdir,
            quote=quote,
        )

    async def file_str_replace(
        self,
        session_id: str,
        path: str,
        old_string: str,
        new_string: str,
        *,
        replace_all: bool = False,
    ) -> ExecResult:
        return await self._sandbox_file_ops.file_str_replace(
            session_id,
            path,
            old_string,
            new_string,
            replace_all=replace_all,
        )

    async def activate_skill(self, session_id: str, skill_name: str) -> str:
        if err := _validate_skill_name(skill_name):
            return err

        sc, _ = await self.ensure_session(session_id)

        # Check that the skill exists in the server-side knowledge store.
        # The sandbox already has it at /workspace/skills/{name} via git clone.
        master_skill_dir = self._knowledge_dir / "skills" / skill_name
        if not master_skill_dir.exists():
            logger.warning(f"Skill '{skill_name}' not found for session {session_id}")
            return f"Skill '{skill_name}' not found."

        activation_msg = ""
        try:
            activation_lines = await self._skill_activation_runner.restore_and_run_detected_providers(
                sc,
                skill_name,
                master_skill_dir,
                run_session_id=session_id,
            )
            activation_msg = "\n".join(activation_lines)
        except SkillActivationError as exc:
            logger.info(f"Activated skill '{skill_name}' in session {session_id} (with errors)")
            raise SkillActivationError(
                f"Skill '{skill_name}' activated at /workspace/skills/{skill_name}/ but "
                f"automatic setup failed: {exc}\n"
                "The skill is available but automatic setup did not complete. "
                "You may need to fix the committed provider files and reactivate the skill."
            ) from exc

        logger.info(f"Activated skill '{skill_name}' in session {session_id}")
        parts = [f"Skill '{skill_name}' activated at /workspace/skills/{skill_name}/"]
        if activation_msg:
            parts.extend(activation_msg.splitlines())
        return "\n".join(parts)

    async def _file_write_in_container(
        self,
        sc: SessionContainer,
        path: str,
        content: str,
        *,
        mode: int | None = None,
        workdir: str | None = None,
        quote: bool = True,
    ) -> ExecResult:
        return await self._sandbox_file_ops.file_write_in_container(
            sc,
            path,
            content,
            mode=mode,
            workdir=workdir,
            quote=quote,
        )

    async def _file_delete_in_container(
        self,
        sc: SessionContainer,
        path: str,
        *,
        workdir: str | None = None,
        quote: bool = True,
    ) -> ExecResult:
        return await self._sandbox_file_ops.file_delete_in_container(sc, path, workdir=workdir, quote=quote)

    async def _write_context_file_credentials(
        self,
        sc: SessionContainer,
        context_file_creds: list[tuple[str, str, str]],
    ) -> list[tuple[str, str]]:
        return await self._sandbox_file_ops.write_context_file_credentials(sc, context_file_creds)

    async def _delete_context_file_credentials(
        self,
        session_id: str,
        written_files: list[tuple[str, str]],
    ) -> None:
        await self._sandbox_file_ops.delete_context_file_credentials(session_id, written_files)

    async def _sync_skill_venv(self, sc: SessionContainer, skill_name: str) -> str:
        """Restore trusted skill files from git and rerun automatic setup providers."""
        master = self._knowledge_dir / "skills" / skill_name
        lines = await self._skill_activation_runner.restore_and_run_detected_providers(sc, skill_name, master)
        return "\n".join(lines)

    async def rebuild_skill_venvs(self, session_id: str, activated_skills: list[str]) -> None:
        """Restore trusted config and rebuild venvs for activated skills.

        Called by SessionEngine after container recreation.
        """
        sc = self._sessions.get(session_id)
        if sc is None:
            logger.warning(f"Cannot rebuild skill venvs: missing container state for session {session_id}")
            return
        for skill_name in activated_skills:
            logger.info(f"Syncing skill '{skill_name}' after container recreation")
            try:
                await self._sync_skill_venv(sc, skill_name)
            except SkillActivationError as exc:
                logger.error(f"Failed to rerun automatic setup for '{skill_name}': {exc}")

    async def _rebuild_skill_venvs(self, session_id: str) -> None:
        """Internal: rebuild venvs using the activated_skills callback (for _exec recreation)."""
        if not self._get_activated_skills_cb:
            return
        activated = self._get_activated_skills_cb(session_id)
        if activated:
            await self.rebuild_skill_venvs(session_id, activated)

    async def cleanup_session(self, session_id: str) -> None:
        await self._session_lifecycle.cleanup_session(session_id)

    async def destroy_session(self, session_id: str) -> None:
        await self._session_lifecycle.destroy_session(session_id)

    async def reset_session(self, session_id: str) -> None:
        await self._session_lifecycle.reset_session(session_id)

    async def cleanup_idle(self) -> None:
        await self._session_lifecycle.cleanup_idle()

    async def cleanup_all(self) -> None:
        await self._session_lifecycle.cleanup_all()

    async def cleanup_orphaned_sandboxes(self, known_sessions: set[str]) -> int:
        return await self._session_lifecycle.cleanup_orphaned_sandboxes(known_sessions)

    def set_session_env(self, session_id: str, env: dict[str, str]) -> None:
        self._session_lifecycle.set_session_env(session_id, env)

    def get_session_env(self, session_id: str) -> dict[str, str]:
        return self._session_lifecycle.get_session_env(session_id)

    def verify_session_token(self, session_id: str, token: str) -> bool:
        return self._session_lifecycle.verify_session_token(session_id, token)

    def allow_domains(self, session_id: str, domains: set[str]) -> None:
        self._exec_coordinator.allow_domains(session_id, domains)

    def get_allowed_domains(self, session_id: str) -> set[str]:
        return self._exec_coordinator.get_allowed_domains(session_id)

    def get_domain_info(self, session_id: str) -> list[dict[str, str]]:
        return self._exec_coordinator.get_domain_info(session_id)

    def get_effective_domains(self, session_id: str) -> set[str]:
        return self._exec_coordinator.get_effective_domains(session_id)

    # ------------------------------------------------------------------
    # Credential cache (per-exec injection, not session_env)
    # ------------------------------------------------------------------

    def cache_credential(self, session_id: str, vault_path: str, value: str) -> None:
        """Store a credential value in memory for later per-exec injection."""
        self._credential_cache.setdefault(session_id, {})[vault_path] = value

    def get_cached_credential(self, session_id: str, vault_path: str) -> str | None:
        """Return a cached credential value, or *None* if not cached."""
        return self._credential_cache.get(session_id, {}).get(vault_path)

    def get_current_contexts(self, session_id: str) -> list[str]:
        return self._exec_coordinator.get_current_contexts(session_id)

    def is_domain_skill_granted(self, session_id: str, domain: str) -> bool:
        return self._exec_coordinator.is_domain_skill_granted(session_id, domain)

    def is_domain_bypass(self, session_id: str) -> bool:
        return self._exec_coordinator.is_domain_bypass(session_id)

    def mark_credential_notified(self, session_id: str, vault_path: str) -> bool:
        return self._exec_coordinator.mark_credential_notified(session_id, vault_path)

    def notify_domain_access(self, session_id: str, domain: str, allowed: bool) -> None:
        self._exec_coordinator.notify_domain_access(session_id, domain, allowed)

    # ------------------------------------------------------------------
    # Proxy domain approval
    # ------------------------------------------------------------------

    def set_domain_approval_callback(self, session_id: str, cb: Callable[[str, str], Awaitable[bool]] | None) -> None:
        self._exec_coordinator.set_domain_approval_callback(session_id, cb)

    def set_domain_notify_callback(
        self,
        session_id: str,
        cb: Callable[[str, str, ApprovalSource | None, ApprovalVerdict | None, str | None], None] | None,
    ) -> None:
        self._exec_coordinator.set_domain_notify_callback(session_id, cb)

    async def request_domain_approval(self, session_id: str, domain: str) -> bool:
        return await self._exec_coordinator.request_domain_approval(session_id, domain)

    def _prepare_session_recreate(self, session_id: str) -> None:
        self._session_lifecycle.prepare_session_recreate(session_id)

    def _cleanup_tracking(
        self,
        session_id: str,
    ) -> None:
        self._session_lifecycle.cleanup_tracking(session_id)
        self._exec_coordinator.cleanup_tracking(session_id)
