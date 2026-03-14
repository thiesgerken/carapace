from __future__ import annotations

from decimal import Decimal

from genai_prices import Usage as PriceUsage
from genai_prices import calc_price
from loguru import logger
from pydantic import BaseModel
from pydantic_ai.usage import RunUsage


class ModelUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    input_audio_tokens: int = 0
    output_audio_tokens: int = 0
    cache_audio_read_tokens: int = 0
    requests: int = 0


class UsageTracker(BaseModel):
    models: dict[str, ModelUsage] = {}
    categories: dict[str, ModelUsage] = {}

    def record(self, model: str, category: str, usage: RunUsage) -> None:
        for bucket in (
            self.models.setdefault(model, ModelUsage()),
            self.categories.setdefault(category, ModelUsage()),
        ):
            bucket.input_tokens += usage.input_tokens or 0
            bucket.output_tokens += usage.output_tokens or 0
            bucket.cache_read_tokens += usage.cache_read_tokens or 0
            bucket.cache_write_tokens += usage.cache_write_tokens or 0
            bucket.input_audio_tokens += usage.input_audio_tokens or 0
            bucket.output_audio_tokens += usage.output_audio_tokens or 0
            bucket.cache_audio_read_tokens += usage.cache_audio_read_tokens or 0
            bucket.requests += usage.requests

    @property
    def total_input(self) -> int:
        return sum(m.input_tokens for m in self.models.values())

    @property
    def total_output(self) -> int:
        return sum(m.output_tokens for m in self.models.values())

    def estimated_cost(self) -> dict[str, Decimal]:
        """Return estimated USD cost per model and total. Keys: model names + 'total'."""
        costs: dict[str, Decimal] = {}
        total = Decimal(0)
        for model_key, u in self.models.items():
            provider_id, _, model_ref = model_key.partition(":")
            if not model_ref:
                model_ref, provider_id = provider_id, None
            try:
                price = calc_price(
                    PriceUsage(
                        input_tokens=u.input_tokens,
                        output_tokens=u.output_tokens,
                        cache_read_tokens=u.cache_read_tokens,
                        cache_write_tokens=u.cache_write_tokens,
                        input_audio_tokens=u.input_audio_tokens,
                        output_audio_tokens=u.output_audio_tokens,
                        cache_audio_read_tokens=u.cache_audio_read_tokens,
                    ),
                    model_ref=model_ref,
                    provider_id=provider_id,
                )
                costs[model_key] = price.total_price
                total += price.total_price
            except LookupError:
                logger.debug(f"No pricing data for model {model_key}")
        costs["total"] = total
        return costs
