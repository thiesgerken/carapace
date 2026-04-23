from __future__ import annotations

import re
import shlex
import shutil
import textwrap
import time
from asyncio.locks import Lock
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from loguru import logger

from carapace.sandbox import file_ops
from carapace.sandbox.exec_flow import SandboxExecCoordinator, SandboxExecState
from carapace.sandbox.file_ops import SandboxFileOps
from carapace.sandbox.runtime import (
    ContainerRuntime,
    ExecResult,
    NetworkTunnel,
    SandboxInspection,
    SkillActivationError,
    SkillActivationInputs,
)
from carapace.sandbox.session_lifecycle import (
    SandboxSessionLifecycle,
    SandboxSessionLifecycleState,
    SessionContainer,
)
from carapace.sandbox.skill_activation import SkillActivationRunner
from carapace.sandbox.state import (
    SessionSandboxSnapshot,
    clear_sandbox_snapshot,
    load_sandbox_snapshot,
    save_sandbox_snapshot,
)
from carapace.security.context import ApprovalSource, ApprovalVerdict

_SKILL_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
FILE_READ_SCRIPT = file_ops.FILE_READ_SCRIPT
MAX_READ_OUTPUT_CHARS = file_ops.MAX_READ_OUTPUT_CHARS
SANDBOX_READ_BODY_SEPARATOR = file_ops.SANDBOX_READ_BODY_SEPARATOR
READ_TOOL_MAX_LINE_WINDOW = file_ops.READ_TOOL_MAX_LINE_WINDOW

_CONTEXT_TUNNEL_HELPER = r"""#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import base64
from pathlib import Path
import sys
from urllib.parse import unquote, urlsplit


async def _close_writer(writer: asyncio.StreamWriter) -> None:
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()
    except (BrokenPipeError, ConnectionResetError):
        pass
    finally:
        await _close_writer(writer)


async def _open_proxy_tunnel(
    proxy_url: str,
    target_host: str,
    target_port: int,
) -> tuple[bytes, asyncio.StreamReader, asyncio.StreamWriter]:
    parsed = urlsplit(proxy_url)
    if not parsed.hostname:
        raise RuntimeError("HTTP_PROXY does not include a hostname")
    proxy_port = parsed.port or 80
    reader, writer = await asyncio.open_connection(parsed.hostname, proxy_port)

    headers = [f"CONNECT {target_host}:{target_port} HTTP/1.1", f"Host: {target_host}:{target_port}"]
    if parsed.username or parsed.password:
        creds = f"{unquote(parsed.username or '')}:{unquote(parsed.password or '')}"
        encoded = base64.b64encode(creds.encode()).decode()
        headers.append(f"Proxy-Authorization: Basic {encoded}")
    request = "\r\n".join(headers) + "\r\n\r\n"
    writer.write(request.encode("latin-1"))
    await writer.drain()

    response = b""
    while b"\r\n\r\n" not in response:
        chunk = await reader.read(4096)
        if not chunk:
            raise RuntimeError("proxy closed CONNECT response early")
        response += chunk
        if len(response) > 65536:
            raise RuntimeError("proxy CONNECT response too large")

    header_block, prebuffer = response.split(b"\r\n\r\n", 1)
    status_line = header_block.split(b"\r\n", 1)[0]
    status = status_line.decode("latin-1", errors="replace")
    if not status.startswith("HTTP/1.1 200") and not status.startswith("HTTP/1.0 200"):
        raise RuntimeError(f"proxy CONNECT failed: {status}")
    return prebuffer, reader, writer


async def _handle_client(
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
    proxy_url: str,
    target_host: str,
    target_port: int,
) -> None:
    upstream_reader: asyncio.StreamReader | None = None
    upstream_writer: asyncio.StreamWriter | None = None
    try:
        prebuffer, upstream_reader, upstream_writer = await _open_proxy_tunnel(proxy_url, target_host, target_port)
        if prebuffer:
            client_writer.write(prebuffer)
            await client_writer.drain()
        await asyncio.gather(
            _pipe(client_reader, upstream_writer),
            _pipe(upstream_reader, client_writer),
        )
    except Exception as exc:
        print(f"tunnel error for {target_host}:{target_port}: {exc}", file=sys.stderr)
        await _close_writer(client_writer)
        if upstream_writer is not None:
            await _close_writer(upstream_writer)


async def _run() -> None:
    parser = argparse.ArgumentParser(description="Carapace CONNECT tunnel helper")
    parser.add_argument("--listen-host", default="127.0.0.1")
    parser.add_argument("--listen-port", type=int, required=True)
    parser.add_argument("--target-host", required=True)
    parser.add_argument("--target-port", type=int, required=True)
    parser.add_argument("--proxy", default="")
    parser.add_argument("--ready-file", default="")
    args = parser.parse_args()

    proxy_url = args.proxy or ""
    if not proxy_url:
        raise RuntimeError("HTTP_PROXY is required for the tunnel helper")

    server = await asyncio.start_server(
        lambda r, w: _handle_client(r, w, proxy_url, args.target_host, args.target_port),
        args.listen_host,
        args.listen_port,
    )
    if args.ready_file:
        Path(args.ready_file).write_text("ready\n")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(_run())
"""


@dataclass(frozen=True, slots=True)
class _TunnelPaths:
    helper_path: str
    hosts_backup_path: str
    pid_path: str
    log_path: str
    ready_path: str


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

    def _sandbox_snapshot_path(self, session_id: str) -> Path:
        return self._data_dir / "sessions" / session_id / "sandbox.yaml"

    def _workspace_path(self, session_id: str) -> Path:
        return self._data_dir / "sessions" / session_id / "workspace"

    def _clear_workspace_storage(self, session_id: str) -> None:
        shutil.rmtree(self._workspace_path(session_id), ignore_errors=True)

    async def refresh_sandbox_snapshot(
        self,
        session_id: str,
        *,
        measure_usage: bool = False,
        container_id: str | None = None,
    ) -> SessionSandboxSnapshot:
        sandbox_name = self._sandbox_name(session_id)
        resolved_container_id = container_id
        if resolved_container_id is None:
            sc = self._sessions.get(session_id)
            if sc is not None:
                resolved_container_id = sc.container_id
            else:
                existing_id = await self._runtime.sandbox_exists(sandbox_name)
                resolved_container_id = existing_id if isinstance(existing_id, str) and existing_id else None

        inspection = SandboxInspection(
            exists=resolved_container_id is not None,
            status="running" if resolved_container_id is not None else "missing",
            resource_id=resolved_container_id,
        )
        inspect_sandbox = getattr(self._runtime, "inspect_sandbox", None)
        if callable(inspect_sandbox):
            try:
                inspected = await inspect_sandbox(session_id, sandbox_name, resolved_container_id)
                if isinstance(inspected, SandboxInspection):
                    inspection = inspected
                else:
                    inspection = SandboxInspection.model_validate(inspected)
            except Exception:
                logger.debug(
                    f"Sandbox inspection unavailable for session {session_id}; falling back to cached/basic state"
                )

        existing = load_sandbox_snapshot(self._sandbox_snapshot_path(session_id))
        measured_used_bytes = existing.last_measured_used_bytes if existing is not None else None
        measured_at = existing.last_measured_at if existing is not None else None
        if measure_usage:
            measure_workspace_usage = getattr(self._runtime, "measure_workspace_usage", None)
            if callable(measure_workspace_usage):
                try:
                    current_used_bytes = await measure_workspace_usage(session_id, resolved_container_id)
                except Exception:
                    current_used_bytes = None
                if isinstance(current_used_bytes, int):
                    measured_used_bytes = current_used_bytes
                    measured_at = datetime.now(tz=UTC)
        if not inspection.storage_present:
            measured_used_bytes = None
            measured_at = None

        runtime_kind = getattr(self._runtime, "runtime_kind", None)
        if runtime_kind not in ("docker", "kubernetes"):
            runtime_kind = None

        snapshot = SessionSandboxSnapshot(
            exists=inspection.exists,
            runtime=runtime_kind,
            status=inspection.status,
            resource_id=inspection.resource_id,
            resource_kind=inspection.resource_kind,
            storage_present=inspection.storage_present,
            provisioned_bytes=inspection.provisioned_bytes,
            last_measured_used_bytes=measured_used_bytes,
            last_measured_at=measured_at,
            updated_at=datetime.now(tz=UTC),
        )
        save_sandbox_snapshot(self._sandbox_snapshot_path(session_id), snapshot)
        return snapshot

    def get_cached_sandbox_snapshot(self, session_id: str) -> SessionSandboxSnapshot | None:
        return load_sandbox_snapshot(self._sandbox_snapshot_path(session_id))

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
        context_tunnels: list[NetworkTunnel] | None = None,
        context_file_creds: list[tuple[str, str, str]] | None = None,
        after_exec_credential_notify: Callable[[], None] | None = None,
    ) -> ExecResult:
        return await self._exec_coordinator.exec(
            session_id,
            command,
            timeout=timeout,
            ensure_session=lambda sid: self.ensure_session(sid),
            rerun_skill_setup=lambda sid: self._rerun_activated_skill_setup(sid),
            log_container_tail=lambda container_id, sid: self._log_container_tail(container_id, sid),
            prepare_session_recreate=lambda sid: self._prepare_session_recreate(sid),
            exec_in_container=lambda sc, cmd, cmd_timeout=30, **kwargs: self._exec_in_container(
                sc,
                cmd,
                timeout=cmd_timeout,
                **kwargs,
            ),
            prepare_context_tunnels=lambda sc, tunnels: self._prepare_context_tunnels(sc, tunnels),
            cleanup_context_tunnels=lambda sc, tunnels: self._cleanup_context_tunnels(sc, tunnels),
            write_context_file_credentials=lambda sc, creds: self._write_context_file_credentials(sc, creds),
            delete_context_file_credentials=lambda sid, written: self._delete_context_file_credentials(sid, written),
            bypass_proxy=bypass_proxy,
            workdir=workdir,
            contexts=contexts,
            extra_env=extra_env,
            context_domains=context_domains,
            context_tunnels=context_tunnels,
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
        context_tunnels: list[NetworkTunnel] | None = None,
        context_file_creds: list[tuple[str, str, str]] | None = None,
        after_exec_credential_notify: Callable[[], None] | None = None,
    ) -> ExecResult:
        """Run a command in the sandbox and return the result.

        *contexts*: activated skill names active for this exec.
        *extra_env*: per-exec env vars (credential values) — merged on top of session env.
        *context_domains*: domains to add to exec-scoped temp allowlist.
        *context_tunnels*: declarative exec-scoped TCP tunnels to establish for this command.
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
            context_tunnels=context_tunnels,
            context_file_creds=context_file_creds,
            after_exec_credential_notify=after_exec_credential_notify,
        )
        output = result.output
        if result.exit_code != 0 and f"[exit code: {result.exit_code}]" not in output:
            logger.debug(f"Command failed in session {session_id} (exit {result.exit_code}): {command}")
            output += f"\n[exit code: {result.exit_code}]"
        await self.refresh_sandbox_snapshot(session_id, measure_usage=True)
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
        result = await self._sandbox_file_ops.file_write(
            session_id,
            path,
            content,
            mode=mode,
            workdir=workdir,
            quote=quote,
        )
        await self.refresh_sandbox_snapshot(session_id, measure_usage=True)
        return result

    async def file_str_replace(
        self,
        session_id: str,
        path: str,
        old_string: str,
        new_string: str,
        *,
        replace_all: bool = False,
    ) -> ExecResult:
        result = await self._sandbox_file_ops.file_str_replace(
            session_id,
            path,
            old_string,
            new_string,
            replace_all=replace_all,
        )
        await self.refresh_sandbox_snapshot(session_id, measure_usage=True)
        return result

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
        await self.refresh_sandbox_snapshot(session_id, measure_usage=True, container_id=sc.container_id)
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

    async def _rerun_skill_setup(self, sc: SessionContainer, skill_name: str) -> str:
        """Restore trusted skill files from git and rerun automatic setup providers."""
        master = self._knowledge_dir / "skills" / skill_name
        lines = await self._skill_activation_runner.restore_and_run_detected_providers(sc, skill_name, master)
        return "\n".join(lines)

    async def rerun_skill_setup(self, session_id: str, activated_skills: list[str]) -> None:
        """Restore trusted config and rerun automatic setup for activated skills.

        Called by SessionEngine after container recreation.
        """
        sc = self._sessions.get(session_id)
        if sc is None:
            logger.warning(f"Cannot rerun skill setup: missing container state for session {session_id}")
            return
        for skill_name in activated_skills:
            logger.info(f"Rerunning automatic setup for skill '{skill_name}' after container recreation")
            try:
                await self._rerun_skill_setup(sc, skill_name)
            except SkillActivationError as exc:
                logger.error(f"Failed to rerun automatic setup for '{skill_name}': {exc}")

    async def _rerun_activated_skill_setup(self, session_id: str) -> None:
        """Internal: rerun automatic setup for activated skills during session recreation."""
        if not self._get_activated_skills_cb:
            return
        activated = self._get_activated_skills_cb(session_id)
        if activated:
            await self.rerun_skill_setup(session_id, activated)

    def _normalize_context_tunnels(self, tunnels: list[NetworkTunnel]) -> list[NetworkTunnel]:
        by_local_port: dict[int, NetworkTunnel] = {}
        unique: dict[tuple[str, int, int], NetworkTunnel] = {}
        for tunnel in tunnels:
            existing = by_local_port.get(tunnel.local_port)
            if existing is not None and (existing.host, existing.remote_port) != (tunnel.host, tunnel.remote_port):
                raise ValueError(
                    "Conflicting network.tunnels declarations for local_port "
                    + f"{tunnel.local_port}: {existing.display} vs {tunnel.display}"
                )
            by_local_port[tunnel.local_port] = tunnel
            unique[(tunnel.host, tunnel.remote_port, tunnel.local_port)] = tunnel
        return sorted(unique.values(), key=lambda tunnel: (tunnel.local_port, tunnel.host, tunnel.remote_port))

    def _context_tunnel_paths(self, session_id: str, tunnel: NetworkTunnel) -> _TunnelPaths:
        return _TunnelPaths(
            helper_path=f"/tmp/carapace-tunnel-helper-{session_id}.py",
            hosts_backup_path=f"/tmp/carapace-tunnel-hosts-{session_id}.bak",
            pid_path=f"/tmp/carapace-tunnel-{session_id}-{tunnel.local_port}.pid",
            log_path=f"/tmp/carapace-tunnel-{session_id}-{tunnel.local_port}.log",
            ready_path=f"/tmp/carapace-tunnel-{session_id}-{tunnel.local_port}.ready",
        )

    async def _prepare_context_tunnels(self, sc: SessionContainer, tunnels: list[NetworkTunnel]) -> None:
        normalized = self._normalize_context_tunnels(tunnels)
        if not normalized:
            return

        await self._cleanup_context_tunnels(sc, normalized)

        helper_path = self._context_tunnel_paths(sc.session_id, normalized[0]).helper_path
        write_result = await self._file_write_in_container(
            sc,
            helper_path,
            _CONTEXT_TUNNEL_HELPER,
            mode=0o700,
            workdir=self._KNOWLEDGE_WORKDIR,
        )
        if write_result.exit_code != 0:
            raise RuntimeError(f"Failed to materialize tunnel helper: {write_result.output}")

        hosts_backup = self._context_tunnel_paths(sc.session_id, normalized[0]).hosts_backup_path
        host_lines = "\n".join(f"127.0.0.1 {host}" for host in sorted({tunnel.host for tunnel in normalized}))
        hosts_cmd = f"cp /etc/hosts {shlex.quote(hosts_backup)} && cat <<'EOF' >> /etc/hosts\n{host_lines}\nEOF"
        hosts_result = await self._exec_in_container(sc, hosts_cmd, timeout=10)
        if hosts_result.exit_code != 0:
            await self._cleanup_context_tunnels(sc, normalized)
            raise RuntimeError(f"Failed to install temporary tunnel hosts: {hosts_result.output}")

        for tunnel in normalized:
            paths = self._context_tunnel_paths(sc.session_id, tunnel)
            wait_cmd = textwrap.dedent(
                f"""
                i=0
                while [ ! -f {shlex.quote(paths.ready_path)} ]; do
                    i=$((i+1))
                    if [ "$i" -ge 10 ]; then
                        exit 1
                    fi
                    kill -0 "$(cat {shlex.quote(paths.pid_path)})" 2>/dev/null || exit 1
                    sleep 1
                done
                """
            ).strip()
            start_cmd = (
                f"rm -f {shlex.quote(paths.pid_path)} {shlex.quote(paths.log_path)} {shlex.quote(paths.ready_path)} && "
                "{ "
                f"nohup python3 {shlex.quote(paths.helper_path)} "
                "--listen-host 127.0.0.1 "
                f"--listen-port {tunnel.local_port} "
                f"--target-host {shlex.quote(tunnel.host)} "
                f"--target-port {tunnel.remote_port} "
                '--proxy "$HTTP_PROXY" '
                f"--ready-file {shlex.quote(paths.ready_path)} "
                f">{shlex.quote(paths.log_path)} 2>&1 & "
                f"echo $! > {shlex.quote(paths.pid_path)}; "
                "} && "
                f'kill -0 "$(cat {shlex.quote(paths.pid_path)})" && '
                f"{wait_cmd}"
            )
            start_result = await self._exec_in_container(sc, start_cmd, timeout=10)
            if start_result.exit_code != 0:
                await self._cleanup_context_tunnels(sc, normalized)
                raise RuntimeError(f"Failed to start tunnel {tunnel.display}: {start_result.output}")

    async def _cleanup_context_tunnels(self, sc: SessionContainer, tunnels: list[NetworkTunnel]) -> None:
        if not tunnels:
            return

        pid_paths = [self._context_tunnel_paths(sc.session_id, tunnel).pid_path for tunnel in tunnels]
        log_paths = [self._context_tunnel_paths(sc.session_id, tunnel).log_path for tunnel in tunnels]
        ready_paths = [self._context_tunnel_paths(sc.session_id, tunnel).ready_path for tunnel in tunnels]
        helper_path = self._context_tunnel_paths(sc.session_id, tunnels[0]).helper_path
        hosts_backup = self._context_tunnel_paths(sc.session_id, tunnels[0]).hosts_backup_path

        pid_cleanup = []
        for pid_path in sorted(set(pid_paths)):
            quoted = shlex.quote(pid_path)
            pid_cleanup.append(
                f'if [ -f {quoted} ]; then kill "$(cat {quoted})" 2>/dev/null || true; rm -f {quoted}; fi'
            )
        quoted_hosts_backup = shlex.quote(hosts_backup)
        restore_hosts_cmd = (
            f"if [ -f {quoted_hosts_backup} ]; then "
            + f"cp {quoted_hosts_backup} /etc/hosts && rm -f {quoted_hosts_backup}; fi"
        )
        cleanup_parts = [
            *pid_cleanup,
            restore_hosts_cmd,
            "rm -f " + " ".join(shlex.quote(path) for path in sorted(set([helper_path, *log_paths, *ready_paths]))),
        ]
        cleanup_cmd = " && ".join(cleanup_parts)
        result = await self._exec_in_container(sc, cleanup_cmd, timeout=10)
        if result.exit_code != 0:
            logger.warning(f"Failed to clean up context tunnels for session {sc.session_id}: {result.output}")

    async def cleanup_session(self, session_id: str) -> None:
        sc = self._sessions.get(session_id)
        if sc is not None:
            await self.refresh_sandbox_snapshot(session_id, measure_usage=True, container_id=sc.container_id)
        await self._session_lifecycle.cleanup_session(session_id)
        await self.refresh_sandbox_snapshot(session_id)

    async def destroy_session(self, session_id: str) -> None:
        await self._session_lifecycle.destroy_session(session_id)
        clear_sandbox_snapshot(self._sandbox_snapshot_path(session_id))

    async def reset_session(self, session_id: str) -> None:
        await self._session_lifecycle.reset_session(session_id)
        self._clear_workspace_storage(session_id)
        save_sandbox_snapshot(
            self._sandbox_snapshot_path(session_id),
            SessionSandboxSnapshot(runtime=self._runtime.runtime_kind, updated_at=datetime.now(tz=UTC)),
        )

    async def cleanup_idle(self) -> None:
        now = time.time()
        to_remove = [sid for sid, sc in self._sessions.items() if now - sc.last_used > self._idle_timeout]
        if to_remove:
            logger.info(f"Cleaning up {len(to_remove)} idle sandbox session(s)")
        for sid in to_remove:
            await self.cleanup_session(sid)

    async def cleanup_all(self) -> None:
        session_ids = list(self._sessions)
        if session_ids:
            logger.info(f"Cleaning up all {len(session_ids)} sandbox session(s)")
        for sid in session_ids:
            await self.cleanup_session(sid)

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
