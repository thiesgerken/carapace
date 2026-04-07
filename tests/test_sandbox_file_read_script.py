"""Tests for the sandbox inline ``FILE_READ_SCRIPT`` (host Python, same as container logic)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from carapace.sandbox.manager import (
    FILE_READ_SCRIPT,
    MAX_READ_OUTPUT_CHARS,
    SANDBOX_READ_BODY_SEPARATOR,
)


def _run_script(
    path: Path, offset: int = 0, limit: int = 100, cap: int | None = None
) -> subprocess.CompletedProcess[str]:
    cap = MAX_READ_OUTPUT_CHARS if cap is None else cap
    return subprocess.run(
        [sys.executable, "-c", FILE_READ_SCRIPT, str(path), str(offset), str(limit), str(cap)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_text_truncation_stops_at_char_cap_with_accurate_line_count(tmp_path: Path) -> None:
    line = "hello\n"
    n_lines = 80
    p = tmp_path / "t.txt"
    p.write_text(line * n_lines, encoding="utf-8")
    cap = 25 * len(line) - 1
    r = _run_script(p, offset=0, limit=100, cap=cap)
    assert r.returncode == 0
    out = r.stdout
    assert SANDBOX_READ_BODY_SEPARATOR in out
    assert "Output is truncated at" in out
    assert "Reading lines 1 through 24." in out or "Reading lines 1 through 25." in out
    assert "Reading lines 1 through 100." not in out


def test_partial_last_line_shows_truncation_suffix(tmp_path: Path) -> None:
    p = tmp_path / "wide.txt"
    body = "x" * 5000
    p.write_text(body + "\n", encoding="utf-8")
    cap = 120
    r = _run_script(p, offset=0, limit=5, cap=cap)
    assert r.returncode == 0
    assert SANDBOX_READ_BODY_SEPARATOR in r.stdout
    assert "truncated:" in r.stdout
    assert "line has 5001 characters" in r.stdout
    assert "The last line is incomplete." in r.stdout


def test_binary_file_metadata_only(tmp_path: Path) -> None:
    p = tmp_path / "b.bin"
    p.write_bytes(b"\x00\x01\x02")
    r = _run_script(p)
    assert r.returncode == 0
    assert "Binary file" in r.stdout
    assert "Size: 3 bytes" in r.stdout
    assert "File description:" in r.stdout
    assert "\x00" not in r.stdout or "content not shown" in r.stdout


def test_directory_lists_names(tmp_path: Path) -> None:
    d = tmp_path / "d"
    d.mkdir()
    (d / "b").write_text("b", encoding="utf-8")
    (d / "a").write_text("a", encoding="utf-8")
    r = _run_script(d)
    assert r.returncode == 0
    assert r.stdout.startswith("::DIR::\n")
    assert "a\nb\n" in r.stdout or "a" in r.stdout


def test_offset_past_eof(tmp_path: Path) -> None:
    p = tmp_path / "small.txt"
    p.write_text("a\nb\nc\n", encoding="utf-8")
    r = _run_script(p, offset=50, limit=10)
    assert r.returncode == 0
    assert SANDBOX_READ_BODY_SEPARATOR in r.stdout
    assert "No lines in this window" in r.stdout
    assert "after skipping 50" in r.stdout
