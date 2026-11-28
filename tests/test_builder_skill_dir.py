"""The builder reads a built skill's directory for the server: SKILL.md, the file list and single files."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from carapace.builder import app as builder_app
from carapace.builder import nix, skill_dir
from carapace.builder.client import BuilderClient
from carapace.builder.models import (
    BuildResult,
    CredentialSlotDeclaration,
    FetchCredential,
    SettingDeclaration,
    SkillDeclarations,
)
from carapace.builder.skill_dir import SkillFileError, checked_skill_dir, list_files, read_file
from carapace.builder.store import SkillStore
from tests.test_builder import AUTH, GRACE, KEY, TOKEN


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A directory standing in for /nix/store, which the path check then accepts."""
    store = tmp_path / "store"
    store.mkdir()
    pattern = re.escape(str(store)) + r"/[0-9a-df-np-sv-z]{32}-[A-Za-z0-9+\-._?=]+"
    monkeypatch.setattr(skill_dir, "_STORE_PATH", re.compile(pattern))
    return store


@pytest.fixture
def directory(store: Path, tmp_path: Path) -> str:
    """A skill directory with a reference, plus a file and a directory that are symlinks out of it."""
    outside = tmp_path / "builder-state"
    outside.mkdir()
    (outside / "token").write_text("secret")
    root = store / f"{'a' * 32}-skill-demo-src"
    (root / "references").mkdir(parents=True)
    (root / "SKILL.md").write_text("---\nname: demo\n---\nBody\n")
    (root / "references" / "syntax.md").write_text("syntax")
    (root / "token").symlink_to(outside / "token")
    (root / "state").symlink_to(outside)
    return str(root)


def test_files_of_the_skill_directory_are_read(directory: str) -> None:
    assert read_file(directory, "SKILL.md").startswith(b"---\nname: demo")
    assert read_file(directory, "references/syntax.md") == b"syntax"
    assert list_files(directory) == ["SKILL.md", "references/syntax.md"]


@pytest.mark.parametrize("path", ["token", "state/token"])
def test_a_symlink_out_of_the_directory_is_not_followed(directory: str, path: str) -> None:
    with pytest.raises(SkillFileError, match="symlink"):
        read_file(directory, path)


@pytest.mark.parametrize("path", ["../escape", "/etc/hosts", "references/../SKILL.md", ""])
def test_a_path_outside_the_directory_is_refused(directory: str, path: str) -> None:
    with pytest.raises(SkillFileError, match="not a relative path inside the skill"):
        read_file(directory, path)


def test_a_directory_or_a_large_file_is_not_read(directory: str, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(SkillFileError, match="not a file"):
        read_file(directory, "references")
    monkeypatch.setattr(skill_dir, "MAX_FILE_BYTES", 3)
    with pytest.raises(SkillFileError, match="larger than 3 bytes"):
        read_file(directory, "references/syntax.md")


def test_a_missing_file_is_not_found(directory: str) -> None:
    with pytest.raises(FileNotFoundError):
        read_file(directory, "missing.md")


@pytest.mark.parametrize("value", ["/etc", "/nix/store/../etc", f"/nix/store/{'a' * 32}-x/sub", 7])
def test_the_metadata_must_name_a_top_level_store_path(value: object) -> None:
    with pytest.raises(SkillFileError, match="skillDir must be a store path"):
        checked_skill_dir({"skillDir": value})


def test_metadata_from_helpers_without_src_names_no_directory() -> None:
    assert checked_skill_dir({"name": "old", "commands": {}}) is None
    assert checked_skill_dir(None) is None


def _nix(directory: str, *, build_code: int = 0, dir_code: int = 0):
    """`nix eval` answers with metadata naming *directory*; building it and the package succeed or fail."""

    async def run(*args: str, credential: FetchCredential | None = None) -> tuple[int, str, str]:
        if args[1] == "eval" and "--apply" in args:
            declared = {"CITY": {"type": "str", "description": "City", "default": "Berlin"}}
            return 0, json.dumps({"settings": declared, "credentials": {"KEY": {"type": "secret"}}}), ""
        if args[1] == "eval":
            return (
                0,
                json.dumps(
                    {"enable": True, "name": "demo", "description": "Demo", "skillDir": directory, "commands": {}}
                ),
                "",
            )
        if args[-1].endswith(".skillDir"):
            return dir_code, "", "error: the skill directory does not build" if dir_code else ""
        if build_code:
            return build_code, "", "error: builder ran out of disk"
        return 0, json.dumps([{"outputs": {"out": "/nix/store/x-skill-demo"}}]), "built"

    return run


async def _build(tmp_path: Path) -> BuildResult:
    source = tmp_path / "source"
    source.mkdir()
    (source / "flake.lock").write_text("{}")
    return await nix.build_skill(source, KEY, "demo", "x86_64-linux", tmp_path / "roots", None)


async def test_a_build_carries_the_skill_md_and_files_it_read_before_the_commands_build(
    directory: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(nix, "_run", _nix(directory))

    result = await _build(tmp_path)

    assert (result.state, result.skill_dir) == ("succeeded", directory)
    assert result.skill_md == "---\nname: demo\n---\nBody\n"
    assert result.skill_files == ["SKILL.md", "references/syntax.md"]


async def test_a_failed_build_still_carries_the_skill_md(
    directory: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(nix, "_run", _nix(directory, build_code=1))

    result = await _build(tmp_path)

    assert result.state == "failed"
    assert result.skill_md is not None and "error: builder ran out of disk" in result.log_tail
    # The manifest evaluated, so the catalog keeps the skill's description.
    assert result.metadata["description"] == "Demo"


async def test_a_skill_dir_that_does_not_build_fails_before_the_commands(
    directory: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(nix, "_run", _nix(directory, dir_code=1, build_code=1))

    result = await _build(tmp_path)

    assert result.state == "failed" and "the skill directory does not build" in result.log_tail
    assert (result.skill_md, result.metadata["description"]) == (None, "Demo")


async def test_a_skill_dir_outside_the_store_fails_the_build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(nix, "_run", _nix("/etc"))

    result = await _build(tmp_path)

    assert result.state == "failed"
    assert "skillDir must be a store path" in result.log_tail
    assert result.skill_md is None


async def test_a_build_carries_the_declarations(
    directory: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(nix, "_run", _nix(directory))

    result = await _build(tmp_path)

    assert result.declarations == SkillDeclarations(
        settings={"CITY": SettingDeclaration(type="str", description="City", default="Berlin")},
        credentials={"KEY": CredentialSlotDeclaration(type="secret")},
    )


async def test_a_manifest_failing_for_a_missing_value_still_has_the_declarations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run(*args: str, credential: FetchCredential | None = None) -> tuple[int, str, str]:
        if "--apply" in args:
            return 0, json.dumps({"settings": {"CITY": {"type": "str", "description": "City"}}, "credentials": {}}), ""
        return 1, "", "error: skill demo: no value for its setting CITY; set it in skills/config.json"

    monkeypatch.setattr(nix, "_run", run)

    result = await _build(tmp_path)

    assert result.state == "failed" and "no value for its setting CITY" in result.log_tail
    assert result.declarations == SkillDeclarations(
        settings={"CITY": SettingDeclaration(type="str", description="City")}, credentials={}
    )


async def test_declarations_this_builder_cannot_read_leave_the_build_alone(
    directory: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = _nix(directory)

    async def newer_helpers(*args: str, credential: FetchCredential | None = None) -> tuple[int, str, str]:
        if "--apply" in args:
            return 0, json.dumps({"settings": {"RATIO": {"type": "float"}}, "credentials": {}}), ""
        return await run(*args)

    monkeypatch.setattr(nix, "_run", newer_helpers)

    result = await _build(tmp_path)

    assert (result.state, result.declarations) == ("succeeded", None)


def test_the_api_serves_files_of_a_stored_build(directory: str, tmp_path: Path) -> None:
    store = SkillStore(tmp_path / "state", GRACE)
    store.save(BuildResult(key=KEY, skill="demo", state="succeeded", skill_dir=directory))
    api = TestClient(builder_app.create_app(TOKEN, store, "x86_64-linux", []))

    assert api.get(f"/builds/{KEY}/files/references/syntax.md").status_code == 401
    response = api.get(f"/builds/{KEY}/files/references/syntax.md", headers=AUTH)
    assert (response.status_code, response.content) == (200, b"syntax")
    assert api.get(f"/builds/{KEY}/files/missing.md", headers=AUTH).status_code == 404
    assert api.get(f"/builds/{KEY}/files/token", headers=AUTH).status_code == 400
    assert api.get(f"/builds/{'f' * 64}/files/SKILL.md", headers=AUTH).status_code == 404


async def test_the_client_refuses_a_path_out_of_the_skill_before_asking() -> None:
    client = BuilderClient("http://builder.invalid", TOKEN, timeout_seconds=1)

    with pytest.raises(SkillFileError):
        await client.skill_file(KEY, "../../builds/other")


async def test_a_skill_turned_off_is_not_built(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def run(*args: str, credential: FetchCredential | None = None) -> tuple[int, str, str]:
        calls.append(args[1])
        if "--apply" in args:
            return 0, json.dumps({"settings": {}, "credentials": {}}), ""
        return 0, json.dumps({"enable": False}), ""

    monkeypatch.setattr(nix, "_run", run)

    result = await _build(tmp_path)

    # Evaluated twice (declarations, manifest), built never.
    assert (result.state, result.metadata, result.store_paths, calls) == (
        "succeeded",
        {"enable": False},
        [],
        ["eval", "eval"],
    )


async def test_a_skills_flake_without_manifests_says_how_to_write_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run(*_args: str, credential: FetchCredential | None = None) -> tuple[int, str, str]:
        return 1, "", "error: flake 'path:/x' does not provide attribute 'manifests.x86_64-linux.demo'"

    monkeypatch.setattr(nix, "_run", run)

    result = await _build(tmp_path)

    assert result.state == "failed"
    assert result.log_tail.startswith("skills/flake.nix has no manifests for its skills: write its outputs with")


async def test_a_path_missing_from_the_archive_gets_a_hint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    missing = f"error: path '/nix/store/{'a' * 32}-source/shared/household.md' does not exist"

    async def run(*args: str, credential: FetchCredential | None = None) -> tuple[int, str, str]:
        if "--apply" in args:
            return 0, json.dumps({"settings": {}, "credentials": {}}), ""
        return 1, "", missing

    monkeypatch.setattr(nix, "_run", run)

    result = await _build(tmp_path)

    assert result.log_tail.startswith(missing)
    assert "Keep an override's files in skills/<attribute>/" in result.log_tail
