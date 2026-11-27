"""Verify that all modules are importable."""


def test_import_carapace():
    import carapace  # noqa: F401


def test_import_models():
    from carapace.models.config import Config  # noqa: F401
    from carapace.models.session import SessionState  # noqa: F401
    from carapace.models.skills import SkillInfo  # noqa: F401


def test_import_agent_deps():
    from carapace.agent.deps import Deps, TaskDone, TaskFailed  # noqa: F401


def test_import_config():
    from carapace.config import (  # noqa: F401
        build_config,
        load_workspace_file,
        resolve_knowledge_repos_dir,
        resolve_user_knowledge_dir,
    )


def test_import_knowledge():
    from carapace.knowledge import KnowledgeRepoHandle, KnowledgeRepoRegistry  # noqa: F401


def test_import_session():
    from carapace.session import SessionManager  # noqa: F401


def test_import_skills():
    from carapace.skills import read_skills_flake  # noqa: F401


def test_import_credentials():
    from carapace.credentials import VaultBackend  # noqa: F401


def test_import_agent():
    from carapace.agent import build_system_prompt, create_agent  # noqa: F401


def test_import_server():
    from carapace.server import app, main  # noqa: F401


def test_import_llm():
    from carapace.llm import infer_model_with_retry_transport, make_model_factory  # noqa: F401


def test_import_auth():
    from carapace.auth import validate_bootstrap_admin_password  # noqa: F401


def test_import_ws_models():
    from carapace.ws_models import (  # noqa: F401
        ApprovalRequest,
        ApprovalResponse,
        CommandResult,
        Done,
        ErrorMessage,
        TokenChunk,
        ToolCallInfo,
        UserMessage,
        parse_client_message,
    )


def test_import_security():
    from carapace.security import CredentialAccessEntry, evaluate_domain_with, record_tool_call  # noqa: F401
    from carapace.security.context import (  # noqa: F401
        ActionLogEntry,
        AuditEntry,
        SentinelVerdict,
        SessionSecurity,
    )
    from carapace.security.sentinel import Sentinel  # noqa: F401


def test_import_ws_credential_models():
    from carapace.ws_models import CredentialApprovalRequest  # noqa: F401
