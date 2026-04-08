"""Pydantic AI model construction: retry-capable HTTP and config-backed model factory."""

from __future__ import annotations

import inspect
from collections.abc import Callable

from httpx import AsyncClient, HTTPStatusError, Timeout
from pydantic_ai.models import Model, infer_model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers import Provider, infer_provider, infer_provider_class
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.retries import AsyncTenacityTransport, RetryConfig, wait_retry_after
from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential

from carapace.models import Config, agent_available_model_entries


def retry_http_client() -> AsyncClient:
    transport = AsyncTenacityTransport(
        config=RetryConfig(
            retry=retry_if_exception_type((HTTPStatusError, ConnectionError)),
            wait=wait_retry_after(fallback_strategy=wait_exponential(multiplier=1, max=60), max_wait=300),
            stop=stop_after_attempt(5),
            reraise=True,
        ),
        validate_response=lambda r: r.raise_for_status() if r.status_code in (429, 502, 503, 504) else None,
    )
    return AsyncClient(transport=transport, timeout=Timeout(60.0))


def infer_model_with_retry_transport(model_name: str) -> Model:
    """Create a Pydantic AI model with retry-capable HTTP transport."""
    http_client = retry_http_client()

    def _provider_factory(name: str) -> Provider:
        if name.startswith("gateway/"):
            return infer_provider(name)
        if name in ("google-vertex", "google-gla"):
            return GoogleProvider(vertexai=name == "google-vertex", http_client=http_client)
        cls = infer_provider_class(name)
        if "http_client" in inspect.signature(cls).parameters:
            return cls(http_client=http_client)  # type: ignore
        return cls()

    return infer_model(model_name, provider_factory=_provider_factory)


def make_model_factory(config: Config) -> Callable[[str], Model]:
    """Resolve registered model ids; OpenAI-compatible overrides use ``OpenAIProvider``."""
    entries = {e.model_id: e for e in agent_available_model_entries(config.agent)}

    def factory(model_name: str) -> Model:
        entry = entries.get(model_name)
        if entry is None:
            raise ValueError(f"Model {model_name!r} is not registered in agent.available_models")
        resolved_model_name = f"{entry.provider}:{entry.name}"
        if entry.provider in ("openai", "openai-chat"):
            api_key: str | None = None
            if entry.api_key is not None:
                api_key = entry.api_key.resolve().get_secret_value()
            if entry.base_url is not None or entry.api_key is not None:
                http_client = retry_http_client()
                provider = OpenAIProvider(
                    base_url=entry.base_url,
                    api_key=api_key,
                    http_client=http_client,
                )
                return OpenAIChatModel(entry.name, provider=provider)
        return infer_model_with_retry_transport(resolved_model_name)

    return factory
