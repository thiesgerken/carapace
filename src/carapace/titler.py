"""Session title generation via a lightweight LLM call."""

from __future__ import annotations

from typing import Any

from loguru import logger
from pydantic_ai import Agent

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

    agent: Agent[None, str] = Agent(model, output_type=str, instructions=_SYSTEM_PROMPT)
    try:
        result = await agent.run(prompt)
        if usage_tracker:
            usage_tracker.record(model, "title", result.usage())
        return result.output.strip()
    except Exception:
        logger.opt(exception=True).warning("Title generation failed")
        return ""
