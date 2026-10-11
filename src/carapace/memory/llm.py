"""Structured LLM calls for memory tasks: one short-lived agent per call, no tools."""

from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal
from typing import cast

from pydantic import BaseModel
from pydantic_ai import Agent, capture_run_messages
from pydantic_ai.exceptions import AgentRunError
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import RunUsage, UsageLimits

from ..llm import ModelFactory, model_settings_for_config, resolve_available_model_entry, with_prompt_cache
from ..models.config import Config
from ..usage import LlmRequestLogCapability, UsageTracker, count_text_tokens, provider_cost_usd_from_messages


@dataclass(frozen=True, slots=True)
class CallUsage:
    input_tokens: int
    output_tokens: int
    # None when the model has no known pricing and the provider reported no cost.
    cost_usd: Decimal | None
    duration_ms: int


@dataclass(frozen=True, slots=True)
class StructuredCall[OutputT: BaseModel]:
    output: OutputT
    usage: CallUsage


class LlmCallError(Exception):
    """The call failed after the provider may already have billed it; *usage* is what it cost."""

    def __init__(self, message: str, usage: CallUsage) -> None:
        super().__init__(message)
        self.usage = usage


class InputTooLargeError(ValueError):
    pass


def prompt_tokens(system: str, user_prompt: str, model: str) -> int:
    """Input token estimate for one call: system prompt plus user prompt."""
    return count_text_tokens(f"{system}\n\n{user_prompt}", model_name=model)


def system_tokens(system: str, model: str) -> int:
    """The part of ``prompt_tokens`` that goes through the prompt cache."""
    return count_text_tokens(system, model_name=model)


def ensure_fits_context(config: Config, model: str, input_tokens: int) -> None:
    """Fail before spending anything when the input cannot fit; unknown context windows pass."""
    max_input_tokens = resolve_available_model_entry(config, model).max_input_tokens
    if max_input_tokens is not None and input_tokens > max_input_tokens:
        raise InputTooLargeError(f"input too large: ~{input_tokens:,} tokens, {model} accepts {max_input_tokens:,}")


def capped_model_settings(config: Config, model: str, output_tokens_cap: int) -> ModelSettings:
    """The model's settings with ``max_tokens`` set to the output cap, caching the system prompt.

    Thinking models may already require a larger ``max_tokens`` (see ``model_settings_for_entry``);
    that larger value then becomes the cap, so estimates stay an upper bound.
    """
    settings = dict(with_prompt_cache(model_settings_for_config(config, model), conversation=False))
    settings["max_tokens"] = max(output_tokens_cap, cast(int, settings.get("max_tokens", 0)))
    return cast(ModelSettings, settings)


def structured_agent[OutputT: BaseModel](
    system: str, output_type: type[OutputT], model: Model | None, *, model_settings: ModelSettings | None
) -> Agent[None, OutputT]:
    """*model* None leaves it to the run, as the prompt preview does."""
    return Agent(
        model,
        output_type=output_type,
        instructions=system,
        model_settings=model_settings,
        capabilities=[LlmRequestLogCapability(source="memory")],
        retries={"output": 0},
    )


async def run_structured[OutputT: BaseModel](
    system: str,
    output_type: type[OutputT],
    user_prompt: str,
    *,
    model: str,
    user: str,
    model_factory: ModelFactory,
    model_settings: ModelSettings,
) -> StructuredCall[OutputT]:
    """Run *user_prompt* under the *system* prompt and return the validated output.

    Exactly one model request: no output retries, so the estimate (one prompt, ``max_tokens`` from
    *model_settings*) is an honest upper bound. An invalid output fails the task; a manual retry
    goes through the budget gate again.
    """
    agent = structured_agent(system, output_type, model_factory(model, user=user), model_settings=model_settings)
    usage = RunUsage()
    started = time.monotonic()
    # The run accumulates into *usage* and *messages* in place, so both survive a failed run:
    # rejected outputs and exceeded caps are billed and must count against the budget.
    with capture_run_messages() as messages:
        try:
            result = await agent.run(
                user_prompt,
                usage=usage,
                usage_limits=UsageLimits(request_limit=1, output_tokens_limit=model_settings["max_tokens"]),
            )
        except AgentRunError as exc:
            raise LlmCallError(str(exc), _call_usage(model, usage, messages, started)) from exc
    return StructuredCall(output=result.output, usage=_call_usage(model, usage, messages, started))


def _call_usage(model: str, usage: RunUsage, messages: list[ModelMessage], started: float) -> CallUsage:
    tracker = UsageTracker()
    tracker.record(model, "memory", usage, cost_usd=provider_cost_usd_from_messages(messages))
    return CallUsage(
        input_tokens=usage.input_tokens or 0,
        output_tokens=usage.output_tokens or 0,
        cost_usd=tracker.estimated_cost().get(model),
        duration_ms=round((time.monotonic() - started) * 1000),
    )
