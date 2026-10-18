"""Tests for SkillRegistry (no LLM tokens needed)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai import RunContext
from pydantic_ai.models import Model
from pydantic_ai.usage import RunUsage

from carapace.agent.deps import Deps
from carapace.agent.tools import create_agent
from carapace.credentials import CredentialRegistry
from carapace.git.store import GitStore
from carapace.models.config import Config
from carapace.models.session import SessionState
from carapace.prompt_prefix import shared_prompt_prefix
from carapace.sandbox.manager import SandboxManager
from carapace.security.context import SessionSecurity
from carapace.security.sentinel import Sentinel
from carapace.skills import SkillRegistry
from carapace.usage import UsageTracker


def test_scan_empty(tmp_path: Path):
    registry = SkillRegistry(tmp_path / "skills")
    catalog = registry.scan()
    assert catalog == []


def test_scan_finds_skill(tmp_path: Path):
    skill_dir = tmp_path / "my-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: my-skill\ndescription: A test skill\n---\nBody here.\n")
    registry = SkillRegistry(tmp_path)
    catalog = registry.scan()
    assert len(catalog) == 1
    assert catalog[0].name == "my-skill"
    assert catalog[0].description == "A test skill"


def test_scan_no_frontmatter(tmp_path: Path):
    skill_dir = tmp_path / "plain-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("Just a body, no frontmatter.\n")
    registry = SkillRegistry(tmp_path)
    catalog = registry.scan()
    assert len(catalog) == 1
    assert catalog[0].name == "plain-skill"


def test_get_full_instructions(tmp_path: Path):
    skill_dir = tmp_path / "my-skill"
    skill_dir.mkdir()
    content = "---\nname: my-skill\n---\nDo the thing.\n"
    (skill_dir / "SKILL.md").write_text(content)
    registry = SkillRegistry(tmp_path)
    assert registry.get_full_instructions("my-skill") == content


def test_get_full_instructions_missing(tmp_path: Path):
    registry = SkillRegistry(tmp_path)
    assert registry.get_full_instructions("nope") is None


def test_scan_caches(tmp_path: Path):
    registry = SkillRegistry(tmp_path)
    cat1 = registry.scan()
    cat2 = registry.scan()
    assert cat1 is cat2


@pytest.mark.parametrize("runtime_config", ["", "    commands: invalid\n"])
def test_disabled_skill_discovery_and_enable_transition(tmp_path: Path, runtime_config: str) -> None:
    skill_dir = tmp_path / "skills" / "private-search"
    skill_dir.mkdir(parents=True)
    skill_md = skill_dir / "SKILL.md"
    text = (
        "---\nname: private-search\ndescription: Private indexed material\n"
        "metadata:\n  carapace:\n    disabled: true\n"
        f"{runtime_config}---\nFull instructions.\n"
    )
    skill_md.write_text(text)
    registry = SkillRegistry(tmp_path / "skills")

    assert registry.scan() == []
    assert registry.is_disabled("private-search")
    assert "Private indexed material" not in shared_prompt_prefix(tmp_path, registry.scan())
    assert registry.get_full_instructions("private-search") == text
    if not runtime_config:
        config = registry.get_carapace_config("private-search")
        assert config is not None and config.disabled

    skill_md.write_text(text.replace("disabled: true", "disabled: false"))
    registry.invalidate()

    assert not registry.is_disabled("private-search")
    assert [skill.name for skill in registry.scan()] == ["private-search"]
    assert "Private indexed material" in shared_prompt_prefix(tmp_path, registry.scan())


def _activation_deps(tmp_path: Path) -> Deps:
    sandbox = MagicMock(spec=SandboxManager)
    sandbox.activate_skill = AsyncMock(return_value="")
    credentials = MagicMock(spec=CredentialRegistry)
    credentials.fetch_metadata = AsyncMock()
    credentials.fetch = AsyncMock()
    return Deps(
        config=Config(),
        data_dir=tmp_path,
        knowledge_dir=tmp_path,
        session_state=SessionState.now(session_id="s1", unattended=False),
        sandbox=sandbox,
        security=SessionSecurity("s1", unattended=False),
        sentinel=MagicMock(spec=Sentinel),
        git_store=MagicMock(spec=GitStore),
        agent_model=MagicMock(spec=Model),
        agent_model_id=Config().agent.model,
        usage_tracker=UsageTracker(),
        credential_registry=credentials,
    )


@pytest.mark.parametrize("approved", [False, True])
@pytest.mark.parametrize("invalid_config", [False, True])
async def test_disabled_activation_has_no_side_effects(tmp_path: Path, approved: bool, invalid_config: bool) -> None:
    skill_dir = tmp_path / "skills" / "private-search"
    skill_dir.mkdir(parents=True)
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        "---\nname: private-search\nmetadata:\n  carapace:\n    disabled: true\n"
        "    credentials:\n      - vault_path: vault/private\n"
        "    mcp:\n      - name: search\n        url: https://search.example/mcp\n"
        "        auth:\n          type: bearer\n          vault_path: vault/mcp\n"
        + ("    commands: invalid\n" if invalid_config else "")
        + "---\nPrivate instructions.\n"
    )
    deps = _activation_deps(tmp_path)
    agent = create_agent(deps)
    ctx = RunContext(deps=deps, model=deps.agent_model, usage=RunUsage(), tool_call_approved=approved)
    with (
        patch("carapace.agent.tools._gate", new_callable=AsyncMock) as gate,
        patch("carapace.agent.tools._cache_skill_credentials", new_callable=AsyncMock) as cache,
        patch("carapace.agent.tools._prewarm_skill_mcp", new_callable=AsyncMock) as connect,
    ):
        result = await agent._function_toolset.tools["use_skill"].function(ctx, "private-search")

    assert "disabled" in result
    deps.credential_registry.fetch_metadata.assert_not_awaited()
    deps.credential_registry.fetch.assert_not_awaited()
    gate.assert_not_awaited()
    cache.assert_not_awaited()
    connect.assert_not_awaited()
    deps.sandbox.activate_skill.assert_not_awaited()
    assert deps.session_state.context_grants == {}
    assert deps.session_state.activated_skills == []
    assert deps.activated_skills == []


@pytest.mark.parametrize("flag", ["", "    disabled: false\n"])
async def test_enabled_skill_activation(tmp_path: Path, flag: str) -> None:
    skill_dir = tmp_path / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: demo\nmetadata:\n  carapace:\n{flag}    network:\n"
        "      domains: [demo.example]\n---\nFull instructions.\n"
    )
    deps = _activation_deps(tmp_path)
    deps.skill_catalog = SkillRegistry(tmp_path / "skills").scan()
    agent = create_agent(deps)
    ctx = RunContext(deps=deps, model=deps.agent_model, usage=RunUsage(), tool_call_approved=True)

    result = await agent._function_toolset.tools["use_skill"].function(ctx, "demo")

    assert "Full instructions." in result
    assert deps.session_state.context_grants["demo"].domains == {"demo.example"}
    assert deps.session_state.activated_skills == ["demo"]
    deps.sandbox.activate_skill.assert_awaited_once_with("s1", "demo")
