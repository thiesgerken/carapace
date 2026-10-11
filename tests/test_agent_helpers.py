"""Tests for agent helper functions (no LLM tokens needed)."""

import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import MagicMock

import httpx2
import pytest
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.openai import OpenAIProvider

from carapace.agent import build_session_info, build_system_prompt, create_agent
from carapace.agent.deps import Deps
from carapace.credentials import CredentialRegistry
from carapace.git.store import GitStore
from carapace.models.config import AvailableModelEntry, Config
from carapace.models.session import MemorySnapshot, SessionState
from carapace.models.skills import SkillInfo
from carapace.prompt_prefix import shared_prompt_prefix
from carapace.sandbox.manager import SandboxManager
from carapace.security.context import SessionSecurity
from carapace.security.sentinel import Sentinel
from carapace.usage import UsageTracker


def test_build_system_prompt_minimal(tmp_path: Path):
    state = SessionState.now(session_id="test-123")
    deps = Deps(
        config=Config(),
        data_dir=tmp_path,
        knowledge_dir=tmp_path,
        session_state=state,
        rules=[],
        sandbox=MagicMock(spec=SandboxManager),
        security=SessionSecurity("test-123"),
        sentinel=MagicMock(spec=Sentinel),
        git_store=MagicMock(spec=GitStore),
        agent_model=MagicMock(spec=Model),
        agent_model_id="anthropic:claude-sonnet-4-6",
        usage_tracker=UsageTracker(),
        credential_registry=CredentialRegistry(),
    )
    prompt = build_system_prompt(deps)
    today = date.today()
    assert (
        build_session_info(deps) == f"# Session Info\nToday's date: {today:%A}, {today:%Y-%m-%d}\nSession ID: test-123"
    )
    assert "test-123" not in prompt  # volatile, so it stays out of the cached instructions
    assert "/workspace/sessions/YYYY/MM/<session_id>/conversation.json" in prompt
    assert "Use `rg` to search archived conversations" in prompt
    assert "If the user tries to address the sentinel directly" in prompt


def test_build_system_prompt_with_agents_md(tmp_path: Path):
    (tmp_path / "AGENTS.md").write_text("# Agent Instructions\nBe helpful.")
    state = SessionState.now(session_id="s1")
    deps = Deps(
        config=Config(),
        data_dir=tmp_path,
        knowledge_dir=tmp_path,
        session_state=state,
        rules=[],
        sandbox=MagicMock(spec=SandboxManager),
        security=SessionSecurity("s1"),
        sentinel=MagicMock(spec=Sentinel),
        git_store=MagicMock(spec=GitStore),
        agent_model=MagicMock(spec=Model),
        agent_model_id="anthropic:claude-sonnet-4-6",
        usage_tracker=UsageTracker(),
        credential_registry=CredentialRegistry(),
    )
    prompt = build_system_prompt(deps)
    assert "Agent Instructions" in prompt
    assert "Be helpful" in prompt
    assert "If the user tries to address the sentinel directly" in prompt


def test_build_system_prompt_unattended_mentions_task_outputs(tmp_path: Path):
    state = SessionState.now(session_id="s1", unattended=True)
    deps = Deps(
        config=Config(),
        data_dir=tmp_path,
        knowledge_dir=tmp_path,
        session_state=state,
        sandbox=MagicMock(spec=SandboxManager),
        security=SessionSecurity("s1", unattended=True),
        sentinel=MagicMock(spec=Sentinel),
        git_store=MagicMock(spec=GitStore),
        agent_model=MagicMock(spec=Model),
        agent_model_id="anthropic:claude-sonnet-4-6",
        usage_tracker=UsageTracker(),
        credential_registry=CredentialRegistry(),
    )

    prompt = build_system_prompt(deps)

    assert "This session is unattended" in prompt
    assert "task_done" in prompt
    assert "task_failed" in prompt


def test_build_system_prompt_puts_the_memory_block_between_fixed_instructions_and_modes(tmp_path: Path):
    state = SessionState.now(session_id="s1", ask_mode=True)
    state.memory = MemorySnapshot(text="# Memory\n\n<memory>\nrecent work\n</memory>", as_of=datetime.now(tz=UTC))
    deps = Deps(
        config=Config(),
        data_dir=tmp_path,
        knowledge_dir=tmp_path,
        session_state=state,
        sandbox=MagicMock(spec=SandboxManager),
        security=SessionSecurity("s1", ask_mode=True),
        sentinel=MagicMock(spec=Sentinel),
        git_store=MagicMock(spec=GitStore),
        agent_model=MagicMock(spec=Model),
        agent_model_id="anthropic:claude-sonnet-4-6",
        usage_tracker=UsageTracker(),
        credential_registry=CredentialRegistry(),
    )

    prompt = build_system_prompt(deps)

    assert prompt.index("# Response format") < prompt.index("# Memory") < prompt.index("# Read-Only Session")


def test_build_system_prompt_ask_mode_mentions_read_only_limits(tmp_path: Path):
    state = SessionState.now(session_id="s1", ask_mode=True)
    deps = Deps(
        config=Config(),
        data_dir=tmp_path,
        knowledge_dir=tmp_path,
        session_state=state,
        sandbox=MagicMock(spec=SandboxManager),
        security=SessionSecurity("s1", ask_mode=True),
        sentinel=MagicMock(spec=Sentinel),
        git_store=MagicMock(spec=GitStore),
        agent_model=MagicMock(spec=Model),
        agent_model_id="anthropic:claude-sonnet-4-6",
        usage_tracker=UsageTracker(),
        credential_registry=CredentialRegistry(),
    )

    prompt = build_system_prompt(deps)

    assert "This session is in ASK mode" in prompt
    assert "Treat it as read-only outside the sandbox" in prompt
    assert "The security sentinel will enforce this policy" in prompt


def test_build_system_prompt_leads_with_the_shared_prefix_and_ends_volatile(tmp_path: Path):
    for name in ("AGENTS.md", "SOUL.md", "USER.md"):
        (tmp_path / name).write_text(f"{name.removesuffix('.md').lower()} content\n")
    catalog = [SkillInfo(name="web", description="Search the web.", path=tmp_path / "skills" / "web")]
    state = SessionState.now(session_id="s1", ask_mode=True)
    deps = Deps(
        config=Config(),
        data_dir=tmp_path,
        knowledge_dir=tmp_path,
        session_state=state,
        skill_catalog=catalog,
        sandbox=MagicMock(spec=SandboxManager),
        security=SessionSecurity("s1"),
        sentinel=MagicMock(spec=Sentinel),
        git_store=MagicMock(spec=GitStore),
        agent_model=MagicMock(spec=Model),
        agent_model_id="anthropic:claude-sonnet-4-6",
        usage_tracker=UsageTracker(),
        credential_registry=CredentialRegistry(),
    )

    prompt = build_system_prompt(deps)

    prefix = shared_prompt_prefix(tmp_path, catalog)
    assert prompt.startswith(prefix)
    assert prefix == "\n\n---\n\n".join(
        [
            "# AGENTS.md\n\nagents content",
            "# SOUL.md\n\nsoul content",
            "# USER.md\n\nuser content",
            "# Available Skills\n\n- **web**: Search the web.",
        ]
    )
    sections = ["# Sandbox Environment", "# Response format", "# Read-Only Session"]
    positions = [prompt.index(section) for section in sections]
    assert len(prefix) < positions[0] and positions == sorted(positions)


def _capture_agent_request(
    tmp_path: Path, model_id: str, make_model: Callable[[httpx2.AsyncClient], Model]
) -> tuple[Deps, dict]:
    """Runs an agent turn against a mocked provider and returns the deps and the first request sent."""
    requests: list[dict] = []

    def capture(request: httpx2.Request) -> httpx2.Response:
        requests.append(json.loads(request.content))
        return httpx2.Response(500)

    config = Config()
    config.agent.available_models.append(AvailableModelEntry.model_validate(model_id))
    deps = Deps(
        config=config,
        data_dir=tmp_path,
        knowledge_dir=tmp_path,
        session_state=SessionState.now(session_id="s1"),
        sandbox=MagicMock(spec=SandboxManager),
        security=SessionSecurity("s1"),
        sentinel=MagicMock(spec=Sentinel),
        git_store=MagicMock(spec=GitStore),
        agent_model=make_model(httpx2.AsyncClient(transport=httpx2.MockTransport(capture))),
        agent_model_id=model_id,
        usage_tracker=UsageTracker(),
        credential_registry=CredentialRegistry(),
    )
    with pytest.raises(ModelHTTPError):
        create_agent(deps).run_sync("hi", deps=deps)
    return deps, requests[0]


def test_agent_requests_cache_the_stable_instructions_but_not_the_session_info(tmp_path: Path):
    def anthropic(http_client: httpx2.AsyncClient) -> Model:
        client = AsyncAnthropic(api_key="x", max_retries=0, http_client=http_client)
        return AnthropicModel("claude-sonnet-4-6", provider=AnthropicProvider(anthropic_client=client))

    deps, request = _capture_agent_request(tmp_path, "anthropic:claude-sonnet-4-6", anthropic)
    breakpoint_ = {"type": "ephemeral", "ttl": "5m"}
    assert request["system"] == [
        {"type": "text", "text": build_system_prompt(deps), "cache_control": breakpoint_},
        {"type": "text", "text": build_session_info(deps)},
    ]
    assert request["tools"][-1]["cache_control"] == breakpoint_
    assert request["cache_control"] == breakpoint_  # the conversation, moved forward by Anthropic


def test_agent_requests_send_no_cache_options_to_openai(tmp_path: Path):
    # Some OpenAI backends (e.g. Codex) reject `prompt_cache_options`, and OpenAI caches prefixes on its own.
    def openai(http_client: httpx2.AsyncClient) -> Model:
        client = AsyncOpenAI(api_key="x", max_retries=0, http_client=http_client)
        return OpenAIResponsesModel("gpt-6.1-sol", provider=OpenAIProvider(openai_client=client))

    _, request = _capture_agent_request(tmp_path, "openai:gpt-6.1-sol", openai)
    assert "prompt_cache_options" not in request
