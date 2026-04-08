"""Session title generation via a lightweight LLM call."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from loguru import logger
from pydantic_ai import Agent
from pydantic_ai.models import Model, infer_model

from carapace.usage import UsageTracker

_SYSTEM_PROMPT = """\
Generate a very short title (3-8 words) for a chat conversation.
The title MUST start with a single emoji that captures the topic.
Do NOT use quotes around the title.
Reply with ONLY the title, nothing else.
"""


async def generate_title(
    events: list[dict[str, Any]],
    *,
    model: str,
    usage_tracker: UsageTracker | None = None,
    model_factory: Callable[[str], Model] | None = None,
) -> str:
    """Build a short emoji-prefixed title from conversation events.

    Only user and assistant messages are included in the prompt.
    The conversation is truncated to keep token usage low.
    """
    lines: list[str] = []
    for e in events:
        role = e.get("role")
        content = e.get("content", "")
        if role == "user":
            lines.append(f"User: {content}")
        elif role == "assistant":
            lines.append(f"Assistant: {content[:300]}")

    if not lines:
        return ""

    # Keep the prompt compact — at most ~2000 chars from the conversation
    prompt = "\n".join(lines)[:2000]

    resolved = model_factory(model) if model_factory is not None else infer_model(model)
    agent: Agent[None, str] = Agent(resolved, output_type=str, instructions=_SYSTEM_PROMPT, retries=1, output_retries=3)
    try:
        result = await agent.run(prompt)
        if usage_tracker:
            usage_tracker.record(model, "title", result.usage())
        return result.output.strip()
    except Exception:
        logger.opt(exception=True).warning("Title generation failed")
        return ""
