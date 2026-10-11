"""Preview of the prompt every LLM role sends, split into sections with token counts.

Each role's real agent is built by the same function its real calls use and run once against a
model that only records the request: the tool definitions and instructions shown are exactly
what would be sent. The sections are the same assembly pieces those instructions are joined
from, and a preview whose sections no longer add up to the recorded instructions fails loudly
instead of showing a prompt that is not the real one.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.tools import ToolDefinition

from .agent.deps import Deps
from .agent.tools import agent_instructions, build_session_info, create_agent
from .credentials import CredentialRegistry
from .knowledge import KnowledgeRepoHandle
from .memory.llm import structured_agent
from .memory.models import DigestLevel, ModelRole, PeriodDigestOutput, SessionExtractionOutput
from .memory.periods import month_key_for_week, period_dates, week_key
from .memory.prompt_block import MemoryBlock
from .memory.prompts import MONTH_DIGEST, SESSION_EXTRACT, WEEK_DIGEST, PromptTemplate, system_prompt
from .models.config import Config
from .models.session import MemorySnapshot, SessionState
from .models.user import UserConfig
from .prompt_prefix import shared_prompt_prefix
from .sandbox.manager import SandboxManager
from .security.context import SessionSecurity
from .security.sentinel import SENTINEL_INSTRUCTIONS, Sentinel, load_security_md
from .session.compaction_summarizer import FOLD_INSTRUCTIONS, summary_agent
from .session.titler import TITLE_INSTRUCTIONS, title_agent
from .usage import UsageTracker, count_text_tokens
from .user_defaults import apply_user_model_defaults, effective_memory_model, effective_memory_prompt_budget

_PREVIEW_SESSION_ID = "prompt-preview"
_PLACEHOLDER = "[Placeholder material for the preview. A real call has the {what} here.]"


class PromptRole(StrEnum):
    agent = "agent"
    sentinel = "sentinel"
    titler = "titler"
    compaction = "compaction"
    session_extract = "session_extract"
    week_digest = "week_digest"
    month_digest = "month_digest"


class PromptSection(BaseModel):
    key: str
    title: str
    text: str
    tokens: int


class PromptPreview(BaseModel):
    role: PromptRole
    model: str
    sections: list[PromptSection]
    total_tokens: int
    # Index of the last section inside the prompt cache prefix; None when the role sets no breakpoint.
    cacheable_until: int | None
    # Agent only.
    memory_budget_tokens: int | None
    memory_used_tokens: int | None


class PromptDriftError(RuntimeError):
    """The preview's sections are not the instructions the role's agent actually sends."""


@dataclass(frozen=True)
class PreviewInputs:
    config: Config
    user: str
    user_config: UserConfig
    data_dir: Path
    repo: KnowledgeRepoHandle
    sandbox: SandboxManager
    # (user, session id) -> the memory block a session starting now gets.
    memory_block: Callable[[str, str], MemoryBlock]
    now: datetime


async def preview_prompt(role: PromptRole, inputs: PreviewInputs) -> PromptPreview:
    match role:
        case PromptRole.agent:
            return await _agent(inputs)
        case PromptRole.sentinel:
            return await _sentinel(inputs)
        case PromptRole.titler:
            return await _titler(inputs)
        case PromptRole.compaction:
            return await _compaction(inputs)
        case PromptRole.session_extract | PromptRole.week_digest | PromptRole.month_digest:
            return await _memory_task(role, inputs)


# --- roles ---


async def _agent(inputs: PreviewInputs) -> PromptPreview:
    state = _fresh_session(inputs)
    model = state.agent_model_name or inputs.config.agent.model
    memory = inputs.memory_block(inputs.user, state.session_id)
    state.memory = MemorySnapshot(text=memory.text, as_of=inputs.now)
    deps = Deps(
        config=inputs.config,
        data_dir=inputs.data_dir,
        knowledge_dir=inputs.repo.knowledge_dir,
        session_state=state,
        sandbox=inputs.sandbox,
        security=SessionSecurity(state.session_id),
        sentinel=_sentinel_for(inputs, state),
        git_store=inputs.repo.git_store,
        skill_catalog=inputs.repo.skill_registry.scan(),
        agent_model=_recording_model(),
        agent_model_id=model,
        usage_tracker=UsageTracker(),
        credential_registry=CredentialRegistry(),
    )
    request = await _record(create_agent(deps), deps=deps)
    sections = [
        *_tool_sections(request, model),
        _section("shared_prefix", "Shared prefix", shared_prompt_prefix(deps.knowledge_dir, deps.skill_catalog), model),
        _section("role_instructions", "Agent instructions", agent_instructions(), model),
        _section("memory", "Memory", memory.text, model),
    ]
    cacheable_until = len(sections) - 1
    sections.append(_section("volatile", "Session info (volatile)", build_session_info(deps), model))
    _check_sections(request, sections)
    return _preview(
        PromptRole.agent,
        model,
        sections,
        cacheable_until=cacheable_until,
        memory_budget_tokens=effective_memory_prompt_budget(inputs.config, inputs.user_config),
        memory_used_tokens=memory.tokens,
    )


async def _sentinel(inputs: PreviewInputs) -> PromptPreview:
    state = _fresh_session(inputs)
    sentinel = _sentinel_for(inputs, state)
    model = state.sentinel_model_name or inputs.config.agent.sentinel_model
    request = await _record(sentinel.agent, deps=sentinel.skills_dir)
    sections = [
        *_tool_sections(request, model),
        _section("role_instructions", "Sentinel instructions", SENTINEL_INSTRUCTIONS, model),
        _section("security_md", "SECURITY.md", load_security_md(inputs.repo.knowledge_dir), model),
    ]
    _check_sections(request, sections)
    # The sentinel sets no cache breakpoint (see persistent-context.md).
    return _preview(PromptRole.sentinel, model, sections, cacheable_until=None)


async def _titler(inputs: PreviewInputs) -> PromptPreview:
    state = _fresh_session(inputs)
    model = state.title_model_name or inputs.config.agent.title_model
    request = await _record(title_agent(None, model_settings=None))
    sections = [
        *_tool_sections(request, model),
        _section("role_instructions", "Titler instructions", TITLE_INSTRUCTIONS, model),
    ]
    _check_sections(request, sections)
    return _preview(PromptRole.titler, model, sections, cacheable_until=None)


async def _compaction(inputs: PreviewInputs) -> PromptPreview:
    state = _fresh_session(inputs)
    config = inputs.config.agent
    model = state.compaction_model_name or config.compaction_model or config.title_model
    prefix = _prompt_prefix(inputs)
    request = await _record(summary_agent(FOLD_INSTRUCTIONS, prompt_prefix=prefix, model=None, model_settings=None))
    sections = [
        *_tool_sections(request, model),
        _section("shared_prefix", "Shared prefix", prefix, model),
        # Tool-output compaction swaps in its own, shorter instructions; folds are the larger call.
        _section("role_instructions", "Compaction instructions (fold)", FOLD_INSTRUCTIONS, model),
    ]
    _check_sections(request, sections)
    return _preview(PromptRole.compaction, model, sections, cacheable_until=len(sections) - 1)


async def _memory_task(role: PromptRole, inputs: PreviewInputs) -> PromptPreview:
    template, output_type, model_role, user_prompt = _memory_call(role, inputs)
    model = effective_memory_model(inputs.config, inputs.user_config, model_role)
    prefix = _prompt_prefix(inputs)
    request = await _record(structured_agent(system_prompt(template, prefix), output_type, None, model_settings=None))
    sections = [
        *_tool_sections(request, model),
        _section("shared_prefix", "Shared prefix", prefix, model),
        _section("role_instructions", f"{_ROLE_TITLES[role]} instructions", template.system, model),
    ]
    _check_sections(request, sections)
    cacheable_until = len(sections) - 1
    sections.append(_section("user_prompt", "User prompt (placeholder material)", user_prompt, model))
    return _preview(role, model, sections, cacheable_until=cacheable_until)


_ROLE_TITLES = {
    PromptRole.session_extract: "Session extraction",
    PromptRole.week_digest: "Week digest",
    PromptRole.month_digest: "Month digest",
}


def _memory_call(role: PromptRole, inputs: PreviewInputs) -> tuple[PromptTemplate, type[BaseModel], ModelRole, str]:
    """The template, output type and model role the role's handler uses, with a placeholder user prompt."""
    tz = ZoneInfo(inputs.user_config.timezone)
    week = week_key(inputs.now, tz)
    match role:
        case PromptRole.session_extract:
            payload = _PLACEHOLDER.format(what="session's rendered transcript")
            today = inputs.now.astimezone(tz).date().isoformat()
            user_prompt = SESSION_EXTRACT.user_prompt(payload, session_date=today)
            return SESSION_EXTRACT, SessionExtractionOutput, ModelRole.memory_low, user_prompt
        case PromptRole.week_digest:
            payload = _PLACEHOLDER.format(what="week's session extractions")
            first_day, last_day = period_dates(DigestLevel.week, week)
            user_prompt = WEEK_DIGEST.user_prompt(
                payload, period_key=week, first_day=first_day.isoformat(), last_day=last_day.isoformat()
            )
            return WEEK_DIGEST, PeriodDigestOutput, ModelRole.memory_high, user_prompt
        case _:
            payload = _PLACEHOLDER.format(what="month's week digests")
            user_prompt = MONTH_DIGEST.user_prompt(payload, period_key=month_key_for_week(week))
            return MONTH_DIGEST, PeriodDigestOutput, ModelRole.memory_high, user_prompt


# --- helpers ---


def _fresh_session(inputs: PreviewInputs) -> SessionState:
    state = SessionState.now(session_id=_PREVIEW_SESSION_ID)
    apply_user_model_defaults(state, inputs.user_config)
    return state


def _sentinel_for(inputs: PreviewInputs, state: SessionState) -> Sentinel:
    return Sentinel(
        model=state.sentinel_model_name or inputs.config.agent.sentinel_model,
        user=inputs.user,
        knowledge_dir=inputs.repo.knowledge_dir,
        skills_dir=inputs.repo.knowledge_dir / "skills",
        model_factory=lambda model_name, *, user: _recording_model(),
    )


def _prompt_prefix(inputs: PreviewInputs) -> str:
    return shared_prompt_prefix(inputs.repo.knowledge_dir, inputs.repo.skill_registry.scan())


@dataclass(frozen=True)
class _Request:
    instructions: str
    tools: list[ToolDefinition]


class _RequestRecordedError(Exception):
    def __init__(self, request: _Request) -> None:
        super().__init__("request recorded")
        self.request = request


def _recording_model() -> FunctionModel:
    def respond(_messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        tools = [*info.function_tools, *info.output_tools]
        raise _RequestRecordedError(_Request(instructions=info.instructions or "", tools=tools))

    return FunctionModel(respond)


async def _record(agent: Agent[Any, Any], *, deps: Any = None) -> _Request:
    """The first request *agent* would send. Nothing reaches a provider: the model only records."""
    try:
        await agent.run("Prompt preview.", deps=deps, model=_recording_model())
    except _RequestRecordedError as recorded:
        return recorded.request
    raise PromptDriftError("the agent finished without sending a request")


def _tool_sections(request: _Request, model: str) -> list[PromptSection]:
    """Tool definitions are part of every request, and Anthropic puts them before the system prompt."""
    if not request.tools:
        return []
    tools = [
        {"name": tool.name, "description": tool.description, "parameters": tool.parameters_json_schema}
        for tool in request.tools
    ]
    return [_section("tools", f"Tool definitions ({len(tools)})", json.dumps(tools, indent=2), model)]


def _check_sections(request: _Request, sections: list[PromptSection]) -> None:
    """The system sections, in order, must be the recorded instructions, with only separators between them."""
    rest = request.instructions
    for section in sections:
        # pydantic-ai strips each instruction, so a section's surrounding whitespace never arrives.
        if section.key == "tools" or not section.text.strip():
            continue
        head, found, rest = rest.partition(section.text.strip())
        if not found or head.strip(" \n-"):
            raise PromptDriftError(f"section {section.key!r} is not where the real prompt has it")
    if rest.strip(" \n-"):
        raise PromptDriftError("the real prompt has text the preview sections do not cover")


def _section(key: str, title: str, text: str, model: str) -> PromptSection:
    return PromptSection(key=key, title=title, text=text, tokens=count_text_tokens(text, model_name=model))


def _preview(
    role: PromptRole,
    model: str,
    sections: list[PromptSection],
    *,
    cacheable_until: int | None,
    memory_budget_tokens: int | None = None,
    memory_used_tokens: int | None = None,
) -> PromptPreview:
    return PromptPreview(
        role=role,
        model=model,
        sections=sections,
        total_tokens=sum(section.tokens for section in sections),
        cacheable_until=cacheable_until,
        memory_budget_tokens=memory_budget_tokens,
        memory_used_tokens=memory_used_tokens,
    )
