from __future__ import annotations

from carapace.credentials.bitwarden import BitwardenBackend
from carapace.credentials.file import FileVaultBackend
from carapace.credentials.protocol import VaultBackend, is_exposed
from carapace.credentials.registry import (
    CredentialRegistry,
    build_credential_registry,
)

__all__ = [
    "BitwardenBackend",
    "CredentialRegistry",
    "FileVaultBackend",
    "VaultBackend",
    "build_credential_registry",
    "is_exposed",
]
