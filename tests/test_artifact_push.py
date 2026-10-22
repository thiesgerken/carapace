from __future__ import annotations

import asyncio
import os
import subprocess
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

from carapace.git.store import GitStore

LIMIT = 10 * 1024 * 1024


@pytest.fixture
def sentinel_endpoint() -> Iterator[tuple[int, list[bytes]]]:
    requests: list[bytes] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            requests.append(self.rfile.read(int(self.headers["Content-Length"])))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"verdict":"allow"}')

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port, requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def _git(directory: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=directory, env=env, capture_output=True, text=True, check=False)


@pytest.mark.parametrize(
    ("extra_bytes", "separate_artifact", "accepted"),
    [(0, False, True), (1, False, False), (1, True, True)],
)
def test_push_limits_each_artifact_tree_before_sentinel(
    tmp_path: Path,
    sentinel_endpoint: tuple[int, list[bytes]],
    extra_bytes: int,
    separate_artifact: bool,
    accepted: bool,
) -> None:
    destination = tmp_path / "knowledge"
    asyncio.run(GitStore(destination).ensure_repo())
    source = tmp_path / "source"
    assert _git(tmp_path, "clone", str(destination), str(source)).returncode == 0
    assert _git(source, "config", "user.name", "Artifact test").returncode == 0
    assert _git(source, "config", "user.email", "artifact@example.test").returncode == 0
    artifact = source / "artifacts" / "quarterly report"
    artifact.mkdir(parents=True)
    (artifact / "index.html").write_bytes(b"x")
    (artifact / "assets").mkdir()
    (artifact / "assets" / "chart\tdata.bin").write_bytes(b"\0" * (LIMIT - 1))
    if extra_bytes:
        extra_dir = source / "artifacts" / "other" if separate_artifact else artifact
        extra_dir.mkdir(parents=True, exist_ok=True)
        (extra_dir / "extra.bin").write_bytes(b"x" * extra_bytes)
    assert _git(source, "add", "artifacts").returncode == 0
    assert _git(source, "commit", "-m", "Add artifact").returncode == 0
    port, requests = sentinel_endpoint
    result = _git(
        source,
        "push",
        "origin",
        "HEAD:main",
        env={
            **os.environ,
            "CARAPACE_API_PORT": str(port),
            "CARAPACE_SESSION_ID": "test",
            "CARAPACE_DEFAULT_BRANCH": "main",
        },
    )
    if accepted:
        assert result.returncode == 0, result.stderr
        assert len(requests) == 1
        assert (destination / "artifacts" / "quarterly report" / "index.html").is_file()
    else:
        assert result.returncode != 0
        assert "quarterly report" in result.stderr
        assert "10 MiB" in result.stderr
        assert requests == []
        assert not (destination / "artifacts").exists()
