from __future__ import annotations

from pathlib import Path

import pytest

from carapace.knowledge import KnowledgeRepoRegistry
from carapace.skills import SkillRegistry


def test_knowledge_repo_registry_returns_handle_for_normalized_owner(tmp_path: Path) -> None:
    registry = KnowledgeRepoRegistry(tmp_path)

    handle = registry.get_for_user("thies")

    assert handle.owner == "thies"
    assert handle.knowledge_dir == (tmp_path / "knowledges" / "thies").resolve()
    assert handle.git_store.repo_dir == handle.knowledge_dir
    assert isinstance(handle.skill_registry, SkillRegistry)
    assert handle.skill_registry.skills_dir == handle.knowledge_dir / "skills"


def test_knowledge_repo_registry_caches_handles_per_owner(tmp_path: Path) -> None:
    registry = KnowledgeRepoRegistry(tmp_path)

    first = registry.get_for_user("thies")
    second = registry.get_for_user("thies")

    assert second is first


def test_knowledge_repo_registry_ensures_user_repo_directory(tmp_path: Path) -> None:
    registry = KnowledgeRepoRegistry(tmp_path)

    handle = registry.ensure_user_repo("thies")

    assert handle.knowledge_dir.is_dir()


def test_knowledge_repo_registry_resolves_session_owner(tmp_path: Path) -> None:
    registry = KnowledgeRepoRegistry(tmp_path)

    handle = registry.get_for_session("sess-123", lambda session_id: "ada" if session_id == "sess-123" else "thies")

    assert handle.owner == "ada"
    assert handle.knowledge_dir == (tmp_path / "knowledges" / "ada").resolve()


def test_knowledge_repo_registry_uses_explicit_repos_dir(tmp_path: Path) -> None:
    repos_dir = tmp_path / "legacy-knowledge"
    registry = KnowledgeRepoRegistry(tmp_path, knowledge_repos_dir=repos_dir)

    handle = registry.get_for_user("thies")

    assert registry.knowledge_repos_dir == repos_dir.resolve()
    assert handle.knowledge_dir == (repos_dir / "thies").resolve()


def test_knowledge_repo_registry_rejects_noncanonical_owner(tmp_path: Path) -> None:
    registry = KnowledgeRepoRegistry(tmp_path)

    with pytest.raises(ValueError, match="username must be lowercase"):
        registry.get_for_user("Thies")


def test_knowledge_repo_registry_lists_the_repos_that_exist(tmp_path: Path) -> None:
    registry = KnowledgeRepoRegistry(tmp_path)
    assert registry.existing() == []

    registry.ensure_user_repo("thies")
    registry.ensure_user_repo("ada")

    assert [repo.owner for repo in registry.existing()] == ["ada", "thies"]
