"""Artifacts: self-contained HTML pages under ``artifacts/<slug>/index.html`` in a knowledge repo."""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

from .knowledge import contained_target


def is_artifact_slug(slug: str) -> bool:
    return bool(slug) and slug not in {".", ".."} and "/" not in slug and "\\" not in slug


def artifact_index(root: Path, slug: str) -> Path | None:
    """Return the artifact's ``index.html`` inside the already-resolved *root*, or None if it has none.

    The slug directory itself must not be a symlink: an artifact is identified by where it lives.
    """
    if not is_artifact_slug(slug):
        return None
    directory = root / "artifacts" / slug
    if contained_target(directory, root) != directory or not directory.is_dir():
        return None
    index = contained_target(directory / "index.html", directory)
    return index if index is not None and index.is_file() else None


class _ArtifactTitleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_title = False
        self.finished = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title" and not self.finished:
            self.in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"title", "head"}:
            self.in_title = False
            self.finished = True

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.parts.append(data)


def artifact_title(index: Path) -> str | None:
    parser = _ArtifactTitleParser()
    with index.open(encoding="utf-8", errors="replace") as document:
        while chunk := document.read(4096):
            parser.feed(chunk)
            if parser.finished:
                break
    return " ".join("".join(parser.parts).split()) or None
