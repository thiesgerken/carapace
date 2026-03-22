"""Tests for GitStore and GitHttpHandler."""

from __future__ import annotations

import base64
import os
import stat
from pathlib import Path

import pytest

from carapace.git.http import GitHttpHandler
from carapace.git.store import _PRE_RECEIVE_HOOK, GitStore

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


class TestGitHttpHandlerCgiConversion:
    """_parse_cgi_output response parsing."""

    def _handler(self) -> GitHttpHandler:
        return GitHttpHandler(
            knowledge_dir=Path("/tmp/knowledge"),
            default_branch="main",
        )

    def test_simple_200(self):
        h = self._handler()
        cgi = b"Content-Type: application/x-git\r\n\r\nbody-data"
        status, headers, body = h._parse_cgi_output(cgi)
        assert status == 200
        assert headers["Content-Type"] == "application/x-git"
        assert body == b"body-data"

    def test_explicit_status(self):
        h = self._handler()
        cgi = b"Status: 404 Not Found\r\nContent-Type: text/plain\r\n\r\nnope"
        status, headers, body = h._parse_cgi_output(cgi)
        assert status == 404
        assert body == b"nope"
        assert "Status" not in headers

    def test_lf_only_separator(self):
        h = self._handler()
        cgi = b"Content-Type: text/plain\n\nbody"
        status, _headers, body = h._parse_cgi_output(cgi)
        assert status == 200
        assert body == b"body"

    def test_no_separator_returns_500(self):
        h = self._handler()
        status, _headers, _body = h._parse_cgi_output(b"garbage without separator")
        assert status == 500


class TestGitHttpHandlerAuth:
    """_extract_basic_token and authenticate."""

    def test_valid_basic_credentials(self):
        creds = base64.b64encode(b"sess-1:my-token").decode()
        assert GitHttpHandler._extract_basic_credentials(f"Basic {creds}") == ("sess-1", "my-token")

    def test_no_password(self):
        creds = base64.b64encode(b"sess-1:").decode()
        assert GitHttpHandler._extract_basic_credentials(f"Basic {creds}") is None

    def test_no_username(self):
        creds = base64.b64encode(b":my-token").decode()
        assert GitHttpHandler._extract_basic_credentials(f"Basic {creds}") is None

    def test_non_basic_scheme(self):
        assert GitHttpHandler._extract_basic_credentials("Bearer xyz") is None

    def test_garbage(self):
        assert GitHttpHandler._extract_basic_credentials("not-valid") is None

    def test_authenticate_success(self):
        h = GitHttpHandler(
            knowledge_dir=Path("/tmp/knowledge"),
            default_branch="main",
            verify_session_token=lambda sid, tok: sid == "sess-1" and tok == "my-token",
        )
        creds = base64.b64encode(b"sess-1:my-token").decode()
        assert h.authenticate(f"Basic {creds}") == "sess-1"

    def test_authenticate_invalid_token(self):
        h = GitHttpHandler(
            knowledge_dir=Path("/tmp/knowledge"),
            default_branch="main",
            verify_session_token=lambda sid, tok: False,
        )
        creds = base64.b64encode(b"sess-1:bad-token").decode()
        assert h.authenticate(f"Basic {creds}") is None

    def test_authenticate_wrong_session(self):
        h = GitHttpHandler(
            knowledge_dir=Path("/tmp/knowledge"),
            default_branch="main",
            verify_session_token=lambda sid, tok: sid == "sess-1" and tok == "tok",
        )
        creds = base64.b64encode(b"sess-2:tok").decode()
        assert h.authenticate(f"Basic {creds}") is None

    def test_authenticate_no_header(self):
        h = GitHttpHandler(
            knowledge_dir=Path("/tmp/knowledge"),
            default_branch="main",
            verify_session_token=lambda sid, tok: True,
        )
        assert h.authenticate(None) is None

    def test_case_insensitive_scheme(self):
        creds = base64.b64encode(b"u:tok").decode()
        assert GitHttpHandler._extract_basic_credentials(f"basic {creds}") == ("u", "tok")


class TestGitHttpHandlerHandle:
    """Integration-level tests for the handle() method."""

    def _handler(self) -> GitHttpHandler:
        return GitHttpHandler(
            knowledge_dir=Path("/tmp/knowledge"),
            default_branch="main",
        )

    async def test_forbidden_path_returns_403(self):
        h = self._handler()

        status, _headers, _body = await h.handle(
            session_id="sess-1",
            method="GET",
            path="/git/etc/passwd",
            query_string="",
            content_type=None,
            body=b"",
        )
        assert status == 403

    async def test_allowed_path_without_dot_git(self):
        h = self._handler()

        # /git/knowledge/info/refs → PATH_INFO=/knowledge/info/refs → allowed
        # (will fail with 500 because no actual git repo, but should NOT be 403)
        status, _headers, _body = await h.handle(
            session_id="sess-1",
            method="GET",
            path="/git/knowledge/info/refs",
            query_string="service=git-upload-pack",
            content_type=None,
            body=b"",
        )
        assert status != 403
