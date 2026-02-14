"""Verify that all modules are importable."""


def test_import_carapace():
    import carapace  # noqa: F401


def test_import_models():
    from carapace.models import (  # noqa: F401
        Config,
        Deps,
        OperationClassification,
        Rule,
        RuleCheckResult,
        RuleMode,
        SessionState,
        SkillInfo,
    )


def test_import_config():
    from carapace.config import get_data_dir, load_config, load_rules  # noqa: F401


def test_import_memory():
    from carapace.memory import MemoryStore  # noqa: F401


def test_import_session():
    from carapace.session import SessionManager  # noqa: F401


def test_import_skills():
    from carapace.skills import SkillRegistry  # noqa: F401


def test_import_credentials():
    from carapace.credentials import MockCredentialBroker  # noqa: F401


def test_import_agent():
    from carapace.agent import build_system_prompt, create_agent  # noqa: F401
