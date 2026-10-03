"""ChatGPT subscription (OpenAI Codex) accounts: credential storage, login flow, per-user providers."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx2
import pytest
from pydantic_ai.models.openai_codex import OpenAICodexModel
from pydantic_ai.providers.openai_codex import CredentialsRefreshError, OpenAICodexCredentials
from pydantic_ai.usage import RunUsage

from carapace import codex_auth
from carapace.auth import AuthStore
from carapace.codex_auth import (
    CodexAccounts,
    CodexCredentialStore,
    CodexLoginError,
    CodexNotConnectedError,
    UserCodexCredentialSource,
)
from carapace.database.engine import SessionFactory
from carapace.llm import make_model_factory
from carapace.models.config import AuthConfig, Config
from carapace.usage import UsageTracker

_CODEX_MODEL = "openai-codex:gpt-5.5"


def _jwt(claims: dict[str, object]) -> str:
    def segment(data: dict[str, object]) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()

    return f"{segment({'alg': 'none'})}.{segment(claims)}.sig"


def _access_token(account_id: str, email: str | None = None) -> str:
    claims: dict[str, object] = {
        "exp": int((datetime.now(tz=UTC) + timedelta(days=1)).timestamp()),
        "https://api.openai.com/auth": {"chatgpt_account_id": account_id},
    }
    if email is not None:
        claims["https://api.openai.com/profile"] = {"email": email}
    return _jwt(claims)


def _credentials(account_id: str, refresh_token: str = "refresh-1") -> OpenAICodexCredentials:
    return OpenAICodexCredentials(
        access_token=_access_token(account_id), refresh_token=refresh_token, account_id=account_id
    )


@pytest.fixture()
def store(db_factory: SessionFactory, tmp_path) -> CodexCredentialStore:
    auth = AuthStore(db_factory, AuthConfig(), tmp_path)
    for username in ("thies", "ada"):
        auth.create_user(username=username, password="secret")
    return CodexCredentialStore(db_factory)


@pytest.fixture()
def token_requests(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, list[str]]]:
    """Replace OpenAI's OAuth token endpoint; records each posted form."""
    requests: list[dict[str, list[str]]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert str(request.url) == "https://auth.openai.com/oauth/token"
        form = parse_qs(request.content.decode())
        requests.append(form)
        if form["code"] == ["bad-code"]:
            return httpx2.Response(400, json={"error": "invalid_grant", "error_description": "code expired"})
        return httpx2.Response(
            200,
            json={
                "access_token": _access_token("acct-thies", email="thies@example.com"),
                "refresh_token": "refresh-from-login",
                "id_token": _jwt({"https://api.openai.com/auth": {"chatgpt_account_id": "acct-thies"}}),
            },
        )

    class _TokenEndpointClient(httpx2.AsyncClient):
        def __init__(self, **kwargs: object) -> None:
            super().__init__(transport=httpx2.MockTransport(handler), **kwargs)  # type: ignore[arg-type]

    # The flow builds a throwaway client per token request, with no transport hook.
    monkeypatch.setattr(httpx2, "AsyncClient", _TokenEndpointClient)
    return requests


def _redirect_url(authorize_url: str, *, code: str = "auth-code") -> str:
    state = parse_qs(urlsplit(authorize_url).query)["state"][0]
    return f"http://localhost:1455/auth/callback?{urlencode({'code': code, 'state': state})}"


# --- credential store / source ---


def test_store_round_trips_credentials(store: CodexCredentialStore) -> None:
    store.connect("thies", _credentials("acct-1"), email="thies@example.com")

    assert store.load("thies") == _credentials("acct-1")
    connection = store.connection("thies")
    assert connection is not None
    assert connection.email == "thies@example.com"


def test_store_load_without_connection_asks_user_to_connect(store: CodexCredentialStore) -> None:
    with pytest.raises(CodexNotConnectedError, match="Settings"):
        store.load("thies")
    assert store.connection("thies") is None


def test_store_rotate_never_recreates_a_disconnected_row(store: CodexCredentialStore) -> None:
    store.connect("thies", _credentials("acct-1"), email=None)
    assert store.disconnect("thies")

    with pytest.raises(CodexNotConnectedError):
        store.rotate("thies", _credentials("acct-1", refresh_token="refresh-2"))
    assert store.connection("thies") is None


async def test_credential_source_loads_and_saves_its_users_row(store: CodexCredentialStore) -> None:
    store.connect("thies", _credentials("acct-thies"), email=None)
    store.connect("ada", _credentials("acct-ada"), email=None)
    source = UserCodexCredentialSource(store, "thies")

    rotated = _credentials("acct-thies", refresh_token="refresh-2")
    await source.save(rotated)

    assert await source.load() == rotated
    assert store.load("ada") == _credentials("acct-ada")


# --- login flow ---


async def test_complete_login_exchanges_code_and_stores_credentials(
    store: CodexCredentialStore, token_requests: list[dict[str, list[str]]]
) -> None:
    accounts = CodexAccounts(store)
    authorize_url = accounts.start_login("thies")

    connection = await accounts.complete_login("thies", _redirect_url(authorize_url))

    assert connection.email == "thies@example.com"
    assert token_requests[0]["code"] == ["auth-code"]
    assert token_requests[0]["redirect_uri"] == ["http://localhost:1455/auth/callback"]
    stored = store.load("thies")
    assert stored.account_id == "acct-thies"
    assert stored.refresh_token == "refresh-from-login"


async def test_complete_login_surfaces_a_rejected_code(
    store: CodexCredentialStore, token_requests: list[dict[str, list[str]]]
) -> None:
    accounts = CodexAccounts(store)
    authorize_url = accounts.start_login("thies")

    with pytest.raises(CredentialsRefreshError, match="code expired"):
        await accounts.complete_login("thies", _redirect_url(authorize_url, code="bad-code"))
    assert store.connection("thies") is None


async def test_complete_login_rejects_a_state_from_another_attempt(
    store: CodexCredentialStore, token_requests: list[dict[str, list[str]]]
) -> None:
    accounts = CodexAccounts(store)
    stale_url = accounts.start_login("thies")
    accounts.start_login("thies")

    with pytest.raises(CodexLoginError, match="different login attempt"):
        await accounts.complete_login("thies", _redirect_url(stale_url))
    assert token_requests == []
    assert store.connection("thies") is None


async def test_complete_login_rejects_another_users_redirect(
    store: CodexCredentialStore, token_requests: list[dict[str, list[str]]]
) -> None:
    accounts = CodexAccounts(store)
    thies_url = accounts.start_login("thies")

    with pytest.raises(CodexLoginError, match="No ChatGPT login is in progress"):
        await accounts.complete_login("ada", _redirect_url(thies_url))
    assert token_requests == []
    assert store.connection("ada") is None


async def test_complete_login_rejects_an_expired_login(
    store: CodexCredentialStore, token_requests: list[dict[str, list[str]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    accounts = CodexAccounts(store)
    authorize_url = accounts.start_login("thies")
    monkeypatch.setattr(codex_auth, "_LOGIN_TTL", timedelta(0))

    with pytest.raises(CodexLoginError, match="expired"):
        await accounts.complete_login("thies", _redirect_url(authorize_url))
    assert token_requests == []


@pytest.mark.parametrize(
    ("redirect_url", "message"),
    [
        ("http://localhost:1455/auth/callback?error=access_denied&error_description=User+cancelled", "User cancelled"),
        ("http://localhost:1455/auth/callback?state=only", "no 'code' and 'state'"),
        ("not a url", "no 'code' and 'state'"),
    ],
)
async def test_complete_login_rejects_unusable_redirects(
    store: CodexCredentialStore, redirect_url: str, message: str
) -> None:
    accounts = CodexAccounts(store)
    accounts.start_login("thies")

    with pytest.raises(CodexLoginError, match=message):
        await accounts.complete_login("thies", redirect_url)


async def test_disconnect_forgets_credentials_and_provider(store: CodexCredentialStore) -> None:
    accounts = CodexAccounts(store)
    store.connect("thies", _credentials("acct-thies"), email=None)
    provider = accounts.provider_for("thies")

    assert accounts.disconnect("thies")

    assert accounts.connection("thies") is None
    assert accounts.provider_for("thies") is not provider
    assert not accounts.disconnect("thies")


# --- per-user model factory ---


@pytest.fixture()
def codex_requests(monkeypatch: pytest.MonkeyPatch) -> list[httpx2.Request]:
    """Route every provider's HTTP client to a fake Codex backend; records the requests."""
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, json={"object": "list", "data": []})

    monkeypatch.setattr(
        codex_auth, "retry_http_client", lambda: httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    )
    return requests


def _codex_config() -> Config:
    return Config.model_validate(
        {
            "agent": {
                "model": _CODEX_MODEL,
                "sentinel_model": _CODEX_MODEL,
                "title_model": _CODEX_MODEL,
                "available_models": [_CODEX_MODEL],
            }
        }
    )


async def test_factory_builds_codex_models_with_each_users_credentials(
    store: CodexCredentialStore, codex_requests: list[httpx2.Request]
) -> None:
    store.connect("thies", _credentials("acct-thies"), email=None)
    store.connect("ada", _credentials("acct-ada"), email=None)
    accounts = CodexAccounts(store)
    factory = make_model_factory(_codex_config(), accounts.provider_for)

    thies_model = factory(_CODEX_MODEL, user="thies")
    ada_model = factory(_CODEX_MODEL, user="ada")
    assert isinstance(thies_model, OpenAICodexModel)
    assert isinstance(ada_model, OpenAICodexModel)
    await thies_model.client.models.list()
    await ada_model.client.models.list()

    assert [r.headers["chatgpt-account-id"] for r in codex_requests] == ["acct-thies", "acct-ada"]
    assert codex_requests[0].headers["authorization"] == f"Bearer {_access_token('acct-thies')}"


def test_factory_shares_one_provider_per_user(store: CodexCredentialStore) -> None:
    # The provider serializes token refreshes; a second provider for the same user could spend
    # the single-use refresh token concurrently.
    accounts = CodexAccounts(store)
    factory = make_model_factory(_codex_config(), accounts.provider_for)

    first = factory(_CODEX_MODEL, user="thies")
    second = factory(_CODEX_MODEL, user="thies")

    assert first.provider is second.provider
    assert first.provider is not factory(_CODEX_MODEL, user="ada").provider


async def test_codex_request_without_connection_raises_not_connected(
    store: CodexCredentialStore, codex_requests: list[httpx2.Request]
) -> None:
    # Constructing the model needs no credentials (platform validation relies on that); the
    # missing connection only surfaces on the first request, as an actionable error.
    model = make_model_factory(_codex_config(), CodexAccounts(store).provider_for)(_CODEX_MODEL, user="thies")

    with pytest.raises(CodexNotConnectedError, match="Connect one under Settings"):
        await model.client.models.list()
    assert codex_requests == []


# --- pricing ---


def test_codex_usage_is_priced_like_the_openai_api() -> None:
    usage = RunUsage(input_tokens=10_000, output_tokens=2_000, requests=1)
    codex = UsageTracker()
    codex.record("openai-codex:gpt-5.4", "agent", usage)
    api = UsageTracker()
    api.record("openai:gpt-5.4", "agent", usage)

    codex_cost = codex.estimated_cost()["openai-codex:gpt-5.4"]
    assert codex_cost > Decimal(0)
    assert codex_cost == api.estimated_cost()["openai:gpt-5.4"]
