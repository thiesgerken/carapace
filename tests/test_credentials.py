"""Tests for credential models, file backend, exposure filter, and registry."""

from pathlib import Path

import pytest

from carapace.credentials import (
    CredentialRegistry,
    FileVaultBackend,
    VaultBackend,
    build_credential_registry,
    is_exposed,
)
from carapace.models import (
    CredentialBackendConfig,
    CredentialMetadata,
    CredentialsConfig,
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
    cfg = CredentialBackendConfig()
    assert is_exposed("anything", cfg) is True


def test_exposed_allowlist_hit():
    cfg = CredentialBackendConfig(expose=["gmail", "ssh"])
    assert is_exposed("gmail", cfg) is True


def test_exposed_allowlist_miss():
    cfg = CredentialBackendConfig(expose=["gmail", "ssh"])
    assert is_exposed("banking", cfg) is False


def test_exposed_blocklist_hit():
    cfg = CredentialBackendConfig(hide=["banking"])
    assert is_exposed("banking", cfg) is False


def test_exposed_blocklist_miss():
    cfg = CredentialBackendConfig(hide=["banking"])
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
    return FileVaultBackend(name="dev", path=env, cfg=CredentialBackendConfig())


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
    backend = FileVaultBackend(name="dev", path=env, cfg=CredentialBackendConfig(hide=["banking"]))
    items = await backend.list()
    assert len(items) == 1
    assert items[0].name == "gmail"


@pytest.mark.asyncio
async def test_file_exposure_filter_hides_from_fetch(tmp_path: Path) -> None:
    env = _write_env(tmp_path, "gmail=pw\nbanking=secret\n")
    backend = FileVaultBackend(name="dev", path=env, cfg=CredentialBackendConfig(hide=["banking"]))
    with pytest.raises(KeyError):
        await backend.fetch("banking")


@pytest.mark.asyncio
async def test_file_allowlist_restricts_list(tmp_path: Path) -> None:
    env = _write_env(tmp_path, "gmail=pw\nbanking=secret\nssh=key\n")
    backend = FileVaultBackend(name="dev", path=env, cfg=CredentialBackendConfig(expose=["gmail"]))
    items = await backend.list()
    assert len(items) == 1
    assert items[0].name == "gmail"


def test_file_missing_file(tmp_path: Path) -> None:
    backend = FileVaultBackend(name="dev", path=tmp_path / "missing.env", cfg=CredentialBackendConfig())
    # Should not crash, just have no secrets
    assert backend._secrets == {}


def test_file_comments_and_blanks(tmp_path: Path) -> None:
    env = _write_env(tmp_path, "# header\n\nkey=value\n  \n# trailing")
    backend = FileVaultBackend(name="dev", path=env, cfg=CredentialBackendConfig())
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
    b1 = FileVaultBackend(name="a", path=env1, cfg=CredentialBackendConfig())
    b2 = FileVaultBackend(name="b", path=env2, cfg=CredentialBackendConfig())
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


def test_build_registry_file_backend(tmp_path: Path) -> None:
    env = _write_env(tmp_path, "token=abc\n")
    config = CredentialsConfig(backends={"dev": CredentialBackendConfig(type="file", path=str(env))})
    reg = build_credential_registry(config, tmp_path)
    assert "dev" in reg.backend_names


def test_build_registry_unknown_type(tmp_path: Path) -> None:
    config = CredentialsConfig(backends={"x": CredentialBackendConfig(type="file", path=str(tmp_path / "missing.env"))})
    reg = build_credential_registry(config, tmp_path)
    assert "x" in reg.backend_names


def test_build_registry_default_path(tmp_path: Path) -> None:
    (tmp_path / "secrets.env").write_text("k=v\n")
    config = CredentialsConfig(backends={"dev": CredentialBackendConfig(type="file")})
    reg = build_credential_registry(config, tmp_path)
    assert "dev" in reg.backend_names
