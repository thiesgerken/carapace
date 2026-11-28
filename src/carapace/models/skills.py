from __future__ import annotations

from pydantic import BaseModel


class SkillInfo(BaseModel):
    name: str
    description: str = ""
