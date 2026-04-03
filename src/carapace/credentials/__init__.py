from __future__ import annotations

from carapace.credentials.file import FileVaultBackend
from carapace.credentials.protocol import VaultBackend, is_exposed
from carapace.credentials.registry import (
    CredentialRegistry,
    build_credential_registry,
    shutdown_credential_registry,
)
from carapace.credentials.vaultwarden import BwServeManager, VaultwardenBackend

__all__ = [
    "BwServeManager",
    "CredentialRegistry",
    "FileVaultBackend",
    "VaultBackend",
    "VaultwardenBackend",
    "build_credential_registry",
    "is_exposed",
    "shutdown_credential_registry",
]
