"""Pydantic AI model construction: retry-capable HTTP and config-backed model factory."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Literal, Protocol, cast

from httpx2 import AsyncClient, HTTPStatusError, Timeout
from pydantic_ai.exceptions import UserError
from pydantic_ai.models import Model, infer_model
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
from pydantic_ai.models.openai_codex import OpenAICodexModel
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.profiles.anthropic import ANTHROPIC_THINKING_BUDGET_MAP
from pydantic_ai.providers import Provider, infer_provider, infer_provider_class
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.openai_codex import OpenAICodexProvider
from pydantic_ai.providers.openrouter import OpenRouterProvider
from pydantic_ai.retries import AsyncHTTPX2TenacityTransport, RetryConfig, wait_retry_after
from pydantic_ai.settings import ModelSettings
from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential

from .models.config import CODEX_PROVIDER, Config, agent_available_model_entries

ThinkingSetting = bool | Literal["minimal", "low", "medium", "high", "xhigh"]

# Output headroom reserved above a budget-based thinking allowance. Anthropic rejects
# requests where max_tokens <= thinking.budget_tokens, and pydantic_ai defaults max_tokens
# to 4096 — too small once thinking maps to a budget (e.g. True -> 10000).
_THINKING_OUTPUT_RESERVE = 8192

# Stand-in for an absent provider key: keeps model construction working so the failure
# surfaces as a provider auth error on the first request instead of blocking server startup.
_PLACEHOLDER_API_KEY = "carapace-unconfigured-api-key"


def retry_http_client() -> AsyncClient:
    transport = AsyncHTTPX2TenacityTransport(
        config=RetryConfig(
            retry=retry_if_exception_type((HTTPStatusError, ConnectionError)),
            wait=wait_retry_after(fallback_strategy=wait_exponential(multiplier=1, max=60), max_wait=300),
            stop=stop_after_attempt(5),
            reraise=True,
        ),
        validate_response=lambda r: r.raise_for_status() if r.status_code in (429, 502, 503, 504) else None,
    )
    return AsyncClient(transport=transport, timeout=Timeout(connect=15.0, read=300.0, write=15.0, pool=60.0))


# pydantic-ai v2 renamed the Google provider prefixes; keep pre-v2 configs working.
_PROVIDER_ALIASES = {"google-gla": "google", "google-vertex": "google-cloud"}


def normalize_provider_prefix(model_name: str) -> str:
    """Rewrite legacy ``provider:name`` prefixes (e.g. ``google-gla``) to their v2 names."""
    prefix, sep, rest = model_name.partition(":")
    if sep and prefix in _PROVIDER_ALIASES:
        return f"{_PROVIDER_ALIASES[prefix]}:{rest}"
    return model_name


def infer_model_with_retry_transport(model_name: str) -> Model:
    """Create a Pydantic AI model with retry-capable HTTP transport."""
    model_name = normalize_provider_prefix(model_name)
    http_client = retry_http_client()

    def _provider_factory(name: str) -> Provider:
        if name.startswith("gateway/"):
            return infer_provider(name)
        cls = infer_provider_class(name)
        params = inspect.signature(cls).parameters
        kwargs: dict[str, object] = {"http_client": http_client} if "http_client" in params else {}
        try:
            return cls(**kwargs)  # type: ignore[arg-type]
        except UserError:
            # Providers reject construction when no key is in the environment. A keyless
            # endpoint (self-hosted proxy behind ANTHROPIC_BASE_URL) is legitimate, and an
            # admin must be able to boot the server before configuring credentials, so hand
            # over a placeholder and let the provider answer with 401 if it does want a key.
            if "api_key" not in params:
                raise
            return cls(api_key=_PLACEHOLDER_API_KEY, **kwargs)  # type: ignore[arg-type]

    return infer_model(model_name, provider_factory=_provider_factory)


class DisabledModelError(ValueError):
    """Raised when a model exists in the catalog but is switched off."""


def resolve_available_model_entry(config: Config, model_name: str):
    entries = {e.model_id: e for e in agent_available_model_entries(config.agent)}
    entry = entries.get(model_name)
    if entry is None:
        raise ValueError(f"Model {model_name!r} is not registered in agent.available_models")
    if not entry.enabled:
        raise DisabledModelError(f"Model {model_name!r} is disabled")
    return entry


def model_supports_vision(config: Config, model_name: str) -> bool:
    """Whether the registered model accepts image input. Unknown ids are treated as text-only."""
    try:
        return resolve_available_model_entry(config, model_name).vision
    except ValueError:
        return False


def model_settings_for_entry(
    entry,
    *,
    default_thinking: ThinkingSetting | None = None,
) -> ModelSettings | None:
    settings: dict[str, object] = {}
    if entry.provider == "openrouter":
        settings["openrouter_usage"] = {"include": True}
    thinking = entry.thinking if entry.thinking is not None else default_thinking
    if thinking is not None:
        settings["thinking"] = thinking
        # Anthropic-specific: their API counts thinking tokens toward max_tokens and rejects
        # requests where max_tokens <= thinking.budget_tokens. pydantic_ai translates a unified
        # thinking level into an Anthropic budget only for budget-based models (those without
        # adaptive thinking, e.g. haiku-4-5), so we must raise max_tokens above that budget.
        # Other providers (openai, openrouter, google) bill thinking separately and ignore this.
        budget = ANTHROPIC_THINKING_BUDGET_MAP.get(thinking)
        if entry.provider == "anthropic" and budget is not None and "max_tokens" not in settings:
            settings["max_tokens"] = budget + _THINKING_OUTPUT_RESERVE
    if entry.thinking_budget_tokens is not None:
        settings["extra_body"] = {"thinking_budget_tokens": entry.thinking_budget_tokens}
    return cast(ModelSettings, settings) if settings else None


def model_settings_for_config(
    config: Config,
    model_name: str,
    *,
    default_thinking: ThinkingSetting | None = None,
) -> ModelSettings | None:
    entry = resolve_available_model_entry(config, model_name)
    return model_settings_for_entry(entry, default_thinking=default_thinking)


class ModelFactory(Protocol):
    """Builds a registered model for the user whose request it will serve.

    The user matters for providers that authenticate per user (ChatGPT subscriptions), so a model
    built for one user must never serve another user's requests.
    """

    def __call__(self, model_name: str, *, user: str) -> Model: ...


def make_model_factory(
    config: Config,
    codex_provider_for: Callable[[str], OpenAICodexProvider],
) -> ModelFactory:
    """Resolve registered model ids; OpenAI-compatible overrides use ``OpenAIProvider``."""

    def factory(model_name: str, *, user: str) -> Model:
        entry = resolve_available_model_entry(config, model_name)
        resolved_model_name = f"{entry.provider}:{entry.name}"
        if entry.provider == CODEX_PROVIDER:
            return OpenAICodexModel(entry.name, provider=codex_provider_for(user))
        if entry.provider == "openrouter":
            api_key: str | None = None
            if entry.api_key is not None:
                api_key = entry.api_key.resolve().get_secret_value()
            provider = OpenRouterProvider(api_key=api_key, http_client=retry_http_client())
            return OpenRouterModel(entry.name, provider=provider)
        if entry.provider in ("openai", "openai-chat", "openai-responses"):
            api_key: str | None = None
            if entry.api_key is not None:
                api_key = entry.api_key.resolve().get_secret_value()
            if entry.base_url is not None or entry.api_key is not None:
                provider = OpenAIProvider(
                    base_url=entry.base_url,
                    api_key=api_key,
                    http_client=retry_http_client(),
                )
                # openai-responses forces the Responses API even on a custom endpoint; openai and
                # openai-chat both use Chat Completions for OpenAI-compatible servers (llama.cpp etc.).
                model_cls = OpenAIResponsesModel if entry.provider == "openai-responses" else OpenAIChatModel
                return model_cls(entry.name, provider=provider)
        return infer_model_with_retry_transport(resolved_model_name)

    return factory
