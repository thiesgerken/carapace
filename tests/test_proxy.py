"""Tests for the sandbox proxy: domain matching, allowlists, and carapace.yaml parsing."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from carapace.models import SkillCarapaceConfig
from carapace.sandbox.exec_flow import SandboxExecCoordinator, SandboxExecState
from carapace.sandbox.manager import _CONTEXT_TUNNEL_HELPER, SandboxManager
from carapace.sandbox.proxy import ProxyServer, domain_matches
from carapace.sandbox.runtime import (
    ContainerGoneError,
    ExecResult,
    NetworkTunnel,
    SkillActivationInputs,
    SkillFileCredential,
)
from carapace.sandbox.session_lifecycle import SessionContainer
from carapace.skills import SkillRegistry
from tests.runtime_mocks import make_runtime_mock

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
    def _make_manager(self, tmp_path: Path):
        runtime = make_runtime_mock()
        return SandboxManager(runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path)

    def test_empty_by_default(self, tmp_path: Path):
        mgr = self._make_manager(tmp_path)
        assert mgr.get_allowed_domains("sess-1") == set()

    def test_allow_domains(self, tmp_path: Path):
        mgr = self._make_manager(tmp_path)
        mgr.allow_domains("sess-1", {"a.com", "b.com"})
        assert mgr.get_allowed_domains("sess-1") == {"a.com", "b.com"}

    def test_allow_domains_accumulates(self, tmp_path: Path):
        mgr = self._make_manager(tmp_path)
        mgr.allow_domains("sess-1", {"a.com"})
        mgr.allow_domains("sess-1", {"b.com"})
        assert mgr.get_allowed_domains("sess-1") == {"a.com", "b.com"}

    def test_cleanup_clears_domains(self, tmp_path: Path):
        mgr = self._make_manager(tmp_path)
        mgr.allow_domains("sess-1", {"a.com"})
        mgr._cleanup_tracking("sess-1")
        assert mgr.get_allowed_domains("sess-1") == set()

    def test_proxy_env_includes_token(self, tmp_path: Path):
        mgr = self._make_manager(tmp_path)
        env = mgr._build_proxy_env("sess-1", "my-secret-token", "http://172.18.0.2:3128")
        assert env["HTTP_PROXY"] == "http://sess-1:my-secret-token@172.18.0.2:3128"
        assert env["HTTPS_PROXY"] == "http://sess-1:my-secret-token@172.18.0.2:3128"
        assert "172.18.0.2" in env["NO_PROXY"]
        assert "GIT_REPO_URL" in env

    def test_proxy_env_includes_session_id(self, tmp_path: Path):
        mgr = self._make_manager(tmp_path)
        env = mgr._build_proxy_env("sess-1", "tok", "http://172.18.0.2:3128")
        assert env["CARAPACE_SESSION_ID"] == "sess-1"

    def test_proxy_env_no_git_identity_vars(self, tmp_path: Path):
        """Git identity is configured via git config inside the container, not env vars."""
        mgr = self._make_manager(tmp_path)
        env = mgr._build_proxy_env("sess-1", "tok", "http://172.18.0.2:3128")
        assert "GIT_AUTHOR_NAME" not in env
        assert "GIT_COMMITTER_NAME" not in env
        assert "GIT_AUTHOR_EMAIL" not in env
        assert "GIT_COMMITTER_EMAIL" not in env

    def test_no_proxy_env_when_empty(self, tmp_path: Path):
        mgr = self._make_manager(tmp_path)
        assert mgr._build_proxy_env("sess-1", "tok", "") == {}

    def test_token_lookup(self, tmp_path: Path):
        mgr = self._make_manager(tmp_path)
        mgr._token_to_session["abc123"] = "sess-1"
        assert mgr.verify_session_token("sess-1", "abc123") is True
        assert mgr.verify_session_token("sess-1", "wrong") is False
        assert mgr.verify_session_token("wrong-session", "abc123") is False

    def test_token_lookup_restores_persisted_token(self, tmp_path: Path):
        mgr = self._make_manager(tmp_path)
        token_path = tmp_path / "sessions" / "sess-1" / "token"
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text("persisted-token")

        assert mgr.verify_session_token("sess-1", "persisted-token") is True
        assert mgr._session_tokens["sess-1"] == "persisted-token"
        assert mgr._token_to_session["persisted-token"] == "sess-1"

    def test_cleanup_clears_tokens(self, tmp_path: Path):
        mgr = self._make_manager(tmp_path)
        mgr._token_to_session["tok"] = "sess-1"
        mgr._session_tokens["sess-1"] = "tok"
        mgr._cleanup_tracking("sess-1")
        assert mgr.verify_session_token("sess-1", "tok") is False


@pytest.mark.anyio
async def test_exec_recreate_preserves_domains(tmp_path: Path):
    runtime = make_runtime_mock()
    runtime.get_host_ip = AsyncMock(return_value="172.18.0.1")
    runtime.create_sandbox = AsyncMock(side_effect=["container-1", "container-2"])
    runtime.get_ip = AsyncMock(return_value="172.18.0.22")
    runtime.logs = AsyncMock(return_value="carapace sandbox ready")
    _git_exists = ExecResult(exit_code=0, output="")
    runtime.exec = AsyncMock(
        side_effect=[
            _git_exists,  # knowledge repo probe after first create
            ContainerGoneError(),  # exec_command triggers recreate
            _git_exists,  # knowledge repo probe after recreate
            ExecResult(exit_code=0, output="ok"),  # actual command retry
        ]
    )

    mgr = SandboxManager(runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path)
    session_id = "sess-1"
    await mgr.ensure_session(session_id)
    mgr.allow_domains(session_id, {"api.example.com"})

    output = await mgr.exec_command(session_id, "curl https://api.example.com")
    assert output.output == "ok"
    assert mgr.get_allowed_domains(session_id) == {"api.example.com"}


@pytest.mark.anyio
async def test_exec_recreate_reinjects_credential_files(tmp_path: Path):
    """After container recreation, activation providers re-materialize file credentials."""
    runtime = make_runtime_mock()
    runtime.get_host_ip = AsyncMock(return_value="172.18.0.1")
    runtime.create_sandbox = AsyncMock(side_effect=["container-1", "container-2"])
    runtime.get_ip = AsyncMock(return_value="172.18.0.22")
    runtime.logs = AsyncMock(return_value="carapace sandbox ready")

    _ok = ExecResult(exit_code=0, output="")
    runtime.exec = AsyncMock(
        side_effect=[
            _ok,  # _clone_knowledge_repo probe after first create
            ContainerGoneError(),  # exec_command triggers recreate
            _ok,  # _clone_knowledge_repo probe after recreate
            _ok,  # git checkout carapace.yaml
            _ok,  # git checkout setup.sh
            _ok,  # _file_write_in_container (credential materialization)
            _ok,  # setup.sh execution
            _ok,  # credential file cleanup
            ExecResult(exit_code=0, output="ok"),  # actual command retry
        ]
    )

    # Create a skill dir with setup.sh so provider rebuild runs after recreation.
    skill_dir = tmp_path / "skills" / "moneydb"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: moneydb\n---\nBody.\n")
    (skill_dir / "setup.sh").write_text("#!/bin/sh\n")

    mgr = SandboxManager(runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path)
    session_id = "sess-1"

    # Register callbacks — the activated-skills callback returns "moneydb",
    # and the activation callback returns one file credential to materialize.
    mgr.set_activated_skills_callback(lambda sid: ["moneydb"])
    activation_cb = AsyncMock(
        return_value=SkillActivationInputs(
            file_credentials=[SkillFileCredential(path="/tmp/creds/api_key.json", value="secret-key-value")]
        )
    )
    mgr.set_skill_activation_inputs_callback(activation_cb)

    await mgr.ensure_session(session_id)
    output = await mgr.exec_command(session_id, "run-moneydb")
    assert output.output == "ok"

    # Verify the activation callback was called for the right session + skill.
    activation_cb.assert_awaited_once_with(session_id, "moneydb")

    # Verify upstream restore is used for trusted provider files.
    restore_call = runtime.exec.call_args_list[4]
    assert "git checkout @{upstream} -- skills/moneydb/setup.sh" in restore_call.args[1]

    # Verify the credential file was written into the new container via exec.
    # The 6th exec call (index 5) is the _file_write_in_container for the
    # credential — check that it targeted the correct workdir.
    write_call = runtime.exec.call_args_list[5]
    shell_cmd = write_call.args[1]
    assert "/tmp/creds/api_key.json" in shell_cmd
    assert base64.b64encode(b"secret-key-value").decode() in shell_cmd
    assert write_call.kwargs.get("workdir") == "/workspace/skills/moneydb"


@pytest.mark.anyio
async def test_activate_skill_runs_setup_provider_with_activation_inputs(tmp_path: Path):
    runtime = make_runtime_mock()
    runtime.get_host_ip = AsyncMock(return_value="172.18.0.1")
    runtime.create_sandbox = AsyncMock(return_value="container-1")
    runtime.get_ip = AsyncMock(return_value="172.18.0.22")
    runtime.logs = AsyncMock(return_value="carapace sandbox ready")
    runtime.exec = AsyncMock(
        side_effect=[
            ExecResult(exit_code=0, output=""),  # _clone_knowledge_repo probe after create
            ExecResult(exit_code=0, output=""),  # git checkout carapace.yaml
            ExecResult(exit_code=0, output=""),  # git checkout setup.sh
            ExecResult(exit_code=0, output=""),  # credential file write
            ExecResult(exit_code=0, output=""),  # setup.sh execution
            ExecResult(exit_code=0, output=""),  # credential file cleanup
        ]
    )

    skill_dir = tmp_path / "skills" / "cred-setup"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: cred-setup\n---\nBody.\n")
    (skill_dir / "setup.sh").write_text("#!/bin/sh\n")

    mgr = SandboxManager(runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path)
    mgr.set_skill_activation_inputs_callback(
        AsyncMock(
            return_value=SkillActivationInputs(
                environment={"API_TOKEN": "secret-token"},
                file_credentials=[SkillFileCredential(path=".config/token.txt", value="secret-token")],
            )
        )
    )

    result = await mgr.activate_skill("sess-1", "cred-setup")
    assert "setup.sh completed." in result

    setup_call = runtime.exec.call_args_list[4]
    assert setup_call.args[1] == "sh ./setup.sh"
    assert setup_call.kwargs.get("workdir") == "/workspace/skills/cred-setup"
    assert setup_call.kwargs.get("env") == {"API_TOKEN": "secret-token"}

    restore_call = runtime.exec.call_args_list[2]
    assert "git checkout @{upstream} -- skills/cred-setup/setup.sh" in restore_call.args[1]


@pytest.mark.anyio
async def test_activate_skill_recovers_if_trusted_restore_hits_gone_container(tmp_path: Path):
    runtime = make_runtime_mock()
    runtime.get_host_ip = AsyncMock(return_value="172.18.0.1")
    runtime.create_sandbox = AsyncMock(side_effect=["container-1", "container-2"])
    runtime.get_ip = AsyncMock(return_value="172.18.0.22")
    runtime.logs = AsyncMock(return_value="carapace sandbox ready")
    runtime.exec = AsyncMock(
        side_effect=[
            ExecResult(exit_code=0, output=""),  # _clone_knowledge_repo probe after first create
            ContainerGoneError(),  # trusted restore triggers recreate
            ExecResult(exit_code=0, output=""),  # _clone_knowledge_repo probe after recreate
            ExecResult(exit_code=0, output=""),  # retried git checkout carapace.yaml
            ExecResult(exit_code=0, output=""),  # git checkout setup.sh
            ExecResult(exit_code=0, output=""),  # setup.sh execution
        ]
    )

    skill_dir = tmp_path / "skills" / "restore-retry"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: restore-retry\n---\nBody.\n")
    (skill_dir / "setup.sh").write_text("#!/bin/sh\n")

    mgr = SandboxManager(runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path)

    result = await mgr.activate_skill("sess-1", "restore-retry")
    assert "setup.sh completed." in result
    assert runtime.create_sandbox.await_count == 2

    restore_retry_call = runtime.exec.call_args_list[3]
    assert "git checkout @{upstream} -- skills/restore-retry/carapace.yaml" in restore_retry_call.args[1]


@pytest.mark.anyio
async def test_activate_skill_prefers_pnpm_when_package_and_pnpm_lockfiles_exist(tmp_path: Path):
    runtime = make_runtime_mock()
    runtime.get_host_ip = AsyncMock(return_value="172.18.0.1")
    runtime.create_sandbox = AsyncMock(return_value="container-1")
    runtime.get_ip = AsyncMock(return_value="172.18.0.22")
    runtime.logs = AsyncMock(return_value="carapace sandbox ready")
    runtime.exec = AsyncMock(return_value=ExecResult(exit_code=0, output=""))

    skill_dir = tmp_path / "skills" / "multi-node-lock"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: multi-node-lock\n---\nBody.\n")
    (skill_dir / "package.json").write_text("{}\n")
    (skill_dir / "package-lock.json").write_text("{}\n")
    (skill_dir / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n")

    mgr = SandboxManager(runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path)

    result = await mgr.activate_skill("sess-1", "multi-node-lock")
    commands = [call.args[1] for call in runtime.exec.call_args_list]
    result_lines = result.splitlines()

    assert "pnpm dependencies installed." in result_lines
    assert "npm dependencies installed." not in result_lines
    assert "pnpm install --frozen-lockfile" in commands
    assert "npm ci" not in commands
    assert not any(
        command.startswith("git checkout @{upstream} --") and "package-lock.json" in command for command in commands
    )


# ── carapace.yaml parsing ───────────────────────────────────────────


class TestCarapaceYamlParsing:
    def test_parse_network_domains(self, tmp_path: Path):
        skill_dir = tmp_path / "web-search"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: web-search\n---\nBody.\n")
        (skill_dir / "carapace.yaml").write_text(
            "network:\n  domains:\n    - api.example.com\n    - '*.cdn.example.com'\n"
        )

        registry = SkillRegistry(tmp_path)
        cfg = registry.get_carapace_config("web-search")
        assert cfg is not None
        assert cfg.network.domains == ["api.example.com", "*.cdn.example.com"]

    def test_parse_network_tunnels(self, tmp_path: Path):
        skill_dir = tmp_path / "zoho-mail"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: zoho-mail\n---\nBody.\n")
        (skill_dir / "carapace.yaml").write_text(
            "network:\n  tunnels:\n    - host: imap.zoho.eu\n      remote_port: 993\n      local_port: 1993\n"
        )

        registry = SkillRegistry(tmp_path)
        cfg = registry.get_carapace_config("zoho-mail")
        assert cfg is not None
        assert len(cfg.network.tunnels) == 1
        assert cfg.network.tunnels[0].display == "imap.zoho.eu:993 via :1993"

    def test_no_carapace_yaml(self, tmp_path: Path):
        skill_dir = tmp_path / "plain"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("Body.\n")

        registry = SkillRegistry(tmp_path)
        assert registry.get_carapace_config("plain") is None

    def test_invalid_carapace_yaml(self, tmp_path: Path):
        skill_dir = tmp_path / "bad"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("Body.\n")
        (skill_dir / "carapace.yaml").write_text(": invalid yaml {{{\n")

        registry = SkillRegistry(tmp_path)
        assert registry.get_carapace_config("bad") is None

    def test_invalid_tunnel_host_rejects_config(self, tmp_path: Path):
        skill_dir = tmp_path / "bad-tunnel"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("Body.\n")
        (skill_dir / "carapace.yaml").write_text(
            "network:\n  tunnels:\n    - host: '*.zoho.eu'\n      remote_port: 993\n      local_port: 1993\n"
        )

        registry = SkillRegistry(tmp_path)
        assert registry.get_carapace_config("bad-tunnel") is None

    def test_invalid_tunnel_ip_literal_rejects_config(self, tmp_path: Path):
        skill_dir = tmp_path / "bad-tunnel-ip"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("Body.\n")
        (skill_dir / "carapace.yaml").write_text(
            "network:\n  tunnels:\n    - host: 10.0.0.1\n      remote_port: 993\n      local_port: 1993\n"
        )

        registry = SkillRegistry(tmp_path)
        assert registry.get_carapace_config("bad-tunnel-ip") is None

    def test_invalid_tunnel_internal_service_rejects_config(self, tmp_path: Path):
        skill_dir = tmp_path / "bad-tunnel-svc"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("Body.\n")
        (skill_dir / "carapace.yaml").write_text(
            "network:\n  tunnels:\n    - host: kubernetes.default.svc\n      remote_port: 443\n      local_port: 1443\n"
        )

        registry = SkillRegistry(tmp_path)
        assert registry.get_carapace_config("bad-tunnel-svc") is None

    def test_invalid_tunnel_trailing_dot_blocked_host_rejects_config(self, tmp_path: Path):
        skill_dir = tmp_path / "bad-tunnel-dot"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("Body.\n")
        (skill_dir / "carapace.yaml").write_text(
            "network:\n  tunnels:\n    - host: localhost.\n      remote_port: 443\n      local_port: 1443\n"
        )

        registry = SkillRegistry(tmp_path)
        assert registry.get_carapace_config("bad-tunnel-dot") is None

    def test_empty_network_section(self, tmp_path: Path):
        skill_dir = tmp_path / "minimal"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("Body.\n")
        (skill_dir / "carapace.yaml").write_text("hints:\n  likely_classification: read_external\n")

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
            }
        )
        assert cfg.network.domains == ["a.com"]
        assert cfg.network.tunnels[0].display == "imap.a.com:993 via :1993"
        assert len(cfg.credentials) == 1
        assert cfg.credentials[0].vault_path == "x/y"
        assert cfg.credentials[0].env_var == "FOO"

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
async def test_exec_command_sets_up_and_cleans_up_tunnels(tmp_path: Path):
    runtime = make_runtime_mock()
    runtime.get_host_ip = AsyncMock(return_value="172.18.0.1")
    runtime.create_sandbox = AsyncMock(return_value="container-1")
    runtime.get_ip = AsyncMock(return_value="172.18.0.22")
    runtime.logs = AsyncMock(return_value="carapace sandbox ready")
    runtime.exec = AsyncMock(return_value=ExecResult(exit_code=0, output="ok"))

    mgr = SandboxManager(runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path)

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
async def test_exec_command_rejects_conflicting_tunnel_local_ports(tmp_path: Path):
    runtime = make_runtime_mock()
    runtime.get_host_ip = AsyncMock(return_value="172.18.0.1")
    runtime.create_sandbox = AsyncMock(return_value="container-1")
    runtime.get_ip = AsyncMock(return_value="172.18.0.22")
    runtime.logs = AsyncMock(return_value="carapace sandbox ready")
    runtime.exec = AsyncMock(return_value=ExecResult(exit_code=0, output="ok"))

    mgr = SandboxManager(runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path)

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
async def test_exec_command_allows_duplicate_tunnel_with_different_descriptions(tmp_path: Path):
    runtime = make_runtime_mock()
    runtime.get_host_ip = AsyncMock(return_value="172.18.0.1")
    runtime.create_sandbox = AsyncMock(return_value="container-1")
    runtime.get_ip = AsyncMock(return_value="172.18.0.22")
    runtime.logs = AsyncMock(return_value="carapace sandbox ready")
    runtime.exec = AsyncMock(return_value=ExecResult(exit_code=0, output="ok"))

    mgr = SandboxManager(runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path)

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
async def test_exec_command_recreates_tunnels_before_retry(tmp_path: Path):
    runtime = make_runtime_mock()
    runtime.get_host_ip = AsyncMock(return_value="172.18.0.1")
    runtime.sandbox_exists = AsyncMock(return_value=None)
    runtime.create_sandbox = AsyncMock(side_effect=["container-1", "container-2"])
    runtime.get_ip = AsyncMock(return_value="172.18.0.22")
    runtime.logs = AsyncMock(return_value="carapace sandbox ready")

    _ok = ExecResult(exit_code=0, output="")
    runtime.exec = AsyncMock(
        side_effect=[
            _ok,
            _ok,
            _ok,
            _ok,
            _ok,
            ContainerGoneError(),
            _ok,
            _ok,
            _ok,
            _ok,
            _ok,
            ExecResult(exit_code=0, output="ok"),
            _ok,
        ]
    )

    mgr = SandboxManager(runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path)

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
async def test_exec_command_cleans_up_tunnels_after_command_failure(tmp_path: Path):
    runtime = make_runtime_mock()
    runtime.get_host_ip = AsyncMock(return_value="172.18.0.1")
    runtime.create_sandbox = AsyncMock(return_value="container-1")
    runtime.get_ip = AsyncMock(return_value="172.18.0.22")
    runtime.logs = AsyncMock(return_value="carapace sandbox ready")
    runtime.exec = AsyncMock(
        side_effect=[
            ExecResult(exit_code=0, output=""),
            ExecResult(exit_code=0, output=""),
            ExecResult(exit_code=0, output=""),
            ExecResult(exit_code=0, output=""),
            ExecResult(exit_code=0, output=""),
            ExecResult(exit_code=5, output="mail failed"),
            ExecResult(exit_code=0, output=""),
        ]
    )

    mgr = SandboxManager(runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path)

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
