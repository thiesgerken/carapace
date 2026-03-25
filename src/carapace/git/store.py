from __future__ import annotations

import asyncio
from pathlib import Path

from loguru import logger

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
    result=$(curl -s --fail --max-time 30 -X POST "$SENTINEL_URL" \\
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


class GitStore:
    """Thin wrapper around Git CLI for managing the knowledge repo.

    Uses ``asyncio.create_subprocess_exec`` for non-blocking operations.
    No ``gitpython`` dependency — the ``git`` binary is always available.
    """

    def __init__(
        self,
        repo_dir: Path,
        *,
        branch: str = "main",
        author: str = "Carapace Session %s <%s@carapace.local>",
    ) -> None:
        self.repo_dir = repo_dir
        self.branch = branch
        self.author_template = author

    async def _run(self, *args: str, cwd: Path | None = None) -> tuple[int, str]:
        """Run a git command and return ``(exit_code, combined_output)``."""
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=cwd or self.repo_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()
        return proc.returncode or 0, stdout.decode(errors="replace").strip()

    async def ensure_repo(self) -> None:
        """Initialise the Git repo if it doesn't exist yet and install hooks."""
        self.repo_dir.mkdir(parents=True, exist_ok=True)

        git_dir = self.repo_dir / ".git"
        if not git_dir.exists():
            code, out = await self._run("init", "-b", self.branch)
            if code != 0:
                raise RuntimeError(f"git init failed: {out}")
            logger.info(f"Initialised knowledge repo at {self.repo_dir}")

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
        """Parse the author template into (name, email)."""
        filled = self.author_template.replace("%s", session_id)
        # Expected format: "Name <email>"
        if "<" in filled and filled.endswith(">"):
            name, _, email = filled.rpartition("<")
            return name.strip(), email.rstrip(">").strip()
        return filled, f"{session_id}@carapace"

    async def commit(self, paths: list[str], message: str, *, session_id: str = "server") -> bool:
        """Stage the given paths and commit. Returns True if a commit was made."""
        for p in paths:
            await self._run("add", "--", p)

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
            logger.warning(f"git commit failed: {out}")
            return False

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
        logger.info(f"Git remote origin set to {url}")

    async def push_to_remote(self) -> None:
        """Push the current branch to the external remote."""
        code, out = await self._run("push", "origin", self.branch)
        if code != 0:
            logger.warning(f"git push to remote failed: {out}")
        else:
            logger.info("Pushed to external remote")

    async def pull_from_remote(self) -> str:
        """Fetch + fast-forward merge from external remote.

        Returns a summary string. Raises ``RuntimeError`` on merge conflict.
        """
        code, out = await self._run("fetch", "origin", self.branch)
        if code != 0:
            raise RuntimeError(f"git fetch failed: {out}")

        code, out = await self._run("merge", "--ff-only", f"origin/{self.branch}")
        if code != 0:
            raise RuntimeError(
                f"Merge conflict in knowledge repo. Resolve manually in {self.repo_dir} and restart.\n{out}"
            )

        # Summarise what changed
        code, summary = await self._run("log", "--oneline", "HEAD@{1}..HEAD")
        if code != 0 or not summary:
            return "Already up to date."
        return summary

    async def has_remote(self) -> bool:
        """Check if an ``origin`` remote is configured."""
        code, _ = await self._run("remote", "get-url", "origin")
        return code == 0

    async def has_commits(self) -> bool:
        """Check if the repo has any commits."""
        code, _ = await self._run("rev-parse", "HEAD")
        return code == 0
