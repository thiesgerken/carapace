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
from carapace.builder.client import BuilderClient
from carapace.builder.models import BuildResult
from carapace.builder.skill_builds import SkillBuilds

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
        self.answer = lambda tree: BuildResult(
            tree=tree, state="succeeded", store_paths=[f"/nix/store/{tree[:32]}-skill"], metadata=_METADATA
        )

    async def get(self, tree: str) -> BuildResult | None:
        if self.unreachable:
            raise httpx.ConnectError("builder down")
        return self.stored.get(tree)

    async def build(self, tree: str, archive: bytes) -> BuildResult:
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            self.built.append((tree, set(tar.getnames())))
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
async def test_an_unreachable_builder_keeps_no_result_and_is_asked_again(repo: Path) -> None:
    builder = FakeBuilder()
    builder.unreachable = True
    builds = SkillBuilds(cast(BuilderClient, builder))
    await builds.ensure_built(repo)

    assert await _settled(builds, repo) == {"notes": "building", "weather": "building"}

    builder.unreachable = False
    assert await _settled(builds, repo) == {"notes": "succeeded", "weather": "succeeded"}


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
