"""Skills are what skills/flake.nix lists, each built under its own key: a push builds only what it changed."""

from __future__ import annotations

import asyncio
import io
import subprocess
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

import carapace.server as srv
from carapace.builder import skill_builds, skills_head
from carapace.builder.client import BuilderClient
from carapace.builder.models import BuildResult, SettingDeclaration, SkillDeclarations, UpdatedLocks
from carapace.builder.skill_builds import SkillBuilds
from carapace.builder.skill_updates import UpdateCheck
from carapace.spans import TurnTrace, attach
from tests.skills_flake import write_skills_flake

_METADATA = {
    "enable": True,
    "name": "weather",
    "settings": {"CITY": "Berlin"},
    "commands": {
        "weather": {
            "description": "Current weather",
            "mcp": False,
            "needs": {"domains": ["api.example.com"], "credentials": {}, "oauth": {}, "tunnels": []},
        }
    },
}


class FakeBuilder:
    """The builder API: stored results by key, and a record of what was sent to build."""

    def __init__(self) -> None:
        self.stored: dict[str, BuildResult] = {}
        self.built: list[tuple[str, str, set[str]]] = []
        self.unreachable = False
        self.reject_with: int | None = None
        self.retries = 0
        self.files: dict[str, bytes] = {"SKILL.md": b"---\nname: weather\ndescription: Current weather\n---\n"}
        self.answer = lambda key, skill: BuildResult(
            key=key,
            skill=skill,
            state="succeeded",
            store_paths=[f"/nix/store/{key[:32]}-skill"],
            # One command per skill, named after it, as command names are unique on PATH.
            metadata=_METADATA | {"commands": {skill: _METADATA["commands"]["weather"]}},
            skill_dir=f"/nix/store/{key[32:64]}-skill-src",
            skill_md=self.files["SKILL.md"].decode(),
            skill_files=sorted(self.files),
        )
        self.file_reads: list[tuple[str, str]] = []

    async def check_updates(self, archive: bytes, inputs: list[str]) -> UpdatedLocks:
        """ensure_built starts an update check for a new skills/ tree; these tests are about builds."""
        return UpdatedLocks(inputs={})

    async def get(self, key: str) -> BuildResult | None:
        if self.unreachable:
            raise httpx.ConnectError("builder down")
        return self.stored.get(key)

    async def build(self, key: str, skill: str, archive: bytes, *, retry: bool = False) -> BuildResult:
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            self.built.append((key, skill, set(tar.getnames())))
        self.retries += retry
        if self.reject_with is not None:
            request = httpx.Request("PUT", f"http://builder/builds/{key}")
            response = httpx.Response(self.reject_with, text="archive member escapes the skills directory")
            raise httpx.HTTPStatusError("rejected", request=request, response=response)
        self.stored[key] = self.answer(key, skill)
        return self.stored[key]

    async def skill_file(self, key: str, path: str) -> bytes | None:
        self.file_reads.append((key, path))
        return self.files.get(path)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def _write_skill(repo: Path, name: str) -> None:
    skill = repo / "skills" / name
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(f"---\nname: {name}\ndescription: demo\n---\nBody\n")
    (skill / "flake.nix").write_text("{ outputs = _: { }; }\n")


def _write_skills_flake(repo: Path, local: list[str], external: tuple[str, ...] = ()) -> None:
    write_skills_flake(repo / "skills", local, external)


def _key(repo: Path, name: str, directory: str | None = None) -> str:
    def object_id(spec: str) -> str:
        return _git(repo, "rev-parse", f"HEAD:{spec}")

    return skill_builds.build_key(
        name,
        object_id("skills/flake.nix"),
        object_id("skills/flake.lock"),
        "",
        object_id(f"skills/{directory or name}") if directory != "" else "",
    )


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", message)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "knowledge"
    repo.mkdir()
    _git(repo, "init", "-q")
    _write_skill(repo, "weather")
    _write_skill(repo, "notes")
    _write_skill(repo, "unlisted")
    _write_skills_flake(repo, ["weather", "notes"])
    _commit(repo, "skills")
    return repo


async def _settled(builds: SkillBuilds, repo: Path) -> dict[str, str]:
    while running := list(builds._running.values()):
        await asyncio.gather(*running)
    return {build.skill: build.state for build in await builds.ensure_built(repo)}


@pytest.mark.anyio
async def test_a_head_change_builds_only_the_skills_whose_key_changed(repo: Path) -> None:
    builder = FakeBuilder()
    builds = SkillBuilds(cast(BuilderClient, builder))

    first = await builds.ensure_built(repo)

    assert {build.skill: build.state for build in first} == {"notes": "building", "weather": "building"}
    assert await _settled(builds, repo) == {"notes": "succeeded", "weather": "succeeded"}
    assert sorted(skill for _, skill, _ in builder.built) == ["notes", "weather"]
    # Each build gets the flake, its lock and its own directory, nothing else of skills/: what its key covers.
    for _, skill, files in builder.built:
        assert {name.rstrip("/") for name in files} == {
            "flake.nix",
            "flake.lock",
            skill,
            f"{skill}/SKILL.md",
            f"{skill}/flake.nix",
        }

    (repo / "skills" / "weather" / "SKILL.md").write_text("---\nname: weather\ndescription: changed\n---\n")
    _commit(repo, "change weather")
    await builds.ensure_built(repo)
    await _settled(builds, repo)

    assert len(builder.built) == 3
    assert builder.built[-1][:2] == (_key(repo, "weather"), "weather")


@pytest.mark.anyio
async def test_a_lock_change_rekeys_every_skill(repo: Path) -> None:
    builder = FakeBuilder()
    builds = SkillBuilds(cast(BuilderClient, builder))
    await builds.ensure_built(repo)
    await _settled(builds, repo)

    _write_skills_flake(repo, ["weather", "notes"], external=("tracker",))
    _commit(repo, "add tracker")
    await builds.ensure_built(repo)

    assert await _settled(builds, repo) == {"notes": "succeeded", "tracker": "succeeded", "weather": "succeeded"}
    assert sorted(skill for _, skill, _ in builder.built[2:]) == ["notes", "tracker", "weather"]


@pytest.mark.anyio
async def test_an_external_skill_is_keyed_without_a_directory(repo: Path) -> None:
    _write_skills_flake(repo, ["weather"], external=("tracker",))
    _commit(repo, "external tracker")
    builds = SkillBuilds(cast(BuilderClient, FakeBuilder()))

    keys = {build.skill: build.key for build in await builds.ensure_built(repo)}

    assert keys == {"tracker": _key(repo, "tracker", directory=""), "weather": _key(repo, "weather")}


@pytest.mark.anyio
async def test_a_built_skill_reports_its_store_paths_and_commands(repo: Path) -> None:
    builds = SkillBuilds(cast(BuilderClient, FakeBuilder()))
    await builds.ensure_built(repo)
    await _settled(builds, repo)

    weather = next(build for build in await builds.ensure_built(repo) if build.skill == "weather")

    assert weather.key == _key(repo, "weather")
    assert weather.store_paths == [f"/nix/store/{weather.key[:32]}-skill"]
    assert weather.commands["weather"].needs.domains == ["api.example.com"]


@pytest.mark.anyio
async def test_a_result_the_builder_already_has_is_not_built_again(repo: Path) -> None:
    builder = FakeBuilder()
    for name in ("weather", "notes"):
        builder.stored[_key(repo, name)] = builder.answer(_key(repo, name), name)
    builds = SkillBuilds(cast(BuilderClient, builder))

    await builds.ensure_built(repo)

    assert await _settled(builds, repo) == {"notes": "succeeded", "weather": "succeeded"}
    assert builder.built == []


@pytest.mark.anyio
async def test_a_failed_build_is_reported_with_its_log(repo: Path) -> None:
    builder = FakeBuilder()
    builder.answer = lambda key, skill: BuildResult(
        key=key, skill=skill, state="failed", log_tail="error: flake.lock is missing nixpkgs"
    )
    builds = SkillBuilds(cast(BuilderClient, builder))
    await builds.ensure_built(repo)
    await _settled(builds, repo)

    [weather] = [build for build in await builds.ensure_built(repo) if build.skill == "weather"]

    assert (weather.state, weather.detail) == ("failed", "error: flake.lock is missing nixpkgs")
    assert len(builder.built) == 2


@pytest.mark.anyio
async def test_a_skill_without_a_manifest_counts_as_failed(repo: Path) -> None:
    builder = FakeBuilder()
    builder.answer = lambda key, skill: BuildResult(
        key=key, skill=skill, state="succeeded", store_paths=["/nix/store/x"], metadata=None
    )
    builds = SkillBuilds(cast(BuilderClient, builder))
    await builds.ensure_built(repo)
    await _settled(builds, repo)

    states = {build.skill: (build.state, build.detail) for build in await builds.ensure_built(repo)}

    assert states["weather"][0] == "failed"
    assert "no valid manifest" in states["weather"][1]


@pytest.mark.anyio
async def test_an_unreachable_builder_reads_unavailable_and_is_asked_again(repo: Path) -> None:
    builder = FakeBuilder()
    builder.unreachable = True
    builds = SkillBuilds(cast(BuilderClient, builder))
    await builds.ensure_built(repo)

    assert await _settled(builds, repo) == {"notes": "unavailable", "weather": "unavailable"}
    [weather] = [build for build in await builds.ensure_built(repo) if build.skill == "weather"]
    assert "ConnectError: builder down" in weather.detail

    builder.unreachable = False
    await _settled(builds, repo)
    assert await _settled(builds, repo) == {"notes": "succeeded", "weather": "succeeded"}


@pytest.mark.anyio
async def test_a_skill_the_builder_refuses_fails_and_is_not_sent_again(repo: Path) -> None:
    builder = FakeBuilder()
    builder.reject_with = 400
    builds = SkillBuilds(cast(BuilderClient, builder))
    await builds.ensure_built(repo)
    await _settled(builds, repo)

    [weather] = [build for build in await builds.ensure_built(repo) if build.skill == "weather"]
    await _settled(builds, repo)

    assert weather.state == "failed"
    assert weather.detail == "The builder refused the skill (400): archive member escapes the skills directory"
    assert len(builder.built) == 2


@pytest.mark.anyio
async def test_without_a_builder_listed_skills_are_unavailable(repo: Path) -> None:
    builds = SkillBuilds(None)

    states = {build.skill: build.state for build in await builds.ensure_built(repo)}

    assert states == {"notes": "unavailable", "weather": "unavailable"}


@pytest.mark.anyio
@pytest.mark.parametrize("missing", ["flake.nix", "flake.lock"])
async def test_without_the_skills_flake_a_repo_has_no_skills(repo: Path, missing: str) -> None:
    (repo / "skills" / missing).unlink()
    _commit(repo, f"drop {missing}")

    assert await SkillBuilds(cast(BuilderClient, FakeBuilder())).ensure_built(repo) == []


@pytest.mark.anyio
async def test_a_repository_without_commits_has_no_skills(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")

    assert await SkillBuilds(cast(BuilderClient, FakeBuilder())).ensure_built(tmp_path) == []


@pytest.mark.anyio
async def test_a_push_syncs_the_builder_roots(monkeypatch: pytest.MonkeyPatch) -> None:
    builds = AsyncMock()
    registry = MagicMock()
    registry.existing.return_value = [MagicMock(knowledge_dir=Path("/repos/thies"))]
    monkeypatch.setattr(srv, "_skill_builds", builds, raising=False)
    monkeypatch.setattr(srv, "_knowledge_git_runtime", AsyncMock(), raising=False)
    monkeypatch.setattr(srv, "_knowledge_repo_registry", registry, raising=False)

    await srv._after_push("thies")

    builds.sync_roots.assert_awaited_once()
    assert list(builds.sync_roots.await_args.args[0]) == [Path("/repos/thies")]


@pytest.mark.anyio
async def test_a_push_is_mirrored_even_when_its_builds_cannot_start(monkeypatch: pytest.MonkeyPatch) -> None:
    builds = AsyncMock()
    builds.ensure_built.side_effect = RuntimeError("git ls-tree failed")
    runtime = AsyncMock()
    registry = MagicMock()
    monkeypatch.setattr(srv, "_skill_builds", builds, raising=False)
    monkeypatch.setattr(srv, "_knowledge_git_runtime", runtime, raising=False)
    monkeypatch.setattr(srv, "_knowledge_repo_registry", registry, raising=False)

    with pytest.raises(RuntimeError):
        await srv._after_push("thies")

    builds.ensure_built.assert_awaited_once_with(registry.get_for_user.return_value.knowledge_dir)
    runtime.push_if_configured.assert_awaited_once_with("thies")


@pytest.mark.anyio
async def test_a_skill_that_cannot_be_archived_fails(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real_git = skills_head._git

    async def git(repo_dir: Path, *args: str) -> bytes:
        if "archive" in args:
            raise RuntimeError("git archive failed: fatal: not a tree object")
        return await real_git(repo_dir, *args)

    monkeypatch.setattr(skills_head, "_git", git)
    builder = FakeBuilder()
    builds = SkillBuilds(cast(BuilderClient, builder))
    await builds.ensure_built(repo)

    assert await _settled(builds, repo) == {"notes": "failed", "weather": "failed"}
    assert builder.built == []


def _held(builder: FakeBuilder) -> asyncio.Event:
    """Hold every build until the returned event is set."""
    release = asyncio.Event()
    build = builder.build

    async def held_build(key: str, skill: str, archive: bytes, *, retry: bool = False) -> BuildResult:
        await release.wait()
        return await build(key, skill, archive, retry=retry)

    builder.build = held_build  # type: ignore[method-assign]
    return release


@pytest.mark.anyio
async def test_waiting_for_a_build_returns_its_result_and_is_a_span(repo: Path) -> None:
    builder = FakeBuilder()
    release = _held(builder)
    builds = SkillBuilds(cast(BuilderClient, builder))
    trace = TurnTrace("t1", on_change=lambda _span: None)
    root = trace.start("turn", "turn", parent_id=None, attrs={})

    with attach(trace, root.span_id):
        waiting = asyncio.create_task(builds.wait_built(repo, "weather"))
        await asyncio.sleep(0.05)
        assert not waiting.done()
        release.set()
        weather = await waiting

    assert weather is not None and weather.state == "succeeded"
    [wait] = [span for span in trace.spans.values() if span.name == "build wait"]
    assert (wait.kind, wait.attrs, wait.status) == ("skill", {"skill": "weather"}, "ok")


@pytest.mark.anyio
async def test_waiting_for_an_unlisted_skill_returns_none_at_once(repo: Path) -> None:
    builds = SkillBuilds(cast(BuilderClient, FakeBuilder()))

    unlisted = await builds.wait_built(repo, "unlisted")

    assert unlisted is None


class RootsBuilder(FakeBuilder):
    def __init__(self) -> None:
        super().__init__()
        self.roots: list[list[str]] = []

    async def put_roots(self, keys: list[str]) -> None:
        self.roots.append(keys)


@pytest.mark.anyio
async def test_the_builder_roots_are_the_skill_keys_of_all_heads(repo: Path, tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    _git(other, "init", "-q")
    _write_skill(other, "weather")
    (other / "skills" / "weather" / "LICENSE").write_text("demo\n")
    _write_skills_flake(other, ["weather"])
    _commit(other, "another user's weather")
    empty = tmp_path / "empty"
    empty.mkdir()
    _git(empty, "init", "-q")
    builder = RootsBuilder()

    await SkillBuilds(cast(BuilderClient, builder)).sync_roots([repo, other, empty])

    expected = {_key(repo, "weather"), _key(repo, "notes"), _key(other, "weather")}
    assert builder.roots == [sorted(expected)]


@pytest.mark.anyio
async def test_a_key_no_head_references_is_looked_up_again(repo: Path) -> None:
    builder = RootsBuilder()
    builds = SkillBuilds(cast(BuilderClient, builder))
    await builds.ensure_built(repo)
    await _settled(builds, repo)
    old_weather = _key(repo, "weather")

    (repo / "skills" / "weather" / "flake.nix").write_text("{ outputs = _: { packages = { }; }; }\n")
    _commit(repo, "change weather")
    await builds.sync_roots([repo])

    # The builder may collect the old key, so its remembered result must not outlive the sync.
    assert old_weather not in builds._results
    assert _key(repo, "notes") in builds._results


@pytest.mark.anyio
async def test_a_failed_build_is_retried_on_request(repo: Path) -> None:
    builder = FakeBuilder()
    builder.answer = lambda key, skill: BuildResult(key=key, skill=skill, state="failed", log_tail="error: reset")
    builds = SkillBuilds(cast(BuilderClient, builder))
    await builds.ensure_built(repo)
    assert (await _settled(builds, repo))["weather"] == "failed"

    builder.answer = FakeBuilder().answer
    await builds.retry(repo, "weather")

    assert (await _settled(builds, repo)) == {"weather": "succeeded", "notes": "failed"}
    assert builder.retries == 1


@pytest.mark.anyio
@pytest.mark.parametrize("name", ["weather", "unlisted", "missing"])
async def test_only_a_failed_listed_skill_can_be_retried(repo: Path, name: str) -> None:
    builds = SkillBuilds(cast(BuilderClient, FakeBuilder()))
    await builds.ensure_built(repo)
    await _settled(builds, repo)

    with pytest.raises(skill_builds.RetryRefusedError):
        await builds.retry(repo, name)


@pytest.mark.anyio
async def test_an_unreadable_repo_does_not_stop_the_other_repos_roots(repo: Path, tmp_path: Path) -> None:
    broken = tmp_path / "broken"
    broken.mkdir()
    _git(broken, "init", "-q")
    _write_skill(broken, "weather")
    _write_skills_flake(broken, ["weather"])
    _commit(broken, "skills")
    # A head that names a missing tree object: reading its skills fails for this repo only.
    tree = _git(broken, "rev-parse", "HEAD^{tree}")
    (broken / ".git" / "objects" / tree[:2] / tree[2:]).unlink()
    builder = RootsBuilder()

    await SkillBuilds(cast(BuilderClient, builder)).sync_roots([broken, repo])

    assert builder.roots == [sorted([_key(repo, "weather"), _key(repo, "notes")])]


@pytest.mark.anyio
async def test_a_cancelled_waiter_leaves_the_build_running_for_the_others(repo: Path) -> None:
    builder = FakeBuilder()
    release = _held(builder)
    builds = SkillBuilds(cast(BuilderClient, builder))
    trace = TurnTrace("t1", on_change=lambda _span: None)
    root = trace.start("turn", "turn", parent_id=None, attrs={})
    with attach(trace, root.span_id):
        stopped = asyncio.create_task(builds.wait_built(repo, "weather"))
        waiting = asyncio.create_task(builds.wait_built(repo, "weather"))
    while sum(span.name == "build wait" for span in trace.spans.values()) < 2:
        await asyncio.sleep(0.01)

    stopped.cancel()
    await asyncio.sleep(0)
    release.set()
    weather = await waiting

    assert stopped.cancelled()
    assert weather is not None and weather.state == "succeeded"
    assert len(builder.built) == 2


def _answer_with(skill_mds: dict[str, str | None], state: str = "succeeded"):
    """Results whose SKILL.md is *skill_mds* by skill, the way the builder reads it from the skill directory."""

    def answer(key: str, skill: str) -> BuildResult:
        return BuildResult.model_validate(
            {
                "key": key,
                "skill": skill,
                "state": state,
                "store_paths": [f"/nix/store/{key[:32]}-skill"] if state == "succeeded" else [],
                "metadata": _METADATA,
                "skill_dir": f"/nix/store/{key[32:64]}-skill-src",
                "skill_md": skill_mds[skill],
                "skill_files": ["SKILL.md"],
                "log_tail": "error: builder ran out of disk" if state == "failed" else "",
            }
        )

    return answer


@pytest.mark.anyio
async def test_the_catalog_names_each_skill_by_its_attribute_with_its_built_description(repo: Path) -> None:
    # Two flakes whose frontmatter names collide coexist under their attributes, one of them from elsewhere.
    _write_skills_flake(repo, ["weather"], external=("tracker",))
    _commit(repo, "external tracker")
    builder = FakeBuilder()
    same = "---\nname: weather\ndescription: {}\n---\n"
    builder.answer = _answer_with({"weather": same.format("Local weather"), "tracker": same.format("Remote weather")})
    builds = SkillBuilds(cast(BuilderClient, builder))

    assert builds.catalog(repo) == []
    await builds.ensure_built(repo)
    building = {info.name: info.description for info in builds.catalog(repo)}
    await _settled(builds, repo)

    assert set(building) == {"tracker", "weather"}
    assert all(description.startswith("Being built") for description in building.values())
    assert {info.name: info.description for info in builds.catalog(repo)} == {
        "tracker": "Remote weather",
        "weather": "Local weather",
    }


@pytest.mark.anyio
async def test_a_failed_build_keeps_the_description_it_read(repo: Path) -> None:
    builder = FakeBuilder()
    builder.answer = _answer_with({"weather": "---\ndescription: Current weather\n---\n", "notes": None}, "failed")
    builds = SkillBuilds(cast(BuilderClient, builder))
    await builds.ensure_built(repo)
    await _settled(builds, repo)

    catalog = {info.name: info.description for info in builds.catalog(repo)}

    assert catalog["weather"] == "Current weather"
    assert catalog["notes"] == "BROKEN, its build has no SKILL.md; read_skill shows why."


@pytest.mark.anyio
async def test_a_broken_frontmatter_is_listed_as_broken(repo: Path) -> None:
    builder = FakeBuilder()
    disabled = "---\ndescription: Private material\nmetadata:\n  carapace:\n    disabled: true\n---\n"
    builder.answer = _answer_with({"weather": disabled, "notes": "Just a body.\n"})
    builds = SkillBuilds(cast(BuilderClient, builder))
    await builds.ensure_built(repo)
    await _settled(builds, repo)

    catalog = {info.name: info.description for info in builds.catalog(repo)}

    assert catalog["weather"].startswith("BROKEN") and "unlist it there" in catalog["weather"]
    assert "Private material" not in catalog["weather"]
    assert catalog["notes"] == ""


@pytest.mark.anyio
async def test_a_package_without_a_skill_directory_counts_as_failed(repo: Path) -> None:
    builder = FakeBuilder()
    builder.answer = lambda key, skill: BuildResult(
        key=key, skill=skill, state="succeeded", store_paths=["/nix/store/x"], metadata=_METADATA
    )
    builds = SkillBuilds(cast(BuilderClient, builder))
    await builds.ensure_built(repo)
    await _settled(builds, repo)

    [weather] = [build for build in await builds.ensure_built(repo) if build.skill == "weather"]

    assert weather.state == "failed"
    assert "nix flake update carapace --flake ./skills" in weather.detail


@pytest.mark.anyio
async def test_an_unavailable_builder_has_a_fixed_catalog_text(repo: Path) -> None:
    builder = FakeBuilder()
    builder.unreachable = True
    builds = SkillBuilds(cast(BuilderClient, builder))
    await builds.ensure_built(repo)
    await _settled(builds, repo)

    # The error text varies; the catalog is part of the cached prompt prefix.
    assert {info.description for info in builds.catalog(repo)} == {
        "Not available: the skill builder cannot be reached. read_skill shows why."
    }


@pytest.mark.anyio
async def test_a_skill_file_is_read_from_the_builder_under_its_build_key(repo: Path) -> None:
    builder = FakeBuilder()
    builder.files["references/syntax.md"] = b"syntax"
    builds = SkillBuilds(cast(BuilderClient, builder))
    await builds.ensure_built(repo)
    await _settled(builds, repo)
    [weather] = [build for build in await builds.ensure_built(repo) if build.skill == "weather"]

    assert weather.skill_files == ["SKILL.md", "references/syntax.md"]
    assert await builds.skill_file(weather, "references/syntax.md") == b"syntax"
    assert await builds.skill_file(weather, "missing.md") is None
    assert builder.file_reads == [(weather.key, "references/syntax.md"), (weather.key, "missing.md")]


@pytest.mark.anyio
async def test_a_rekeyed_skill_keeps_its_description_and_files_while_it_builds(repo: Path) -> None:
    builder = FakeBuilder()
    builds = SkillBuilds(cast(BuilderClient, builder))
    await builds.refresh(repo)
    await _settled(builds, repo)
    await builds.ensure_built(repo)
    before = builds.catalog(repo)
    previous = builds.readable(repo, "weather")

    _write_skills_flake(repo, ["weather", "notes"], external=("tracker",))
    _commit(repo, "add tracker")
    release = _held(builder)
    await builds.ensure_built(repo)

    # Every key changed and builds; the catalog and the sentinel keep what they had.
    assert {info.name: info.description for info in builds.catalog(repo)} == {
        **{info.name: info.description for info in before},
        "tracker": "Being built; its description follows once it is. read_skill waits for the build.",
    }
    assert previous is not None and builds.readable(repo, "weather") == previous
    assert builds.readable(repo, "tracker") is None
    release.set()
    await _settled(builds, repo)
    weather = builds.readable(repo, "weather")
    assert weather is not None and weather.key != previous.key


@pytest.mark.anyio
async def test_after_a_restart_the_refresh_waits_for_what_the_builder_already_has(repo: Path) -> None:
    builder = FakeBuilder()
    for name in ("weather", "notes"):
        builder.stored[_key(repo, name)] = builder.answer(_key(repo, name), name)
    builds = SkillBuilds(cast(BuilderClient, builder))

    await builds.refresh(repo)

    assert {info.name: info.description for info in builds.catalog(repo)} == {
        "notes": "Current weather",
        "weather": "Current weather",
    }
    assert builder.built == []


@pytest.mark.anyio
async def test_a_slow_lookup_does_not_hold_up_the_refresh(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    builder = FakeBuilder()
    answered = asyncio.Event()

    async def slow_get(_key: str) -> BuildResult | None:
        await answered.wait()
        return None

    builder.get = slow_get  # type: ignore[method-assign]
    monkeypatch.setattr(skill_builds, "_LOOKUP_WAIT_SECONDS", 0.01)
    builds = SkillBuilds(cast(BuilderClient, builder))

    await builds.refresh(repo)

    assert {info.description for info in builds.catalog(repo)} == {
        "Being built; its description follows once it is. read_skill waits for the build."
    }
    answered.set()
    await _settled(builds, repo)


@pytest.mark.anyio
async def test_the_profile_keeps_the_last_succeeded_build_while_skills_rebuild_or_fail(repo: Path) -> None:
    builder = FakeBuilder()
    builds = SkillBuilds(cast(BuilderClient, builder))
    await builds.ensure_built(repo)
    await _settled(builds, repo)
    before = {build.skill: build for build in await builds.installable(repo)}

    _write_skills_flake(repo, ["weather", "notes"], external=("tracker",))
    _commit(repo, "add tracker")
    release = _held(builder)

    # Every key builds: the old commands stay, the new skill has nothing to install yet.
    during = {build.skill: build for build in await builds.installable(repo)}
    assert during["weather"] == before["weather"] and during["notes"] == before["notes"]
    assert during["tracker"].state == "building"

    builder.answer = lambda key, skill: BuildResult(key=key, skill=skill, state="failed", log_tail="error: boom")
    release.set()
    await _settled(builds, repo)

    after = {build.skill: build for build in await builds.installable(repo)}
    assert after["weather"] == before["weather"]
    assert after["tracker"].state == "failed"


@pytest.mark.anyio
async def test_an_external_skill_gets_only_the_flake_and_its_lock(repo: Path) -> None:
    _write_skills_flake(repo, [], external=("tracker",))
    _commit(repo, "only tracker")
    builder = FakeBuilder()
    builds = SkillBuilds(cast(BuilderClient, builder))
    await builds.ensure_built(repo)

    assert await _settled(builds, repo) == {"tracker": "succeeded"}
    assert [files for _, _, files in builder.built] == [{"flake.nix", "flake.lock"}]


@pytest.mark.anyio
async def test_next_to_a_local_skill_an_external_one_still_gets_only_the_flake_and_its_lock(repo: Path) -> None:
    """Each build gets only what its key covers: skillsFlake evaluates every skill on its own, so the
    external one never reads the local one's flake.nix (nix/skills/tests.nix checks that side)."""
    _write_skills_flake(repo, ["weather"], external=("tracker",))
    _commit(repo, "a local and an external skill")
    builder = FakeBuilder()
    builds = SkillBuilds(cast(BuilderClient, builder))
    await builds.ensure_built(repo)

    assert await _settled(builds, repo) == {"tracker": "succeeded", "weather": "succeeded"}
    archives = {skill: {name.rstrip("/") for name in files} for _, skill, files in builder.built}
    assert archives["tracker"] == {"flake.nix", "flake.lock"}
    assert archives["weather"] == {"flake.nix", "flake.lock", "weather", "weather/SKILL.md", "weather/flake.nix"}


@pytest.mark.anyio
async def test_a_listed_directory_that_is_missing_fails_before_the_builder(repo: Path) -> None:
    _write_skills_flake(repo, ["weather", "gone"])
    _commit(repo, "list a skill without its directory")
    builder = FakeBuilder()
    builds = SkillBuilds(cast(BuilderClient, builder))
    await builds.ensure_built(repo)
    await _settled(builds, repo)

    gone = next(build for build in await builds.ensure_built(repo) if build.skill == "gone")
    assert gone.state == "failed" and "gone" in gone.detail
    assert [skill for _, skill, _ in builder.built] == ["weather"]


@pytest.mark.anyio
async def test_a_new_skills_tree_at_head_gets_an_update_check(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    builds = SkillBuilds(cast(BuilderClient, FakeBuilder()))
    started: list[Path] = []
    monkeypatch.setattr(builds.updates, "start", started.append)

    await builds.ensure_built(repo)
    tree = _git(repo, "rev-parse", "HEAD:skills")
    builds.updates._checks[repo] = UpdateCheck(skills_tree=tree, checked_at=datetime.now(UTC), skills={})
    await builds.ensure_built(repo)
    (repo / "notes.md").write_text("a commit that leaves skills/ alone\n")
    _commit(repo, "notes")
    await builds.ensure_built(repo)
    (repo / "skills" / "weather" / "SKILL.md").write_text("---\nname: weather\ndescription: changed\n---\n")
    _commit(repo, "change weather")
    await builds.ensure_built(repo)

    assert started == [repo, repo]


@pytest.mark.anyio
async def test_a_skill_directory_name_is_no_pattern(repo: Path) -> None:
    (repo / "skills" / "w*").mkdir()
    (repo / "skills" / "w*" / "SKILL.md").write_text("---\nname: w\ndescription: d\n---\n")
    write_skills_flake(repo / "skills", {"w": "w*"})
    _commit(repo, "a skill directory named like a glob")
    builder = FakeBuilder()
    builds = SkillBuilds(cast(BuilderClient, builder))
    await builds.ensure_built(repo)
    await _settled(builds, repo)

    assert [{name.rstrip("/") for name in files} for _, _, files in builder.built] == [
        {"flake.nix", "flake.lock", "w*", "w*/SKILL.md"}
    ]


@pytest.mark.anyio
async def test_config_json_rekeys_every_skill_and_goes_to_the_builder(repo: Path) -> None:
    builder = FakeBuilder()
    builds = SkillBuilds(cast(BuilderClient, builder))
    before = {build.skill: build.key for build in await builds.ensure_built(repo)}
    await _settled(builds, repo)

    (repo / "skills" / "config.json").write_text('{"weather": {"settings": {"CITY": "Berlin"}}}\n')
    _commit(repo, "configure weather")
    after = {build.skill: build.key for build in await builds.ensure_built(repo)}
    await _settled(builds, repo)

    assert all(after[name] != before[name] for name in before)
    archived = next(files for _, skill, files in reversed(builder.built) if skill == "weather")
    assert {"config.json", "flake.nix", "flake.lock", "weather"} <= archived
    weather = next(build for build in await builds.installable(repo) if build.skill == "weather")
    assert weather.settings == {"CITY": "Berlin"}


@pytest.mark.anyio
async def test_a_skill_turned_off_counts_as_not_listed(repo: Path) -> None:
    builder = FakeBuilder()
    builds = SkillBuilds(cast(BuilderClient, builder))
    await builds.ensure_built(repo)
    await _settled(builds, repo)
    weather = next(build for build in await builds.installable(repo) if build.skill == "weather")

    (repo / "skills" / "config.json").write_text('{"weather": {"enable": false}}\n')
    _commit(repo, "turn weather off")
    on = builder.answer
    builder.answer = lambda key, skill: (
        BuildResult(key=key, skill=skill, state="succeeded", metadata={"enable": False})
        if skill == "weather"
        else on(key, skill)
    )
    await builds.refresh(repo)
    await _settled(builds, repo)

    assert [build.skill for build in await builds.installable(repo)] == ["notes"]
    assert [info.name for info in builds.catalog(repo)] == ["notes"]
    assert builds.readable(repo, "weather") is None
    assert await builds.command_build(repo, weather.store_paths[0], "weather") is None
    off = await builds.wait_built(repo, "weather")
    assert off is not None and not off.enabled and off.detail == "Turned off in skills/config.json."

    # Another config change re-keys it: while it builds, it stays off instead of showing up as broken.
    (repo / "skills" / "config.json").write_text('{"notes": {"enable": true}, "weather": {"enable": false}}\n')
    _commit(repo, "touch config")
    release = _held(builder)
    await builds.ensure_built(repo)
    assert [info.name for info in builds.catalog(repo)] == ["notes"]
    assert builds.readable(repo, "weather") is None
    assert [build.skill for build in await builds.installable(repo)] == ["notes"]
    release.set()
    await _settled(builds, repo)


@pytest.mark.anyio
async def test_a_wrapper_finds_its_build_by_store_path_then_by_command(repo: Path) -> None:
    builds = SkillBuilds(cast(BuilderClient, FakeBuilder()))
    await builds.ensure_built(repo)
    await _settled(builds, repo)
    weather = next(build for build in await builds.installable(repo) if build.skill == "weather")
    workspace = f"/nix/store/{'z' * 32}-skill-weather"

    assert await builds.command_build(repo, weather.store_paths[0], "weather") == weather
    # A package built in the workspace gets the committed version of its command.
    assert await builds.command_build(repo, workspace, "weather") == weather
    assert await builds.command_build(repo, weather.store_paths[0], "unknown") is None


@pytest.mark.anyio
async def test_declarations_outlive_a_rekey_even_from_a_build_that_failed(repo: Path) -> None:
    declared = SkillDeclarations(settings={"CITY": SettingDeclaration(type="str")}, credentials={})
    builder = FakeBuilder()
    builder.answer = lambda key, skill: BuildResult(
        key=key, skill=skill, state="failed", log_tail="no value for CITY", declarations=declared
    )
    builds = SkillBuilds(cast(BuilderClient, builder))
    await builds.ensure_built(repo)
    await _settled(builds, repo)

    (repo / "skills" / "config.json").write_text('{"weather": {"settings": {"CITY": "Kiel"}}}\n')
    _commit(repo, "configure weather")
    held = _held(builder)
    weather = next(build for build in await builds.ensure_built(repo) if build.skill == "weather")

    assert weather.state == "building" and weather.declarations is None
    assert builds.declarations(repo, weather) == declared
    held.set()
