"""Tests for credential models, file backend, exposure filter, and registry."""

from pathlib import Path

import httpx
import pytest

from carapace.credentials import (
    BitwardenBackend,
    CredentialBackendError,
    CredentialRegistry,
    FileVaultBackend,
    VaultBackend,
    build_credential_registry,
    is_exposed,
)
from carapace.credentials.protocol import UnsupportedCredentialValueKindError
from carapace.credentials.registry import FILE_CREDENTIAL_BACKEND_ENV, file_credential_backend_allowed_from_env
from carapace.models.credentials import (
    BasicAuthConfig,
    BitwardenCredentialBackendConfig,
    CredentialMetadata,
    CredentialsConfig,
    CredentialValueKind,
    FileCredentialBackendConfig,
)
from carapace.models.skills import SkillCredentialDecl

# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


def test_credential_metadata_defaults():
    meta = CredentialMetadata(vault_path="dev/gmail", name="Gmail")
    assert meta.vault_path == "dev/gmail"
    assert meta.name == "Gmail"
    assert meta.description == ""


def test_bitwarden_backend_basic_auth_requires_password() -> None:
    cfg = BitwardenCredentialBackendConfig(basic_auth=BasicAuthConfig(username="carapace"))

    with pytest.raises(ValueError, match=r"basic_auth\.password"):
        BitwardenBackend(name="bw", base_url="http://bitwarden.local", cfg=cfg)


def test_bitwarden_backend_configures_basic_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class FakeAsyncClient:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("carapace.credentials.bitwarden.httpx.AsyncClient", FakeAsyncClient)
    cfg = BitwardenCredentialBackendConfig(
        basic_auth=BasicAuthConfig(username="carapace", password="proxy-password"),
    )

    BitwardenBackend(name="bw", base_url="http://bitwarden.local", cfg=cfg)

    assert isinstance(captured["auth"], httpx.BasicAuth)


def test_file_backend_env_switch_defaults_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(FILE_CREDENTIAL_BACKEND_ENV, raising=False)
    assert file_credential_backend_allowed_from_env() is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_file_backend_env_switch_accepts_true_values(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv(FILE_CREDENTIAL_BACKEND_ENV, value)
    assert file_credential_backend_allowed_from_env() is True


@pytest.mark.parametrize("value", ["", "0", "false", "FALSE", "no", "off"])
def test_file_backend_env_switch_accepts_false_values(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv(FILE_CREDENTIAL_BACKEND_ENV, value)
    assert file_credential_backend_allowed_from_env() is False


def test_file_backend_env_switch_rejects_invalid_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(FILE_CREDENTIAL_BACKEND_ENV, "sometimes")
    with pytest.raises(ValueError, match=FILE_CREDENTIAL_BACKEND_ENV):
        file_credential_backend_allowed_from_env()


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
@pytest.mark.parametrize("kind", ["login", "json"])
async def test_file_fetch_rejects_provider_specific_kinds(
    file_backend: FileVaultBackend,
    kind: CredentialValueKind,
) -> None:
    with pytest.raises(UnsupportedCredentialValueKindError):
        await file_backend.fetch("gmail", kind)


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
# FileVaultBackend YAML tests
# ---------------------------------------------------------------------------


def _write_yaml(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "secrets.yaml"
    p.write_text(content)
    return p


@pytest.fixture()
def yaml_backend(tmp_path: Path) -> FileVaultBackend:
    path = _write_yaml(
        tmp_path,
        "- id: gmail\n  name: Gmail App Password\n  value: myapppassword\n"
        "- id: github-token\n  name: GitHub API Token\n  value: ghp_xxx\n"
        "- id: ssh-key\n  value: secretkey\n",
    )
    return FileVaultBackend(name="dev", path=path, cfg=FileCredentialBackendConfig())


@pytest.mark.asyncio
async def test_yaml_fetch(yaml_backend: FileVaultBackend) -> None:
    assert await yaml_backend.fetch("gmail") == "myapppassword"


@pytest.mark.asyncio
async def test_yaml_fetch_missing(yaml_backend: FileVaultBackend) -> None:
    with pytest.raises(KeyError):
        await yaml_backend.fetch("nonexistent")


@pytest.mark.asyncio
async def test_yaml_fetch_metadata_with_name(yaml_backend: FileVaultBackend) -> None:
    meta = await yaml_backend.fetch_metadata("gmail")
    assert meta.vault_path == "dev/gmail"
    assert meta.name == "Gmail App Password"


@pytest.mark.asyncio
async def test_yaml_fetch_metadata_without_name(yaml_backend: FileVaultBackend) -> None:
    meta = await yaml_backend.fetch_metadata("ssh-key")
    assert meta.vault_path == "dev/ssh-key"
    assert meta.name == "ssh-key"


@pytest.mark.asyncio
async def test_yaml_list_all(yaml_backend: FileVaultBackend) -> None:
    items = await yaml_backend.list()
    assert len(items) == 3
    paths = {i.vault_path for i in items}
    assert paths == {"dev/gmail", "dev/github-token", "dev/ssh-key"}
    names = {i.name for i in items}
    assert "Gmail App Password" in names
    assert "GitHub API Token" in names


@pytest.mark.asyncio
async def test_yaml_list_query_matches_name(yaml_backend: FileVaultBackend) -> None:
    items = await yaml_backend.list("Gmail")
    assert len(items) == 1
    assert items[0].name == "Gmail App Password"


@pytest.mark.asyncio
async def test_yaml_list_query_matches_id(yaml_backend: FileVaultBackend) -> None:
    items = await yaml_backend.list("github")
    assert len(items) == 1
    assert items[0].name == "GitHub API Token"


@pytest.mark.asyncio
async def test_yaml_exposure_filter(tmp_path: Path) -> None:
    path = _write_yaml(
        tmp_path,
        "- id: gmail\n  name: Gmail\n  value: pw\n- id: banking\n  name: Banking Secret\n  value: secret\n",
    )
    backend = FileVaultBackend(name="dev", path=path, cfg=FileCredentialBackendConfig(hide=["banking"]))
    items = await backend.list()
    assert len(items) == 1
    assert items[0].name == "Gmail"


def test_yaml_missing_file(tmp_path: Path) -> None:
    backend = FileVaultBackend(name="dev", path=tmp_path / "missing.yaml", cfg=FileCredentialBackendConfig())
    assert backend._secrets == {}


def test_yaml_invalid_structure(tmp_path: Path) -> None:
    path = _write_yaml(tmp_path, "key: value\n")
    backend = FileVaultBackend(name="dev", path=path, cfg=FileCredentialBackendConfig())
    assert len(backend._secrets) == 0


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
async def test_build_registry_file_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(FILE_CREDENTIAL_BACKEND_ENV, "true")
    env = _write_env(tmp_path, "token=abc\n")
    config = CredentialsConfig(
        backends={"dev": FileCredentialBackendConfig(type="file", path=str(env))},
    )
    reg = await build_credential_registry(config, tmp_path)
    assert "dev" in reg.backend_names


@pytest.mark.asyncio
async def test_build_registry_file_backend_disabled_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(FILE_CREDENTIAL_BACKEND_ENV, raising=False)
    config = CredentialsConfig(
        backends={"x": FileCredentialBackendConfig(type="file", path=str(tmp_path / "missing.env"))}
    )
    reg = await build_credential_registry(config, tmp_path)
    assert "x" not in reg.backend_names


@pytest.mark.asyncio
async def test_build_registry_file_backend_respects_server_override(tmp_path: Path) -> None:
    env = _write_env(tmp_path, "token=abc\n")
    config = CredentialsConfig(
        backends={"dev": FileCredentialBackendConfig(type="file", path=str(env))},
    )
    reg = await build_credential_registry(config, tmp_path, file_backend_allowed=False)
    assert "dev" not in reg.backend_names


@pytest.mark.asyncio
async def test_build_registry_default_path(tmp_path: Path) -> None:
    (tmp_path / "secrets.env").write_text("k=v\n")
    config = CredentialsConfig(backends={"dev": FileCredentialBackendConfig(type="file")})
    reg = await build_credential_registry(config, tmp_path, file_backend_allowed=True)
    assert "dev" in reg.backend_names


@pytest.mark.asyncio
async def test_build_registry_relative_path_under_data_dir(tmp_path: Path) -> None:
    (tmp_path / "secrets.env").write_text("k=v\n")
    config = CredentialsConfig(
        backends={"dev": FileCredentialBackendConfig(type="file", path="secrets.env")},
    )
    reg = await build_credential_registry(config, tmp_path, file_backend_allowed=True)
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


class _FailingBitwardenClient:
    def __init__(self, exc: httpx.RequestError) -> None:
        self._exc = exc

    async def get(self, path: str, params: dict[str, str] | None = None) -> _FakeResponse:
        raise self._exc

    async def aclose(self) -> None:
        pass


@pytest.mark.asyncio
async def test_bitwarden_fetch_success() -> None:
    backend = BitwardenBackend(name="bw", base_url="http://bitwarden.local", cfg=BitwardenCredentialBackendConfig())
    backend._client = _FakeBitwardenClient(  # type: ignore[assignment]
        {"/object/password/id-1": _FakeResponse(status_code=200, payload={"data": {"data": "s3cr3t"}})}
    )

    result = await backend.fetch("id-1")
    assert result == "s3cr3t"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "path", "payload", "expected"),
    [
        ("login", "/object/username/id-1", {"data": {"data": "alice"}}, "alice"),
        (
            "json",
            "/object/item/id-1",
            {"data": {"id": "id-1", "name": "Example", "login": {"username": "alice", "password": "secret"}}},
            '{"id":"id-1","name":"Example","login":{"username":"alice","password":"secret"}}',
        ),
    ],
)
async def test_bitwarden_fetch_alternate_kind(
    kind: CredentialValueKind,
    path: str,
    payload: dict,
    expected: str,
) -> None:
    backend = BitwardenBackend(name="bw", base_url="http://bitwarden.local", cfg=BitwardenCredentialBackendConfig())
    backend._client = _FakeBitwardenClient({path: _FakeResponse(status_code=200, payload=payload)})  # type: ignore[assignment]

    assert await backend.fetch("id-1", kind) == expected


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
async def test_bitwarden_fetch_connection_error_has_clear_message() -> None:
    request = httpx.Request("GET", "http://bitwarden.local/object/password/id-1")
    backend = BitwardenBackend(name="bw", base_url="http://bitwarden.local", cfg=BitwardenCredentialBackendConfig())
    backend._client = _FailingBitwardenClient(httpx.ConnectError("All connection attempts failed", request=request))  # type: ignore[assignment]

    with pytest.raises(CredentialBackendError) as exc_info:
        await backend.fetch("id-1")

    message = str(exc_info.value)
    assert "Bitwarden credential backend 'bw' is unreachable" in message
    assert "Check that the `bw serve` sidecar or proxy is running" in message
    assert "All connection attempts failed" not in message


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
