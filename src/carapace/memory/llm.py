"""Structured LLM calls for memory tasks: one short-lived agent per call, no tools."""

from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal
from typing import cast

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import UsageLimits

from ..llm import ModelFactory, model_settings_for_config
from ..models.config import Config
from ..usage import LlmRequestLogCapability, UsageTracker, provider_cost_usd_from_messages
from .prompts import PromptTemplate


@dataclass(frozen=True, slots=True)
class StructuredCall[OutputT: BaseModel]:
    output: OutputT
    input_tokens: int
    output_tokens: int
    # None when the model has no known pricing and the provider reported no cost.
    cost_usd: Decimal | None
    duration_ms: int


def capped_model_settings(config: Config, model: str, output_tokens_cap: int) -> ModelSettings:
    """The model's settings with ``max_tokens`` set to the output cap.

    Thinking models may already require a larger ``max_tokens`` (see ``model_settings_for_entry``);
    that larger value then becomes the cap, so estimates stay an upper bound.
    """
    settings = dict(model_settings_for_config(config, model) or {})
    settings["max_tokens"] = max(output_tokens_cap, cast(int, settings.get("max_tokens", 0)))
    return cast(ModelSettings, settings)


async def run_structured[OutputT: BaseModel](
    template: PromptTemplate,
    output_type: type[OutputT],
    user_prompt: str,
    *,
    model: str,
    user: str,
    model_factory: ModelFactory,
    model_settings: ModelSettings,
) -> StructuredCall[OutputT]:
    """Run *user_prompt* (built by ``template.user_prompt``) and return the validated output.

    ``max_tokens`` from *model_settings* (see ``capped_model_settings``) also caps the output
    tokens of the whole run, output retries included; exceeding it raises and fails the task.
    """
    agent = Agent(
        model_factory(model, user=user),
        output_type=output_type,
        instructions=template.system,
        model_settings=model_settings,
        capabilities=[LlmRequestLogCapability(source="memory")],
        retries={"output": 2},
    )
    started = time.monotonic()
    result = await agent.run(user_prompt, usage_limits=UsageLimits(output_tokens_limit=model_settings["max_tokens"]))
    duration_ms = round((time.monotonic() - started) * 1000)

    usage = result.usage
    tracker = UsageTracker()
    tracker.record(model, "memory", usage, cost_usd=provider_cost_usd_from_messages(result.new_messages()))
    return StructuredCall(
        output=result.output,
        input_tokens=usage.input_tokens or 0,
        output_tokens=usage.output_tokens or 0,
        cost_usd=tracker.estimated_cost().get(model),
        duration_ms=duration_ms,
    )
