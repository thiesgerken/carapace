from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .config import resolve_knowledge_repos_dir, resolve_user_knowledge_dir
from .git.store import GitStore
from .skills import SkillRegistry
from .usernames import normalize_username

type GitStoreFactory = Callable[[Path], GitStore]
type SkillRegistryFactory = Callable[[Path], SkillRegistry]
type SessionOwnerResolver = Callable[[str], str]


@dataclass(frozen=True)
class KnowledgeRepoHandle:
    owner: str
    knowledge_dir: Path
    git_store: GitStore
    skill_registry: SkillRegistry


type KnowledgeRepoResolver = Callable[[str], KnowledgeRepoHandle]


class KnowledgeRepoRegistry:
    def __init__(
        self,
        data_dir: Path,
        *,
        knowledge_repos_dir: Path | None = None,
        git_store_factory: GitStoreFactory | None = None,
        skill_registry_factory: SkillRegistryFactory | None = None,
    ) -> None:
        self._data_dir = data_dir
        self._knowledge_repos_dir = resolve_knowledge_repos_dir(data_dir, knowledge_repos_dir)
        self._git_store_factory = git_store_factory or GitStore
        self._skill_registry_factory = skill_registry_factory or SkillRegistry
        self._handles: dict[str, KnowledgeRepoHandle] = {}

    @property
    def knowledge_repos_dir(self) -> Path:
        return self._knowledge_repos_dir

    def get_for_user(self, username: str) -> KnowledgeRepoHandle:
        owner = normalize_username(username)
        cached = self._handles.get(owner)
        if cached is not None:
            return cached

        knowledge_dir = resolve_user_knowledge_dir(
            self._data_dir,
            owner,
            knowledge_repos_dir=self._knowledge_repos_dir,
        )
        handle = KnowledgeRepoHandle(
            owner=owner,
            knowledge_dir=knowledge_dir,
            git_store=self._git_store_factory(knowledge_dir),
            skill_registry=self._skill_registry_factory(knowledge_dir / "skills"),
        )
        self._handles[owner] = handle
        return handle

    def ensure_user_repo(self, username: str) -> KnowledgeRepoHandle:
        handle = self.get_for_user(username)
        handle.knowledge_dir.mkdir(parents=True, exist_ok=True)
        return handle

    def get_for_session(self, session_id: str, resolve_owner: SessionOwnerResolver) -> KnowledgeRepoHandle:
        return self.get_for_user(resolve_owner(session_id))


def contained_target(child: Path, root: Path) -> Path | None:
    """Resolve *child*, or return None if it is unreadable or out of bounds.

    Listing a directory means reading through its entries (a SKILL.md, a README, a
    session's conversation.json), and a symlink committed into the repo can point
    anywhere. Every such read resolves through here first, so the guards that
    ``resolve_target`` applies to the browsed path also cover the reads the listing
    does on its own: outside the repo, and inside ``.git`` (which holds the remote
    URL with its access token).
    """
    try:
        target = child.resolve(strict=True)
    except (OSError, RuntimeError):
        # Broken symlink, symlink loop, or an unreadable parent: nothing to read.
        return None
    if not target.is_relative_to(root):
        return None
    return None if ".git" in target.relative_to(root).parts else target
