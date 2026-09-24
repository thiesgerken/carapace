from __future__ import annotations

import asyncio
import os
import re
import socket
from datetime import UTC, datetime
from pathlib import Path

from loguru import logger

from ..models.git import FileCommit

# Record separator for the ``git log`` walk in last_commits, keeping records
# distinguishable from the NUL-separated paths. Git does accept a subject containing
# this byte, so split only where a commit header follows: otherwise a single
# `git commit -m "$(printf 'a\001b')"` splits its own record, every path in it is
# dropped, and those entries silently show an older commit.
_LOG_RECORD_SEP = "%x01"
_LOG_RECORD_SPLIT = re.compile(r"\x01(?=[0-9a-f]{40}\x00)")


def _parse_last_commits(out: str, prefix: str) -> dict[str, FileCommit]:
    """Fold a ``git log -z --name-only`` walk into one commit per immediate child."""
    found: dict[str, FileCommit] = {}
    for record in _LOG_RECORD_SPLIT.split(out):
        if not record:
            continue
        fields = record.split("\x00")
        if len(fields) < 4:
            continue
        full, short, timestamp, subject, *paths = fields
        if not full or not short or not timestamp.isdigit():
            continue
        commit = FileCommit(
            hash=full,
            short=short,
            subject=subject,
            committed_at=datetime.fromtimestamp(int(timestamp), tz=UTC),
        )
        for raw in paths:
            path = raw.strip("\n")
            if not path or not path.startswith(prefix):
                continue
            # Fold e.g. "skills/weather/src/x.py" to the "weather" row under "skills/".
            child = path[len(prefix) :].split("/", 1)[0]
            # Commits arrive newest first, so the first one seen wins.
            found.setdefault(child, commit)
    return found


# Pre-receive hook script — gates every push through the sentinel.
# CARAPACE_SESSION_ID, CARAPACE_DEFAULT_BRANCH, and CARAPACE_API_PORT
# are set by the Git HTTP handler.
_PRE_RECEIVE_HOOK = """\
#!/bin/sh
# Pre-receive hook — sentinel evaluation of incoming pushes
set -e

if ! command -v jq >/dev/null 2>&1; then
    echo "DENIED: jq is required but not installed" >&2
    exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
    echo "DENIED: curl is required but not installed" >&2
    exit 1
fi

NULL_SHA="0000000000000000000000000000000000000000"
EMPTY_TREE=$(git hash-object -t tree /dev/null)
EVALUATED=0

while read old_sha new_sha ref; do
    EVALUATED=$((EVALUATED + 1))

    if [ "$old_sha" = "$NULL_SHA" ]; then
        # New branch: show all commits and diff against empty tree
        changes=$(git log --oneline "$new_sha" 2>/dev/null)
        diff=$(git diff "$EMPTY_TREE" "$new_sha" 2>/dev/null)
    else
        changes=$(git log --oneline "$old_sha..$new_sha" 2>/dev/null)
        diff=$(git diff "$old_sha" "$new_sha" 2>/dev/null)
    fi

    branch=$(echo "$ref" | sed 's|refs/heads/||')
    is_default="false"
    if [ "$branch" = "$CARAPACE_DEFAULT_BRANCH" ]; then
        is_default="true"
    fi

    SENTINEL_URL="http://127.0.0.1:${CARAPACE_API_PORT:-8320}/internal/sentinel/evaluate-push"
    payload=$(jq -n \\
        --arg sid "$CARAPACE_SESSION_ID" \\
        --arg ref "$ref" \\
        --argjson def "$is_default" \\
        --arg commits "$changes" \\
        --arg diff "$diff" \\
        '{session_id: $sid, ref: $ref, is_default_branch: $def, commits: $commits, diff: $diff}')
    # No --max-time: the sentinel may escalate to the user for approval,
    # which can take arbitrarily long. --connect-timeout still catches a
    # down server quickly.
    result=$(curl -s --fail --connect-timeout 10 -X POST "$SENTINEL_URL" \\
        -H "Content-Type: application/json" \\
        -d "$payload") || {
        echo "DENIED: failed to reach sentinel API" >&2
        exit 1
    }

    verdict=$(echo "$result" | jq -r '.verdict')

    if [ "$verdict" != "allow" ]; then
        reason=$(echo "$result" | jq -r '.reason')
        echo "DENIED by sentinel: $reason" >&2
        exit 1
    fi
done

if [ "$EVALUATED" -eq 0 ]; then
    echo "DENIED: no refs received for evaluation" >&2
    exit 1
fi
"""


def _log_subjects_as_bullets(subjects_stdout: str) -> str:
    lines = [s.strip() for s in subjects_stdout.split("\n") if s.strip()]
    return "\n".join(f"• {line}" for line in lines)


class GitStore:
    """Thin wrapper around Git CLI for managing the knowledge repo.

    Uses ``asyncio.create_subprocess_exec`` for non-blocking operations.
    No ``gitpython`` dependency — the ``git`` binary is always available.
    """

    _LOCAL_BRANCH = "main"

    def __init__(
        self,
        repo_dir: Path,
        *,
        remote_branch: str = "main",
        author: str = "carapace <carapace@%h>",
    ) -> None:
        self.repo_dir = repo_dir
        self.remote_branch = remote_branch
        self.author_template = author
        self._index_lock = asyncio.Lock()
        self._remote_configured = False

    @property
    def remote_configured(self) -> bool:
        return self._remote_configured

    async def _run(self, *args: str, cwd: Path | None = None) -> tuple[int, str]:
        """Run a git command and return ``(exit_code, combined_output)``."""
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=cwd or self.repo_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await proc.communicate()
        code = proc.returncode or 0
        out = stdout.decode(errors="replace").strip()
        err = stderr.decode(errors="replace").strip()
        if err:
            log = logger.warning if code != 0 else logger.debug
            log(f"git {args[0]}: {err}")
        # Combine stdout + stderr so callers can inspect error messages.
        combined = f"{out}\n{err}".strip() if err else out
        return code, combined

    async def ensure_repo(self) -> None:
        """Initialise the Git repo if it doesn't exist yet and install hooks."""
        self.repo_dir.mkdir(parents=True, exist_ok=True)

        # Mark the repo directory as safe so git doesn't reject it when the
        # current user differs from the directory owner (e.g. bind-mounted
        # host dirs in Docker).
        await self._run("config", "--global", "--replace-all", "safe.directory", str(self.repo_dir))

        git_dir = self.repo_dir / ".git"
        if not git_dir.exists():
            code, out = await self._run("init", "-b", self._LOCAL_BRANCH)
            if code != 0:
                raise RuntimeError(f"git init failed: {out}")
            logger.info(f"initialized knowledge repo at {self.repo_dir}")

            # Set default git config for server-side commits
            author_name, author_email = self._parse_author("server")
            await self._run("config", "user.name", author_name)
            await self._run("config", "user.email", author_email)

            # Enable receive.denyCurrentBranch so pushes to a non-bare repo
            # update the working tree automatically.
            await self._run("config", "receive.denyCurrentBranch", "updateInstead")
        else:
            # Ensure updateInstead is set even on existing repos
            await self._run("config", "receive.denyCurrentBranch", "updateInstead")

        self._install_hook()

    def _install_hook(self) -> None:
        """Install or update the pre-receive hook."""
        hooks_dir = self.repo_dir / ".git" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        hook_path = hooks_dir / "pre-receive"
        hook_path.write_text(_PRE_RECEIVE_HOOK, encoding="utf-8")
        hook_path.chmod(0o755)
        logger.debug("Installed pre-receive hook")

    def _parse_author(self, session_id: str) -> tuple[str, str]:
        """Parse the author template into (name, email).

        Supported placeholders: ``%s`` → *session_id*, ``%h`` → hostname.
        """
        filled = self.author_template.replace("%s", session_id).replace("%h", socket.gethostname())
        # Expected format: "Name <email>"
        if "<" in filled and filled.endswith(">"):
            name, _, email = filled.rpartition("<")
            return name.strip(), email.rstrip(">").strip()
        return filled, f"{session_id}@carapace"

    async def commit(self, paths: list[str], message: str, *, session_id: str = "server") -> bool:
        """Stage the given paths and commit. Returns True if a commit was made."""
        async with self._index_lock:
            for p in paths:
                await self._run("add", "--", p)

            return await self._commit_staged_paths(message, session_id=session_id)

    async def commit_removals(self, paths: list[str], message: str, *, session_id: str = "server") -> bool:
        """Stage tracked path removals and commit. Returns True if a commit was made."""
        async with self._index_lock:
            for p in paths:
                await self._run("rm", "--ignore-unmatch", "--", p)

            return await self._commit_staged_paths(message, session_id=session_id)

    async def _commit_staged_paths(self, message: str, *, session_id: str = "server") -> bool:
        """Create a commit from the current index if anything is staged."""

        # Check if there's anything staged
        code, _ = await self._run("diff", "--cached", "--quiet")
        if code == 0:
            # Nothing to commit
            return False

        author_name, author_email = self._parse_author(session_id)
        code, out = await self._run(
            "commit",
            "-m",
            message,
            "--author",
            f"{author_name} <{author_email}>",
        )
        if code != 0:
            raise RuntimeError(f"git commit failed: {out}")

        logger.info(f"Knowledge commit: {message}")
        return True

    # ------------------------------------------------------------------
    # Optional external remote management
    # ------------------------------------------------------------------

    async def add_remote(self, url: str, token: str | None = None) -> None:
        """Add or update the ``origin`` remote."""
        # Build authenticated URL if token provided
        if token and "://" in url:
            scheme, rest = url.split("://", 1)
            authed_url = f"{scheme}://x-access-token:{token}@{rest}"
        else:
            authed_url = url

        code, _ = await self._run("remote", "get-url", "origin")
        if code == 0:
            await self._run("remote", "set-url", "origin", authed_url)
        else:
            await self._run("remote", "add", "origin", authed_url)
        self._remote_configured = True
        logger.info(f"Git remote origin set to {url}")

    async def get_remote_url(self) -> str | None:
        """Return the current ``origin`` URL if configured."""
        code, out = await self._run("remote", "get-url", "origin")
        if code != 0:
            return None
        return out or None

    async def restore_remote(self, url: str) -> None:
        """Restore the ``origin`` remote from a previously captured URL."""
        code, _ = await self._run("remote", "get-url", "origin")
        if code == 0:
            await self._run("remote", "set-url", "origin", url)
        else:
            await self._run("remote", "add", "origin", url)
        self._remote_configured = True
        logger.info("Git remote origin restored")

    async def remove_remote(self) -> None:
        """Remove the ``origin`` remote when upstream sync is disabled."""
        code, _ = await self._run("remote", "get-url", "origin")
        if code == 0:
            await self._run("remote", "remove", "origin")
            logger.info("Git remote origin removed")
        self._remote_configured = False

    async def push_to_remote(self) -> bool:
        """Push the local branch to the configured remote branch. Returns success."""
        refspec = f"{self._LOCAL_BRANCH}:{self.remote_branch}"
        logger.info(f"Pushing {refspec} to origin")
        code, out = await self._run("push", "origin", refspec)
        if code != 0:
            logger.warning(f"git push to remote failed: {out}")
            return False
        logger.info("Pushed to external remote")
        return True

    async def pull_from_remote(self) -> str:
        """Fetch + fast-forward merge from external remote.

        If the local repo has no commits yet (fresh init), the remote branch
        is adopted directly via ``git reset``.  Otherwise a fast-forward
        merge is attempted.

        Returns a summary string. Raises ``RuntimeError`` on merge conflict
        or fetch failure.
        """
        logger.info(f"Fetching from origin/{self.remote_branch}")
        code, out = await self._run("fetch", "origin", self.remote_branch)
        if code != 0:
            raise RuntimeError(f"git fetch failed: {out}")

        # Check whether the remote branch actually has any commits.
        code, _ = await self._run("rev-parse", "--verify", f"origin/{self.remote_branch}")
        if code != 0:
            logger.info("Remote branch has no commits yet — nothing to pull")
            return "Remote branch is empty."

        if not await self.has_commits():
            # Empty local repo — adopt the remote branch wholesale.
            logger.info(f"Local repo is empty, resetting to origin/{self.remote_branch}")
            code, out = await self._run("reset", "--hard", f"origin/{self.remote_branch}")
            if code != 0:
                raise RuntimeError(f"git reset to origin/{self.remote_branch} failed: {out}")
            code, short = await self._run("rev-parse", "--short", "HEAD")
            tip = short.strip() if code == 0 else "?"
            code, subjects = await self._run("log", "-10", "--format=%s")
            lead = f"Loaded the remote knowledge branch into this workspace. Your copy is now at revision {tip}."
            if code == 0 and subjects.strip():
                bullets = _log_subjects_as_bullets(subjects)
                return f"{lead}\n\nLatest commits on that branch (newest first):\n{bullets}"
            return lead

        logger.info("Merging from remote")
        code, head_before = await self._run("rev-parse", "HEAD")
        if code != 0:
            raise RuntimeError(f"git rev-parse HEAD failed: {head_before}")
        head_before = head_before.strip()
        code, out = await self._run("merge", "--allow-unrelated-histories", "--no-edit", f"origin/{self.remote_branch}")
        if code != 0:
            raise RuntimeError(
                f"Merge conflict in knowledge repo. Resolve manually in {self.repo_dir} and restart.\n{out}"
            )

        code, head_after = await self._run("rev-parse", "HEAD")
        if code != 0:
            raise RuntimeError(f"git rev-parse HEAD failed after merge: {head_after}")
        head_after = head_after.strip()
        if head_before == head_after:
            return "Already up to date."

        code_s, short = await self._run("rev-parse", "--short", "HEAD")
        tip = short.strip() if code_s == 0 else head_after[:7]
        code_n, n_out = await self._run("rev-list", "--count", f"{head_before}..{head_after}")
        n = int(n_out.strip()) if code_n == 0 and n_out.strip().isdigit() else 0
        if n == 1:
            lead = "Pulled 1 new commit from the remote."
        elif n > 1:
            lead = f"Pulled {n} new commits from the remote."
        else:
            lead = "Pulled updates from the remote."

        code, subjects = await self._run(
            "log",
            "--reverse",
            "--format=%s",
            f"{head_before}..{head_after}",
        )
        tail = f"Your knowledge repo is now at revision {tip}."
        if code != 0 or not subjects.strip():
            return f"{lead} {tail}"
        bullets = _log_subjects_as_bullets(subjects)
        return f"{lead} {tail}\n\nWhat changed:\n{bullets}"

    async def remote_status(self) -> tuple[int, int]:
        """Fetch the remote and return ``(ahead, behind)`` for local vs remote.

        ``ahead`` = local commits not on the remote branch; ``behind`` = remote
        commits not in the local branch. Returns ``(0, 0)`` when no remote is
        configured, the remote branch is empty, or the local repo has no commits.
        """
        if not self._remote_configured:
            return 0, 0

        code, _ = await self._run("fetch", "origin", self.remote_branch)
        if code != 0:
            raise RuntimeError("git fetch from origin failed")

        code, _ = await self._run("rev-parse", "--verify", f"origin/{self.remote_branch}")
        if code != 0:
            # Remote branch has no commits yet — everything local is "ahead".
            if not await self.has_commits():
                return 0, 0
            code_a, a_out = await self._run("rev-list", "--count", "HEAD")
            ahead = int(a_out.strip()) if code_a == 0 and a_out.strip().isdigit() else 0
            return ahead, 0

        if not await self.has_commits():
            code_b, b_out = await self._run("rev-list", "--count", f"origin/{self.remote_branch}")
            behind = int(b_out.strip()) if code_b == 0 and b_out.strip().isdigit() else 0
            return 0, behind

        code, out = await self._run(
            "rev-list",
            "--left-right",
            "--count",
            f"{self._LOCAL_BRANCH}...origin/{self.remote_branch}",
        )
        if code != 0:
            raise RuntimeError(f"git rev-list failed: {out}")
        parts = out.split()
        if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
            return 0, 0
        return int(parts[0]), int(parts[1])

    async def has_remote(self) -> bool:
        """Check if an ``origin`` remote is configured."""
        code, _ = await self._run("remote", "get-url", "origin")
        return code == 0

    async def has_commits(self) -> bool:
        """Check if the repo has any commits."""
        code, _ = await self._run("rev-parse", "HEAD")
        return code == 0

    async def head_sha(self) -> str | None:
        """Return the full object ID of HEAD, or ``None`` if there are no commits."""
        code, out = await self._run("rev-parse", "HEAD")
        revision = out.strip()
        return revision if code == 0 and re.fullmatch(r"[0-9a-f]{40,64}", revision) else None

    async def head_revision(self) -> tuple[str, str] | None:
        """Return ``(short_hash, subject)`` of HEAD, or ``None`` if there are no commits."""
        code, out = await self._run("log", "-1", "--format=%h%x00%s")
        if code != 0 or not out:
            return None
        short, _, subject = out.partition("\0")
        return short.strip(), subject.strip()

    async def last_commits(self, relative_dir: str, *, limit: int = 2000) -> dict[str, FileCommit]:
        """Map each immediate child of *relative_dir* to the newest commit touching it.

        One ``git log`` walk for the whole directory rather than a process per entry.
        Paths are reported relative to the repo root, so each is folded back to the
        child of *relative_dir* that contains it — that is what a directory row shows.

        ponytail: only the newest *limit* commits touching the directory are walked, so
        a file untouched for longer reports nothing and the row falls back to its mtime.
        The cap bounds the cost on a large history (~0.1s for a 1k-commit walk); stream
        the walk with an early exit once every entry is covered if that stops being
        enough.
        """
        prefix = f"{relative_dir.strip('/')}/" if relative_dir.strip("/") else ""
        args = [
            "log",
            f"-n{limit}",
            "-z",
            f"--format={_LOG_RECORD_SEP}%H%x00%h%x00%ct%x00%s",
            "--name-only",
            "HEAD",
        ]
        if prefix:
            args += ["--", prefix.rstrip("/")]
        code, out = await self._run(*args)
        if code != 0 or not out:
            return {}
        return _parse_last_commits(out, prefix)
