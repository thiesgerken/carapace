from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "scripts" / "memory_eval.py"


def _archive(path: Path, session_id: str, last_active: str, history: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    session = {
        "session_id": session_id,
        "title": f"title {session_id}",
        "created_at": "2026-09-01T08:00:00+00:00",
        "last_active": last_active,
    }
    path.write_text(json.dumps({"schema_version": 1, "session": session, "archive": {}, "history": history}))


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, check=False)


def _sessions(tmp_path: Path) -> Path:
    chat = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]
    longer = [*chat, {"role": "user", "content": "more"}, {"role": "assistant", "content": "sure"}]
    _archive(tmp_path / "a" / "s1" / "conversation.json", "s1", "2026-09-01T09:00:00+00:00", chat)
    # A newer copy of s1 elsewhere (another sandbox clone) wins over the older one.
    _archive(tmp_path / "b" / "s1" / "conversation.json", "s1", "2026-09-02T09:00:00+00:00", longer)
    _archive(tmp_path / "a" / "s2" / "conversation.json", "s2", "2026-09-01T09:00:00+00:00", [])
    return tmp_path


def test_dry_run_prints_estimates_without_calls(tmp_path: Path) -> None:
    result = _run(str(_sessions(tmp_path)))

    assert result.returncode == 0, result.stderr
    assert "2 sessions, 1 without a user message (skipped)" in result.stdout
    s1_row = next(line for line in result.stdout.splitlines() if line.startswith("s1 "))
    assert s1_row.split()[1] == "4"  # events of the newer copy
    assert "est. max cost: total $" in result.stdout
    assert "input share alone: total $" in result.stdout
    assert "usage:" not in result.stdout


def test_test_model_runs_the_call_path(tmp_path: Path) -> None:
    result = _run("--test-model", str(_sessions(tmp_path)))

    assert result.returncode == 0, result.stderr
    assert '"abstract": "Test extraction."' in result.stdout
    assert result.stdout.count("usage: ") == 1
