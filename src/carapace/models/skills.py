from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, model_validator

# What a skill needs from outside the sandbox, and its MCP servers, are declared in its flake now
# (docs/skill-flakes.md).
_MOVED_TO_FLAKE = ("network", "credentials", "commands", "mcp")


class SkillCarapaceConfig(BaseModel):
    """Parsed carapace config declared inline in SKILL.md frontmatter."""

    hints: dict[str, str] = {}

    @model_validator(mode="before")
    @classmethod
    def _reject_moved_declarations(cls, data: Any) -> Any:
        # Ignoring them would leave a skill that looks declared and gets nothing.
        if isinstance(data, dict) and (moved := [key for key in _MOVED_TO_FLAKE if key in data]):
            raise ValueError(
                f"{', '.join(moved)} moved out of the frontmatter into the skill's flake "
                "(mkSkill needs and mcpCommands, see docs/skill-flakes.md)"
            )
        # Ignoring it would leave a skill active that its author turned off.
        if isinstance(data, dict) and "disabled" in data:
            raise ValueError("disabled is gone: a skill is active when skills/flake.nix lists it, so unlist it there")
        return data


class SkillInfo(BaseModel):
    name: str
    description: str = ""
    path: Path
