"""Session title generation via a lightweight LLM call."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from loguru import logger
from pydantic_ai import Agent
from pydantic_ai.models import infer_model
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import UsageLimits

from ..llm import ModelFactory
from ..usage import LlmRequestLogCapability, UsageTracker, provider_cost_usd_from_messages

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
    user: str,
    usage_tracker: UsageTracker | None = None,
    before_llm_call: Callable[[], None] | None = None,
    model_factory: ModelFactory | None = None,
    model_settings: ModelSettings | None = None,
    usage_limits: UsageLimits | None = None,
) -> str:
    """Build a short emoji-prefixed title from conversation events.

    Only user and assistant messages are included. User lines followed by a
    command-result event are skipped. Each line is truncated to 300 characters.
    The joined prompt is capped at ~2000 characters.
    """
    lines: list[str] = []
    for index, e in enumerate(events):
        role = e.get("role")
        content = e.get("content", "")
        if role == "user":
            if not isinstance(content, str):
                content = str(content)
            next_event = events[index + 1] if index + 1 < len(events) else None
            if content.startswith("/") and isinstance(next_event, dict) and next_event.get("role") == "command":
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

    resolved = model_factory(model, user=user) if model_factory is not None else infer_model(model)
    agent: Agent[None, str] = Agent(
        resolved,
        output_type=str,
        instructions=_SYSTEM_PROMPT,
        model_settings=model_settings,
        capabilities=[LlmRequestLogCapability(source="titler")],
        retries={"tools": 1, "output": 2},
    )
    try:
        if before_llm_call is not None:
            before_llm_call()
        result = await agent.run(prompt, usage_limits=usage_limits)
        if usage_tracker:
            usage_tracker.record(
                model,
                "title",
                result.usage,
                cost_usd=provider_cost_usd_from_messages(result.new_messages()),
            )
        return result.output.strip()
    except Exception:
        logger.opt(exception=True).warning("Title generation failed")
        return ""
