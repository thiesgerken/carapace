"""Tests for GitStore and GitHttpHandler."""

from __future__ import annotations

import base64
import os
import stat
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from carapace.git.http import GitHttpHandler
from carapace.git.store import _PRE_RECEIVE_HOOK, GitStore, _parse_last_commits

# ── Helpers ──────────────────────────────────────────────────────────


def _has_git() -> bool:
    """Return True if git CLI is available."""
    return os.system("git --version >/dev/null 2>&1") == 0


needs_git = pytest.mark.skipif(not _has_git(), reason="git not available")


# ── GitStore ─────────────────────────────────────────────────────────


class TestGitStoreParseAuthor:
    """_parse_author template substitution."""

    def test_default_template(self):
        store = GitStore(Path("/tmp"))
        name, email = store._parse_author("sess-123")
        import socket

        expected_host = socket.gethostname()
        assert name == "carapace"
        assert email == f"carapace@{expected_host}"

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
        import socket

        expected_host = socket.gethostname()
        assert name == "carapace"
        assert email == f"carapace@{expected_host}"

    def test_hostname_placeholder(self):
        store = GitStore(Path("/tmp"), author="Agent <%s@%h>")
        name, email = store._parse_author("sess-1")
        import socket

        assert name == "Agent"
        assert email == f"sess-1@{socket.gethostname()}"


@needs_git
class TestGitStoreEnsureRepo:
    """ensure_repo creates a valid Git repo with the pre-receive hook."""

    @pytest.fixture
    def repo_dir(self, tmp_path: Path) -> Path:
        return tmp_path / "knowledge"

    async def test_creates_repo(self, repo_dir: Path):
        store = GitStore(repo_dir, remote_branch="main")
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
class TestGitStoreHeadRevision:
    @pytest.fixture
    async def store(self, tmp_path: Path) -> GitStore:
        s = GitStore(tmp_path / "knowledge", remote_branch="main")
        await s.ensure_repo()
        return s

    async def test_none_without_commits(self, store: GitStore):
        assert await store.head_sha() is None
        assert await store.head_revision() is None

    async def test_returns_short_hash_and_subject(self, store: GitStore):
        (store.repo_dir / "test.md").write_text("hello")
        await store.commit(["test.md"], "add test file")

        revision = await store.head_revision()

        assert revision is not None
        short, subject = revision
        assert subject == "add test file"
        _, full = await store._run("rev-parse", "HEAD")
        assert await store.head_sha() == full
        assert full.startswith(short)

    async def test_subject_with_null_safe_characters(self, store: GitStore):
        (store.repo_dir / "test.md").write_text("hello")
        await store.commit(["test.md"], "\U0001f4be session: add 2026-06-01-21-07-0062199d")

        revision = await store.head_revision()

        assert revision is not None
        assert revision[1] == "\U0001f4be session: add 2026-06-01-21-07-0062199d"


@needs_git
class TestGitStoreCommit:
    @pytest.fixture
    async def store(self, tmp_path: Path) -> GitStore:
        repo = tmp_path / "knowledge"
        s = GitStore(repo, remote_branch="main")
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

    async def test_commit_does_not_stage_unrelated_deletions(self, store: GitStore):
        tracked = store.repo_dir / "tracked.txt"
        unrelated = store.repo_dir / "unrelated.txt"
        tracked.write_text("one")
        unrelated.write_text("two")
        await store.commit(["tracked.txt", "unrelated.txt"], "initial")

        tracked.write_text("updated")
        unrelated.unlink()

        result = await store.commit(["tracked.txt"], "update tracked")

        assert result is True
        assert unrelated.exists() is False
        code, _ = await store._run("ls-files", "--error-unmatch", "unrelated.txt")
        assert code == 0

    async def test_commit_removals_stages_deleted_file(self, store: GitStore):
        target = store.repo_dir / "gone.txt"
        target.write_text("bye")
        await store.commit(["gone.txt"], "initial")

        target.unlink()

        result = await store.commit_removals(["gone.txt"], "remove file")

        assert result is True
        code, _ = await store._run("ls-files", "--error-unmatch", "gone.txt")
        assert code != 0

    async def test_commit_raises_on_git_failure(self, store: GitStore):
        (store.repo_dir / "test.md").write_text("hello")

        async def fake_run(*args: str, **kwargs) -> tuple[int, str]:
            if args[0] == "add":
                return 0, ""
            if args[0] == "diff":
                return 1, ""
            if args[0] == "commit":
                return 1, "boom"
            raise AssertionError(f"unexpected git command: {args!r}")

        store._run = AsyncMock(side_effect=fake_run)

        with pytest.raises(RuntimeError, match="git commit failed: boom"):
            await store.commit(["test.md"], "add test file")

    async def test_commit_does_not_push_when_remote_is_configured(self, store: GitStore):
        (store.repo_dir / "test.md").write_text("hello")
        store.has_remote = AsyncMock(return_value=True)
        store.push_to_remote = AsyncMock()

        result = await store.commit(["test.md"], "add test file")

        assert result is True
        store.push_to_remote.assert_not_awaited()

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
        s = GitStore(repo, remote_branch="main")
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

    async def test_remove_remote(self, store: GitStore):
        await store.add_remote("https://example.com/repo.git", token="tok123")
        assert store.remote_configured is True

        await store.remove_remote()

        assert store.remote_configured is False
        assert not await store.has_remote()

    async def test_pull_no_remote_fails(self, store: GitStore):
        with pytest.raises(RuntimeError, match="fetch failed"):
            await store.pull_from_remote()

    async def test_push_no_remote_does_not_raise(self, store: GitStore):
        # push logs a warning but does not raise
        await store.push_to_remote()

    async def test_pull_twice_reports_already_up_to_date_second_time(self, tmp_path: Path) -> None:
        """Second pull with no new remote commits must not repeat the prior log summary."""
        bare = tmp_path / "origin.git"
        bare.mkdir()
        subprocess.run(["git", "init", "--bare", "-b", "main"], cwd=bare, check=True)

        seed = tmp_path / "seed"
        seed.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=seed, check=True)
        subprocess.run(["git", "config", "user.email", "seed@test"], cwd=seed, check=True)
        subprocess.run(["git", "config", "user.name", "seed"], cwd=seed, check=True)
        (seed / "a.txt").write_text("x")
        subprocess.run(["git", "add", "a.txt"], cwd=seed, check=True)
        subprocess.run(["git", "commit", "-m", "seed commit"], cwd=seed, check=True)
        subprocess.run(["git", "remote", "add", "origin", str(bare.resolve())], cwd=seed, check=True)
        subprocess.run(["git", "push", "-u", "origin", "main"], cwd=seed, check=True)

        knowledge = tmp_path / "knowledge"
        store = GitStore(knowledge, remote_branch="main")
        await store.ensure_repo()
        await store.add_remote(str(bare.resolve()))

        first = await store.pull_from_remote()
        assert "revision" in first
        assert "seed commit" in first
        second = await store.pull_from_remote()
        assert second == "Already up to date."


@needs_git
class TestGitStoreRemoteStatus:
    async def _seeded_bare(self, tmp_path: Path) -> Path:
        """Create a bare remote with one commit on main and return its path."""
        bare = tmp_path / "origin.git"
        bare.mkdir()
        subprocess.run(["git", "init", "--bare", "-b", "main"], cwd=bare, check=True)
        seed = tmp_path / "seed"
        seed.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=seed, check=True)
        subprocess.run(["git", "config", "user.email", "seed@test"], cwd=seed, check=True)
        subprocess.run(["git", "config", "user.name", "seed"], cwd=seed, check=True)
        (seed / "a.txt").write_text("x")
        subprocess.run(["git", "add", "a.txt"], cwd=seed, check=True)
        subprocess.run(["git", "commit", "-m", "seed commit"], cwd=seed, check=True)
        subprocess.run(["git", "remote", "add", "origin", str(bare.resolve())], cwd=seed, check=True)
        subprocess.run(["git", "push", "-u", "origin", "main"], cwd=seed, check=True)
        return bare

    async def test_no_remote_returns_zero(self, tmp_path: Path) -> None:
        store = GitStore(tmp_path / "knowledge", remote_branch="main")
        await store.ensure_repo()
        assert await store.remote_status() == (0, 0)

    async def test_in_sync_after_pull(self, tmp_path: Path) -> None:
        bare = await self._seeded_bare(tmp_path)
        store = GitStore(tmp_path / "knowledge", remote_branch="main")
        await store.ensure_repo()
        await store.add_remote(str(bare.resolve()))
        await store.pull_from_remote()
        assert await store.remote_status() == (0, 0)

    async def test_ahead_after_local_commit(self, tmp_path: Path) -> None:
        bare = await self._seeded_bare(tmp_path)
        repo = tmp_path / "knowledge"
        store = GitStore(repo, remote_branch="main")
        await store.ensure_repo()
        await store.add_remote(str(bare.resolve()))
        await store.pull_from_remote()
        (repo / "local.txt").write_text("y")
        await store.commit(["local.txt"], "local change")
        ahead, behind = await store.remote_status()
        assert (ahead, behind) == (1, 0)

    async def test_behind_after_remote_commit(self, tmp_path: Path) -> None:
        bare = await self._seeded_bare(tmp_path)
        repo = tmp_path / "knowledge"
        store = GitStore(repo, remote_branch="main")
        await store.ensure_repo()
        await store.add_remote(str(bare.resolve()))
        await store.pull_from_remote()
        # Add a new commit to the remote via a separate clone.
        worker = tmp_path / "worker"
        subprocess.run(["git", "clone", str(bare.resolve()), str(worker)], check=True)
        subprocess.run(["git", "config", "user.email", "w@test"], cwd=worker, check=True)
        subprocess.run(["git", "config", "user.name", "w"], cwd=worker, check=True)
        (worker / "b.txt").write_text("z")
        subprocess.run(["git", "add", "b.txt"], cwd=worker, check=True)
        subprocess.run(["git", "commit", "-m", "remote change"], cwd=worker, check=True)
        subprocess.run(["git", "push", "origin", "main"], cwd=worker, check=True)
        ahead, behind = await store.remote_status()
        assert (ahead, behind) == (0, 1)


# ── GitHttpHandler ───────────────────────────────────────────────────


class TestGitHttpHandlerCgiConversion:
    """_parse_cgi_output response parsing."""

    def _handler(self) -> GitHttpHandler:
        return GitHttpHandler(
            knowledge_root=Path("/tmp"),
            owner_for_session=lambda _session_id: "knowledge",
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
            knowledge_root=Path("/tmp"),
            owner_for_session=lambda _session_id: "knowledge",
            default_branch="main",
            verify_session_token=lambda sid, tok: sid == "sess-1" and tok == "my-token",
        )
        creds = base64.b64encode(b"sess-1:my-token").decode()
        assert h.authenticate(f"Basic {creds}") == "sess-1"

    def test_authenticate_invalid_token(self):
        h = GitHttpHandler(
            knowledge_root=Path("/tmp"),
            owner_for_session=lambda _session_id: "knowledge",
            default_branch="main",
            verify_session_token=lambda sid, tok: False,
        )
        creds = base64.b64encode(b"sess-1:bad-token").decode()
        assert h.authenticate(f"Basic {creds}") is None

    def test_authenticate_wrong_session(self):
        h = GitHttpHandler(
            knowledge_root=Path("/tmp"),
            owner_for_session=lambda _session_id: "knowledge",
            default_branch="main",
            verify_session_token=lambda sid, tok: sid == "sess-1" and tok == "tok",
        )
        creds = base64.b64encode(b"sess-2:tok").decode()
        assert h.authenticate(f"Basic {creds}") is None

    def test_authenticate_no_header(self):
        h = GitHttpHandler(
            knowledge_root=Path("/tmp"),
            owner_for_session=lambda _session_id: "knowledge",
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
            knowledge_root=Path("/tmp"),
            owner_for_session=lambda _session_id: "knowledge",
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

    async def test_path_traversal_returns_403(self):
        h = self._handler()

        status, _headers, _body = await h.handle(
            session_id="sess-1",
            method="GET",
            path="/git/knowledge/../otherrepo/info/refs",
            query_string="",
            content_type=None,
            body=b"",
        )
        assert status == 403

    async def test_backslash_in_path_returns_403(self):
        h = self._handler()

        status, _headers, _body = await h.handle(
            session_id="sess-1",
            method="GET",
            path="/git/knowledge\\evil",
            query_string="",
            content_type=None,
            body=b"",
        )
        assert status == 403

    async def test_cross_user_repo_path_returns_403(self):
        h = GitHttpHandler(
            knowledge_root=Path("/tmp/knowledges"),
            owner_for_session=lambda session_id: "thies" if session_id == "sess-1" else "ada",
            default_branch="main",
        )

        status, _headers, _body = await h.handle(
            session_id="sess-1",
            method="GET",
            path="/git/ada/info/refs",
            query_string="service=git-upload-pack",
            content_type=None,
            body=b"",
        )

        assert status == 403


class TestParseLastCommits:
    """Folding a ``git log -z --name-only`` walk into one commit per child."""

    def _record(self, short: str, ts: int, subject: str, paths: list[str]) -> str:
        full = short * 5 + short[:5]  # 45 chars, stands in for a 40-char hash
        return "\x01" + "\x00".join([full[:40], short, str(ts), subject, *paths])

    def test_newest_commit_per_child_wins(self):
        out = self._record("aaa1111", 1_780_000_100, "newer", ["skills/weather/SKILL.md"]) + self._record(
            "bbb2222", 1_780_000_000, "older", ["skills/weather/SKILL.md", "skills/web/SKILL.md"]
        )

        found = _parse_last_commits(out, "skills/")

        assert found["weather"].short == "aaa1111"
        assert found["weather"].subject == "newer"
        assert found["web"].short == "bbb2222"

    def test_nested_paths_fold_to_the_child_directory(self):
        out = self._record("aaa1111", 1_780_000_000, "deep", ["skills/weather/src/fetch/api.py"])
        assert list(_parse_last_commits(out, "skills/")) == ["weather"]

    def test_root_listing_uses_empty_prefix(self):
        out = self._record("aaa1111", 1_780_000_000, "root", ["SOUL.md", "skills/weather/SKILL.md"])
        assert sorted(_parse_last_commits(out, "")) == ["SOUL.md", "skills"]

    def test_a_record_separator_in_the_subject_does_not_split_the_record(self):
        """Git accepts \\x01 in a subject. Splitting on it blindly drops every path in
        that commit, so those entries silently fall back to an older one."""
        out = self._record("aaa1111", 1_780_000_000, "pwn\x01deadbeef", ["skills/weather/SKILL.md"])

        found = _parse_last_commits(out, "skills/")

        assert found["weather"].subject == "pwn\x01deadbeef"

    def test_paths_outside_the_prefix_are_ignored(self):
        out = self._record("aaa1111", 1_780_000_000, "other", ["sessions/2026/06/x/conversation.json"])
        assert _parse_last_commits(out, "skills/") == {}

    def test_merge_commits_without_paths_are_skipped(self):
        out = self._record("aaa1111", 1_780_000_100, "merge", []) + self._record(
            "bbb2222", 1_780_000_000, "real", ["skills/weather/SKILL.md"]
        )
        assert _parse_last_commits(out, "skills/")["weather"].short == "bbb2222"

    def test_committed_at_is_utc(self):
        out = self._record("aaa1111", 1_780_000_000, "s", ["skills/weather/SKILL.md"])
        assert _parse_last_commits(out, "skills/")["weather"].committed_at == datetime.fromtimestamp(
            1_780_000_000, tz=UTC
        )

    def test_malformed_records_are_skipped(self):
        out = "\x01truncated" + self._record("aaa1111", 1_780_000_000, "ok", ["skills/web/SKILL.md"])
        assert list(_parse_last_commits(out, "skills/")) == ["web"]


@needs_git
class TestGitStoreLastCommits:
    async def test_reports_newest_commit_per_entry(self, tmp_path: Path):
        store = GitStore(tmp_path / "repo", remote_branch="main")
        await store.ensure_repo()
        (store.repo_dir / "notes").mkdir()
        (store.repo_dir / "notes" / "a.md").write_text("a")
        await store.commit(["notes/a.md"], "add a")
        (store.repo_dir / "notes" / "b.md").write_text("b")
        await store.commit(["notes/b.md"], "add b")

        found = await store.last_commits("notes")

        assert found["a.md"].subject == "add a"
        assert found["b.md"].subject == "add b"
        assert await store.last_commits("") == {"notes": found["b.md"]}

    async def test_empty_repo_returns_nothing(self, tmp_path: Path):
        store = GitStore(tmp_path / "repo", remote_branch="main")
        await store.ensure_repo()
        assert await store.last_commits("") == {}


def test_parse_last_commits_keeps_full_and_short_hash():
    full = "a" * 40
    out = "\x01" + "\x00".join([full, "aaa1111", "1780000000", "s", "skills/web/SKILL.md"])

    commit = _parse_last_commits(out, "skills/")["web"]

    assert (commit.hash, commit.short) == (full, "aaa1111")
