from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from loguru import logger

from carapace.sandbox.file_ops import ContextFileCredential, WrittenContextFile
from carapace.sandbox.runtime import ContainerGoneError, ContainerRuntime, ExecResult
from carapace.sandbox.session_lifecycle import SessionContainer
from carapace.security.context import ApprovalSource, ApprovalVerdict

type DomainApprovalCallback = Callable[[str, str], Awaitable[bool]]
type DomainNotifyCallback = Callable[[str, str, ApprovalSource | None, ApprovalVerdict | None, str | None], None]
type AfterExecCredentialNotify = Callable[[], None]
type EnsureSessionCallback = Callable[[str], Awaitable[tuple[SessionContainer, bool]]]
type RerunSkillSetupCallback = Callable[[str], Awaitable[None]]
type LogContainerTailCallback = Callable[[str, str], Awaitable[None]]
type PrepareSessionRecreateCallback = Callable[[str], None]
type ExecInContainerCallback = Callable[..., Awaitable[ExecResult]]
type WriteContextFileCredentialsCallback = Callable[
    [SessionContainer, list[ContextFileCredential]],
    Awaitable[list[WrittenContextFile]],
]
type DeleteContextFileCredentialsCallback = Callable[[str, list[WrittenContextFile]], Awaitable[None]]


@dataclass
class SandboxExecState:
    sessions: dict[str, SessionContainer]
    allowed_domains: dict[str, set[str]]
    exec_temp_domains: dict[str, set[str]]
    exec_context_skill_domains: dict[str, set[str]]
    session_current_command: dict[str, str]
    domain_approval_cbs: dict[str, DomainApprovalCallback]
    domain_notify_cbs: dict[str, DomainNotifyCallback]
    exec_locks: dict[str, asyncio.Lock]
    proxy_bypass_sessions: set[str]
    session_current_contexts: dict[str, list[str]]
    exec_notified_domains: dict[str, set[str]]
    exec_notified_credentials: dict[str, set[str]]


class SandboxExecCoordinator:
    def __init__(self, *, runtime: ContainerRuntime, state: SandboxExecState) -> None:
        self._runtime = runtime
        self._state = state

    def get_exec_lock(self, session_id: str) -> asyncio.Lock:
        if session_id not in self._state.exec_locks:
            self._state.exec_locks[session_id] = asyncio.Lock()
        return self._state.exec_locks[session_id]

    async def exec_in_container(
        self,
        sc: SessionContainer,
        command: str,
        timeout: int = 30,
        *,
        bypass_proxy: bool = False,
        workdir: str | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> ExecResult:
        """Run *command* in *sc* without acquiring the exec lock."""
        if bypass_proxy:
            self._state.proxy_bypass_sessions.add(sc.session_id)
            logger.info(f"Proxy bypass ENABLED for session {sc.session_id}")
        try:
            env = sc.session_env or None
            if extra_env:
                env = {**(sc.session_env or {}), **extra_env}
            return await self._runtime.exec(
                sc.container_id,
                command,
                timeout=timeout,
                workdir=workdir,
                env=env,
            )
        finally:
            if bypass_proxy:
                self._state.proxy_bypass_sessions.discard(sc.session_id)
                logger.info(f"Proxy bypass DISABLED for session {sc.session_id}")

    async def exec(
        self,
        session_id: str,
        command: str,
        timeout: int = 30,
        *,
        ensure_session: EnsureSessionCallback,
        rerun_skill_setup: RerunSkillSetupCallback,
        log_container_tail: LogContainerTailCallback,
        prepare_session_recreate: PrepareSessionRecreateCallback,
        exec_in_container: ExecInContainerCallback,
        write_context_file_credentials: WriteContextFileCredentialsCallback,
        delete_context_file_credentials: DeleteContextFileCredentialsCallback,
        bypass_proxy: bool = False,
        workdir: str | None = None,
        contexts: list[str] | None = None,
        extra_env: dict[str, str] | None = None,
        context_domains: set[str] | None = None,
        context_file_creds: list[ContextFileCredential] | None = None,
        after_exec_credential_notify: AfterExecCredentialNotify | None = None,
    ) -> ExecResult:
        """Run a command in the sandbox and return the raw ExecResult."""
        contexts = contexts or []
        written_files: list[WrittenContextFile] = []

        async with self.get_exec_lock(session_id):
            if bypass_proxy:
                self._state.proxy_bypass_sessions.add(session_id)
                logger.info(f"Proxy bypass ENABLED for session {session_id}")
            try:
                sc, was_created = await ensure_session(session_id)
                if was_created:
                    await rerun_skill_setup(session_id)
                sc.last_used = time.time()
                logger.debug(f"Exec in session {session_id}: {command}")

                self._state.session_current_command[session_id] = command
                self._state.session_current_contexts[session_id] = contexts
                self._state.exec_temp_domains[session_id] = set()
                self._state.exec_context_skill_domains[session_id] = set()
                self._state.exec_notified_domains[session_id] = set()
                self._state.exec_notified_credentials[session_id] = set()

                if context_domains:
                    self._state.exec_temp_domains[session_id].update(context_domains)
                    self._state.exec_context_skill_domains[session_id].update(context_domains)

                try:
                    if context_file_creds:
                        written_files = await write_context_file_credentials(sc, context_file_creds)
                    exec_result = await exec_in_container(
                        sc,
                        command,
                        timeout,
                        workdir=workdir,
                        bypass_proxy=False,
                        extra_env=extra_env,
                    )
                except ContainerGoneError:
                    logger.warning(f"Container gone for session {session_id}, recreating sandbox")
                    await log_container_tail(sc.container_id, session_id)
                    prepare_session_recreate(session_id)
                    sc, _ = await ensure_session(session_id)
                    await rerun_skill_setup(session_id)

                    written_files.clear()
                    if context_file_creds:
                        written_files = await write_context_file_credentials(sc, context_file_creds)
                    exec_result = await exec_in_container(
                        sc,
                        command,
                        timeout,
                        workdir=workdir,
                        bypass_proxy=False,
                        extra_env=extra_env,
                    )

                if after_exec_credential_notify is not None:
                    after_exec_credential_notify()
                return exec_result
            finally:
                if bypass_proxy:
                    self._state.proxy_bypass_sessions.discard(session_id)
                    logger.info(f"Proxy bypass DISABLED for session {session_id}")
                self._state.session_current_command.pop(session_id, None)
                self._state.session_current_contexts.pop(session_id, None)
                self._state.exec_temp_domains.pop(session_id, None)
                self._state.exec_context_skill_domains.pop(session_id, None)
                self._state.exec_notified_domains.pop(session_id, None)
                self._state.exec_notified_credentials.pop(session_id, None)

                if written_files:
                    await delete_context_file_credentials(session_id, written_files)

    def allow_domains(self, session_id: str, domains: set[str]) -> None:
        existing = self._state.allowed_domains.setdefault(session_id, set())
        existing.update(domains)
        logger.info(f"Allowed domains for session {session_id}: {existing}")

    def get_allowed_domains(self, session_id: str) -> set[str]:
        return self._state.allowed_domains.get(session_id, set())

    def get_domain_info(self, session_id: str) -> list[dict[str, str]]:
        entries: list[dict[str, str]] = []
        for domain in sorted(self._state.allowed_domains.get(session_id, set())):
            entries.append({"domain": domain, "scope": "permanent"})
        for domain in sorted(self._state.exec_temp_domains.get(session_id, set())):
            entries.append({"domain": domain, "scope": "this exec only"})
        return entries

    def get_effective_domains(self, session_id: str) -> set[str]:
        if session_id in self._state.proxy_bypass_sessions:
            return {"*"}
        domains = set(self._state.allowed_domains.get(session_id, set()))
        domains.update(self._state.exec_temp_domains.get(session_id, set()))
        return domains

    def get_current_contexts(self, session_id: str) -> list[str]:
        return self._state.session_current_contexts.get(session_id, [])

    def is_domain_skill_granted(self, session_id: str, domain: str) -> bool:
        from carapace.sandbox.proxy import domain_matches

        skill_domains = self._state.exec_context_skill_domains.get(session_id, set())
        domain_lower = domain.lower()
        return any(domain_matches(domain_lower, pattern.lower()) for pattern in skill_domains)

    def is_domain_bypass(self, session_id: str) -> bool:
        return session_id in self._state.proxy_bypass_sessions

    def mark_credential_notified(self, session_id: str, vault_path: str) -> bool:
        notified = self._state.exec_notified_credentials.get(session_id)
        if notified is None:
            return False
        if vault_path in notified:
            return True
        notified.add(vault_path)
        return False

    def notify_domain_access(self, session_id: str, domain: str, allowed: bool) -> None:
        cb = self._state.domain_notify_cbs.get(session_id)
        if cb is None:
            return

        if allowed:
            if self.is_domain_bypass(session_id):
                notified = self._state.exec_notified_domains.get(session_id)
                if notified is not None and domain in notified:
                    return
                if notified is not None:
                    notified.add(domain)
                cb(domain, f"[bypass] {domain}", "bypass", "allow", "proxy bypass active")
            elif self.is_domain_skill_granted(session_id, domain):
                notified = self._state.exec_notified_domains.get(session_id)
                if notified is not None and domain in notified:
                    return
                if notified is not None:
                    notified.add(domain)
                cb(domain, f"[skill] {domain}", "skill", "allow", "skill-declared domain")
        else:
            cb(domain, f"[denied] {domain}", "unknown", "deny", "no approval callback configured")

    def set_domain_approval_callback(self, session_id: str, cb: DomainApprovalCallback | None) -> None:
        if cb is None:
            self._state.domain_approval_cbs.pop(session_id, None)
        else:
            self._state.domain_approval_cbs[session_id] = cb

    def set_domain_notify_callback(self, session_id: str, cb: DomainNotifyCallback | None) -> None:
        if cb is None:
            self._state.domain_notify_cbs.pop(session_id, None)
        else:
            self._state.domain_notify_cbs[session_id] = cb

    async def request_domain_approval(self, session_id: str, domain: str) -> bool:
        cb = self._state.domain_approval_cbs.get(session_id)
        if cb is None:
            logger.warning(f"No domain approval callback for session {session_id}, denying {domain}")
            return False

        command = self._state.session_current_command.get(session_id, "")
        allowed = await cb(domain, command)
        if allowed:
            self._state.exec_temp_domains.setdefault(session_id, set()).add(domain)
            logger.info(f"Security approved {domain} for session {session_id}")
        else:
            logger.info(f"Security denied {domain} for session {session_id}")
        return allowed

    def cleanup_tracking(self, session_id: str) -> None:
        self._state.domain_approval_cbs.pop(session_id, None)
        self._state.domain_notify_cbs.pop(session_id, None)
        self._state.exec_notified_domains.pop(session_id, None)
        self._state.exec_notified_credentials.pop(session_id, None)
