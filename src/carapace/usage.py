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


def _price_for_usage(model_key: str, u: ModelUsage) -> Decimal | None:
    provider_id, _, model_ref = model_key.partition(":")
    if not model_ref:
        model_ref, provider_id = provider_id, None
    try:
        return calc_price(
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
        ).total_price
    except LookupError:
        logger.debug(f"No pricing data for model {model_key}")
        return None


class UsageTracker(BaseModel):
    models: dict[str, ModelUsage] = {}
    categories: dict[str, ModelUsage] = {}
    category_by_model: dict[str, dict[str, ModelUsage]] = {}

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
        cm = self.category_by_model.setdefault(category, {})
        m_bucket = cm.setdefault(model, ModelUsage())
        m_bucket.input_tokens += usage.input_tokens or 0
        m_bucket.output_tokens += usage.output_tokens or 0
        m_bucket.cache_read_tokens += usage.cache_read_tokens or 0
        m_bucket.cache_write_tokens += usage.cache_write_tokens or 0
        m_bucket.input_audio_tokens += usage.input_audio_tokens or 0
        m_bucket.output_audio_tokens += usage.output_audio_tokens or 0
        m_bucket.cache_audio_read_tokens += usage.cache_audio_read_tokens or 0
        m_bucket.requests += usage.requests

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
            p = _price_for_usage(model_key, u)
            if p is not None:
                costs[model_key] = p
                total += p
        costs["total"] = total
        return costs

    def estimated_category_cost(self) -> dict[str, Decimal]:
        """Return estimated USD cost per usage category (tokens attributed per model)."""
        costs: dict[str, Decimal] = {}
        for category, by_model in self.category_by_model.items():
            cat_total = Decimal(0)
            for model_key, u in by_model.items():
                p = _price_for_usage(model_key, u)
                if p is not None:
                    cat_total += p
            costs[category] = cat_total
        return costs
