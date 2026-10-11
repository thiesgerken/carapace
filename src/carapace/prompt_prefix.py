"""The system prompt prefix shared by every role that acts as the user's agent.

Agent turns, compaction and memory tasks all start their instructions with this prefix, so each
role sees itself as the same agent, and providers that cache by prompt prefix can reuse it across
calls. It therefore holds only what is stable and the same for every role. Role instructions
follow it, and anything volatile (date, session, modes) goes last.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from .config import load_workspace_file
from .models.skills import SkillInfo

_SECTION_SEPARATOR = "\n\n---\n\n"
_PREFIX_FILES = ("AGENTS.md", "SOUL.md", "USER.md")


def shared_prompt_prefix(knowledge_dir: Path, skill_catalog: Sequence[SkillInfo]) -> str:
    # Each file is labeled with its name: role instructions refer to the files by name, and a
    # file's own headings are user-written and can't be relied on.
    sections = [_workspace_file_section(knowledge_dir, name) for name in _PREFIX_FILES]
    if skill_catalog:
        skills = "\n".join(f"- **{skill.name}**: {skill.description.strip()}" for skill in skill_catalog)
        sections.append(f"# Available Skills\n\n{skills}")
    return join_prompt_sections(*sections)


def _workspace_file_section(knowledge_dir: Path, name: str) -> str:
    content = load_workspace_file(knowledge_dir, name).strip()
    return f"# {name}\n\n{content}" if content else ""


def join_prompt_sections(*sections: str) -> str:
    return _SECTION_SEPARATOR.join(section for section in sections if section)
