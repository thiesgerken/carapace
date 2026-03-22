"""Tests for GitStore and GitHttpHandler."""

from __future__ import annotations

import asyncio
import base64
import os
import stat
from pathlib import Path

import pytest

from carapace.git_http import GitHttpHandler
from carapace.git_store import _PRE_RECEIVE_HOOK, GitStore

# ── Helpers ──────────────────────────────────────────────────────────


def _has_git() -> bool:
    """Return True if git CLI is available."""
    return os.system("git --version >/dev/null 2>&1") == 0


needs_git = pytest.mark.skipif(not _has_git(), reason="git not available")


# ── GitStore ─────────────────────────────────────────────────────────


class TestGitStoreParseAuthor:
    """_parse_author template substitution."""

    def test_default_template(self):
        store = GitStore(Path("/tmp"), author="Carapace Agent <%s>")
        name, email = store._parse_author("sess-123")
        assert name == "Carapace Agent"
        assert email == "sess-123"

    def test_custom_template(self):
        store = GitStore(Path("/tmp"), author="Bot <%s@example.com>")
        name, email = store._parse_author("abc")
        assert name == "Bot"
        assert email == "abc@example.com"

    def test_no_angle_brackets(self):
        store = GitStore(Path("/tmp"), author="plain-%s")
        name, email = store._parse_author("sid")
        assert name == "plain-sid"
        assert email == "sid@carapace"

    def test_server_default(self):
        store = GitStore(Path("/tmp"))
        name, email = store._parse_author("server")
        assert name == "Carapace Agent"
        assert email == "server"


@needs_git
class TestGitStoreEnsureRepo:
    """ensure_repo creates a valid Git repo with the pre-receive hook."""

    @pytest.fixture
    def repo_dir(self, tmp_path: Path) -> Path:
        return tmp_path / "knowledge"

    async def test_creates_repo(self, repo_dir: Path):
        store = GitStore(repo_dir, branch="main")
        await store.ensure_repo()

        assert (repo_dir / ".git").is_dir()
        assert (repo_dir / ".git" / "hooks" / "pre-receive").exists()

    async def test_hook_is_executable(self, repo_dir: Path):
        store = GitStore(repo_dir)
        await store.ensure_repo()

        hook = repo_dir / ".git" / "hooks" / "pre-receive"
        mode = hook.stat().st_mode
        assert mode & stat.S_IXUSR

    async def test_hook_content(self, repo_dir: Path):
        store = GitStore(repo_dir)
        await store.ensure_repo()

        hook = repo_dir / ".git" / "hooks" / "pre-receive"
        assert hook.read_text() == _PRE_RECEIVE_HOOK

    async def test_idempotent(self, repo_dir: Path):
        store = GitStore(repo_dir)
        await store.ensure_repo()
        await store.ensure_repo()  # second call should not fail

        assert (repo_dir / ".git").is_dir()

    async def test_update_instead_configured(self, repo_dir: Path):
        store = GitStore(repo_dir)
        await store.ensure_repo()

        _, out = await store._run("config", "receive.denyCurrentBranch")
        assert out == "updateInstead"


@needs_git
class TestGitStoreCommit:
    @pytest.fixture
    async def store(self, tmp_path: Path) -> GitStore:
        repo = tmp_path / "knowledge"
        s = GitStore(repo, branch="main")
        await s.ensure_repo()
        return s

    async def test_commit_new_file(self, store: GitStore):
        (store.repo_dir / "test.md").write_text("hello")
        result = await store.commit(["test.md"], "add test file")
        assert result is True

    async def test_commit_nothing_staged(self, store: GitStore):
        result = await store.commit([], "empty commit")
        assert result is False

    async def test_commit_no_changes(self, store: GitStore):
        (store.repo_dir / "test.md").write_text("hello")
        await store.commit(["test.md"], "first")
        # Same content, no changes
        result = await store.commit(["test.md"], "second")
        assert result is False

    async def test_has_commits(self, store: GitStore):
        assert not await store.has_commits()
        (store.repo_dir / "f.txt").write_text("x")
        await store.commit(["f.txt"], "init")
        assert await store.has_commits()


@needs_git
class TestGitStoreRemote:
    @pytest.fixture
    async def store(self, tmp_path: Path) -> GitStore:
        repo = tmp_path / "knowledge"
        s = GitStore(repo, branch="main")
        await s.ensure_repo()
        return s

    async def test_no_remote_initially(self, store: GitStore):
        assert not await store.has_remote()

    async def test_add_remote(self, store: GitStore):
        await store.add_remote("https://example.com/repo.git")
        assert await store.has_remote()

    async def test_add_remote_with_token(self, store: GitStore):
        await store.add_remote("https://example.com/repo.git", token="tok123")
        assert await store.has_remote()
        _, url = await store._run("remote", "get-url", "origin")
        assert "x-access-token:tok123@" in url

    async def test_update_remote(self, store: GitStore):
        await store.add_remote("https://old.com/repo.git")
        await store.add_remote("https://new.com/repo.git")
        _, url = await store._run("remote", "get-url", "origin")
        assert "new.com" in url

    async def test_pull_no_remote_fails(self, store: GitStore):
        with pytest.raises(RuntimeError, match="fetch failed"):
            await store.pull_from_remote()

    async def test_push_no_remote_does_not_raise(self, store: GitStore):
        # push logs a warning but does not raise
        await store.push_to_remote()


# ── GitHttpHandler ───────────────────────────────────────────────────


class TestGitHttpHandlerAuth:
    """_extract_basic_auth parsing."""

    def _handler(self) -> GitHttpHandler:
        return GitHttpHandler(
            knowledge_dir=Path("/tmp/knowledge"),
            default_branch="main",
            get_session_by_token=lambda t: "sess-1" if t == "valid-token" else None,
        )

    def test_valid_basic_auth(self):
        h = self._handler()
        creds = base64.b64encode(b"anything:valid-token").decode()
        headers = [f"Authorization: Basic {creds}".encode()]
        assert h._extract_basic_auth(headers) == "valid-token"

    def test_no_auth_header(self):
        h = self._handler()
        assert h._extract_basic_auth([]) is None

    def test_wrong_scheme(self):
        h = self._handler()
        headers = [b"Authorization: Bearer sometoken"]
        assert h._extract_basic_auth(headers) is None

    def test_empty_password(self):
        h = self._handler()
        creds = base64.b64encode(b"user:").decode()
        headers = [f"Authorization: Basic {creds}".encode()]
        assert h._extract_basic_auth(headers) is None

    def test_no_colon_in_decoded(self):
        h = self._handler()
        # No colon → partition returns empty password
        creds = base64.b64encode(b"justtoken").decode()
        headers = [f"Authorization: Basic {creds}".encode()]
        assert h._extract_basic_auth(headers) is None

    def test_case_insensitive_header(self):
        h = self._handler()
        creds = base64.b64encode(b"x:mytoken").decode()
        headers = [f"AUTHORIZATION: Basic {creds}".encode()]
        assert h._extract_basic_auth(headers) == "mytoken"

    def test_multiple_headers(self):
        h = self._handler()
        creds = base64.b64encode(b"x:tok").decode()
        headers = [b"Content-Type: text/plain", f"Authorization: Basic {creds}".encode()]
        assert h._extract_basic_auth(headers) == "tok"


class TestGitHttpHandlerCgiConversion:
    """_cgi_to_http response parsing."""

    def _handler(self) -> GitHttpHandler:
        return GitHttpHandler(
            knowledge_dir=Path("/tmp/knowledge"),
            default_branch="main",
            get_session_by_token=lambda t: None,
        )

    def test_simple_200(self):
        h = self._handler()
        cgi = b"Content-Type: application/x-git\r\n\r\nbody-data"
        result = h._cgi_to_http(cgi)
        assert result.startswith(b"HTTP/1.1 200 OK\r\n")
        assert result.endswith(b"body-data")

    def test_explicit_status(self):
        h = self._handler()
        cgi = b"Status: 404 Not Found\r\nContent-Type: text/plain\r\n\r\nnope"
        result = h._cgi_to_http(cgi)
        assert result.startswith(b"HTTP/1.1 404 Not Found\r\n")
        assert b"nope" in result
        # Status header should be stripped from response headers
        assert b"Status:" not in result.split(b"\r\n\r\n")[0]

    def test_lf_only_separator(self):
        h = self._handler()
        cgi = b"Content-Type: text/plain\n\nbody"
        result = h._cgi_to_http(cgi)
        assert b"200 OK" in result
        assert result.endswith(b"body")

    def test_no_separator_returns_500(self):
        h = self._handler()
        result = h._cgi_to_http(b"garbage without separator")
        assert b"500" in result


class TestGitHttpHandlerGetHeader:
    def test_found(self):
        headers = [b"Content-Type: application/json", b"Accept: */*"]
        assert GitHttpHandler._get_header(headers, b"content-type") == "application/json"

    def test_not_found(self):
        assert GitHttpHandler._get_header([], b"content-type") is None

    def test_case_insensitive(self):
        headers = [b"CONTENT-TYPE: text/html"]
        assert GitHttpHandler._get_header(headers, b"content-type") == "text/html"


class TestGitHttpHandlerHandle:
    """Integration-level tests for the handle() method using mock streams."""

    def _handler(self, token_map: dict[str, str] | None = None) -> GitHttpHandler:
        mapping = token_map or {"valid-tok": "sess-1"}
        return GitHttpHandler(
            knowledge_dir=Path("/tmp/knowledge"),
            default_branch="main",
            get_session_by_token=lambda t: mapping.get(t),
        )

    def _make_writer(self) -> asyncio.StreamWriter:
        writer = AsyncStreamWriter()
        return writer  # type: ignore[return-value]

    async def test_unauthenticated_returns_401(self):
        h = self._handler()
        writer = self._make_writer()
        reader = asyncio.StreamReader()

        await h.handle(
            reader,
            writer,
            method="GET",
            path="/git/knowledge.git/info/refs",
            query_string="service=git-upload-pack",
            raw_headers=[],
            body=b"",
        )
        assert b"401" in writer.data  # type: ignore[attr-defined]

    async def test_invalid_token_returns_401(self):
        h = self._handler()
        writer = self._make_writer()
        reader = asyncio.StreamReader()

        creds = base64.b64encode(b"x:wrong-token").decode()
        headers = [f"Authorization: Basic {creds}".encode()]

        await h.handle(
            reader,
            writer,
            method="GET",
            path="/git/knowledge.git/info/refs",
            query_string="",
            raw_headers=headers,
            body=b"",
        )
        assert b"401" in writer.data  # type: ignore[attr-defined]

    async def test_forbidden_path_returns_403(self):
        h = self._handler()
        writer = self._make_writer()
        reader = asyncio.StreamReader()

        creds = base64.b64encode(b"x:valid-tok").decode()
        headers = [f"Authorization: Basic {creds}".encode()]

        # Try to access a different repo under the parent dir
        await h.handle(
            reader,
            writer,
            method="GET",
            path="/git/etc/passwd",
            query_string="",
            raw_headers=headers,
            body=b"",
        )
        assert b"403" in writer.data  # type: ignore[attr-defined]

    async def test_allowed_path_without_dot_git(self):
        h = self._handler()
        writer = self._make_writer()
        reader = asyncio.StreamReader()

        creds = base64.b64encode(b"x:valid-tok").decode()
        headers = [f"Authorization: Basic {creds}".encode()]

        # /git/knowledge/info/refs → PATH_INFO=/knowledge/info/refs → allowed
        # (will fail with 500 because no actual git repo, but should NOT be 403)
        await h.handle(
            reader,
            writer,
            method="GET",
            path="/git/knowledge/info/refs",
            query_string="service=git-upload-pack",
            raw_headers=headers,
            body=b"",
        )
        assert b"403" not in writer.data  # type: ignore[attr-defined]


class AsyncStreamWriter:
    """Minimal mock for asyncio.StreamWriter used in handler tests."""

    def __init__(self):
        self.data = b""

    def write(self, data: bytes):
        self.data += data

    async def drain(self):
        pass
