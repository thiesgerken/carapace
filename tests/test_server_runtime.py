from __future__ import annotations

import asyncio
import itertools
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call

import pytest

import carapace.server.runtime as server_runtime
from carapace.git.store import GitStore
from carapace.knowledge import KnowledgeRepoRegistry
from carapace.models.user import UserConfig
from carapace.sandbox.manager import SandboxManager
from carapace.server.runtime import KnowledgeGitConfig, KnowledgeGitRuntime, MatrixChannelManager, MatrixChannelState


class _FakeMatrixChannel:
    def __init__(self, *, start_error: Exception | None = None) -> None:
        self.start_error = start_error
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        if self.start_error is not None:
            raise self.start_error
        self.started = True

    async def stop(self) -> None:
        self.stopped = True


def _repo_registry(tmp_path: Path, git_store: GitStore) -> KnowledgeRepoRegistry:
    return KnowledgeRepoRegistry(tmp_path, git_store_factory=lambda _path: git_store)


@pytest.mark.anyio
async def test_matrix_channel_manager_replaces_running_channel() -> None:
    created: list[_FakeMatrixChannel] = []

    def channel_factory(_username: str, _config: UserConfig) -> _FakeMatrixChannel:
        channel = _FakeMatrixChannel()
        created.append(channel)
        return channel

    manager = MatrixChannelManager(channel_factory)
    config = UserConfig.model_validate({"channels": {"matrix": {"enabled": True}}})

    await manager.reload_user("thies", config)
    await manager.reload_user("thies", config)

    assert manager.channel_count == 1
    assert created[0].started is True
    assert created[0].stopped is True
    assert created[1].started is True


@pytest.mark.anyio
async def test_matrix_channel_manager_stops_old_channel_before_replacement() -> None:
    first = _FakeMatrixChannel()
    second = _FakeMatrixChannel(start_error=RuntimeError("login failed"))
    rollback = _FakeMatrixChannel()
    created = [first, second, rollback]

    def channel_factory(_username: str, _config: UserConfig) -> _FakeMatrixChannel:
        return created.pop(0)

    manager = MatrixChannelManager(channel_factory)
    config = UserConfig.model_validate({"channels": {"matrix": {"enabled": True}}})

    await manager.reload_user("thies", config)
    with pytest.raises(RuntimeError, match="login failed"):
        await manager.reload_user("thies", config)

    assert manager.channel_count == 1
    assert first.stopped is True
    assert rollback.started is True
    assert created == []


_MATRIX_ENABLED = UserConfig.model_validate({"channels": {"matrix": {"enabled": True}}})
_MATRIX_DISABLED = UserConfig()


class _ChannelSequence:
    """Channel factory handing out prepared fake channels in order."""

    def __init__(self, *channels: _FakeMatrixChannel) -> None:
        self.remaining = list(channels)
        self.created: list[_FakeMatrixChannel] = []

    def __call__(self, _username: str, _config: UserConfig) -> _FakeMatrixChannel:
        channel = self.remaining.pop(0)
        self.created.append(channel)
        return channel


@pytest.fixture
def instant_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    def delays() -> Iterator[float]:
        return itertools.repeat(0.0)

    monkeypatch.setattr(server_runtime, "_start_retry_delays", delays)


async def _wait_until(condition, *, timeout: float = 1.0) -> None:
    async with asyncio.timeout(timeout):
        while not condition():
            await asyncio.sleep(0)


def test_start_retry_delays_double_up_to_five_minutes() -> None:
    assert list(itertools.islice(server_runtime._start_retry_delays(), 9)) == [
        5.0,
        10.0,
        20.0,
        40.0,
        80.0,
        160.0,
        300.0,
        300.0,
        300.0,
    ]


@pytest.mark.anyio
async def test_matrix_channel_manager_retries_failed_startup_until_it_succeeds(instant_retries: None) -> None:
    first = _FakeMatrixChannel(start_error=RuntimeError("Matrix initial sync failed: None: unknown error"))
    second = _FakeMatrixChannel(start_error=RuntimeError("homeserver still down"))
    third = _FakeMatrixChannel()
    factory = _ChannelSequence(first, second, third)
    manager = MatrixChannelManager(factory)

    await manager.start_user_with_retry("thies", _MATRIX_ENABLED)

    assert manager.state_for_user("thies") == MatrixChannelState(
        status="failed", error="Matrix initial sync failed: None: unknown error"
    )
    assert first.stopped is True

    await _wait_until(lambda: third.started)

    assert manager.state_for_user("thies") == MatrixChannelState(status="running")
    assert manager.channel_count == 1
    assert second.stopped is True
    assert manager._start_retries == {}


@pytest.mark.anyio
async def test_matrix_channel_manager_failed_startup_keeps_other_users_running() -> None:
    def factory(username: str, _config: UserConfig) -> _FakeMatrixChannel:
        if username == "broken":
            return _FakeMatrixChannel(start_error=RuntimeError("login failed"))
        return _FakeMatrixChannel()

    manager = MatrixChannelManager(factory)

    await manager.start_user_with_retry("broken", _MATRIX_ENABLED)
    await manager.start_user_with_retry("thies", _MATRIX_ENABLED)

    assert manager.state_for_user("broken").status == "failed"
    assert manager.state_for_user("thies").status == "running"
    assert manager.state_for_user("nobody").status == "disabled"
    await manager.stop_all()


@pytest.mark.anyio
async def test_matrix_channel_manager_reload_cancels_startup_retry() -> None:
    failing = _FakeMatrixChannel(start_error=RuntimeError("login failed"))
    factory = _ChannelSequence(failing)
    manager = MatrixChannelManager(factory)
    await manager.start_user_with_retry("thies", _MATRIX_ENABLED)
    retry = manager._start_retries["thies"]

    await manager.reload_user("thies", _MATRIX_DISABLED)

    assert retry.cancelled()
    assert manager._start_retries == {}
    assert manager.state_for_user("thies") == MatrixChannelState(status="disabled")


@pytest.mark.anyio
async def test_matrix_channel_manager_stop_all_cancels_startup_retry() -> None:
    manager = MatrixChannelManager(_ChannelSequence(_FakeMatrixChannel(start_error=RuntimeError("login failed"))))
    await manager.start_user_with_retry("thies", _MATRIX_ENABLED)
    retry = manager._start_retries["thies"]

    await manager.stop_all()

    assert retry.cancelled()
    assert manager.state_for_user("thies") == MatrixChannelState(status="disabled")


@pytest.mark.anyio
async def test_matrix_channel_manager_reload_still_raises_and_records_error() -> None:
    manager = MatrixChannelManager(_ChannelSequence(_FakeMatrixChannel(start_error=RuntimeError("bad password"))))

    with pytest.raises(RuntimeError, match="bad password"):
        await manager.reload_user("thies", _MATRIX_ENABLED)

    assert manager._start_retries == {}
    assert manager.state_for_user("thies") == MatrixChannelState(status="failed", error="bad password")


@pytest.mark.anyio
async def test_knowledge_git_runtime_applies_remote_and_updates_sandbox_identity(tmp_path: Path) -> None:
    git_store = MagicMock(spec=GitStore)
    git_store.remote_branch = "main"
    git_store.author_template = "carapace <carapace@%h>"
    git_store.remote_configured = False
    git_store.add_remote = AsyncMock()
    git_store.remove_remote = AsyncMock()
    git_store.ensure_repo = AsyncMock()
    git_store.pull_from_remote = AsyncMock(return_value="Already up to date.")
    git_store.push_to_remote = AsyncMock()
    git_store.get_remote_url = AsyncMock(return_value=None)
    git_store.restore_remote = AsyncMock()
    sandbox_mgr = MagicMock(spec=SandboxManager)
    sandbox_mgr.refresh_git_identities = AsyncMock()
    runtime = KnowledgeGitRuntime(repo_registry=_repo_registry(tmp_path, git_store), sandbox_mgr=sandbox_mgr)

    config = KnowledgeGitConfig(
        owner="thies",
        remote="https://git.example.test/knowledge.git",
        branch="prod",
        author="Thies <thies@example.test>",
        token="secret-token",
    )

    await runtime.apply_user_config("thies", config)

    assert runtime.config_for_user("thies") == config
    assert git_store.remote_branch == "prod"
    assert git_store.author_template == "Thies <thies@example.test>"
    git_store.add_remote.assert_awaited_once_with("https://git.example.test/knowledge.git", "secret-token")
    git_store.pull_from_remote.assert_awaited_once()
    sandbox_mgr.refresh_git_identities.assert_awaited_once()


@pytest.mark.anyio
async def test_knowledge_git_runtime_rolls_back_when_remote_pull_fails(tmp_path: Path) -> None:
    previous = KnowledgeGitConfig(
        owner="thies",
        remote="https://git.example.test/old.git",
        branch="main",
        author="Thies <thies@example.test>",
        token="old-token",
    )
    git_store = MagicMock(spec=GitStore)
    git_store.remote_branch = previous.branch
    git_store.author_template = previous.author
    git_store.add_remote = AsyncMock()
    git_store.remove_remote = AsyncMock()
    git_store.ensure_repo = AsyncMock()
    git_store.pull_from_remote = AsyncMock(side_effect=RuntimeError("pull failed"))
    git_store.get_remote_url = AsyncMock(return_value="https://x-access-token:old-token@git.example.test/old.git")
    git_store.restore_remote = AsyncMock()
    sandbox_mgr = MagicMock(spec=SandboxManager)
    sandbox_mgr.refresh_git_identities = AsyncMock()
    runtime = KnowledgeGitRuntime(
        repo_registry=_repo_registry(tmp_path, git_store),
        sandbox_mgr=sandbox_mgr,
        current_configs={"thies": previous},
    )

    with pytest.raises(RuntimeError, match="pull failed"):
        await runtime.apply_user_config(
            "thies",
            KnowledgeGitConfig(
                owner="thies",
                remote="https://git.example.test/new.git",
                branch="prod",
                author="Thies <thies@example.test>",
                token="new-token",
            ),
        )

    assert runtime.config_for_user("thies") == previous
    assert git_store.remote_branch == previous.branch
    assert git_store.author_template == previous.author
    assert git_store.add_remote.await_args_list == [
        call("https://git.example.test/new.git", "new-token"),
        call(previous.remote, previous.token),
    ]
    git_store.restore_remote.assert_not_awaited()
    sandbox_mgr.refresh_git_identities.assert_awaited_once()


@pytest.mark.anyio
async def test_knowledge_git_runtime_rolls_back_to_existing_remote_when_cache_is_empty(tmp_path: Path) -> None:
    git_store = MagicMock(spec=GitStore)
    git_store.remote_branch = "main"
    git_store.author_template = "Thies <thies@example.test>"
    git_store.remote_configured = True
    git_store.add_remote = AsyncMock()
    git_store.remove_remote = AsyncMock()
    git_store.ensure_repo = AsyncMock()
    git_store.pull_from_remote = AsyncMock(side_effect=RuntimeError("pull failed"))
    git_store.get_remote_url = AsyncMock(return_value="https://x-access-token:old-token@git.example.test/old.git")
    git_store.restore_remote = AsyncMock()
    sandbox_mgr = MagicMock(spec=SandboxManager)
    sandbox_mgr.refresh_git_identities = AsyncMock()
    runtime = KnowledgeGitRuntime(repo_registry=_repo_registry(tmp_path, git_store), sandbox_mgr=sandbox_mgr)

    with pytest.raises(RuntimeError, match="pull failed"):
        await runtime.apply_user_config(
            "thies",
            KnowledgeGitConfig(
                owner="thies",
                remote="https://git.example.test/new.git",
                branch="prod",
                author="Thies <thies@example.test>",
                token="new-token",
            ),
        )

    git_store.restore_remote.assert_awaited_once_with("https://x-access-token:old-token@git.example.test/old.git")
    git_store.remove_remote.assert_not_awaited()


@pytest.mark.anyio
async def test_knowledge_git_runtime_push_callback_checks_current_remote_state(tmp_path: Path) -> None:
    git_store = MagicMock(spec=GitStore)
    git_store.remote_configured = False
    git_store.remote_branch = "main"
    git_store.author_template = "carapace <carapace@%h>"
    git_store.push_to_remote = AsyncMock()
    git_store.add_remote = AsyncMock()
    git_store.remove_remote = AsyncMock()
    git_store.ensure_repo = AsyncMock()
    git_store.pull_from_remote = AsyncMock(return_value="Already up to date.")
    git_store.get_remote_url = AsyncMock(return_value=None)
    git_store.restore_remote = AsyncMock()
    sandbox_mgr = MagicMock(spec=SandboxManager)
    sandbox_mgr.refresh_git_identities = AsyncMock()
    runtime = KnowledgeGitRuntime(repo_registry=_repo_registry(tmp_path, git_store), sandbox_mgr=sandbox_mgr)

    await runtime.push_if_configured("thies")
    git_store.push_to_remote.assert_not_awaited()

    await runtime.apply_user_config(
        "thies",
        KnowledgeGitConfig(
            owner="thies",
            remote="https://git.example.test/thies.git",
            branch="prod",
            author="Thies <thies@example.test>",
            token="secret-token",
        ),
    )
    git_store.remote_branch = "main"
    git_store.author_template = "carapace <carapace@%h>"
    git_store.remote_configured = True
    await runtime.push_if_configured("thies")

    git_store.push_to_remote.assert_awaited_once()
    assert git_store.remote_branch == "prod"
    assert git_store.author_template == "Thies <thies@example.test>"


@pytest.mark.anyio
async def test_pull_and_push_for_user_report_not_ok_without_remote(tmp_path: Path) -> None:
    git_store = MagicMock(spec=GitStore)
    git_store.remote_configured = False
    git_store.remote_branch = "main"
    git_store.author_template = "carapace <carapace@%h>"
    git_store.pull_from_remote = AsyncMock(return_value="Pulled")
    git_store.push_to_remote = AsyncMock()
    sandbox_mgr = MagicMock(spec=SandboxManager)
    runtime = KnowledgeGitRuntime(repo_registry=_repo_registry(tmp_path, git_store), sandbox_mgr=sandbox_mgr)

    pull_ok, pull_msg = await runtime.pull_for_user("thies")
    assert pull_ok is False
    assert "No external remote" in pull_msg
    git_store.pull_from_remote.assert_not_awaited()

    push_ok, push_msg = await runtime.push_for_user("thies")
    assert push_ok is False
    assert "No external remote" in push_msg
    git_store.push_to_remote.assert_not_awaited()

    git_store.remote_configured = True
    pull_ok, pull_msg = await runtime.pull_for_user("thies")
    assert pull_ok is True
    assert pull_msg == "Pulled"
    git_store.pull_from_remote.assert_awaited_once()

    push_ok, _ = await runtime.push_for_user("thies")
    assert push_ok is True
    git_store.push_to_remote.assert_awaited_once()


@pytest.mark.anyio
async def test_knowledge_git_runtime_keeps_other_user_repo_state_unchanged(tmp_path: Path) -> None:
    def make_git_store(branch: str, author: str) -> MagicMock:
        git_store = MagicMock(spec=GitStore)
        git_store.remote_branch = branch
        git_store.author_template = author
        git_store.remote_configured = False
        git_store.add_remote = AsyncMock()
        git_store.remove_remote = AsyncMock()
        git_store.ensure_repo = AsyncMock()
        git_store.pull_from_remote = AsyncMock(return_value="Already up to date.")
        git_store.push_to_remote = AsyncMock()
        git_store.get_remote_url = AsyncMock(return_value=None)
        git_store.restore_remote = AsyncMock()
        return git_store

    stores = {
        "thies": make_git_store("main", "carapace <carapace@%h>"),
        "ada": make_git_store("stable", "Ada <ada@example.test>"),
    }
    repo_registry = KnowledgeRepoRegistry(tmp_path, git_store_factory=lambda path: stores[path.name])
    sandbox_mgr = MagicMock(spec=SandboxManager)
    sandbox_mgr.refresh_git_identities = AsyncMock()
    runtime = KnowledgeGitRuntime(
        repo_registry=repo_registry,
        sandbox_mgr=sandbox_mgr,
        current_configs={
            "ada": KnowledgeGitConfig(
                owner="ada",
                remote="https://git.example.test/ada.git",
                branch="stable",
                author="Ada <ada@example.test>",
                token="ada-token",
            )
        },
    )

    repo_registry.get_for_user("thies")
    repo_registry.get_for_user("ada")

    thies_config = KnowledgeGitConfig(
        owner="thies",
        remote="https://git.example.test/thies.git",
        branch="prod",
        author="Thies <thies@example.test>",
        token="thies-token",
    )

    await runtime.apply_user_config("thies", thies_config)

    assert runtime.config_for_user("thies") == thies_config
    assert runtime.config_for_user("ada") is not None
    assert stores["thies"].remote_branch == "prod"
    assert stores["thies"].author_template == "Thies <thies@example.test>"
    stores["thies"].add_remote.assert_awaited_once_with("https://git.example.test/thies.git", "thies-token")
    stores["ada"].ensure_repo.assert_not_awaited()
    stores["ada"].add_remote.assert_not_awaited()
    assert stores["ada"].remote_branch == "stable"
    assert stores["ada"].author_template == "Ada <ada@example.test>"
