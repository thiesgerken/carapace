from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from ..usernames import normalize_username


class MatrixConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MatrixTokenFile(MatrixConfigModel):
    """Schema for one persisted Matrix access token."""

    access_token: str
    device_id: str | None = None
    user_id: str | None = None
    user: str

    def belongs_to(self, owner: str, matrix_user_id: str | None) -> bool:
        """Whether this is the token of ``owner``'s channel for the Matrix account ``matrix_user_id``.

        Entries without a ``user_id`` cannot be told apart by account, so they count as the owner's.
        """
        return normalize_username(self.user) == normalize_username(owner) and self.user_id in (None, matrix_user_id)


class MatrixTokensFile(MatrixConfigModel):
    """Schema for the persisted ``matrix_token.yaml`` file, shared by every user's channel."""

    version: int = 1
    tokens: list[MatrixTokenFile] = []

    def without_tokens_of(self, owner: str, matrix_user_id: str | None) -> MatrixTokensFile:
        return self.model_copy(
            update={"tokens": [token for token in self.tokens if not token.belongs_to(owner, matrix_user_id)]}
        )

    def with_token(self, token: MatrixTokenFile) -> MatrixTokensFile:
        """Replace the owner's entries for ``token``'s Matrix account, keeping every other user's."""
        remaining = self.without_tokens_of(token.user, token.user_id)
        return remaining.model_copy(update={"tokens": [*remaining.tokens, token]})


class MatrixChannelConfig(MatrixConfigModel):
    enabled: bool = False
    homeserver: str = ""
    user_id: str = ""
    device_name: str = "carapace"
    password: str | None = None
    token: str | None = None
    allowed_rooms: list[str] = []
    allowed_users: list[str] = []
