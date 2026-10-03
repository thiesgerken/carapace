"""ChatGPT subscription (OpenAI Codex) accounts: per-user credentials, providers and the login flow."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

from openai import OpenAIError
from pydantic_ai.exceptions import ModelAPIError
from pydantic_ai.providers.openai_codex import (
    OpenAICodexCredentials,
    OpenAICodexCredentialSource,
    OpenAICodexOAuthFlow,
    OpenAICodexProvider,
)
from sqlalchemy import delete, update

from .database.engine import SessionFactory
from .database.models import UserCodexCredentialsRow
from .llm import retry_http_client
from .models.config import CODEX_PROVIDER

# The authorization code is short-lived on OpenAI's side as well; this only bounds how long an
# abandoned login occupies memory.
_LOGIN_TTL = timedelta(minutes=10)

_PROFILE_CLAIM = "https://api.openai.com/profile"


class CodexNotConnectedError(ModelAPIError, OpenAIError):
    """A Codex model was used by a user who has not connected a ChatGPT subscription.

    Also an ``OpenAIError`` because it is raised from the provider's credential loading inside the
    HTTP auth flow: the OpenAI SDK passes ``OpenAIError`` through unchanged, while anything else is
    retried as a transport failure and ends up as an opaque connection error.
    """

    def __init__(self, user: str) -> None:
        super().__init__(
            model_name=CODEX_PROVIDER,
            message=(
                f"User {user!r} has not connected a ChatGPT subscription. "
                "Connect one under Settings > ChatGPT subscription to use openai-codex models."
            ),
        )


class CodexLoginError(ValueError):
    """The pasted login redirect cannot complete a login."""


@dataclass(frozen=True)
class CodexConnection:
    email: str | None
    updated_at: datetime


class CodexCredentialStore:
    """Database rows holding each user's Codex OAuth credentials."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def connection(self, user: str) -> CodexConnection | None:
        with self._session_factory() as db:
            row = db.get(UserCodexCredentialsRow, user)
            return None if row is None else CodexConnection(email=row.email, updated_at=row.updated_at)

    def load(self, user: str) -> OpenAICodexCredentials:
        with self._session_factory() as db:
            row = db.get(UserCodexCredentialsRow, user)
            if row is None:
                raise CodexNotConnectedError(user)
            return OpenAICodexCredentials(
                access_token=row.access_token, refresh_token=row.refresh_token, account_id=row.account_id
            )

    def connect(self, user: str, credentials: OpenAICodexCredentials, *, email: str | None) -> CodexConnection:
        now = datetime.now(tz=UTC)
        with self._session_factory.begin() as db:
            db.merge(
                UserCodexCredentialsRow(
                    user=user,
                    access_token=credentials.access_token,
                    refresh_token=credentials.refresh_token,
                    account_id=credentials.account_id,
                    email=email,
                    updated_at=now,
                )
            )
        return CodexConnection(email=email, updated_at=now)

    def rotate(self, user: str, credentials: OpenAICodexCredentials) -> None:
        """Store refreshed tokens. Never recreates a row: a disconnect must not be undone by a refresh."""
        with self._session_factory.begin() as db:
            result = db.execute(
                update(UserCodexCredentialsRow)
                .where(UserCodexCredentialsRow.user == user)
                .values(
                    access_token=credentials.access_token,
                    refresh_token=credentials.refresh_token,
                    account_id=credentials.account_id,
                    updated_at=datetime.now(tz=UTC),
                )
            )
            if result.rowcount == 0:  # type: ignore[missing-attribute]
                raise CodexNotConnectedError(user)

    def disconnect(self, user: str) -> bool:
        with self._session_factory.begin() as db:
            result = db.execute(delete(UserCodexCredentialsRow).where(UserCodexCredentialsRow.user == user))
            return result.rowcount > 0  # type: ignore[missing-attribute]


class UserCodexCredentialSource(OpenAICodexCredentialSource):
    """One user's row in the credential store, as the provider's durable credential source."""

    def __init__(self, store: CodexCredentialStore, user: str) -> None:
        self._store = store
        self._user = user

    async def load(self) -> OpenAICodexCredentials:
        return self._store.load(self._user)

    async def save(self, credentials: OpenAICodexCredentials) -> None:
        self._store.rotate(self._user, credentials)


@dataclass(frozen=True)
class _PendingLogin:
    flow: OpenAICodexOAuthFlow
    started_at: datetime


class CodexAccounts:
    """Per-user ChatGPT subscription lifecycle: login, disconnect, and the provider serving requests.

    Every model of a user shares one provider: the provider is the single-flight unit for token
    refreshes, and refresh tokens are single-use, so two providers refreshing the same user's grant
    concurrently would spend the same token and log that user out.

    Pending logins live in memory. The server runs as a single replica and a login only has to
    survive the minutes between opening the authorize URL and pasting the redirect back.
    """

    def __init__(self, store: CodexCredentialStore) -> None:
        self._store = store
        self._providers: dict[str, OpenAICodexProvider] = {}
        self._pending: dict[str, _PendingLogin] = {}

    def provider_for(self, user: str) -> OpenAICodexProvider:
        """The user's provider. Construction does no I/O: credentials load on the first request."""
        provider = self._providers.get(user)
        if provider is None:
            provider = OpenAICodexProvider(
                credential_source=UserCodexCredentialSource(self._store, user),
                http_client=retry_http_client(),
            )
            self._providers[user] = provider
        return provider

    def connection(self, user: str) -> CodexConnection | None:
        return self._store.connection(user)

    def start_login(self, user: str) -> str:
        """Begin a login and return the authorize URL; replaces any login the user left pending."""
        flow = OpenAICodexOAuthFlow()
        self._pending[user] = _PendingLogin(flow=flow, started_at=datetime.now(tz=UTC))
        return flow.authorization_url()

    async def complete_login(self, user: str, redirect_url: str) -> CodexConnection:
        """Finish the user's pending login from the localhost redirect URL their browser landed on."""
        code, state = _parse_redirect(redirect_url)
        pending = self._pending.get(user)
        if pending is None or datetime.now(tz=UTC) - pending.started_at > _LOGIN_TTL:
            self._pending.pop(user, None)
            raise CodexLoginError("No ChatGPT login is in progress or it expired. Start the login again.")
        if state != pending.flow.state:
            raise CodexLoginError("This redirect URL belongs to a different login attempt. Start the login again.")
        del self._pending[user]
        credentials = await pending.flow.exchange_code(code)
        connection = self._store.connect(user, credentials, email=_email_from_access_token(credentials.access_token))
        # The cached provider holds the previous login in memory and would keep using it.
        self._providers.pop(user, None)
        return connection

    def disconnect(self, user: str) -> bool:
        self._pending.pop(user, None)
        self._providers.pop(user, None)
        return self._store.disconnect(user)


def _parse_redirect(redirect_url: str) -> tuple[str, str]:
    query = parse_qs(urlsplit(redirect_url.strip()).query)
    if error := query.get("error"):
        description = query.get("error_description", error)[0]
        raise CodexLoginError(f"ChatGPT login failed: {description}")
    code = query.get("code")
    state = query.get("state")
    if not code or not state:
        raise CodexLoginError("The pasted URL has no 'code' and 'state' parameters. Paste the full address bar URL.")
    return code[0], state[0]


def _email_from_access_token(access_token: str) -> str | None:
    """The account email from the access token's unverified profile claim, for display only."""
    try:
        segment = access_token.split(".")[1]
        payload = json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))
    except (IndexError, ValueError):
        return None
    profile = payload.get(_PROFILE_CLAIM) if isinstance(payload, dict) else None
    email = profile.get("email") if isinstance(profile, dict) else None
    return email if isinstance(email, str) and email else None
