from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, Field, model_validator

# What a skill needs from outside the sandbox, and its MCP servers, are declared in its flake now
# (docs/skill-flakes.md).
_MOVED_TO_FLAKE = ("network", "credentials", "commands", "mcp")


class SkillCarapaceConfig(BaseModel):
    """Parsed carapace config declared inline in SKILL.md frontmatter."""

    disabled: Annotated[bool, Field(strict=True)] = False
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
        return data


class SkillInfo(BaseModel):
    name: str
    description: str = ""
    path: Path
