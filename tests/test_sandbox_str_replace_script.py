"""Tests for sandbox ``SANDBOX_STR_REPLACE_SCRIPT`` behavior."""

from __future__ import annotations

import base64
import subprocess
import sys
from pathlib import Path

from carapace.sandbox.container_scripts import SANDBOX_STR_REPLACE_SCRIPT


def _run_script(path: Path, old: str, new: str, *, replace_all: bool) -> subprocess.CompletedProcess[str]:
    old_b64 = base64.b64encode(old.encode()).decode()
    new_b64 = base64.b64encode(new.encode()).decode()
    return subprocess.run(
        [
            sys.executable,
            "-c",
            SANDBOX_STR_REPLACE_SCRIPT,
            str(path),
            old_b64,
            new_b64,
            "1" if replace_all else "0",
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_single_replace_reports_original_line(tmp_path: Path) -> None:
    path = tmp_path / "sample.txt"
    path.write_text("a\nneedle\nc\n", encoding="utf-8")

    result = _run_script(path, "needle", "x", replace_all=False)

    assert result.returncode == 0
    assert result.stdout.strip() == f"Replaced 1 occurrence in {path} at line 2."
    assert path.read_text(encoding="utf-8") == "a\nx\nc\n"


def test_single_replace_fails_with_multiple_occurrences_and_line_numbers(tmp_path: Path) -> None:
    path = tmp_path / "sample.txt"
    path.write_text("needle\na\nneedle\n", encoding="utf-8")

    result = _run_script(path, "needle", "x", replace_all=False)

    assert result.returncode == 1
    assert "appears 2 times" in result.stdout
    assert "lines 1,3" in result.stdout
    assert path.read_text(encoding="utf-8") == "needle\na\nneedle\n"


def test_replace_all_reports_all_line_numbers(tmp_path: Path) -> None:
    path = tmp_path / "sample.txt"
    path.write_text("needle\na\nneedle\nneedle\n", encoding="utf-8")

    result = _run_script(path, "needle", "x", replace_all=True)

    assert result.returncode == 0
    assert result.stdout.strip() == f"Replaced 3 occurrences in {path} at lines 1,3,4."
    assert path.read_text(encoding="utf-8") == "x\na\nx\nx\n"


def test_no_match_error(tmp_path: Path) -> None:
    path = tmp_path / "sample.txt"
    path.write_text("a\nb\n", encoding="utf-8")

    result = _run_script(path, "needle", "x", replace_all=True)

    assert result.returncode == 1
    assert result.stdout.strip() == f"Error: old_string not found in {path}."


def test_empty_old_string_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "sample.txt"
    path.write_text("a\n", encoding="utf-8")

    result = _run_script(path, "", "x", replace_all=True)

    assert result.returncode == 1
    assert result.stdout.strip() == "Error: old_string must not be empty."
