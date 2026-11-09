from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai import RunContext
from pydantic_ai.messages import BinaryContent, ToolReturn
from pydantic_ai.models import Model
from pydantic_ai.usage import RunUsage

from carapace.agent.autonomy import AutonomyStreak
from carapace.agent.deps import Deps
from carapace.agent.tools import (
    _READ_TOOL_DESCRIPTION_TEXT,
    _READ_TOOL_DESCRIPTION_VISION,
    _image_media_type,
    create_agent,
)
from carapace.credentials import CredentialRegistry
from carapace.git.store import GitStore
from carapace.llm import model_supports_vision
from carapace.models.config import Config
from carapace.models.session import SessionState
from carapace.models.tooling import ToolResult
from carapace.sandbox.manager import SandboxManager
from carapace.security.context import SessionSecurity
from carapace.security.sentinel import Sentinel
from carapace.usage import UsageTracker

VISION_MODEL = "anthropic:claude-sonnet-4-6"
TEXT_MODEL = "anthropic:claude-haiku-4-5"


def _config(*, vision_default: bool) -> Config:
    return Config.model_validate(
        {
            "agent": {
                "model": VISION_MODEL,
                "available_models": [
                    {"provider": "anthropic", "name": "claude-sonnet-4-6", "vision": vision_default},
                    {"provider": "anthropic", "name": "claude-haiku-4-5"},
                ],
            }
        }
    )


def _deps(tmp_path: Path, *, model_id: str, vision: bool, results: list[ToolResult]) -> Deps:
    sandbox = MagicMock(spec=SandboxManager)
    sandbox.file_read = AsyncMock(return_value="TEXT-STUB")
    sandbox.file_read_bytes = AsyncMock(return_value=b"\x89PNG-bytes")
    return Deps(
        config=_config(vision_default=vision),
        data_dir=tmp_path,
        knowledge_dir=tmp_path,
        session_state=SessionState.now(session_id="s1", unattended=False),
        sandbox=sandbox,
        security=SessionSecurity("s1", unattended=False),
        sentinel=MagicMock(spec=Sentinel),
        git_store=MagicMock(spec=GitStore),
        agent_model=MagicMock(spec=Model),
        agent_model_id=model_id,
        usage_tracker=UsageTracker(),
        autonomy=AutonomyStreak(),
        credential_registry=CredentialRegistry(),
        tool_result_callback=results.append,
    )


def _read_tool(deps: Deps):
    agent = create_agent(deps)
    return agent._function_toolset.tools["read"]


def _ctx(deps: Deps) -> RunContext[Deps]:
    return RunContext(deps=deps, model=MagicMock(spec=Model), usage=RunUsage(), tool_call_approved=True)


# --- pure helpers ---


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("a.png", "image/png"),
        ("a.PNG", "image/png"),
        ("a.jpg", "image/jpeg"),
        ("a.jpeg", "image/jpeg"),
        ("a.gif", "image/gif"),
        ("a.webp", "image/webp"),
        ("a.svg", None),
        ("a.txt", None),
        ("noext", None),
    ],
)
def test_image_media_type(name: str, expected: str | None) -> None:
    assert _image_media_type(name) == expected


def test_model_supports_vision() -> None:
    cfg = _config(vision_default=True)
    assert model_supports_vision(cfg, VISION_MODEL) is True
    assert model_supports_vision(cfg, TEXT_MODEL) is False
    assert model_supports_vision(cfg, "anthropic:unknown") is False


def test_descriptions_differ() -> None:
    assert "Images" in _READ_TOOL_DESCRIPTION_VISION
    assert "Images" not in _READ_TOOL_DESCRIPTION_TEXT


# --- tool description switches on capability ---


def test_read_description_vision(tmp_path: Path) -> None:
    deps = _deps(tmp_path, model_id=VISION_MODEL, vision=True, results=[])
    assert _read_tool(deps).description == _READ_TOOL_DESCRIPTION_VISION


def test_read_description_text(tmp_path: Path) -> None:
    deps = _deps(tmp_path, model_id=VISION_MODEL, vision=False, results=[])
    assert _read_tool(deps).description == _READ_TOOL_DESCRIPTION_TEXT


# --- branch behavior ---


@pytest.mark.anyio
async def test_image_injected_when_vision_and_default_call(tmp_path: Path) -> None:
    results: list[ToolResult] = []
    deps = _deps(tmp_path, model_id=VISION_MODEL, vision=True, results=results)
    out = await _read_tool(deps).function(_ctx(deps), "logo.png")
    assert isinstance(out, ToolReturn)
    blocks = [c for c in out.content if isinstance(c, BinaryContent)]
    assert len(blocks) == 1
    assert blocks[0].media_type == "image/png"
    assert blocks[0].data == b"\x89PNG-bytes"
    deps.sandbox.file_read.assert_not_awaited()
    # callback still records a text summary
    assert results and isinstance(results[-1].output, str)


@pytest.mark.anyio
async def test_line_numbers_force_text_read(tmp_path: Path) -> None:
    deps = _deps(tmp_path, model_id=VISION_MODEL, vision=True, results=[])
    out = await _read_tool(deps).function(_ctx(deps), "logo.png", offset=0)
    assert out == "TEXT-STUB"
    deps.sandbox.file_read_bytes.assert_not_awaited()


@pytest.mark.anyio
async def test_svg_always_text(tmp_path: Path) -> None:
    deps = _deps(tmp_path, model_id=VISION_MODEL, vision=True, results=[])
    out = await _read_tool(deps).function(_ctx(deps), "icon.svg")
    assert out == "TEXT-STUB"
    deps.sandbox.file_read_bytes.assert_not_awaited()


@pytest.mark.anyio
async def test_no_vision_reads_text(tmp_path: Path) -> None:
    deps = _deps(tmp_path, model_id=VISION_MODEL, vision=False, results=[])
    out = await _read_tool(deps).function(_ctx(deps), "logo.png")
    assert out == "TEXT-STUB"
    deps.sandbox.file_read_bytes.assert_not_awaited()


@pytest.mark.anyio
async def test_oversized_image_falls_back_to_text(tmp_path: Path) -> None:
    deps = _deps(tmp_path, model_id=VISION_MODEL, vision=True, results=[])
    deps.sandbox.file_read_bytes = AsyncMock(return_value="File too large to return as an image: 9 bytes.")
    out = await _read_tool(deps).function(_ctx(deps), "logo.png")
    assert out == "TEXT-STUB"
    deps.sandbox.file_read.assert_awaited_once()
