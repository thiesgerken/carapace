"""Tests for credential models and vault backend protocol."""

from carapace.credentials import VaultBackend
from carapace.models import CredentialMetadata, SkillCredentialDecl


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
