"""Tests for session title prompt building (no LLM tokens)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from carapace.session.titler import MAX_MESSAGE_CHARS, MAX_PROMPT_CHARS, generate_title


@pytest.mark.asyncio
async def test_generate_title_skips_slash_user_and_truncates() -> None:
    """Command-result echoes are omitted; user and assistant bodies are capped per message."""
    long = "x" * (MAX_MESSAGE_CHARS + 100)
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
    assert "x" * MAX_MESSAGE_CHARS in body
    assert "x" * (MAX_MESSAGE_CHARS + 1) not in body


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


@pytest.mark.asyncio
async def test_generate_title_cuts_the_tail_and_keeps_the_opening_request() -> None:
    events: list[dict[str, str]] = [{"role": "user", "content": "OPENING " + "a" * MAX_MESSAGE_CHARS}]
    events += [{"role": "assistant", "content": "b" * MAX_MESSAGE_CHARS} for _ in range(5)]
    events.append({"role": "user", "content": "LATEST"})
    prompts: list[str] = []

    async def _fake_run(*args: object, **_kw: object) -> MagicMock:
        prompts.append(str(args[0]))
        m = MagicMock()
        m.output = "📌 t"
        m.usage = MagicMock(return_value=MagicMock())
        return m

    with patch("carapace.session.titler.Agent") as agent_cls:
        inst = MagicMock()
        inst.run = AsyncMock(side_effect=_fake_run)
        agent_cls.return_value = inst
        await generate_title(
            events,
            model="anthropic:claude-3-5-haiku-latest",
            user="thies",
            model_factory=lambda _m, *, user: MagicMock(),
        )

    assert len(prompts[0]) == MAX_PROMPT_CHARS
    assert prompts[0].startswith("User: OPENING ")
    assert "LATEST" not in prompts[0]


@pytest.mark.asyncio
async def test_generate_title_appends_previous_title_after_the_cap() -> None:
    events: list[dict[str, str]] = [{"role": "assistant", "content": "b" * MAX_MESSAGE_CHARS} for _ in range(5)]
    prompts: list[str] = []

    async def _fake_run(*args: object, **_kw: object) -> MagicMock:
        prompts.append(str(args[0]))
        m = MagicMock()
        m.output = "📌 t"
        m.usage = MagicMock(return_value=MagicMock())
        return m

    with patch("carapace.session.titler.Agent") as agent_cls:
        inst = MagicMock()
        inst.run = AsyncMock(side_effect=_fake_run)
        agent_cls.return_value = inst
        await generate_title(
            events,
            previous_title="📓 Tagebucheintrag hinzufügen",
            model="anthropic:claude-3-5-haiku-latest",
            user="thies",
            model_factory=lambda _m, *, user: MagicMock(),
        )

    assert prompts[0].endswith(
        "Current title, given based on the first user message: 📓 Tagebucheintrag hinzufügen\n"
        "Keep it unless the topic is clearly different now."
    )
