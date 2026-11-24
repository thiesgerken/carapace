"""Tests for the sandbox proxy: domain matching, allowlists, and skill metadata parsing."""

from __future__ import annotations

import base64
import contextlib
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from carapace.builder.client import BuilderUnavailableError
from carapace.database.models import SandboxTokenRow
from carapace.git.store import GitStore
from carapace.knowledge import KnowledgeRepoHandle
from carapace.sandbox.exec_flow import (
    EXEC_ENDED_REJECTION,
    ORPHANED_REQUEST_REJECTION,
    SandboxExecCoordinator,
    SandboxExecState,
)
from carapace.sandbox.exec_scope import RunningExec
from carapace.sandbox.manager import SandboxManager as _SandboxManager
from carapace.sandbox.proxy import ProxyServer, domain_matches
from carapace.sandbox.runtime import (
    ContainerGoneError,
    ExecResult,
)
from carapace.sandbox.session_lifecycle import SessionContainer
from carapace.sandbox.skill_profile import SkillProfileSync
from carapace.security.context import BoundaryEvaluation
from carapace.session.manager import SessionManager, SessionMeta
from carapace.skills import SkillDocumentError, SkillRegistry
from tests.runtime_mocks import NO_LEFTOVER_PROCESSES, fake_dns, make_runtime_mock


def _seed_session_row(session_factory, data_dir: Path, *session_ids: str) -> None:
    """Create minimal `sessions` rows so snapshot/token FK constraints are satisfied."""
    mgr = SessionManager(session_factory, data_dir)
    for session_id in session_ids:
        mgr.save_meta(session_id, SessionMeta(user="thies"))


def _sandbox_manager(
    *,
    runtime: Any,
    data_dir: Path,
    session_factory,
    knowledge_dir: Path | None = None,
    knowledge_repo_for_session=None,
    **kwargs: Any,
) -> _SandboxManager:
    if knowledge_repo_for_session is None:
        if knowledge_dir is None:
            raise TypeError("knowledge_dir or knowledge_repo_for_session is required in tests")
        handle = KnowledgeRepoHandle(
            owner="thies",
            knowledge_dir=knowledge_dir,
            git_store=GitStore(knowledge_dir),
            skill_registry=SkillRegistry(knowledge_dir / "skills"),
        )

        def knowledge_repo_for_session(_session_id: str) -> KnowledgeRepoHandle:
            return handle

    return _SandboxManager(
        runtime=runtime,
        data_dir=data_dir,
        knowledge_repo_for_session=knowledge_repo_for_session,
        session_factory=session_factory,
        **kwargs,
    )


# ── domain_matches ──────────────────────────────────────────────────


class TestDomainMatches:
    def test_exact_match(self):
        assert domain_matches("example.com", "example.com")

    def test_exact_no_match(self):
        assert not domain_matches("other.com", "example.com")

    def test_wildcard_subdomain(self):
        assert domain_matches("api.example.com", "*.example.com")

    def test_wildcard_deep_subdomain(self):
        assert domain_matches("a.b.example.com", "*.example.com")

    def test_wildcard_does_not_match_bare(self):
        assert not domain_matches("example.com", "*.example.com")

    def test_wildcard_does_not_match_unrelated(self):
        assert not domain_matches("notexample.com", "*.example.com")

    def test_case_insensitive_via_caller(self):
        assert domain_matches("api.example.com", "*.example.com")


# ── ProxyServer._is_allowed ─────────────────────────────────────────


class TestProxyCheckDomain:
    def _make_proxy(self, domains: set[str]) -> ProxyServer:
        return ProxyServer(
            verify_session_token=lambda sid, tok: True,
            get_allowed_domains=lambda sid: domains,
            attach_sandbox_call=lambda sid: contextlib.nullcontext(),
        )

    def test_allowed_exact(self):
        proxy = self._make_proxy({"pypi.org"})
        assert proxy._is_allowed("sess-1", "pypi.org")

    def test_denied(self):
        proxy = self._make_proxy({"pypi.org"})
        assert not proxy._is_allowed("sess-1", "evil.com")

    def test_allowed_wildcard(self):
        proxy = self._make_proxy({"*.googleapis.com"})
        assert proxy._is_allowed("sess-1", "storage.googleapis.com")

    def test_empty_allowlist(self):
        proxy = self._make_proxy(set())
        assert not proxy._is_allowed("sess-1", "anything.com")

    def test_case_insensitive(self):
        proxy = self._make_proxy({"PyPI.org"})
        assert proxy._is_allowed("sess-1", "pypi.org")


# ── ProxyServer URL parsing ─────────────────────────────────────────


class TestProxyParsing:
    def test_parse_host_port(self):
        assert ProxyServer._parse_host_port("example.com:443") == ("example.com", 443)

    def test_parse_host_port_default(self):
        assert ProxyServer._parse_host_port("example.com") == ("example.com", 443)

    def test_parse_absolute_url(self):
        host, port, path = ProxyServer._parse_absolute_url("http://example.com/foo/bar")
        assert host == "example.com"
        assert port == 80
        assert path == "/foo/bar"

    def test_parse_absolute_url_with_port(self):
        host, port, path = ProxyServer._parse_absolute_url("http://example.com:8080/api")
        assert host == "example.com"
        assert port == 8080
        assert path == "/api"

    def test_parse_absolute_url_no_path(self):
        host, port, path = ProxyServer._parse_absolute_url("http://example.com")
        assert host == "example.com"
        assert port == 80
        assert path == "/"

    def test_parse_absolute_https_url(self):
        host, port, path = ProxyServer._parse_absolute_url("https://example.com/foo/bar")
        assert host == "example.com"
        assert port == 443
        assert path == "/foo/bar"

    def test_parse_absolute_https_url_with_query_and_port(self):
        host, port, path = ProxyServer._parse_absolute_url("https://example.com:8443/api?x=1")
        assert host == "example.com"
        assert port == 8443
        assert path == "/api?x=1"

    def test_parse_non_absolute(self):
        assert ProxyServer._parse_absolute_url("/relative") == ("", 0, "")


@pytest.mark.anyio
async def test_handle_http_supports_absolute_https_urls(monkeypatch: pytest.MonkeyPatch):
    fake_dns(monkeypatch, {"paperless.gerken.haus": ["93.184.215.14"]})
    proxy = ProxyServer(
        verify_session_token=lambda sid, tok: True,
        get_allowed_domains=lambda sid: {"paperless.gerken.haus"},
        attach_sandbox_call=lambda sid: contextlib.nullcontext(),
    )

    class FakeReader:
        async def readexactly(self, _size: int) -> bytes:
            raise AssertionError("body should not be read for GET requests without content-length")

    class FakeWriter:
        def __init__(self) -> None:
            self.writes: list[bytes] = []

        def write(self, data: bytes) -> None:
            self.writes.append(data)

        async def drain(self) -> None:
            return None

    class FakeRemoteReader:
        def __init__(self) -> None:
            self._chunks = [b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok", b""]

        async def read(self, _size: int) -> bytes:
            return self._chunks.pop(0)

    class FakeRemoteWriter:
        def __init__(self) -> None:
            self.writes: list[bytes] = []

        def write(self, data: bytes) -> None:
            self.writes.append(data)

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            return None

    opened: dict[str, Any] = {}
    remote_reader = FakeRemoteReader()
    remote_writer = FakeRemoteWriter()

    async def fake_open_connection(host: str, port: int, **kwargs: Any):
        opened["host"] = host
        opened["port"] = port
        opened["kwargs"] = kwargs
        return remote_reader, remote_writer

    monkeypatch.setattr("carapace.sandbox.proxy.asyncio.open_connection", fake_open_connection)

    client_reader = FakeReader()
    client_writer = FakeWriter()
    await proxy._handle_http(
        client_reader,  # type: ignore[arg-type]
        client_writer,  # type: ignore[arg-type]
        "sess-1",
        "127.0.0.1",
        "GET",
        "https://paperless.gerken.haus/api/tags/?page_size=1",
        "HTTP/1.1",
        [b"Host: paperless.gerken.haus\r\n"],
    )

    # Connects to the checked address, verifies the certificate against the name.
    assert opened["host"] == "93.184.215.14"
    assert opened["port"] == 443
    assert opened["kwargs"].get("server_hostname") == "paperless.gerken.haus"
    assert opened["kwargs"].get("ssl") is not None
    assert remote_writer.writes[0] == b"GET /api/tags/?page_size=1 HTTP/1.1\r\n"
    assert client_writer.writes == [b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok"]


# ── SandboxManager allowlists ───────────────────────────────────────


async def _session_env(mgr: _SandboxManager) -> dict[str, str]:
    """The env a session sandbox starts with; the token lookup is stubbed (no session row needed)."""
    mgr._session_lifecycle.get_or_create_token = lambda _session_id: "tok"  # type: ignore[method-assign]
    return await mgr._session_lifecycle.build_session_proxy_env("sess-1")


class TestSandboxManagerAllowlists:
    def _make_manager(self, tmp_path: Path, db_factory):
        runtime = make_runtime_mock()
        return _sandbox_manager(runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path, session_factory=db_factory)

    def test_empty_by_default(self, tmp_path: Path, db_factory):
        mgr = self._make_manager(tmp_path, db_factory)
        assert mgr.get_allowed_domains("sess-1") == set()

    def test_allow_domains(self, tmp_path: Path, db_factory):
        mgr = self._make_manager(tmp_path, db_factory)
        mgr.allow_domains("sess-1", {"a.com", "b.com"})
        assert mgr.get_allowed_domains("sess-1") == {"a.com", "b.com"}

    def test_allow_domains_accumulates(self, tmp_path: Path, db_factory):
        mgr = self._make_manager(tmp_path, db_factory)
        mgr.allow_domains("sess-1", {"a.com"})
        mgr.allow_domains("sess-1", {"b.com"})
        assert mgr.get_allowed_domains("sess-1") == {"a.com", "b.com"}

    def test_cleanup_clears_domains(self, tmp_path: Path, db_factory):
        mgr = self._make_manager(tmp_path, db_factory)
        mgr.allow_domains("sess-1", {"a.com"})
        mgr._cleanup_tracking("sess-1")
        assert mgr.get_allowed_domains("sess-1") == set()

    def test_proxy_env_includes_token(self, tmp_path: Path, db_factory):
        mgr = self._make_manager(tmp_path, db_factory)
        env = mgr._build_proxy_env("sess-1", "my-secret-token", "http://172.18.0.2:3128")
        assert env["HTTP_PROXY"] == "http://sess-1:my-secret-token@172.18.0.2:3128"
        assert env["HTTPS_PROXY"] == "http://sess-1:my-secret-token@172.18.0.2:3128"
        assert "172.18.0.2" in env["NO_PROXY"]
        assert "GIT_REPO_URL" in env

    def test_proxy_env_includes_session_id(self, tmp_path: Path, db_factory):
        mgr = self._make_manager(tmp_path, db_factory)
        env = mgr._build_proxy_env("sess-1", "tok", "http://172.18.0.2:3128")
        assert env["CARAPACE_SESSION_ID"] == "sess-1"

    async def test_session_env_points_nix_at_the_builder_cache(self, tmp_path: Path, db_factory):
        async def nix_config() -> str:
            return "substituters = http://cache.carapace.internal"

        mgr = _sandbox_manager(
            runtime=make_runtime_mock(),
            data_dir=tmp_path,
            knowledge_dir=tmp_path,
            session_factory=db_factory,
            nix_config=nix_config,
        )
        env = await _session_env(mgr)
        assert env["NIX_CONFIG"] == "substituters = http://cache.carapace.internal"

    async def test_session_env_fails_when_the_builder_does_not_answer(self, tmp_path: Path, db_factory):
        async def nix_config() -> str:
            raise BuilderUnavailableError("The skill builder is configured but unreachable")

        mgr = _sandbox_manager(
            runtime=make_runtime_mock(),
            data_dir=tmp_path,
            knowledge_dir=tmp_path,
            session_factory=db_factory,
            nix_config=nix_config,
        )
        with pytest.raises(BuilderUnavailableError):
            await _session_env(mgr)

    async def test_session_env_has_no_nix_config_without_a_builder(self, tmp_path: Path, db_factory):
        env = await _session_env(self._make_manager(tmp_path, db_factory))
        assert "NIX_CONFIG" not in env

    def test_proxy_env_uses_owner_repo_name(self, tmp_path: Path, db_factory):
        runtime = make_runtime_mock()
        mgr = _sandbox_manager(
            runtime=runtime,
            data_dir=tmp_path,
            session_factory=db_factory,
            knowledge_dir=tmp_path,
            knowledge_repo_for_session=lambda _session_id: KnowledgeRepoHandle(
                owner="ada",
                knowledge_dir=tmp_path / "knowledges" / "ada",
                git_store=GitStore(tmp_path / "knowledges" / "ada"),
                skill_registry=SkillRegistry(tmp_path / "knowledges" / "ada" / "skills"),
            ),
        )

        env = mgr._build_proxy_env("sess-1", "tok", "http://172.18.0.2:3128")

        assert env["GIT_REPO_URL"].endswith("/git/ada")

    def test_proxy_env_keeps_two_session_repos_isolated(self, tmp_path: Path, db_factory):
        runtime = make_runtime_mock()
        handles = {
            "sess-thies": KnowledgeRepoHandle(
                owner="thies",
                knowledge_dir=tmp_path / "knowledges" / "thies",
                git_store=GitStore(tmp_path / "knowledges" / "thies"),
                skill_registry=SkillRegistry(tmp_path / "knowledges" / "thies" / "skills"),
            ),
            "sess-ada": KnowledgeRepoHandle(
                owner="ada",
                knowledge_dir=tmp_path / "knowledges" / "ada",
                git_store=GitStore(tmp_path / "knowledges" / "ada"),
                skill_registry=SkillRegistry(tmp_path / "knowledges" / "ada" / "skills"),
            ),
        }

        def knowledge_repo_for_session(session_id: str) -> KnowledgeRepoHandle:
            return handles[session_id]

        mgr = _sandbox_manager(
            runtime=runtime,
            data_dir=tmp_path,
            session_factory=db_factory,
            knowledge_repo_for_session=knowledge_repo_for_session,
        )

        thies_env = mgr._build_proxy_env("sess-thies", "tok-a", "http://172.18.0.2:3128")
        ada_env = mgr._build_proxy_env("sess-ada", "tok-b", "http://172.18.0.2:3128")

        assert thies_env["GIT_REPO_URL"].endswith("/git/thies")
        assert ada_env["GIT_REPO_URL"].endswith("/git/ada")

    def test_proxy_env_no_git_identity_vars(self, tmp_path: Path, db_factory):
        """Git identity is configured via git config inside the container, not env vars."""
        mgr = self._make_manager(tmp_path, db_factory)
        env = mgr._build_proxy_env("sess-1", "tok", "http://172.18.0.2:3128")
        assert "GIT_AUTHOR_NAME" not in env
        assert "GIT_COMMITTER_NAME" not in env
        assert "GIT_AUTHOR_EMAIL" not in env
        assert "GIT_COMMITTER_EMAIL" not in env

    def test_no_proxy_env_when_empty(self, tmp_path: Path, db_factory):
        mgr = self._make_manager(tmp_path, db_factory)
        assert mgr._build_proxy_env("sess-1", "tok", "") == {}

    def test_token_lookup(self, tmp_path: Path, db_factory):
        mgr = self._make_manager(tmp_path, db_factory)
        mgr._token_to_session["abc123"] = "sess-1"
        assert mgr.verify_session_token("sess-1", "abc123") is True
        assert mgr.verify_session_token("sess-1", "wrong") is False
        assert mgr.verify_session_token("wrong-session", "abc123") is False

    def test_token_lookup_restores_persisted_token(self, tmp_path: Path, db_factory):
        mgr = self._make_manager(tmp_path, db_factory)
        _seed_session_row(db_factory, tmp_path, "sess-1")
        with db_factory.begin() as db:
            db.add(SandboxTokenRow(session_id="sess-1", token="persisted-token"))

        assert mgr.verify_session_token("sess-1", "persisted-token") is True
        assert mgr._session_tokens["sess-1"] == "persisted-token"
        assert mgr._token_to_session["persisted-token"] == "sess-1"

    def test_cleanup_clears_tokens(self, tmp_path: Path, db_factory):
        mgr = self._make_manager(tmp_path, db_factory)
        mgr._token_to_session["tok"] = "sess-1"
        mgr._session_tokens["sess-1"] = "tok"
        mgr._cleanup_tracking("sess-1")
        assert mgr.verify_session_token("sess-1", "tok") is False


@pytest.mark.anyio
async def test_exec_recreate_preserves_domains(tmp_path: Path, db_factory):
    runtime = make_runtime_mock()
    runtime.get_host_ip = AsyncMock(return_value="172.18.0.1")
    runtime.create_sandbox = AsyncMock(side_effect=["container-1", "container-2"])
    runtime.get_ip = AsyncMock(return_value="172.18.0.22")
    runtime.logs = AsyncMock(return_value="carapace sandbox ready")
    _git_exists = ExecResult(stdout="", exit_code=0, output="")
    runtime.exec = AsyncMock(
        side_effect=[
            _git_exists,  # knowledge repo probe after first create
            _git_exists,  # install_commit_msg_hook
            _git_exists,  # setup_git_identity
            NO_LEFTOVER_PROCESSES,  # leftover process kill
            ContainerGoneError(),  # exec_command triggers recreate
            _git_exists,  # knowledge repo probe after recreate
            _git_exists,  # install_commit_msg_hook
            _git_exists,  # setup_git_identity
            NO_LEFTOVER_PROCESSES,  # leftover process kill in the new sandbox
            ExecResult(stdout="ok", exit_code=0, output="ok"),  # actual command retry
        ]
    )

    mgr = _sandbox_manager(runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path, session_factory=db_factory)
    _seed_session_row(db_factory, tmp_path, "sess-1")
    session_id = "sess-1"
    await mgr.ensure_session(session_id)
    mgr.allow_domains(session_id, {"api.example.com"})

    output = await mgr.exec_command(session_id, "curl https://api.example.com")
    assert output.output == "ok"
    assert output.stdout == "ok"
    assert mgr.get_allowed_domains(session_id) == {"api.example.com"}


@pytest.mark.anyio
async def test_exec_container_gone_recovery_restores_git_identity(tmp_path: Path, db_factory):
    runtime = make_runtime_mock()
    runtime.sandbox_exists = AsyncMock(return_value="container-1")
    runtime.exec = AsyncMock(
        side_effect=[
            ContainerGoneError(),  # leftover process kill
            ExecResult(stdout="", exit_code=0, output=""),  # setup_git_identity
            NO_LEFTOVER_PROCESSES,  # leftover process kill in the restarted sandbox
            ExecResult(stdout="ok", exit_code=0, output="ok"),
        ]
    )
    mgr = _sandbox_manager(runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path, session_factory=db_factory)
    _seed_session_row(db_factory, tmp_path, "sess-1")
    mgr._sessions["sess-1"] = SessionContainer(
        container_id="container-1",
        session_id="sess-1",
        created_at=1.0,
        last_used=1.0,
    )

    result = await mgr.exec_command("sess-1", "check-mail")

    assert result.output == "ok"
    # The runtime already restarted the container, so the lifecycle re-attaches
    # without reporting a fresh runtime; recovery must restore the identity anyway.
    runtime.create_sandbox.assert_not_awaited()
    assert "git config --global user.name" in runtime.exec.await_args_list[1].args[1]


# ── SKILL.md metadata parsing ───────────────────────────────────────


class TestSkillMetadataParsing:
    def _write_skill_md(self, skill_dir: Path, body: str) -> None:
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(body)

    def test_no_carapace_metadata(self, tmp_path: Path):
        skill_dir = tmp_path / "plain"
        self._write_skill_md(skill_dir, "Body.\n")

        registry = SkillRegistry(tmp_path)
        assert registry.get_carapace_config("plain") is None

    def test_invalid_frontmatter_carapace_raises(self, tmp_path: Path):
        skill_dir = tmp_path / "bad-inline"
        self._write_skill_md(
            skill_dir,
            "---\n"
            "name: bad-inline\n"
            "metadata:\n"
            "  carapace:\n"
            "    commands:\n"
            "      - name: ok\n"
            "        command: uv run ok\n"
            "---\n"
            "Body.\n",
        )

        registry = SkillRegistry(tmp_path)
        with pytest.raises(SkillDocumentError, match="moved out of the frontmatter into the skill's flake"):
            registry.get_carapace_config("bad-inline")


def _make_exec_state(**overrides) -> SandboxExecState:
    base = dict(
        sessions={},
        allowed_domains={},
        exec_temp_domains={},
        session_current_command={},
        domain_approval_cbs={},
        domain_notify_cbs={},
        exec_locks={},
        exec_notified_domains={},
        exec_notified_credentials={},
        running_execs={},
    )
    base.update(overrides)
    return SandboxExecState(**base)


@pytest.mark.anyio
async def test_request_domain_approval_denies_orphaned_request_without_sentinel():
    """No live exec → deny without invoking the sentinel callback (orphaned process)."""
    cb = AsyncMock(return_value=BoundaryEvaluation(allowed=True, rejection=""))
    state = _make_exec_state(domain_approval_cbs={"sess-1": cb})
    coordinator = SandboxExecCoordinator(
        runtime=make_runtime_mock(), state=state, profile_sync=SkillProfileSync(make_runtime_mock())
    )

    evaluation = await coordinator.request_domain_approval("sess-1", "registry.npmjs.org")

    assert evaluation == BoundaryEvaluation(allowed=False, rejection=ORPHANED_REQUEST_REJECTION)
    cb.assert_not_awaited()
    assert "registry.npmjs.org" not in state.exec_temp_domains.get("sess-1", set())


@pytest.mark.anyio
async def test_request_domain_approval_consults_sentinel_during_live_exec():
    """Live exec (command recorded) → callback is consulted as before."""
    cb = AsyncMock(return_value=BoundaryEvaluation(allowed=True, rejection=""))
    state = _make_exec_state(domain_approval_cbs={"sess-1": cb})
    coordinator = SandboxExecCoordinator(
        runtime=make_runtime_mock(), state=state, profile_sync=SkillProfileSync(make_runtime_mock())
    )
    _grant(coordinator, "npm ci")

    running = coordinator.running_exec("sess-1")

    evaluation = await coordinator.request_domain_approval("sess-1", "registry.npmjs.org")

    assert evaluation.allowed is True
    cb.assert_awaited_once_with("registry.npmjs.org", running)
    assert "registry.npmjs.org" in state.exec_temp_domains["sess-1"]


@pytest.mark.anyio
async def test_credential_approval_lasts_until_the_exec_ends():
    state = _make_exec_state()
    coordinator = SandboxExecCoordinator(
        runtime=make_runtime_mock(), state=state, profile_sync=SkillProfileSync(make_runtime_mock())
    )
    sc = SessionContainer(container_id="container-1", session_id="sess-1", created_at=0, last_used=0)
    captured: list[RunningExec] = []

    async def exec_in_container(*_args: Any, **_kwargs: Any) -> ExecResult:
        running = coordinator.running_exec("sess-1")
        assert running is not None and running.command == "ccred get vault/token"
        running.credentials.add(("vault/token", "password"))
        captured.append(running)
        return ExecResult(exit_code=0, output="", stdout="")

    await coordinator.exec(
        "sess-1",
        "ccred get vault/token",
        ensure_session=AsyncMock(return_value=sc),
        recreate_session=AsyncMock(),
        log_container_tail=AsyncMock(),
        exec_in_container=exec_in_container,
    )

    assert coordinator.running_exec("sess-1") is None
    assert coordinator.is_running(captured[0]) is False


def _grant(coordinator: SandboxExecCoordinator, command: str) -> None:
    coordinator._grant_exec_scope("sess-1", command)


@pytest.mark.anyio
async def test_domain_approval_after_its_exec_ended_is_not_granted():
    state = _make_exec_state()
    coordinator = SandboxExecCoordinator(
        runtime=make_runtime_mock(), state=state, profile_sync=SkillProfileSync(make_runtime_mock())
    )
    _grant(coordinator, "curl https://api.example.com &")

    async def review_outlasting_the_exec(_domain: str, _running: RunningExec) -> BoundaryEvaluation:
        coordinator._revoke_exec_scope("sess-1")
        return BoundaryEvaluation(allowed=True, rejection="")

    state.domain_approval_cbs["sess-1"] = review_outlasting_the_exec

    evaluation = await coordinator.request_domain_approval("sess-1", "api.example.com")

    assert evaluation == BoundaryEvaluation(allowed=False, rejection=EXEC_ENDED_REJECTION)
    assert "api.example.com" not in coordinator.get_effective_domains("sess-1")


@pytest.mark.anyio
async def test_domain_approval_does_not_land_in_the_next_exec():
    state = _make_exec_state()
    coordinator = SandboxExecCoordinator(
        runtime=make_runtime_mock(), state=state, profile_sync=SkillProfileSync(make_runtime_mock())
    )
    _grant(coordinator, "curl https://api.example.com &")

    async def review_until_the_next_exec(_domain: str, _running: RunningExec) -> BoundaryEvaluation:
        coordinator._revoke_exec_scope("sess-1")
        _grant(coordinator, "ls")
        return BoundaryEvaluation(allowed=True, rejection="")

    state.domain_approval_cbs["sess-1"] = review_until_the_next_exec

    evaluation = await coordinator.request_domain_approval("sess-1", "api.example.com")

    assert evaluation.allowed is False
    assert "api.example.com" not in coordinator.get_effective_domains("sess-1")


@pytest.mark.anyio
async def test_only_later_requests_of_the_same_exec_are_follow_ups():
    """Parallel tool calls run their execs one after the other; each exec starts with the full form."""
    state = _make_exec_state()
    coordinator = SandboxExecCoordinator(
        runtime=make_runtime_mock(), state=state, profile_sync=SkillProfileSync(make_runtime_mock())
    )
    seen: list[tuple[str, str, bool]] = []

    async def review(domain: str, running: RunningExec) -> BoundaryEvaluation:
        seen.append((domain, running.command, running.boundary_reviewed))
        return BoundaryEvaluation(allowed=True, rejection="")

    state.domain_approval_cbs["sess-1"] = review

    _grant(coordinator, "fetch-a")
    await coordinator.request_domain_approval("sess-1", "a.example.com")
    await coordinator.request_domain_approval("sess-1", "b.example.com")
    coordinator._revoke_exec_scope("sess-1")
    _grant(coordinator, "fetch-b")
    await coordinator.request_domain_approval("sess-1", "c.example.com")

    assert seen == [
        ("a.example.com", "fetch-a", False),
        ("b.example.com", "fetch-a", True),
        ("c.example.com", "fetch-b", False),
    ]


@pytest.mark.anyio
async def test_denied_connect_answers_with_the_rejection_in_the_body(monkeypatch: pytest.MonkeyPatch):
    fake_dns(monkeypatch, {"evil.example.com": ["93.184.215.14"]})
    proxy = ProxyServer(
        verify_session_token=lambda sid, tok: True,
        get_allowed_domains=lambda sid: set(),
        attach_sandbox_call=lambda sid: contextlib.nullcontext(),
        request_approval=AsyncMock(
            return_value=BoundaryEvaluation(allowed=False, rejection="Sentinel denied this operation. Not needed.")
        ),
    )

    class FakeWriter:
        def __init__(self) -> None:
            self.writes: list[bytes] = []

        def write(self, data: bytes) -> None:
            self.writes.append(data)

        async def drain(self) -> None:
            return None

    writer = FakeWriter()
    await proxy._handle_connect(
        AsyncMock(),  # type: ignore[arg-type]
        writer,  # type: ignore[arg-type]
        "sess-1",
        "127.0.0.1",
        "evil.example.com:443",
    )

    response = b"".join(writer.writes)
    head, _, body = response.partition(b"\r\n\r\n")
    assert head.startswith(b"HTTP/1.1 403 Forbidden")
    assert f"Content-Length: {len(body)}".encode() in head
    assert body == b"Sentinel denied this operation. Not needed.\n"


# ── Proxy token extraction ───────────────────────────────────────────


class TestProxyCredentialExtraction:
    def test_basic_auth_credentials(self):
        encoded = base64.b64encode(b"sess-1:my-token").decode()
        header = f"Proxy-Authorization: Basic {encoded}\r\n".encode()
        assert ProxyServer._extract_basic_credentials(header) == ("sess-1", "my-token")

    def test_no_password(self):
        encoded = base64.b64encode(b"sess-1:").decode()
        header = f"Proxy-Authorization: Basic {encoded}\r\n".encode()
        assert ProxyServer._extract_basic_credentials(header) is None

    def test_no_username(self):
        encoded = base64.b64encode(b":password").decode()
        header = f"Proxy-Authorization: Basic {encoded}\r\n".encode()
        assert ProxyServer._extract_basic_credentials(header) is None

    def test_non_basic_scheme(self):
        header = b"Proxy-Authorization: Bearer abc\r\n"
        assert ProxyServer._extract_basic_credentials(header) is None

    def test_garbage(self):
        assert ProxyServer._extract_basic_credentials(b"garbage\r\n") is None


# ── ProxyServer start/stop ──────────────────────────────────────────


@pytest.mark.anyio
async def test_proxy_start_stop():
    proxy = ProxyServer(
        verify_session_token=lambda sid, tok: False,
        get_allowed_domains=lambda sid: set(),
        attach_sandbox_call=lambda sid: contextlib.nullcontext(),
        host="127.0.0.1",
        port=0,  # OS-assigned port
    )
    await proxy.start()
    assert proxy._server is not None
    assert proxy._server.is_serving()
    await proxy.stop()
