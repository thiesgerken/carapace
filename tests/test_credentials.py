"""Tests for credential models, file backend, exposure filter, and registry."""

from pathlib import Path

import httpx
import pytest

from carapace.credentials import (
    BitwardenBackend,
    CredentialRegistry,
    FileVaultBackend,
    VaultBackend,
    build_credential_registry,
    is_exposed,
)
from carapace.models import (
    BitwardenCredentialBackendConfig,
    CredentialMetadata,
    CredentialsConfig,
    FileCredentialBackendConfig,
    SkillCredentialDecl,
)

# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


def test_credential_metadata_defaults():
    meta = CredentialMetadata(vault_path="dev/gmail", name="Gmail")
    assert meta.vault_path == "dev/gmail"
    assert meta.name == "Gmail"
    assert meta.description == ""


def test_credential_metadata_with_description():
    meta = CredentialMetadata(vault_path="personal/abc-123", name="SSH key", description="Deploy key for prod")
    assert meta.description == "Deploy key for prod"


def test_skill_credential_decl_env_var():
    decl = SkillCredentialDecl(vault_path="dev/token", description="API token", env_var="API_TOKEN")
    assert decl.env_var == "API_TOKEN"
    assert decl.file is None


def test_skill_credential_decl_file():
    decl = SkillCredentialDecl(vault_path="dev/ssh", file="/home/sandbox/.ssh/id_ed25519")
    assert decl.file == "/home/sandbox/.ssh/id_ed25519"
    assert decl.env_var is None


def test_vault_backend_is_protocol():
    assert isinstance(VaultBackend, type)


# ---------------------------------------------------------------------------
# Exposure filter tests
# ---------------------------------------------------------------------------


def test_exposed_no_rules():
    cfg = FileCredentialBackendConfig()
    assert is_exposed("anything", cfg) is True


def test_exposed_allowlist_hit():
    cfg = FileCredentialBackendConfig(expose=["gmail", "ssh"])
    assert is_exposed("gmail", cfg) is True


def test_exposed_allowlist_miss():
    cfg = FileCredentialBackendConfig(expose=["gmail", "ssh"])
    assert is_exposed("banking", cfg) is False


def test_exposed_blocklist_hit():
    cfg = FileCredentialBackendConfig(hide=["banking"])
    assert is_exposed("banking", cfg) is False


def test_exposed_blocklist_miss():
    cfg = FileCredentialBackendConfig(hide=["banking"])
    assert is_exposed("gmail", cfg) is True


# ---------------------------------------------------------------------------
# FileVaultBackend tests
# ---------------------------------------------------------------------------


def _write_env(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "secrets.env"
    p.write_text(content)
    return p


@pytest.fixture()
def file_backend(tmp_path: Path) -> FileVaultBackend:
    env = _write_env(
        tmp_path,
        "gmail=myapppassword\ngithub-token=ghp_xxx\n# comment\n\nssh-key=secretkey\n",
    )
    return FileVaultBackend(name="dev", path=env, cfg=FileCredentialBackendConfig())


@pytest.mark.asyncio
async def test_file_fetch(file_backend: FileVaultBackend) -> None:
    assert await file_backend.fetch("gmail") == "myapppassword"


@pytest.mark.asyncio
async def test_file_fetch_missing(file_backend: FileVaultBackend) -> None:
    with pytest.raises(KeyError):
        await file_backend.fetch("nonexistent")


@pytest.mark.asyncio
async def test_file_fetch_metadata(file_backend: FileVaultBackend) -> None:
    meta = await file_backend.fetch_metadata("gmail")
    assert meta.vault_path == "dev/gmail"
    assert meta.name == "gmail"


@pytest.mark.asyncio
async def test_file_list_all(file_backend: FileVaultBackend) -> None:
    items = await file_backend.list()
    assert len(items) == 3
    paths = {i.vault_path for i in items}
    assert paths == {"dev/gmail", "dev/github-token", "dev/ssh-key"}


@pytest.mark.asyncio
async def test_file_list_with_query(file_backend: FileVaultBackend) -> None:
    items = await file_backend.list("git")
    assert len(items) == 1
    assert items[0].vault_path == "dev/github-token"


@pytest.mark.asyncio
async def test_file_list_case_insensitive(file_backend: FileVaultBackend) -> None:
    items = await file_backend.list("GMAIL")
    assert len(items) == 1


@pytest.mark.asyncio
async def test_file_exposure_filter_hides_from_list(tmp_path: Path) -> None:
    env = _write_env(tmp_path, "gmail=pw\nbanking=secret\n")
    backend = FileVaultBackend(name="dev", path=env, cfg=FileCredentialBackendConfig(hide=["banking"]))
    items = await backend.list()
    assert len(items) == 1
    assert items[0].name == "gmail"


@pytest.mark.asyncio
async def test_file_exposure_filter_hides_from_fetch(tmp_path: Path) -> None:
    env = _write_env(tmp_path, "gmail=pw\nbanking=secret\n")
    backend = FileVaultBackend(name="dev", path=env, cfg=FileCredentialBackendConfig(hide=["banking"]))
    with pytest.raises(KeyError):
        await backend.fetch("banking")


@pytest.mark.asyncio
async def test_file_allowlist_restricts_list(tmp_path: Path) -> None:
    env = _write_env(tmp_path, "gmail=pw\nbanking=secret\nssh=key\n")
    backend = FileVaultBackend(name="dev", path=env, cfg=FileCredentialBackendConfig(expose=["gmail"]))
    items = await backend.list()
    assert len(items) == 1
    assert items[0].name == "gmail"


def test_file_missing_file(tmp_path: Path) -> None:
    backend = FileVaultBackend(name="dev", path=tmp_path / "missing.env", cfg=FileCredentialBackendConfig())
    # Should not crash, just have no secrets
    assert backend._secrets == {}


def test_file_comments_and_blanks(tmp_path: Path) -> None:
    env = _write_env(tmp_path, "# header\n\nkey=value\n  \n# trailing")
    backend = FileVaultBackend(name="dev", path=env, cfg=FileCredentialBackendConfig())
    assert "key" in backend._secrets
    assert len(backend._secrets) == 1


# ---------------------------------------------------------------------------
# CredentialRegistry tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_registry_fetch(file_backend: FileVaultBackend) -> None:
    reg = CredentialRegistry()
    reg.register("dev", file_backend)
    assert await reg.fetch("dev/gmail") == "myapppassword"


@pytest.mark.asyncio
async def test_registry_fetch_unknown_backend() -> None:
    reg = CredentialRegistry()
    with pytest.raises(KeyError, match="Unknown credential backend"):
        await reg.fetch("unknown/key")


@pytest.mark.asyncio
async def test_registry_fetch_no_slash() -> None:
    reg = CredentialRegistry()
    with pytest.raises(KeyError, match="missing backend prefix"):
        await reg.fetch("noslash")


@pytest.mark.asyncio
async def test_registry_list_all(file_backend: FileVaultBackend) -> None:
    reg = CredentialRegistry()
    reg.register("dev", file_backend)
    items = await reg.list()
    assert len(items) == 3


@pytest.mark.asyncio
async def test_registry_list_with_query(file_backend: FileVaultBackend) -> None:
    reg = CredentialRegistry()
    reg.register("dev", file_backend)
    items = await reg.list("gmail")
    assert len(items) == 1


@pytest.mark.asyncio
async def test_registry_list_multiple_backends(tmp_path: Path) -> None:
    dir_a = tmp_path / "a"
    dir_a.mkdir()
    env1 = _write_env(dir_a, "k1=v1\n")
    dir_b = tmp_path / "b"
    dir_b.mkdir()
    env2 = _write_env(dir_b, "k2=v2\n")
    b1 = FileVaultBackend(name="a", path=env1, cfg=FileCredentialBackendConfig())
    b2 = FileVaultBackend(name="b", path=env2, cfg=FileCredentialBackendConfig())
    reg = CredentialRegistry()
    reg.register("a", b1)
    reg.register("b", b2)
    items = await reg.list()
    assert len(items) == 2
    paths = {i.vault_path for i in items}
    assert paths == {"a/k1", "b/k2"}


def test_registry_backend_names(file_backend: FileVaultBackend) -> None:
    reg = CredentialRegistry()
    reg.register("dev", file_backend)
    assert reg.backend_names == ["dev"]


# ---------------------------------------------------------------------------
# build_credential_registry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_registry_file_backend(tmp_path: Path) -> None:
    env = _write_env(tmp_path, "token=abc\n")
    config = CredentialsConfig(backends={"dev": FileCredentialBackendConfig(type="file", path=str(env))})
    reg = await build_credential_registry(config, tmp_path)
    assert "dev" in reg.backend_names


@pytest.mark.asyncio
async def test_build_registry_unknown_type(tmp_path: Path) -> None:
    config = CredentialsConfig(
        backends={"x": FileCredentialBackendConfig(type="file", path=str(tmp_path / "missing.env"))}
    )
    reg = await build_credential_registry(config, tmp_path)
    assert "x" in reg.backend_names


@pytest.mark.asyncio
async def test_build_registry_default_path(tmp_path: Path) -> None:
    (tmp_path / "secrets.env").write_text("k=v\n")
    config = CredentialsConfig(backends={"dev": FileCredentialBackendConfig(type="file")})
    reg = await build_credential_registry(config, tmp_path)
    assert "dev" in reg.backend_names


@pytest.mark.asyncio
async def test_build_registry_relative_path_under_data_dir(tmp_path: Path) -> None:
    (tmp_path / "secrets.env").write_text("k=v\n")
    config = CredentialsConfig(backends={"dev": FileCredentialBackendConfig(type="file", path="secrets.env")})
    reg = await build_credential_registry(config, tmp_path)
    assert await reg.fetch("dev/k") == "v"


# ---------------------------------------------------------------------------
# BitwardenBackend tests
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, *, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self._request = httpx.Request("GET", "http://bitwarden.local")

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("request failed", request=self._request, response=self)

    def json(self) -> dict:
        return self._payload


class _FakeBitwardenClient:
    def __init__(self, responses: dict[str, _FakeResponse]) -> None:
        self._responses = responses
        self.calls: list[tuple[str, dict[str, str] | None]] = []
        self.closed = False

    async def get(self, path: str, params: dict[str, str] | None = None) -> _FakeResponse:
        self.calls.append((path, params))
        key = path if params is None else f"{path}?search={params.get('search', '')}"
        return self._responses[key]

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_bitwarden_fetch_success() -> None:
    backend = BitwardenBackend(name="bw", base_url="http://bitwarden.local", cfg=BitwardenCredentialBackendConfig())
    backend._client = _FakeBitwardenClient(  # type: ignore[assignment]
        {"/object/password/id-1": _FakeResponse(status_code=200, payload={"data": {"data": "s3cr3t"}})}
    )

    result = await backend.fetch("id-1")
    assert result == "s3cr3t"


@pytest.mark.asyncio
async def test_bitwarden_fetch_missing_raises_keyerror() -> None:
    backend = BitwardenBackend(name="bw", base_url="http://bitwarden.local", cfg=BitwardenCredentialBackendConfig())
    backend._client = _FakeBitwardenClient(  # type: ignore[assignment]
        {"/object/password/missing": _FakeResponse(status_code=404, payload={"data": {}})}
    )

    with pytest.raises(KeyError):
        await backend.fetch("missing")


@pytest.mark.asyncio
async def test_bitwarden_fetch_respects_expose_allowlist() -> None:
    cfg = BitwardenCredentialBackendConfig(expose=["allowed-id"])
    backend = BitwardenBackend(name="bw", base_url="http://bitwarden.local", cfg=cfg)
    backend._client = _FakeBitwardenClient(  # type: ignore[assignment]
        {"/object/password/blocked-id": _FakeResponse(status_code=200, payload={"data": {"data": "ignored"}})}
    )

    with pytest.raises(KeyError):
        await backend.fetch("blocked-id")


@pytest.mark.asyncio
async def test_bitwarden_fetch_metadata_success() -> None:
    backend = BitwardenBackend(name="bw", base_url="http://bitwarden.local", cfg=BitwardenCredentialBackendConfig())
    backend._client = _FakeBitwardenClient(  # type: ignore[assignment]
        {"/object/item/id-2": _FakeResponse(status_code=200, payload={"data": {"name": "GitHub Token"}})}
    )

    meta = await backend.fetch_metadata("id-2")
    assert meta.vault_path == "bw/id-2"
    assert meta.name == "GitHub Token"


@pytest.mark.asyncio
async def test_bitwarden_list_filters_hidden_and_passes_query() -> None:
    cfg = BitwardenCredentialBackendConfig(hide=["hidden-id"])
    backend = BitwardenBackend(name="bw", base_url="http://bitwarden.local", cfg=cfg)
    fake_client = _FakeBitwardenClient(
        {
            "/list/object/items?search=git": _FakeResponse(
                status_code=200,
                payload={
                    "data": {
                        "data": [
                            {"id": "visible-id", "name": "GitHub"},
                            {"id": "hidden-id", "name": "Hidden"},
                        ]
                    }
                },
            )
        }
    )
    backend._client = fake_client  # type: ignore[assignment]

    items = await backend.list("git")
    assert [item.vault_path for item in items] == ["bw/visible-id"]
    assert fake_client.calls == [("/list/object/items", {"search": "git"})]


@pytest.mark.asyncio
async def test_build_registry_bitwarden_backend(tmp_path: Path) -> None:
    config = CredentialsConfig(
        backends={"bw": BitwardenCredentialBackendConfig(type="bitwarden", url="http://bitwarden.local")}
    )
    reg = await build_credential_registry(config, tmp_path)
    assert "bw" in reg.backend_names
