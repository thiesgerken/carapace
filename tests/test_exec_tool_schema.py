from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from pydantic_ai.models import Model

from carapace.agent.autonomy import AutonomyStreak
from carapace.agent.deps import Deps
from carapace.agent.tools import create_agent
from carapace.credentials import CredentialRegistry
from carapace.git.store import GitStore
from carapace.models.config import Config
from carapace.models.session import SessionState
from carapace.sandbox.manager import SandboxManager
from carapace.security.context import SessionSecurity
from carapace.security.sentinel import Sentinel
from carapace.usage import UsageTracker


def test_exec_offers_title_and_contexts_before_the_command(tmp_path: Path) -> None:
    """Strict decoding keeps the schema order, which GPT ignores otherwise.

    A title after a long heredoc would reach the chat last.
    """
    deps = Deps(
        config=Config(),
        data_dir=tmp_path,
        knowledge_dir=tmp_path,
        session_state=SessionState.now(session_id="s1"),
        sandbox=MagicMock(spec=SandboxManager),
        security=SessionSecurity("s1"),
        sentinel=MagicMock(spec=Sentinel),
        git_store=MagicMock(spec=GitStore),
        agent_model=MagicMock(spec=Model),
        agent_model_id="anthropic:claude-sonnet-4-6",
        usage_tracker=UsageTracker(),
        autonomy=AutonomyStreak(),
        credential_registry=CredentialRegistry(),
        load_session_events=list,
    )
    tool_def = create_agent(deps)._function_toolset.tools["exec"].tool_def
    schema = tool_def.parameters_json_schema

    assert tool_def.strict is True
    assert list(schema["properties"]) == ["title", "contexts", "command"]
    assert schema["required"] == ["command"]
    assert schema["properties"]["command"]["description"] == "The shell command to execute."
    assert schema["properties"]["title"]["description"].startswith("Optional short label")
