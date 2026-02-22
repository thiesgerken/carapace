"""Tests for the sandbox proxy: domain matching, allowlists, and carapace.yaml parsing."""

from __future__ import annotations

import base64
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from carapace.models import SkillCarapaceConfig
from carapace.sandbox.proxy import ProxyServer, domain_matches
from carapace.sandbox.runtime import ContainerRuntime

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


# ── ProxyServer._check_domain ───────────────────────────────────────


class TestProxyCheckDomain:
    def _make_proxy(self, domains: set[str]) -> ProxyServer:
        return ProxyServer(
            get_session_by_token=lambda tok: "sess-1",
            get_allowed_domains=lambda sid: domains,
        )

    def test_allowed_exact(self):
        proxy = self._make_proxy({"pypi.org"})
        assert proxy._check_domain("sess-1", "pypi.org")

    def test_denied(self):
        proxy = self._make_proxy({"pypi.org"})
        assert not proxy._check_domain("sess-1", "evil.com")

    def test_allowed_wildcard(self):
        proxy = self._make_proxy({"*.googleapis.com"})
        assert proxy._check_domain("sess-1", "storage.googleapis.com")

    def test_empty_allowlist(self):
        proxy = self._make_proxy(set())
        assert not proxy._check_domain("sess-1", "anything.com")

    def test_case_insensitive(self):
        proxy = self._make_proxy({"PyPI.org"})
        assert proxy._check_domain("sess-1", "pypi.org")


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
        from carapace.sandbox.manager import SandboxManager

        runtime = MagicMock(spec=ContainerRuntime)
        return SandboxManager(runtime=runtime, data_dir=tmp_path)

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
        env = mgr._build_proxy_env("my-secret-token", "http://172.18.0.2:3128")
        assert env["HTTP_PROXY"] == "http://my-secret-token@172.18.0.2:3128"
        assert env["HTTPS_PROXY"] == "http://my-secret-token@172.18.0.2:3128"
        assert "172.18.0.2" in env["NO_PROXY"]

    def test_no_proxy_env_when_empty(self, tmp_path: Path):
        mgr = self._make_manager(tmp_path)
        assert mgr._build_proxy_env("tok", "") == {}

    def test_token_lookup(self, tmp_path: Path):
        mgr = self._make_manager(tmp_path)
        mgr._token_to_session["abc123"] = "sess-1"
        assert mgr.get_session_by_token("abc123") == "sess-1"
        assert mgr.get_session_by_token("wrong") is None

    def test_cleanup_clears_tokens(self, tmp_path: Path):
        mgr = self._make_manager(tmp_path)
        mgr._token_to_session["tok"] = "sess-1"
        mgr._session_tokens["sess-1"] = "tok"
        mgr._cleanup_tracking("sess-1")
        assert mgr.get_session_by_token("tok") is None


# ── carapace.yaml parsing ───────────────────────────────────────────


class TestCarapaceYamlParsing:
    def test_parse_network_domains(self, tmp_path: Path):
        from carapace.skills import SkillRegistry

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
        from carapace.skills import SkillRegistry

        skill_dir = tmp_path / "plain"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("Body.\n")

        registry = SkillRegistry(tmp_path)
        assert registry.get_carapace_config("plain") is None

    def test_invalid_carapace_yaml(self, tmp_path: Path):
        from carapace.skills import SkillRegistry

        skill_dir = tmp_path / "bad"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("Body.\n")
        (skill_dir / "carapace.yaml").write_text(": invalid yaml {{{\n")

        registry = SkillRegistry(tmp_path)
        assert registry.get_carapace_config("bad") is None

    def test_empty_network_section(self, tmp_path: Path):
        from carapace.skills import SkillRegistry

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
                "credentials": [{"name": "FOO", "vault_path": "x/y"}],
            }
        )
        assert cfg.network.domains == ["a.com"]
        assert cfg.credentials == [{"name": "FOO", "vault_path": "x/y"}]


# ── Proxy token extraction ───────────────────────────────────────────


class TestProxyTokenExtraction:
    def test_basic_auth_token(self):
        encoded = base64.b64encode(b"my-token:").decode()
        header = f"Proxy-Authorization: Basic {encoded}\r\n".encode()
        assert ProxyServer._extract_proxy_token(header) == "my-token"

    def test_no_password(self):
        encoded = base64.b64encode(b"tok123:").decode()
        header = f"Proxy-Authorization: Basic {encoded}\r\n".encode()
        assert ProxyServer._extract_proxy_token(header) == "tok123"

    def test_non_basic_scheme(self):
        header = b"Proxy-Authorization: Bearer abc\r\n"
        assert ProxyServer._extract_proxy_token(header) is None

    def test_garbage(self):
        assert ProxyServer._extract_proxy_token(b"garbage\r\n") is None

    def test_empty_username(self):
        encoded = base64.b64encode(b":password").decode()
        header = f"Proxy-Authorization: Basic {encoded}\r\n".encode()
        assert ProxyServer._extract_proxy_token(header) is None


# ── ProxyServer start/stop ──────────────────────────────────────────


@pytest.mark.anyio
async def test_proxy_start_stop():
    proxy = ProxyServer(
        get_session_by_token=lambda tok: None,
        get_allowed_domains=lambda sid: set(),
        host="127.0.0.1",
        port=0,  # OS-assigned port
    )
    await proxy.start()
    assert proxy._server is not None
    assert proxy._server.is_serving()
    await proxy.stop()
