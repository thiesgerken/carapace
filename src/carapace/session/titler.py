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
    before_llm_call: Callable[[], None] | None = None,
    model_factory: Callable[[str], Model] | None = None,
) -> str:
    """Build a short emoji-prefixed title from conversation events.

    Only user and assistant messages are included. User lines that start with
    ``/`` (slash commands) are skipped. Each line is truncated to 300 characters.
    The joined prompt is capped at ~2000 characters.
    """
    lines: list[str] = []
    for e in events:
        role = e.get("role")
        content = e.get("content", "")
        if role == "user":
            if not isinstance(content, str):
                content = str(content)
            if content.startswith("/"):
                continue
            lines.append(f"User: {content[:300]}")
        elif role == "assistant":
            if not isinstance(content, str):
                content = str(content)
            lines.append(f"Assistant: {content[:300]}")

    if not lines:
        return ""

    # Keep the prompt compact — at most ~2000 chars from the conversation
    prompt = "\n".join(lines)[:2000]

    resolved = model_factory(model) if model_factory is not None else infer_model(model)
    agent: Agent[None, str] = Agent(resolved, output_type=str, instructions=_SYSTEM_PROMPT, retries=1, output_retries=3)
    try:
        if before_llm_call is not None:
            before_llm_call()
        result = await agent.run(prompt)
        if usage_tracker:
            usage_tracker.record(model, "title", result.usage())
        return result.output.strip()
    except Exception:
        logger.opt(exception=True).warning("Title generation failed")
        return ""
