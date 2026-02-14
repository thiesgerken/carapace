from __future__ import annotations


class MockCredentialBroker:
    """Mock credential broker for the PoC. Returns placeholder values."""

    def __init__(self) -> None:
        self._cache: dict[str, str] = {}

    def get(self, credential_name: str) -> str:
        if credential_name not in self._cache:
            self._cache[credential_name] = f"<mock-value-for-{credential_name}>"
        return self._cache[credential_name]

    def is_approved(self, credential_name: str, approved_list: list[str]) -> bool:
        return credential_name in approved_list
