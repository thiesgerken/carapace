"""Run standalone as Git's pre-receive hook using only the standard library.

Do not import carapace: the installed hook runs outside the package and must not
load the server or its dependencies.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from http.client import HTTPConnection, HTTPException


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], encoding="utf-8", errors="replace").rstrip("\n")


def _oversized_artifacts(commit: str) -> list[str]:
    sizes: dict[str, int] = {}
    # Inspect the incoming tree; NUL delimiters keep filenames from altering totals.
    for entry in _git("ls-tree", "-r", "-l", "-z", commit, "--", "artifacts/").split("\0"):
        if not entry:
            continue
        metadata, path = entry.split("\t", 1)
        _mode, object_type, _sha, byte_size = metadata.split()
        if object_type != "blob":
            continue
        artifact, separator, _relative_path = path.removeprefix("artifacts/").partition("/")
        if separator:
            sizes[artifact] = sizes.get(artifact, 0) + int(byte_size)
    return [artifact for artifact in sorted(sizes) if sizes[artifact] > 10 * 1024 * 1024]


def main() -> int:
    null_sha = "0" * 40
    evaluated = False
    # The Git HTTP handler supplies the session, default branch, and API port.
    port = int(os.environ.get("CARAPACE_API_PORT", "8320"))

    for line in sys.stdin:
        old_sha, new_sha, ref = line.split()
        evaluated = True
        if new_sha != null_sha:
            oversized = _oversized_artifacts(new_sha)
            for artifact in oversized:
                print(f"DENIED: artifact {artifact} exceeds the 10 MiB directory limit", file=sys.stderr)
            if oversized:
                return 1
        if old_sha == null_sha:
            changes = _git("log", "--oneline", new_sha)
            empty_tree = _git("hash-object", "-t", "tree", os.devnull)
            diff = _git("diff", empty_tree, new_sha)
        else:
            changes = _git("log", "--oneline", f"{old_sha}..{new_sha}")
            diff = _git("diff", old_sha, new_sha)

        payload = {
            "session_id": os.environ["CARAPACE_SESSION_ID"],
            "ref": ref,
            "is_default_branch": ref.removeprefix("refs/heads/") == os.environ["CARAPACE_DEFAULT_BRANCH"],
            "commits": changes,
            "diff": diff,
        }
        connection = HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            connection.connect()
            # Approval may take arbitrarily long; only connecting has a deadline.
            assert connection.sock is not None
            connection.sock.settimeout(None)
            connection.request(
                "POST",
                "/internal/sentinel/evaluate-push",
                json.dumps(payload).encode(),
                {"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            if response.status != 200:
                print(f"DENIED: sentinel API returned HTTP {response.status}", file=sys.stderr)
                return 1
            result = json.load(response)
        except (OSError, HTTPException):
            print("DENIED: failed to reach sentinel API", file=sys.stderr)
            return 1
        finally:
            connection.close()

        if result["verdict"] != "allow":
            print(f"DENIED by sentinel: {result['reason']}", file=sys.stderr)
            return 1

    if not evaluated:
        print("DENIED: no refs received for evaluation", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
