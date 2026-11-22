"""Tests for session title prompt building (no LLM tokens)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from carapace.session.titler import MAX_MESSAGE_CHARS, MAX_PROMPT_CHARS, generate_title


async def _title_prompt(events: list[dict[str, Any]], *, previous_title: str | None = None) -> str:
    """Run the titler against a fake agent and return the prompt it sent."""
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
        out = await generate_title(
            events,
            previous_title=previous_title,
            model="anthropic:claude-3-5-haiku-latest",
            user="thies",
            model_factory=lambda _m, *, user: MagicMock(),
        )

    assert out == "📌 t"
    assert len(prompts) == 1
    return prompts[0]


@pytest.mark.asyncio
async def test_generate_title_skips_slash_user_and_truncates() -> None:
    """Command-result echoes are omitted; user and assistant bodies are capped per message."""
    long = "x" * (MAX_MESSAGE_CHARS + 100)
    body = await _title_prompt(
        [
            {"role": "user", "content": "/model openai:gpt-4o"},
            {"role": "command", "command": "model", "data": {}},
            {"role": "user", "content": long},
            {"role": "assistant", "content": "ok"},
        ]
    )

    assert "/model" not in body
    assert "x" * MAX_MESSAGE_CHARS in body
    assert "x" * (MAX_MESSAGE_CHARS + 1) not in body


@pytest.mark.asyncio
async def test_generate_title_includes_unknown_slash_message() -> None:
    body = await _title_prompt([{"role": "user", "content": "/tmp"}, {"role": "assistant", "content": "ok"}])

    assert "User: /tmp" in body


@pytest.mark.asyncio
async def test_generate_title_cuts_the_tail_and_keeps_the_opening_request() -> None:
    events: list[dict[str, Any]] = [{"role": "user", "content": "OPENING " + "a" * MAX_MESSAGE_CHARS}]
    events += [{"role": "assistant", "content": "b" * MAX_MESSAGE_CHARS} for _ in range(5)]
    events.append({"role": "user", "content": "LATEST"})

    body = await _title_prompt(events)

    assert len(body) == MAX_PROMPT_CHARS
    assert body.startswith("User: OPENING ")
    assert "LATEST" not in body


@pytest.mark.asyncio
async def test_generate_title_appends_previous_title_after_the_cap() -> None:
    events: list[dict[str, Any]] = [{"role": "assistant", "content": "b" * MAX_MESSAGE_CHARS} for _ in range(5)]

    body = await _title_prompt(events, previous_title="📓 Tagebucheintrag hinzufügen")

    assert body.endswith(
        "Current title: 📓 Tagebucheintrag hinzufügen\nKeep it unless the topic is clearly different now."
    )
