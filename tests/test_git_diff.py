from __future__ import annotations

import pytest

from carapace.git.diff import touched_paths


@pytest.mark.parametrize(
    ("diff", "expected"),
    [
        ("--- /dev/null\n+++ b/artifacts/report/index.html", {"artifacts/report/index.html"}),
        ("--- a/artifacts/report/index.html\n+++ /dev/null", {"artifacts/report/index.html"}),
        ("--- a/b/notes.md\n+++ b/b/notes.md", {"b/notes.md"}),
        (
            'diff --git "a/artifacts/quarterly report/chart\\tdata.png" '
            '"b/artifacts/quarterly report/chart\\tdata.png"\nBinary files differ',
            {"artifacts/quarterly report/chart\tdata.png"},
        ),
        (
            "diff --git a/artifacts/a b/chart.png b/artifacts/a b/chart.png\nBinary files differ",
            {"artifacts/a b/chart.png"},
        ),
        (
            '--- "a/artifacts/\\303\\274ber/index.html"\n+++ "b/artifacts/\\303\\274ber/index.html"',
            {"artifacts/über/index.html"},
        ),
        (
            "rename from notes/report.html\nrename to artifacts/report/index.html",
            {"notes/report.html", "artifacts/report/index.html"},
        ),
        (
            'copy from "notes/quarterly report.html"\ncopy to "artifacts/quarterly report/index.html"',
            {"notes/quarterly report.html", "artifacts/quarterly report/index.html"},
        ),
        ("--- a/notes.md\n+++ b/notes.md\n+artifacts/report/index.html", {"notes.md"}),
    ],
)
def test_touched_paths_covers_changes_and_preserves_filenames(diff: str, expected: set[str]) -> None:
    assert touched_paths(diff) == expected
