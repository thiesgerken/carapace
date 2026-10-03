"""Tests for session title prompt building (no LLM tokens)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from carapace.session.titler import generate_title


@pytest.mark.asyncio
async def test_generate_title_skips_slash_user_and_truncates() -> None:
    """Command-result echoes are omitted; user and assistant bodies are capped at 300 chars."""
    long = "x" * 400
    events: list[dict[str, Any]] = [
        {"role": "user", "content": "/model openai:gpt-4o"},
        {"role": "command", "command": "model", "data": {}},
        {"role": "user", "content": long},
        {"role": "assistant", "content": "ok"},
    ]
    prompts: list[str] = []

    async def _fake_run(*args: object, **_kw: object) -> MagicMock:
        prompt = str(args[0]) if args else ""
        prompts.append(prompt)
        m = MagicMock()
        m.output = "📌 t"
        m.usage = MagicMock(return_value=MagicMock())
        return m

    with patch("carapace.session.titler.Agent") as agent_cls:
        inst = MagicMock()
        inst.run = AsyncMock(side_effect=_fake_run)
        agent_cls.return_value = inst
        out = await generate_title(
            events,
            model="anthropic:claude-3-5-haiku-latest",
            user="thies",
            model_factory=lambda _m, *, user: MagicMock(),
        )

    assert out == "📌 t"
    assert len(prompts) == 1
    body = prompts[0]
    assert "/model" not in body
    assert "x" * 300 in body
    assert "x" * 301 not in body


@pytest.mark.asyncio
async def test_generate_title_includes_unknown_slash_message() -> None:
    events: list[dict[str, str]] = [
        {"role": "user", "content": "/tmp"},
        {"role": "assistant", "content": "ok"},
    ]
    prompts: list[str] = []

    async def _fake_run(*args: object, **_kw: object) -> MagicMock:
        prompt = str(args[0]) if args else ""
        prompts.append(prompt)
        m = MagicMock()
        m.output = "📌 t"
        m.usage = MagicMock(return_value=MagicMock())
        return m

    with patch("carapace.session.titler.Agent") as agent_cls:
        inst = MagicMock()
        inst.run = AsyncMock(side_effect=_fake_run)
        agent_cls.return_value = inst
        out = await generate_title(
            events,
            model="anthropic:claude-3-5-haiku-latest",
            user="thies",
            model_factory=lambda _m, *, user: MagicMock(),
        )

    assert out == "📌 t"
    assert "User: /tmp" in prompts[0]
