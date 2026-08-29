"""Tests for the sandbox proxy: domain matching, allowlists, and skill metadata parsing."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from carapace.database.models import SandboxTokenRow
from carapace.git.store import GitStore
from carapace.knowledge import KnowledgeRepoHandle
from carapace.models.skills import SkillCarapaceConfig
from carapace.sandbox.exec_flow import SandboxExecCoordinator, SandboxExecState
from carapace.sandbox.manager import _CONTEXT_TUNNEL_HELPER
from carapace.sandbox.manager import SandboxManager as _SandboxManager
from carapace.sandbox.proxy import ProxyServer, domain_matches
from carapace.sandbox.runtime import (
    ContainerGoneError,
    ExecResult,
    NetworkTunnel,
)
from carapace.sandbox.session_lifecycle import SessionContainer
from carapace.session.manager import SessionManager, SessionMeta
from carapace.skills import SkillRegistry
from tests.runtime_mocks import make_runtime_mock


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
    proxy = ProxyServer(
        verify_session_token=lambda sid, tok: True,
        get_allowed_domains=lambda sid: {"paperless.gerken.haus"},
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

    assert opened["host"] == "paperless.gerken.haus"
    assert opened["port"] == 443
    assert opened["kwargs"].get("server_hostname") == "paperless.gerken.haus"
    assert opened["kwargs"].get("ssl") is not None
    assert remote_writer.writes[0] == b"GET /api/tags/?page_size=1 HTTP/1.1\r\n"
    assert client_writer.writes == [b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok"]


# ── SandboxManager allowlists ───────────────────────────────────────


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
    _git_exists = ExecResult(exit_code=0, output="")
    runtime.exec = AsyncMock(
        side_effect=[
            _git_exists,  # knowledge repo probe after first create
            _git_exists,  # setup_git_identity
            _git_exists,  # install_commit_msg_hook
            ContainerGoneError(),  # exec_command triggers recreate
            _git_exists,  # knowledge repo probe after recreate
            _git_exists,  # setup_git_identity
            _git_exists,  # install_commit_msg_hook
            ExecResult(exit_code=0, output="ok"),  # actual command retry
        ]
    )

    mgr = _sandbox_manager(runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path, session_factory=db_factory)
    _seed_session_row(db_factory, tmp_path, "sess-1")
    session_id = "sess-1"
    await mgr.ensure_session(session_id)
    mgr.allow_domains(session_id, {"api.example.com"})

    output = await mgr.exec_command(session_id, "curl https://api.example.com")
    assert output.output == "ok"
    assert mgr.get_allowed_domains(session_id) == {"api.example.com"}


@pytest.mark.anyio
async def test_activate_skill_registers_command_aliases_in_image_shim_dir(tmp_path: Path, db_factory):
    runtime = make_runtime_mock()
    runtime.get_host_ip = AsyncMock(return_value="172.18.0.1")
    runtime.create_sandbox = AsyncMock(return_value="container-1")
    runtime.get_ip = AsyncMock(return_value="172.18.0.22")
    runtime.logs = AsyncMock(return_value="carapace sandbox ready")
    runtime.exec = AsyncMock(
        side_effect=[
            ExecResult(exit_code=0, output=""),  # _clone_knowledge_repo probe after create
            ExecResult(exit_code=0, output=""),  # setup_git_identity
            ExecResult(exit_code=0, output=""),  # install_commit_msg_hook
            ExecResult(exit_code=0, output=""),  # command alias registration
        ]
    )

    skill_dir = tmp_path / "skills" / "web"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: web\n---\nBody.\n")

    mgr = _sandbox_manager(runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path, session_factory=db_factory)
    _seed_session_row(db_factory, tmp_path, "sess-1")
    mgr.set_skill_command_aliases_callback(
        lambda _session_id, skill_name: (
            [("web", "uv run --directory /workspace/skills/web web-search")] if skill_name == "web" else []
        )
    )

    result = await mgr.activate_skill("sess-1", "web")

    assert "Command aliases registered: web." in result
    assert "PATH" not in mgr.get_session_env("sess-1")

    register_call = runtime.exec.call_args_list[3]
    shell_cmd = register_call.args[1]
    wrapper = '#!/bin/sh\nexec uv run --directory /workspace/skills/web web-search "$@"\n'
    assert "/workspace/.carapace/bin/web" in shell_cmd
    assert base64.b64encode(wrapper.encode()).decode() in shell_cmd


# ── SKILL.md metadata parsing ───────────────────────────────────────


class TestSkillMetadataParsing:
    def _write_skill_md(self, skill_dir: Path, body: str) -> None:
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(body)

    def test_parse_frontmatter_carapace_metadata(self, tmp_path: Path):
        skill_dir = tmp_path / "inline"
        self._write_skill_md(
            skill_dir,
            "---\n"
            "name: inline\n"
            "metadata:\n"
            "  carapace:\n"
            "    network:\n"
            "      domains:\n"
            "        - api.example.com\n"
            "    commands:\n"
            "      - name: inline-search\n"
            "        command: uv run inline-search\n"
            "---\n"
            "Body.\n",
        )

        registry = SkillRegistry(tmp_path)
        cfg = registry.get_carapace_config("inline")
        assert cfg is not None
        assert cfg.network.domains == ["api.example.com"]
        assert len(cfg.commands) == 1
        assert cfg.commands[0].name == "inline-search"

    def test_parse_network_domains(self, tmp_path: Path):
        skill_dir = tmp_path / "web-search"
        self._write_skill_md(
            skill_dir,
            "---\n"
            "name: web-search\n"
            "metadata:\n"
            "  carapace:\n"
            "    network:\n"
            "      domains:\n"
            "        - api.example.com\n"
            "        - '*.cdn.example.com'\n"
            "---\n"
            "Body.\n",
        )

        registry = SkillRegistry(tmp_path)
        cfg = registry.get_carapace_config("web-search")
        assert cfg is not None
        assert cfg.network.domains == ["api.example.com", "*.cdn.example.com"]

    def test_parse_network_tunnels(self, tmp_path: Path):
        skill_dir = tmp_path / "zoho-mail"
        self._write_skill_md(
            skill_dir,
            "---\n"
            "name: zoho-mail\n"
            "metadata:\n"
            "  carapace:\n"
            "    network:\n"
            "      tunnels:\n"
            "        - host: imap.zoho.eu\n"
            "          remote_port: 993\n"
            "          local_port: 1993\n"
            "---\n"
            "Body.\n",
        )

        registry = SkillRegistry(tmp_path)
        cfg = registry.get_carapace_config("zoho-mail")
        assert cfg is not None
        assert len(cfg.network.tunnels) == 1
        assert cfg.network.tunnels[0].display == "imap.zoho.eu:993 via :1993"

    def test_no_carapace_metadata(self, tmp_path: Path):
        skill_dir = tmp_path / "plain"
        self._write_skill_md(skill_dir, "Body.\n")

        registry = SkillRegistry(tmp_path)
        assert registry.get_carapace_config("plain") is None

    def test_invalid_frontmatter_carapace_returns_none(self, tmp_path: Path):
        skill_dir = tmp_path / "bad-inline"
        self._write_skill_md(
            skill_dir,
            "---\n"
            "name: bad-inline\n"
            "metadata:\n"
            "  carapace:\n"
            "    commands:\n"
            "      - name: bad command\n"
            "        command: uv run ok\n"
            "---\n"
            "Body.\n",
        )

        registry = SkillRegistry(tmp_path)
        assert registry.get_carapace_config("bad-inline") is None

    def test_invalid_tunnel_host_rejects_config(self, tmp_path: Path):
        skill_dir = tmp_path / "bad-tunnel"
        self._write_skill_md(
            skill_dir,
            "---\n"
            "name: bad-tunnel\n"
            "metadata:\n"
            "  carapace:\n"
            "    network:\n"
            "      tunnels:\n"
            "        - host: '*.zoho.eu'\n"
            "          remote_port: 993\n"
            "          local_port: 1993\n"
            "---\n"
            "Body.\n",
        )

        registry = SkillRegistry(tmp_path)
        assert registry.get_carapace_config("bad-tunnel") is None

    def test_invalid_tunnel_ip_literal_rejects_config(self, tmp_path: Path):
        skill_dir = tmp_path / "bad-tunnel-ip"
        self._write_skill_md(
            skill_dir,
            "---\n"
            "name: bad-tunnel-ip\n"
            "metadata:\n"
            "  carapace:\n"
            "    network:\n"
            "      tunnels:\n"
            "        - host: 10.0.0.1\n"
            "          remote_port: 993\n"
            "          local_port: 1993\n"
            "---\n"
            "Body.\n",
        )

        registry = SkillRegistry(tmp_path)
        assert registry.get_carapace_config("bad-tunnel-ip") is None

    def test_invalid_tunnel_internal_service_rejects_config(self, tmp_path: Path):
        skill_dir = tmp_path / "bad-tunnel-svc"
        self._write_skill_md(
            skill_dir,
            "---\n"
            "name: bad-tunnel-svc\n"
            "metadata:\n"
            "  carapace:\n"
            "    network:\n"
            "      tunnels:\n"
            "        - host: kubernetes.default.svc\n"
            "          remote_port: 443\n"
            "          local_port: 1443\n"
            "---\n"
            "Body.\n",
        )

        registry = SkillRegistry(tmp_path)
        assert registry.get_carapace_config("bad-tunnel-svc") is None

    def test_invalid_tunnel_trailing_dot_blocked_host_rejects_config(self, tmp_path: Path):
        skill_dir = tmp_path / "bad-tunnel-dot"
        self._write_skill_md(
            skill_dir,
            "---\n"
            "name: bad-tunnel-dot\n"
            "metadata:\n"
            "  carapace:\n"
            "    network:\n"
            "      tunnels:\n"
            "        - host: localhost.\n"
            "          remote_port: 443\n"
            "          local_port: 1443\n"
            "---\n"
            "Body.\n",
        )

        registry = SkillRegistry(tmp_path)
        assert registry.get_carapace_config("bad-tunnel-dot") is None

    def test_empty_network_section(self, tmp_path: Path):
        skill_dir = tmp_path / "minimal"
        self._write_skill_md(
            skill_dir,
            "---\n"
            "name: minimal\n"
            "metadata:\n"
            "  carapace:\n"
            "    hints:\n"
            "      likely_classification: read_external\n"
            "---\n"
            "Body.\n",
        )

        registry = SkillRegistry(tmp_path)
        cfg = registry.get_carapace_config("minimal")
        assert cfg is not None
        assert cfg.network.domains == []

    def test_model_validation(self):
        cfg = SkillCarapaceConfig.model_validate(
            {
                "network": {
                    "domains": ["a.com"],
                    "tunnels": [{"host": "imap.a.com", "remote_port": 993, "local_port": 1993}],
                },
                "credentials": [{"vault_path": "x/y", "description": "Test cred", "env_var": "FOO"}],
                "commands": [{"name": "demo", "command": "uv run demo"}],
            }
        )
        assert cfg.network.domains == ["a.com"]
        assert cfg.network.tunnels[0].display == "imap.a.com:993 via :1993"
        assert len(cfg.credentials) == 1
        assert cfg.credentials[0].vault_path == "x/y"
        assert cfg.credentials[0].env_var == "FOO"
        assert len(cfg.commands) == 1
        assert cfg.commands[0].name == "demo"
        assert cfg.commands[0].command == "uv run demo"

    def test_model_validation_rejects_multiline_command(self):
        with pytest.raises(ValueError, match="single line"):
            SkillCarapaceConfig.model_validate(
                {
                    "commands": [{"name": "demo", "command": "uv run demo\necho nope"}],
                }
            )

    def test_model_validation_rejects_duplicate_command_names(self):
        with pytest.raises(ValueError, match="duplicate skill command name"):
            SkillCarapaceConfig.model_validate(
                {
                    "commands": [
                        {"name": "demo", "command": "uv run demo"},
                        {"name": "demo", "command": "uv run demo --help"},
                    ]
                }
            )

    def test_model_validation_rejects_duplicate_local_ports(self):
        with pytest.raises(ValueError, match="local_port 1993"):
            SkillCarapaceConfig.model_validate(
                {
                    "network": {
                        "tunnels": [
                            {"host": "imap.a.com", "remote_port": 993, "local_port": 1993},
                            {"host": "imap.b.com", "remote_port": 993, "local_port": 1993},
                        ]
                    }
                }
            )

    @pytest.mark.anyio
    async def test_context_tunnel_helper_accepts_minimal_connect_response(self):
        namespace: dict[str, Any] = {"__name__": "test_context_tunnel_helper"}
        compile(_CONTEXT_TUNNEL_HELPER, "carapace_tunnel_helper.py", "exec")
        exec(_CONTEXT_TUNNEL_HELPER, namespace)
        open_proxy_tunnel = cast(Any, namespace["_open_proxy_tunnel"])
        helper_asyncio = cast(Any, namespace["asyncio"])

        class FakeReader:
            def __init__(self, chunks: list[bytes]):
                self._chunks = list(chunks)

            async def read(self, _size: int) -> bytes:
                if self._chunks:
                    return self._chunks.pop(0)
                return b""

        class FakeWriter:
            def __init__(self):
                self.writes: list[bytes] = []

            def write(self, data: bytes) -> None:
                self.writes.append(data)

            async def drain(self) -> None:
                return None

        reader = FakeReader([b"HTTP/1.1 200 Connection Established\r\n\r\n"])
        writer = FakeWriter()

        async def fake_open_connection(host: str, port: int):
            assert host == "proxy.internal"
            assert port == 8080
            return reader, writer

        original_open_connection = helper_asyncio.open_connection
        helper_asyncio.open_connection = fake_open_connection
        try:
            prebuffer, upstream_reader, upstream_writer = await open_proxy_tunnel(
                "http://proxy.internal:8080",
                "imap.zoho.eu",
                993,
            )
        finally:
            helper_asyncio.open_connection = original_open_connection

        assert prebuffer == b""
        assert upstream_reader is reader
        assert upstream_writer is writer
        assert writer.writes == [b"CONNECT imap.zoho.eu:993 HTTP/1.1\r\nHost: imap.zoho.eu:993\r\n\r\n"]


@pytest.mark.anyio
async def test_exec_command_sets_up_and_cleans_up_tunnels(tmp_path: Path, db_factory):
    runtime = make_runtime_mock()
    runtime.get_host_ip = AsyncMock(return_value="172.18.0.1")
    runtime.create_sandbox = AsyncMock(return_value="container-1")
    runtime.get_ip = AsyncMock(return_value="172.18.0.22")
    runtime.logs = AsyncMock(return_value="carapace sandbox ready")
    runtime.exec = AsyncMock(return_value=ExecResult(exit_code=0, output="ok"))

    mgr = _sandbox_manager(runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path, session_factory=db_factory)
    _seed_session_row(db_factory, tmp_path, "sess-1")

    result = await mgr.exec_command(
        "sess-1",
        "run-mail-sync",
        context_tunnels=[NetworkTunnel(host="imap.zoho.eu", remote_port=993, local_port=1993)],
    )

    assert result.output == "ok"

    commands = [call.args[1] for call in runtime.exec.call_args_list]
    assert any("carapace-tunnel-helper-sess-1.py" in command for command in commands)
    assert any("cp /etc/hosts /tmp/carapace-tunnel-hosts-sess-1.bak" in command for command in commands)
    assert any("{ nohup python3 /tmp/carapace-tunnel-helper-sess-1.py" in command for command in commands)
    assert any("--listen-port 1993" in command and "--target-port 993" in command for command in commands)
    assert any("--ready-file /tmp/carapace-tunnel-sess-1-1993.ready" in command for command in commands)
    assert any(command == "run-mail-sync" for command in commands)
    assert any("echo $! > /tmp/carapace-tunnel-sess-1-1993.pid; } && kill -0" in command for command in commands)
    assert any("while [ ! -f /tmp/carapace-tunnel-sess-1-1993.ready ]" in command for command in commands)
    assert any('kill "$(cat /tmp/carapace-tunnel-sess-1-1993.pid)"' in command for command in commands)
    assert not any("do;" in command for command in commands)
    assert not any("then;" in command for command in commands)


@pytest.mark.anyio
async def test_exec_command_rejects_conflicting_tunnel_local_ports(tmp_path: Path, db_factory):
    runtime = make_runtime_mock()
    runtime.get_host_ip = AsyncMock(return_value="172.18.0.1")
    runtime.create_sandbox = AsyncMock(return_value="container-1")
    runtime.get_ip = AsyncMock(return_value="172.18.0.22")
    runtime.logs = AsyncMock(return_value="carapace sandbox ready")
    runtime.exec = AsyncMock(return_value=ExecResult(exit_code=0, output="ok"))

    mgr = _sandbox_manager(runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path, session_factory=db_factory)
    _seed_session_row(db_factory, tmp_path, "sess-1")

    with pytest.raises(ValueError, match=r"Conflicting network\.tunnels declarations"):
        await mgr.exec_command(
            "sess-1",
            "run-mail-sync",
            context_tunnels=[
                NetworkTunnel(host="imap.zoho.eu", remote_port=993, local_port=1993),
                NetworkTunnel(host="smtp.zoho.eu", remote_port=465, local_port=1993),
            ],
        )


@pytest.mark.anyio
async def test_exec_command_allows_duplicate_tunnel_with_different_descriptions(tmp_path: Path, db_factory):
    runtime = make_runtime_mock()
    runtime.get_host_ip = AsyncMock(return_value="172.18.0.1")
    runtime.create_sandbox = AsyncMock(return_value="container-1")
    runtime.get_ip = AsyncMock(return_value="172.18.0.22")
    runtime.logs = AsyncMock(return_value="carapace sandbox ready")
    runtime.exec = AsyncMock(return_value=ExecResult(exit_code=0, output="ok"))

    mgr = _sandbox_manager(runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path, session_factory=db_factory)
    _seed_session_row(db_factory, tmp_path, "sess-1")

    result = await mgr.exec_command(
        "sess-1",
        "run-mail-sync",
        context_tunnels=[
            NetworkTunnel(
                host="imap.zoho.eu",
                remote_port=993,
                local_port=1993,
                description="Primary IMAP tunnel",
            ),
            NetworkTunnel(
                host="imap.zoho.eu",
                remote_port=993,
                local_port=1993,
                description="Same tunnel from another skill",
            ),
        ],
    )

    assert result.output == "ok"

    commands = [call.args[1] for call in runtime.exec.call_args_list]
    assert sum("nohup python3 /tmp/carapace-tunnel-helper-sess-1.py" in command for command in commands) == 1


@pytest.mark.anyio
async def test_exec_command_recreates_tunnels_before_retry(tmp_path: Path, db_factory):
    runtime = make_runtime_mock()
    runtime.get_host_ip = AsyncMock(return_value="172.18.0.1")
    runtime.sandbox_exists = AsyncMock(return_value=None)
    runtime.create_sandbox = AsyncMock(side_effect=["container-1", "container-2"])
    runtime.get_ip = AsyncMock(return_value="172.18.0.22")
    runtime.logs = AsyncMock(return_value="carapace sandbox ready")

    _ok = ExecResult(exit_code=0, output="")
    runtime.exec = AsyncMock(
        side_effect=[
            _ok,  # clone probe (create)
            _ok,  # setup_git_identity
            _ok,  # install_commit_msg_hook
            _ok,  # tunnel prep
            _ok,
            _ok,
            _ok,
            ContainerGoneError(),  # command exec triggers recreate
            _ok,  # clone probe (recreate)
            _ok,  # setup_git_identity
            _ok,  # install_commit_msg_hook
            _ok,  # tunnel prep
            _ok,
            _ok,
            _ok,
            ExecResult(exit_code=0, output="ok"),  # retried command
            _ok,  # cleanup
        ]
    )

    mgr = _sandbox_manager(runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path, session_factory=db_factory)
    _seed_session_row(db_factory, tmp_path, "sess-1")

    result = await mgr.exec_command(
        "sess-1",
        "run-mail-sync",
        context_tunnels=[NetworkTunnel(host="imap.zoho.eu", remote_port=993, local_port=1993)],
    )

    assert result.output == "ok"
    assert runtime.create_sandbox.await_count == 2

    commands = [call.args[1] for call in runtime.exec.call_args_list]
    assert sum("carapace-tunnel-helper-sess-1.py" in command for command in commands) >= 2
    assert sum("--listen-port 1993" in command and "--target-port 993" in command for command in commands) == 2


@pytest.mark.anyio
async def test_exec_command_cleans_up_tunnels_after_command_failure(tmp_path: Path, db_factory):
    runtime = make_runtime_mock()
    runtime.get_host_ip = AsyncMock(return_value="172.18.0.1")
    runtime.create_sandbox = AsyncMock(return_value="container-1")
    runtime.get_ip = AsyncMock(return_value="172.18.0.22")
    runtime.logs = AsyncMock(return_value="carapace sandbox ready")
    runtime.exec = AsyncMock(
        side_effect=[
            ExecResult(exit_code=0, output=""),  # clone probe
            ExecResult(exit_code=0, output=""),  # setup_git_identity
            ExecResult(exit_code=0, output=""),  # install_commit_msg_hook
            ExecResult(exit_code=0, output=""),  # tunnel prep
            ExecResult(exit_code=0, output=""),
            ExecResult(exit_code=0, output=""),
            ExecResult(exit_code=0, output=""),
            ExecResult(exit_code=5, output="mail failed"),  # command
            ExecResult(exit_code=0, output=""),  # cleanup
        ]
    )

    mgr = _sandbox_manager(runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path, session_factory=db_factory)
    _seed_session_row(db_factory, tmp_path, "sess-1")

    result = await mgr.exec_command(
        "sess-1",
        "run-mail-sync",
        context_tunnels=[NetworkTunnel(host="imap.zoho.eu", remote_port=993, local_port=1993)],
    )

    assert result.exit_code == 5
    assert "mail failed" in result.output
    assert "[exit code: 5]" in result.output

    cleanup_command = runtime.exec.call_args_list[-1].args[1]
    assert 'kill "$(cat /tmp/carapace-tunnel-sess-1-1993.pid)"' in cleanup_command
    assert "cp /tmp/carapace-tunnel-hosts-sess-1.bak /etc/hosts" in cleanup_command


@pytest.mark.anyio
async def test_exec_cleanup_tunnel_error_does_not_mask_command_error_or_skip_credential_cleanup():
    runtime = make_runtime_mock()
    state = SandboxExecState(
        sessions={},
        allowed_domains={},
        exec_temp_domains={},
        exec_context_skill_domains={},
        session_current_command={},
        domain_approval_cbs={},
        domain_notify_cbs={},
        exec_locks={},
        proxy_bypass_sessions=set(),
        session_current_contexts={},
        exec_notified_domains={},
        exec_notified_credentials={},
    )
    coordinator = SandboxExecCoordinator(runtime=runtime, state=state)
    sc1 = SessionContainer(container_id="container-1", session_id="sess-1", created_at=0, last_used=0)
    sc2 = SessionContainer(container_id="container-2", session_id="sess-1", created_at=0, last_used=0)
    written_files = [("example", "/workspace/skills/example/.secrets/token.txt")]

    ensure_session = AsyncMock(side_effect=[(sc1, False), (sc2, False)])
    rerun_skill_setup = AsyncMock()
    log_container_tail = AsyncMock()
    prepare_session_recreate = MagicMock()
    exec_in_container = AsyncMock(side_effect=[ContainerGoneError("gone"), RuntimeError("command failed")])
    prepare_context_tunnels = AsyncMock()
    cleanup_context_tunnels = AsyncMock(side_effect=ContainerGoneError("cleanup failed"))
    write_context_file_credentials = AsyncMock(side_effect=[list(written_files), list(written_files)])
    delete_context_file_credentials = AsyncMock()

    with pytest.raises(RuntimeError, match="command failed"):
        await coordinator.exec(
            "sess-1",
            "run-mail-sync",
            ensure_session=ensure_session,
            rerun_skill_setup=rerun_skill_setup,
            log_container_tail=log_container_tail,
            prepare_session_recreate=prepare_session_recreate,
            exec_in_container=exec_in_container,
            prepare_context_tunnels=prepare_context_tunnels,
            cleanup_context_tunnels=cleanup_context_tunnels,
            write_context_file_credentials=write_context_file_credentials,
            delete_context_file_credentials=delete_context_file_credentials,
            context_tunnels=[NetworkTunnel(host="imap.zoho.eu", remote_port=993, local_port=1993)],
            context_file_creds=[("example", ".secrets/token.txt", "secret")],
        )

    delete_context_file_credentials.assert_awaited_once_with("sess-1", written_files)


def _make_exec_state(**overrides) -> SandboxExecState:
    base = dict(
        sessions={},
        allowed_domains={},
        exec_temp_domains={},
        exec_context_skill_domains={},
        session_current_command={},
        domain_approval_cbs={},
        domain_notify_cbs={},
        exec_locks={},
        proxy_bypass_sessions=set(),
        session_current_contexts={},
        exec_notified_domains={},
        exec_notified_credentials={},
    )
    base.update(overrides)
    return SandboxExecState(**base)


@pytest.mark.anyio
async def test_request_domain_approval_denies_orphaned_request_without_sentinel():
    """No live exec → deny without invoking the sentinel callback (orphaned process)."""
    cb = AsyncMock(return_value=True)
    state = _make_exec_state(domain_approval_cbs={"sess-1": cb})
    coordinator = SandboxExecCoordinator(runtime=make_runtime_mock(), state=state)

    allowed = await coordinator.request_domain_approval("sess-1", "registry.npmjs.org")

    assert allowed is False
    cb.assert_not_awaited()
    assert "registry.npmjs.org" not in state.exec_temp_domains.get("sess-1", set())


@pytest.mark.anyio
async def test_request_domain_approval_consults_sentinel_during_live_exec():
    """Live exec (command recorded) → callback is consulted as before."""
    cb = AsyncMock(return_value=True)
    state = _make_exec_state(
        domain_approval_cbs={"sess-1": cb},
        session_current_command={"sess-1": "npm ci"},
    )
    coordinator = SandboxExecCoordinator(runtime=make_runtime_mock(), state=state)

    allowed = await coordinator.request_domain_approval("sess-1", "registry.npmjs.org")

    assert allowed is True
    cb.assert_awaited_once_with("registry.npmjs.org", "npm ci")
    assert "registry.npmjs.org" in state.exec_temp_domains["sess-1"]


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
        host="127.0.0.1",
        port=0,  # OS-assigned port
    )
    await proxy.start()
    assert proxy._server is not None
    assert proxy._server.is_serving()
    await proxy.stop()
