"""Skills are built per tree when a head changes: only what changed, never what is disabled or has no flake."""

from __future__ import annotations

import asyncio
import io
import subprocess
import tarfile
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

import carapace.server as srv
from carapace.builder import skill_builds
from carapace.builder.client import BuilderClient
from carapace.builder.models import BuildResult
from carapace.builder.skill_builds import SkillBuilds
from carapace.spans import TurnTrace, attach

_METADATA = {
    "name": "weather",
    "commands": {
        "weather": {
            "description": "Current weather",
            "needs": {"domains": ["api.example.com"], "credentials": {}, "tunnels": []},
        }
    },
}


class FakeBuilder:
    """The builder API: stored results by tree, and a record of what was sent to build."""

    def __init__(self) -> None:
        self.stored: dict[str, BuildResult] = {}
        self.built: list[tuple[str, set[str]]] = []
        self.unreachable = False
        self.reject_with: int | None = None
        self.retries = 0
        self.answer = lambda tree: BuildResult(
            tree=tree, state="succeeded", store_paths=[f"/nix/store/{tree[:32]}-skill"], metadata=_METADATA
        )

    async def get(self, tree: str) -> BuildResult | None:
        if self.unreachable:
            raise httpx.ConnectError("builder down")
        return self.stored.get(tree)

    async def build(self, tree: str, archive: bytes, *, retry: bool = False) -> BuildResult:
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            self.built.append((tree, set(tar.getnames())))
        self.retries += retry
        if self.reject_with is not None:
            request = httpx.Request("PUT", f"http://builder/builds/{tree}")
            response = httpx.Response(self.reject_with, text="archive member escapes the skill directory")
            raise httpx.HTTPStatusError("rejected", request=request, response=response)
        self.stored[tree] = self.answer(tree)
        return self.stored[tree]


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def _write_skill(repo: Path, name: str, *, flake: bool = True, frontmatter: str = "") -> None:
    skill = repo / "skills" / name
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(f"---\nname: {name}\ndescription: demo\n{frontmatter}---\nBody\n")
    if flake:
        (skill / "flake.nix").write_text("{ outputs = _: { }; }\n")
        (skill / "flake.lock").write_text('{"nodes": {"root": {}}, "root": "root", "version": 7}\n')


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
    _write_skill(repo, "instructions-only", flake=False)
    _write_skill(repo, "parked", frontmatter="metadata:\n  carapace:\n    disabled: true\n")
    _commit(repo, "skills")
    return repo


async def _settled(builds: SkillBuilds, repo: Path) -> dict[str, str]:
    while running := list(builds._running.values()):
        await asyncio.gather(*running)
    return {build.skill: build.state for build in await builds.ensure_built(repo)}


@pytest.mark.anyio
async def test_a_head_change_builds_only_the_skill_trees_without_a_result(repo: Path) -> None:
    builder = FakeBuilder()
    builds = SkillBuilds(cast(BuilderClient, builder))

    first = await builds.ensure_built(repo)

    assert {build.skill: build.state for build in first} == {"notes": "building", "weather": "building"}
    assert await _settled(builds, repo) == {"notes": "succeeded", "weather": "succeeded"}
    assert sorted(files for _, files in builder.built) == [{"SKILL.md", "flake.lock", "flake.nix"}] * 2

    (repo / "skills" / "weather" / "flake.nix").write_text("{ outputs = _: { packages = { }; }; }\n")
    _commit(repo, "change weather")
    await builds.ensure_built(repo)
    await _settled(builds, repo)

    weather_tree = _git(repo, "rev-parse", "HEAD:skills/weather")
    assert len(builder.built) == 3
    assert builder.built[-1][0] == weather_tree


@pytest.mark.anyio
async def test_a_built_skill_reports_its_store_paths_and_commands(repo: Path) -> None:
    builds = SkillBuilds(cast(BuilderClient, FakeBuilder()))
    await builds.ensure_built(repo)
    await _settled(builds, repo)

    weather = next(build for build in await builds.ensure_built(repo) if build.skill == "weather")

    assert weather.tree == _git(repo, "rev-parse", "HEAD:skills/weather")
    assert weather.store_paths == [f"/nix/store/{weather.tree[:32]}-skill"]
    assert weather.commands["weather"].needs.domains == ["api.example.com"]


@pytest.mark.anyio
async def test_a_result_the_builder_already_has_is_not_built_again(repo: Path) -> None:
    builder = FakeBuilder()
    for name in ("weather", "notes"):
        tree = _git(repo, "rev-parse", f"HEAD:skills/{name}")
        builder.stored[tree] = builder.answer(tree)
    builds = SkillBuilds(cast(BuilderClient, builder))

    await builds.ensure_built(repo)

    assert await _settled(builds, repo) == {"notes": "succeeded", "weather": "succeeded"}
    assert builder.built == []


@pytest.mark.anyio
async def test_a_failed_build_is_reported_with_its_log(repo: Path) -> None:
    builder = FakeBuilder()
    builder.answer = lambda tree: BuildResult(
        tree=tree, state="failed", log_tail="error: flake.lock is missing nixpkgs"
    )
    builds = SkillBuilds(cast(BuilderClient, builder))
    await builds.ensure_built(repo)
    await _settled(builds, repo)

    [weather] = [build for build in await builds.ensure_built(repo) if build.skill == "weather"]

    assert (weather.state, weather.detail) == ("failed", "error: flake.lock is missing nixpkgs")
    assert len(builder.built) == 2


@pytest.mark.anyio
async def test_a_package_without_mkskill_metadata_counts_as_failed(repo: Path) -> None:
    builder = FakeBuilder()
    builder.answer = lambda tree: BuildResult(tree=tree, state="succeeded", store_paths=["/nix/store/x"], metadata=None)
    builds = SkillBuilds(cast(BuilderClient, builder))
    await builds.ensure_built(repo)
    await _settled(builds, repo)

    states = {build.skill: (build.state, build.detail) for build in await builds.ensure_built(repo)}

    assert states["weather"][0] == "failed"
    assert "build it with mkSkill" in states["weather"][1]


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
    assert weather.detail == "The builder refused the skill (400): archive member escapes the skill directory"
    assert len(builder.built) == 2


@pytest.mark.anyio
async def test_without_a_builder_flake_skills_are_unavailable(repo: Path) -> None:
    builds = SkillBuilds(None)

    states = {build.skill: build.state for build in await builds.ensure_built(repo)}

    assert states == {"notes": "unavailable", "weather": "unavailable"}


@pytest.mark.anyio
async def test_an_unreadable_skill_md_is_reported_and_not_built(repo: Path) -> None:
    (repo / "skills" / "weather" / "SKILL.md").write_text("---\nname: [unclosed\n---\n")
    _commit(repo, "break weather")
    builder = FakeBuilder()
    builds = SkillBuilds(cast(BuilderClient, builder))

    [weather] = [build for build in await builds.ensure_built(repo) if build.skill == "weather"]
    await _settled(builds, repo)

    assert weather.state == "failed"
    assert weather.detail.startswith("skills/weather/SKILL.md:")
    assert [tree for tree, _ in builder.built] == [_git(repo, "rev-parse", "HEAD:skills/notes")]


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
    real_git = skill_builds._git

    async def git(repo_dir: Path, *args: str) -> bytes:
        if args[0] == "archive":
            raise RuntimeError("git archive failed: fatal: not a tree object")
        return await real_git(repo_dir, *args)

    monkeypatch.setattr(skill_builds, "_git", git)
    builder = FakeBuilder()
    builds = SkillBuilds(cast(BuilderClient, builder))
    await builds.ensure_built(repo)

    assert await _settled(builds, repo) == {"notes": "failed", "weather": "failed"}
    assert builder.built == []


@pytest.mark.anyio
async def test_waiting_for_a_build_returns_its_result_and_is_a_span(repo: Path) -> None:
    builder = FakeBuilder()
    release = asyncio.Event()
    build = builder.build

    async def held_build(tree: str, archive: bytes, *, retry: bool = False) -> BuildResult:
        await release.wait()
        return await build(tree, archive, retry=retry)

    builder.build = held_build  # type: ignore[method-assign]
    builds = SkillBuilds(cast(BuilderClient, builder))
    trace = TurnTrace("t1", on_change=lambda _span: None)
    root = trace.start("turn", "turn", parent_id=None, attrs={})

    with attach(trace, root.span_id):
        waiting = asyncio.create_task(builds.wait_built(repo, "weather"))
        await asyncio.sleep(0.05)
        assert not waiting.done()
        release.set()
        weather, every = await waiting

    assert weather is not None and weather.state == "succeeded"
    assert {build.skill for build in every} == {"notes", "weather"}
    [wait] = [span for span in trace.spans.values() if span.name == "build wait"]
    assert (wait.kind, wait.attrs, wait.status) == ("skill", {"skill": "weather"}, "ok")


@pytest.mark.anyio
async def test_waiting_for_a_skill_without_a_flake_returns_none_at_once(repo: Path) -> None:
    builds = SkillBuilds(cast(BuilderClient, FakeBuilder()))

    instructions_only, _ = await builds.wait_built(repo, "instructions-only")

    assert instructions_only is None


class RootsBuilder(FakeBuilder):
    def __init__(self) -> None:
        super().__init__()
        self.roots: list[list[str]] = []

    async def put_roots(self, trees: list[str]) -> None:
        self.roots.append(trees)


@pytest.mark.anyio
async def test_the_builder_roots_are_the_flake_skill_trees_of_all_heads(repo: Path, tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    _git(other, "init", "-q")
    _write_skill(other, "weather", frontmatter="license: demo\n")
    _commit(other, "another user's weather")
    empty = tmp_path / "empty"
    empty.mkdir()
    _git(empty, "init", "-q")
    builder = RootsBuilder()

    await SkillBuilds(cast(BuilderClient, builder)).sync_roots([repo, other, empty])

    expected = {_git(repo, "rev-parse", f"HEAD:skills/{name}") for name in ("weather", "notes")}
    expected.add(_git(other, "rev-parse", "HEAD:skills/weather"))
    assert builder.roots == [sorted(expected)]


@pytest.mark.anyio
async def test_a_tree_no_head_references_is_looked_up_again(repo: Path) -> None:
    builder = RootsBuilder()
    builds = SkillBuilds(cast(BuilderClient, builder))
    await builds.ensure_built(repo)
    await _settled(builds, repo)
    old_weather = _git(repo, "rev-parse", "HEAD:skills/weather")

    (repo / "skills" / "weather" / "flake.nix").write_text("{ outputs = _: { packages = { }; }; }\n")
    _commit(repo, "change weather")
    await builds.sync_roots([repo])

    # The builder may collect the old tree, so its remembered result must not outlive the sync.
    assert old_weather not in builds._results
    assert _git(repo, "rev-parse", "HEAD:skills/notes") in builds._results


@pytest.mark.anyio
async def test_a_failed_build_is_retried_on_request(repo: Path) -> None:
    builder = FakeBuilder()
    builder.answer = lambda tree: BuildResult(tree=tree, state="failed", log_tail="error: connection reset")
    builds = SkillBuilds(cast(BuilderClient, builder))
    await builds.ensure_built(repo)
    assert (await _settled(builds, repo))["weather"] == "failed"

    builder.answer = FakeBuilder().answer
    await builds.retry(repo, "weather")

    assert (await _settled(builds, repo)) == {"weather": "succeeded", "notes": "failed"}
    assert builder.retries == 1


@pytest.mark.anyio
@pytest.mark.parametrize("name", ["weather", "parked", "instructions-only", "missing"])
async def test_only_a_failed_flake_skill_can_be_retried(repo: Path, name: str) -> None:
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
    _commit(broken, "skills")
    # A head that names a missing tree object: git ls-tree fails for this repo only.
    tree = _git(broken, "rev-parse", "HEAD^{tree}")
    (broken / ".git" / "objects" / tree[:2] / tree[2:]).unlink()
    builder = RootsBuilder()

    await SkillBuilds(cast(BuilderClient, builder)).sync_roots([broken, repo])

    expected = sorted(_git(repo, "rev-parse", f"HEAD:skills/{name}") for name in ("weather", "notes"))
    assert builder.roots == [expected]
