from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from ..api_keys import Access, Scope
from ..auth import UserIdentity
from ..prompt_preview import PreviewInputs, PromptPreview, PromptRole, preview_prompt
from .auth import require
from .state import server_module

server = server_module()
router = APIRouter(prefix="/prompts")

# The prompts carry the knowledge repo's AGENTS/SOUL/USER.md and memory, so reading them is a knowledge read.
_Reader = Annotated[UserIdentity, Depends(require(Scope.knowledge, Access.read))]


@router.get("/preview", response_model=PromptPreview)
async def get_preview(role: PromptRole, user: _Reader) -> PromptPreview:
    inputs = PreviewInputs(
        config=server._config,
        user=user.username,
        user_config=server._user_config(user.username),
        data_dir=server._data_dir,
        repo=server._knowledge_repo_registry.ensure_user_repo(user.username),
        sandbox=server._engine.sandbox_mgr,
        memory_block=server._memory_service.prompt_block,
        now=datetime.now(tz=UTC),
    )
    return await preview_prompt(role, inputs)
