"""Tests for the knowledge repo browse endpoint helpers."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import HTTPException

from carapace.server.knowledge import (
    MAX_INLINE_TEXT_BYTES,
    build_entry,
    list_dir,
    read_text_content,
    resolve_target,
    resolve_vault_status,
    session_archive_entry,
)


def _make_repo(tmp_path: Path) -> Path:
    root = tmp_path / "knowledge"
    (root / ".git").mkdir(parents=True)
    (root / ".git" / "config").write_text("secret")
    (root / "skills" / "weather").mkdir(parents=True)
    (root / "skills" / "weather" / "SKILL.md").write_text("---\nname: weather\n---\n")
    (root / "SOUL.md").write_text("# soul")
    return root


def test_resolve_target_root(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    assert resolve_target(root, "") == root.resolve()
    assert resolve_target(root, "skills/weather") == (root / "skills" / "weather").resolve()


def test_resolve_target_rejects_traversal(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    (tmp_path / "outside.txt").write_text("nope")
    for bad in ("../outside.txt", "..", "skills/../../outside.txt", "/etc/passwd"):
        with pytest.raises(HTTPException) as exc:
            resolve_target(root, bad)
        assert exc.value.status_code == 404


def test_resolve_target_rejects_git_dir(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    for bad in (".git", ".git/config"):
        with pytest.raises(HTTPException) as exc:
            resolve_target(root, bad)
        assert exc.value.status_code == 404


def test_resolve_target_rejects_symlink_escape(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    (tmp_path / "outside.txt").write_text("nope")
    (root / "link.txt").symlink_to(tmp_path / "outside.txt")
    with pytest.raises(HTTPException):
        resolve_target(root, "link.txt")


def test_list_dir_hides_git_and_sorts_dirs_first(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    listing = list_dir(root, root.resolve())
    assert listing.path == ""
    assert [(e.name, e.type) for e in listing.entries] == [("skills", "dir"), ("SOUL.md", "file")]
    assert listing.entries[1].size == len("# soul")


def test_list_dir_subdir_path(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    listing = list_dir(root, (root / "skills" / "weather").resolve())
    assert listing.path == "skills/weather"
    assert [e.name for e in listing.entries] == ["SKILL.md"]


def _write(tmp_path: Path, name: str, data: bytes) -> Path:
    target = tmp_path / name
    target.write_bytes(data)
    return target


@pytest.mark.parametrize(
    "name,data",
    [
        (".gitignore", b"__pycache__/\n*.pyc\n"),  # no extension to guess from
        ("Dockerfile", b"FROM python:3.12\n"),
        ("notes.md", "# über\n".encode()),  # multi-byte UTF-8
        ("empty", b""),
    ],
)
def test_read_text_content_returns_text(tmp_path: Path, name: str, data: bytes) -> None:
    target = _write(tmp_path, name, data)
    assert read_text_content(target, len(data)) == data.decode("utf-8")


@pytest.mark.parametrize(
    "name,data",
    [
        ("logo.png", b"\x89PNG\r\n\x1a\n\x00\x00binary"),  # NUL byte
        ("data.bin", b"\xff\xfe\xfd\xfc"),  # invalid UTF-8
    ],
)
def test_read_text_content_rejects_binary(tmp_path: Path, name: str, data: bytes) -> None:
    target = _write(tmp_path, name, data)
    assert read_text_content(target, len(data)) is None


def test_read_text_content_rejects_oversized(tmp_path: Path) -> None:
    target = _write(tmp_path, "big.txt", b"x")
    assert read_text_content(target, MAX_INLINE_TEXT_BYTES + 1) is None


def _archive(root: Path, session_id: str, payload: object) -> Path:
    directory = root / "sessions" / "2026" / "06" / session_id
    directory.mkdir(parents=True)
    (directory / "conversation.json").write_text(json.dumps(payload))
    return directory


def test_session_archive_entry_reads_title(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    directory = _archive(
        root,
        "2026-06-01-21-07-0062199d",
        {"session": {"session_id": "2026-06-01-21-07-0062199d", "title": "Weather skill"}},
    )
    assert session_archive_entry(directory, root.resolve()) == ("Weather skill", "2026-06-01-21-07-0062199d")


def test_session_archive_entry_untitled_falls_back_to_dir_name(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    directory = _archive(root, "2026-06-02-10-00-abcdef01", {"session": {"title": "   "}})
    assert session_archive_entry(directory, root.resolve()) == (None, "2026-06-02-10-00-abcdef01")


def test_session_archive_entry_ignores_plain_dir(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    assert session_archive_entry((root / "skills" / "weather").resolve(), root.resolve()) is None


def test_session_archive_entry_tolerates_corrupt_json(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    directory = root / "sessions" / "2026" / "06" / "broken"
    directory.mkdir(parents=True)
    (directory / "conversation.json").write_text("{not json")
    assert session_archive_entry(directory, root.resolve()) is None


def test_build_entry_tags_session_dirs(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    directory = _archive(
        root,
        "2026-06-03-08-30-11223344",
        {"session": {"session_id": "2026-06-03-08-30-11223344", "title": "Groceries"}},
    )

    entry = build_entry(directory, root.resolve())

    assert (entry.kind, entry.label, entry.session_id) == ("session", "Groceries", "2026-06-03-08-30-11223344")
    assert build_entry(root / "skills", root.resolve()).kind is None
    assert build_entry(root / "SOUL.md", root.resolve()).kind is None


def test_list_dir_inlines_skill_doc(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    skill = root / "skills" / "weather"

    listing = list_dir(root, skill.resolve())

    assert (listing.kind, listing.doc_name) == ("skill", "SKILL.md")
    # Frontmatter-only SKILL.md: nothing left in the body once it is stripped.
    assert listing.doc == ""
    assert listing.skill is not None and listing.skill.name == "weather"


def test_list_dir_without_skill_doc_has_no_kind(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    listing = list_dir(root, (root / "skills").resolve())
    assert (listing.kind, listing.doc_name, listing.doc) == (None, None, None)


_SKILL_MD = """---
name: weather
description: Forecast via Home Assistant
metadata:
  carapace:
    network:
      domains:
        - homeassistant.example
    credentials:
      - vault_path: vault/abc
        env_var: HA_TOKEN
    commands:
      - name: weather
        command: uv run weather
    mcp:
      - name: hass
        url: https://homeassistant.example/api/mcp
        auth:
          type: bearer
          vault_path: vault/abc
---

# Weather

Body prose.
"""


def _skill(root: Path, name: str, text: str) -> Path:
    directory = root / "skills" / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text(text)
    return directory


def test_list_dir_strips_frontmatter_into_skill(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    _skill(root, "weather", _SKILL_MD)

    listing = list_dir(root, (root / "skills" / "weather").resolve())

    assert listing.kind == "skill"
    assert listing.doc == "# Weather\n\nBody prose.\n"
    assert listing.skill is not None
    assert (listing.skill.name, listing.skill.description) == ("weather", "Forecast via Home Assistant")
    carapace = listing.skill.carapace
    assert carapace is not None
    assert carapace.network.domains == ["homeassistant.example"]
    assert [c.name for c in carapace.commands] == ["weather"]
    assert [c.env_var for c in carapace.credentials] == ["HA_TOKEN"]
    assert [(s.name, s.url) for s in carapace.mcp] == [("hass", "https://homeassistant.example/api/mcp")]
    assert carapace.mcp[0].auth is not None and carapace.mcp[0].auth.vault_path == "vault/abc"


def test_disabled_skill_remains_browsable_and_readable(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    text = (
        "---\nname: private-search\ndescription: Private search\n"
        "metadata:\n  carapace:\n    disabled: true\n---\nEditable instructions.\n"
    )
    directory = _skill(root, "private-search", text)

    assert "private-search" in [entry.name for entry in list_dir(root, root / "skills").entries]
    listing = list_dir(root, directory.resolve())
    assert listing.doc == "Editable instructions.\n"
    assert listing.skill is not None
    assert listing.skill.carapace is not None and listing.skill.carapace.disabled
    skill_md = resolve_target(root, "skills/private-search/SKILL.md")
    assert read_text_content(skill_md, skill_md.stat().st_size) == text


def test_list_dir_skill_without_carapace_metadata(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    _skill(root, "plain", "---\nname: plain\ndescription: No metadata\n---\n\nBody.\n")

    listing = list_dir(root, (root / "skills" / "plain").resolve())

    assert listing.skill is not None
    assert listing.skill.carapace is None
    assert listing.doc == "Body.\n"


def test_list_dir_skill_with_invalid_carapace_keeps_prose(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    # commands must be a list of {name, command}; a bare string fails validation.
    _skill(root, "broken", "---\nname: broken\nmetadata:\n  carapace:\n    commands: nope\n---\n\nBody.\n")

    listing = list_dir(root, (root / "skills" / "broken").resolve())

    assert listing.skill is not None
    assert listing.skill.carapace is None
    assert listing.doc == "Body.\n"


def test_list_dir_skill_without_frontmatter_falls_back_to_dir_name(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    _skill(root, "bare", "# Bare skill\n")

    listing = list_dir(root, (root / "skills" / "bare").resolve())

    assert listing.skill is not None
    assert (listing.skill.name, listing.skill.description) == ("bare", "")
    assert listing.doc == "# Bare skill\n"


def test_list_dir_inlines_readme_for_plain_dir(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    (root / "notes").mkdir()
    (root / "notes" / "README.md").write_text("# Notes\n\nProse.\n")

    listing = list_dir(root, (root / "notes").resolve())

    assert listing.kind is None
    assert listing.skill is None
    assert (listing.doc_name, listing.doc) == ("README.md", "# Notes\n\nProse.\n")


def test_list_dir_readme_match_is_case_insensitive(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    (root / "notes").mkdir()
    (root / "notes" / "readme.md").write_text("lower\n")

    listing = list_dir(root, (root / "notes").resolve())

    assert (listing.doc_name, listing.doc) == ("readme.md", "lower\n")


def test_list_dir_skill_doc_wins_over_readme(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    skill = root / "skills" / "weather"
    (skill / "README.md").write_text("readme body\n")

    listing = list_dir(root, skill.resolve())

    assert (listing.kind, listing.doc_name) == ("skill", "SKILL.md")
    assert "readme body" not in (listing.doc or "")


def test_list_dir_readme_frontmatter_is_not_stripped(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    (root / "notes").mkdir()
    (root / "notes" / "README.md").write_text("---\ntitle: keep\n---\n\nBody.\n")

    listing = list_dir(root, (root / "notes").resolve())

    assert listing.doc == "---\ntitle: keep\n---\n\nBody.\n"


def test_build_entry_tags_skill_dirs(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)

    assert build_entry(root / "skills" / "weather", root.resolve()).kind == "skill"
    assert build_entry(root / "skills", root.resolve()).kind is None


def test_build_entry_session_wins_over_skill(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    directory = _archive(root, "2026-06-04-09-00-deadbeef", {"session": {"title": "Odd one"}})
    (directory / "SKILL.md").write_text("---\nname: odd\n---\n")

    assert build_entry(directory, root.resolve()).kind == "session"


def test_build_entry_reports_file_mtime(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    target = root / "SOUL.md"
    os.utime(target, (1_780_000_000, 1_780_000_000))

    entry = build_entry(target, root.resolve())

    assert entry.modified == datetime.fromtimestamp(1_780_000_000, tz=UTC)
    # Directories carry no mtime: the client shows a title or nothing for them.
    assert build_entry(root / "skills", root.resolve()).modified is None


def test_list_dir_does_not_read_through_escaping_skill_doc(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    (tmp_path / "secret.txt").write_text("HOST SECRET")
    escaping = root / "skills" / "escaping"
    escaping.mkdir()
    (escaping / "SKILL.md").symlink_to(tmp_path / "secret.txt")

    listing = list_dir(root, escaping.resolve())

    assert (listing.doc, listing.skill, listing.kind) == (None, None, None)


def test_list_dir_does_not_read_through_escaping_readme(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    (tmp_path / "secret.txt").write_text("HOST SECRET")
    notes = root / "notes"
    notes.mkdir()
    (notes / "README.md").symlink_to(tmp_path / "secret.txt")

    assert list_dir(root, notes.resolve()).doc is None


def test_session_archive_entry_ignores_escaping_conversation(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    (tmp_path / "secret.json").write_text(json.dumps({"session": {"title": "leaked"}}))
    directory = root / "sessions" / "2026" / "06" / "escaping"
    directory.mkdir(parents=True)
    (directory / "conversation.json").symlink_to(tmp_path / "secret.json")

    assert session_archive_entry(directory, root.resolve()) is None
    assert build_entry(directory, root.resolve()).kind is None


def test_build_entry_tolerates_broken_symlink(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    (root / "dangling.md").symlink_to(tmp_path / "does-not-exist")

    entry = build_entry(root / "dangling.md", root.resolve())

    assert (entry.name, entry.type, entry.size, entry.modified) == ("dangling.md", "file", None, None)
    # The whole listing must still render around it.
    assert "dangling.md" in [e.name for e in list_dir(root, root.resolve()).entries]


def test_build_entry_reports_symlink_inside_the_repo(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    (root / "alias.md").symlink_to(root / "SOUL.md")

    entry = build_entry(root / "alias.md", root.resolve())

    assert (entry.type, entry.size) == ("file", len("# soul"))


def test_list_dir_does_not_read_dot_git_through_a_symlink(tmp_path: Path) -> None:
    """A symlink pointing back into .git stays inside the repo, so containment alone
    would pass it — and .git/config holds the remote URL with its access token."""
    root = _make_repo(tmp_path)
    notes = root / "notes"
    notes.mkdir()
    (notes / "README.md").symlink_to(root / ".git" / "config")

    assert list_dir(root, notes.resolve()).doc is None
    # And it is not reachable by browsing to it directly either.
    with pytest.raises(HTTPException):
        resolve_target(root.resolve(), "notes/README.md")


def test_session_archive_entry_ignores_an_oversized_archive(tmp_path: Path) -> None:
    """Runs for every subdirectory of a listing, on a file the pushing client sizes."""
    root = _make_repo(tmp_path)
    directory = root / "sessions" / "2026" / "06" / "huge"
    directory.mkdir(parents=True)
    payload = {"session": {"title": "t", "session_id": "s"}, "pad": "x" * (MAX_INLINE_TEXT_BYTES + 1)}
    (directory / "conversation.json").write_text(json.dumps(payload))

    assert session_archive_entry(directory, root.resolve()) is None


# ── Vault presence status ───────────────────────────────────────────


class _FakeRegistry:
    """Minimal credential registry: only paths in `present` resolve; `errors` raise."""

    def __init__(self, present: set[str], errors: set[str] | None = None, unconfigured: set[str] | None = None) -> None:
        self._present = present
        self._errors = errors or set()
        self._unconfigured = unconfigured or set()

    async def fetch_metadata(self, vault_path: str):
        from carapace.credentials import CredentialBackendError, UnknownBackendError
        from carapace.models.credentials import CredentialMetadata

        if vault_path in self._errors:
            raise CredentialBackendError("vault down")
        if vault_path in self._unconfigured:
            raise UnknownBackendError(f"Unknown credential backend: {vault_path!r}")
        if vault_path not in self._present:
            raise KeyError(vault_path)
        return CredentialMetadata(vault_path=vault_path, name=vault_path)


async def test_resolve_vault_status_present_absent_error():
    from carapace.models.skills import SkillCarapaceConfig

    cfg = SkillCarapaceConfig.model_validate(
        {
            "credentials": [
                {"vault_path": "vault/have", "env_var": "A"},
                {"vault_path": "vault/missing", "env_var": "B"},
            ],
            "mcp": [
                {"name": "o", "url": "https://e.example/mcp", "auth": {"type": "oauth", "vault_path": "vault/down"}},
            ],
        }
    )
    registry = _FakeRegistry(present={"vault/have"}, errors={"vault/down"})
    status = await resolve_vault_status(cfg, registry)
    assert status == {"vault/have": "present", "vault/missing": "absent", "vault/down": "error"}


async def test_resolve_vault_status_unconfigured_backend():
    """An unregistered/disabled backend is 'unconfigured', not a missing secret."""
    from carapace.models.skills import SkillCarapaceConfig

    cfg = SkillCarapaceConfig.model_validate({"credentials": [{"vault_path": "vault/x", "env_var": "A"}]})
    registry = _FakeRegistry(present=set(), unconfigured={"vault/x"})
    assert await resolve_vault_status(cfg, registry) == {"vault/x": "unconfigured"}


def test_artifact_directory_label_uses_its_html_title(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    directory = root / "artifacts" / "report"
    directory.mkdir(parents=True)
    (directory / "index.html").write_text(
        "<head><title> Quarterly &amp;\n report </title></head><svg><title>Chart label</title></svg>"
        + "x" * (MAX_INLINE_TEXT_BYTES + 1)
    )
    entry = build_entry(directory, root.resolve())
    assert entry.kind == "artifact"
    assert entry.label == "Quarterly & report"


def test_only_artifact_directories_with_contained_entry_points_get_the_kind(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    directory = root / "artifacts" / "report"
    directory.mkdir(parents=True)
    assert build_entry(directory, root.resolve()).kind is None
    (root / "private.html").write_text("<title>Private</title>")
    (directory / "index.html").symlink_to(root / "private.html")
    assert build_entry(directory, root.resolve()).kind is None
    ordinary = root / "notes"
    ordinary.mkdir()
    (ordinary / "index.html").write_text("<title>Not an artifact</title>")
    assert build_entry(ordinary, root.resolve()).kind is None
