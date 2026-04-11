"""Tests for the sandbox proxy: domain matching, allowlists, and carapace.yaml parsing."""

from __future__ import annotations

import base64
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from carapace.models import SkillCarapaceConfig
from carapace.sandbox.manager import SandboxManager
from carapace.sandbox.proxy import ProxyServer, domain_matches
from carapace.sandbox.runtime import ContainerGoneError, ContainerRuntime, ExecResult
from carapace.skills import SkillRegistry

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

    def test_parse_non_absolute(self):
        assert ProxyServer._parse_absolute_url("/relative") == ("", 0, "")


# ── SandboxManager allowlists ───────────────────────────────────────


class TestSandboxManagerAllowlists:
    def _make_manager(self, tmp_path: Path):
        runtime = MagicMock(spec=ContainerRuntime)
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

    def test_cleanup_clears_tokens(self, tmp_path: Path):
        mgr = self._make_manager(tmp_path)
        mgr._token_to_session["tok"] = "sess-1"
        mgr._session_tokens["sess-1"] = "tok"
        mgr._cleanup_tracking("sess-1")
        assert mgr.verify_session_token("sess-1", "tok") is False


@pytest.mark.anyio
async def test_exec_recreate_preserves_domains(tmp_path: Path):
    runtime = MagicMock(spec=ContainerRuntime)
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
    """After container recreation, _rebuild_skill_venvs re-injects file credentials."""
    runtime = MagicMock(spec=ContainerRuntime)
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
            _ok,  # git checkout pyproject.toml
            _ok,  # git checkout uv.lock
            _ok,  # _file_write_in_container (credential re-injection)
            ExecResult(exit_code=0, output="ok"),  # actual command retry
        ]
    )

    # Create a skill dir without pyproject.toml so venv build is skipped
    skill_dir = tmp_path / "skills" / "moneydb"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: moneydb\n---\nBody.\n")

    mgr = SandboxManager(runtime=runtime, data_dir=tmp_path, knowledge_dir=tmp_path)
    session_id = "sess-1"

    # Register callbacks — the activated-skills callback returns "moneydb",
    # and the reinject callback returns one file credential to write.
    mgr.set_activated_skills_callback(lambda sid: ["moneydb"])
    reinject_cb = AsyncMock(return_value=[("/tmp/creds/api_key.json", "secret-key-value")])
    mgr.set_reinject_credentials_callback(reinject_cb)

    await mgr.ensure_session(session_id)
    output = await mgr.exec_command(session_id, "run-moneydb")
    assert output.output == "ok"

    # Verify the reinject callback was called for the right session + skill
    reinject_cb.assert_awaited_once_with(session_id, "moneydb")

    # Verify the credential file was written into the new container via exec.
    # The 7th exec call (index 6) is the _file_write_in_container for the
    # credential — check that it targeted the correct workdir.
    write_call = runtime.exec.call_args_list[6]
    shell_cmd = write_call.args[1]
    assert "/tmp/creds/api_key.json" in shell_cmd
    assert base64.b64encode(b"secret-key-value").decode() in shell_cmd
    assert write_call.kwargs.get("workdir") == "/workspace/skills/moneydb"


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
                "network": {"domains": ["a.com"]},
                "credentials": [{"vault_path": "x/y", "description": "Test cred", "env_var": "FOO"}],
            }
        )
        assert cfg.network.domains == ["a.com"]
        assert len(cfg.credentials) == 1
        assert cfg.credentials[0].vault_path == "x/y"
        assert cfg.credentials[0].env_var == "FOO"


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
