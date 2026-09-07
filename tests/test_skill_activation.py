from __future__ import annotations

import base64
import json
import os
import shlex
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from carapace.sandbox.runtime import ExecResult, SkillActivationError, SkillActivationInputs, SkillFileCredential
from carapace.sandbox.skill_activation import SKILL_ACTIVATOR_MARKER, SKILL_ACTIVATOR_PATH, SkillActivationRunner

_SOURCE_REVISION = "a" * 40


def _runner(
    *,
    exec_in_session: AsyncMock,
    get_activation_inputs: AsyncMock | None = None,
) -> SkillActivationRunner:
    return SkillActivationRunner(
        knowledge_workdir="/workspace",
        activator_timeout=600,
        get_activation_inputs=get_activation_inputs or AsyncMock(return_value=SkillActivationInputs()),
        exec_in_session=exec_in_session,
        exec_in_container=AsyncMock(),
        write_context_file_credentials=AsyncMock(),
        delete_context_file_credentials=AsyncMock(),
    )


def _response(payload: dict[str, object]) -> str:
    return SKILL_ACTIVATOR_MARKER + json.dumps({"protocol_version": 1, **payload})


@pytest.mark.anyio
async def test_activator_receives_revision_credentials_and_all_commands() -> None:
    exec_in_session = AsyncMock(
        side_effect=[
            ExecResult(
                exit_code=0,
                output="[stderr]\n" + _response({"error": "diagnostics must not be parsed"}),
                stdout=_response(
                    {
                        "command_overrides": {"search": "/nix/store/search/bin/search"},
                        "messages": ["Realized search."],
                    }
                ),
            ),
            ExecResult(exit_code=0, output=""),
        ]
    )
    get_inputs = AsyncMock(
        return_value=SkillActivationInputs(
            environment={"API_TOKEN": "secret"},
            file_credentials=[SkillFileCredential(path=".config/token", value="secret")],
        )
    )
    runner = _runner(
        exec_in_session=exec_in_session,
        get_activation_inputs=get_inputs,
    )

    messages = await runner.activate(
        SimpleNamespace(session_id="session-1"),
        "web",
        _SOURCE_REVISION,
        command_aliases=[("search", "uv run search"), ("fetch", "uv run fetch")],
        run_session_id="session-1",
    )

    assert messages == ["Realized search.", "Command aliases registered: search, fetch."]
    get_inputs.assert_awaited_once_with("session-1", "web")

    activator_call = exec_in_session.await_args_list[0]
    assert activator_call.kwargs["timeout"] == 600
    assert activator_call.kwargs["bypass_proxy"] is True
    assert activator_call.kwargs["extra_env"] == {"API_TOKEN": "secret"}
    assert activator_call.kwargs["context_file_creds"] == [("web", ".config/token", "secret")]

    assert f"exec {SKILL_ACTIVATOR_PATH} --request-base64" in activator_call.args[1]
    encoded_request = shlex.split(activator_call.args[1])[-1]
    request = json.loads(base64.b64decode(encoded_request))
    assert request == {
        "protocol_version": 1,
        "skill": "web",
        "skill_dir": "/workspace/skills/web",
        "workspace": "/workspace",
        "source_revision": _SOURCE_REVISION,
        "commands": [
            {"name": "search", "command": "uv run search"},
            {"name": "fetch", "command": "uv run fetch"},
        ],
    }

    shim_command = exec_in_session.await_args_list[1].args[1]
    wrapper = '#!/bin/sh\nexec /nix/store/search/bin/search "$@"\n'
    assert base64.b64encode(wrapper.encode()).decode() in shim_command


@pytest.mark.anyio
async def test_invalid_override_does_not_replace_shims() -> None:
    exec_in_session = AsyncMock(
        return_value=ExecResult(
            exit_code=0,
            output="",
            stdout=_response({"command_overrides": {"undeclared": "echo nope"}, "messages": []}),
        )
    )
    runner = _runner(exec_in_session=exec_in_session)

    with pytest.raises(SkillActivationError, match="undeclared command"):
        await runner.activate(
            SimpleNamespace(session_id="session-1"),
            "web",
            _SOURCE_REVISION,
            command_aliases=[("search", "uv run search")],
            run_session_id="session-1",
        )

    exec_in_session.assert_awaited_once()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("result", "message"),
    [
        (ExecResult(exit_code=126, output=""), "missing or not executable"),
        (ExecResult(exit_code=-1, output=""), "timed out after 600 seconds"),
        (ExecResult(exit_code=1, output="", stdout=_response({"error": "realization failed"})), "realization failed"),
        (ExecResult(exit_code=0, output=_response({})), "exactly one marked"),
    ],
)
async def test_activator_failure_does_not_register_shims(result: ExecResult, message: str) -> None:
    exec_in_session = AsyncMock(return_value=result)
    runner = _runner(exec_in_session=exec_in_session)

    with pytest.raises(SkillActivationError, match=message):
        await runner.activate(
            SimpleNamespace(session_id="session-1"),
            "web",
            _SOURCE_REVISION,
            command_aliases=[("search", "uv run search")],
            run_session_id="session-1",
        )

    exec_in_session.assert_awaited_once()


@pytest.mark.anyio
async def test_explicit_noop_activator_registers_declared_commands_unchanged() -> None:
    exec_in_session = AsyncMock(return_value=ExecResult(exit_code=0, output="", stdout=_response({})))
    runner = _runner(exec_in_session=exec_in_session)

    messages = await runner.activate(
        SimpleNamespace(session_id="session-1"),
        "web",
        _SOURCE_REVISION,
        command_aliases=[("search", "uv run search")],
        run_session_id="session-1",
    )

    assert messages == ["Command aliases registered: search."]
    assert exec_in_session.await_count == 2
    assert "uv run search" not in exec_in_session.await_args.args[1]
    wrapper = '#!/bin/sh\nexec uv run search "$@"\n'
    assert base64.b64encode(wrapper.encode()).decode() in exec_in_session.await_args.args[1]


@pytest.mark.parametrize("fetch_state", ["present", "missing", "unreachable"])
def test_official_activator_restores_setup_from_source_revision(tmp_path: Path, fetch_state: str) -> None:
    workspace = tmp_path / "workspace"
    skill_dir = workspace / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: demo\n---\n")
    (skill_dir / "setup.sh").write_text("printf committed > activation-result\n")

    subprocess.run(["git", "init", "-b", "main"], cwd=workspace, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=workspace, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=workspace, check=True)
    subprocess.run(["git", "add", "."], cwd=workspace, check=True)
    subprocess.run(["git", "commit", "-m", "add skill"], cwd=workspace, check=True, capture_output=True)
    remote = tmp_path / "remote"
    subprocess.run(["git", "clone", str(workspace), str(remote)], check=True, capture_output=True)
    if fetch_state != "present":
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.com",
                "commit",
                "--allow-empty",
                "-m",
                "new",
            ],
            cwd=remote,
            check=True,
            capture_output=True,
        )
    source_revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=remote,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    head_before = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=workspace)
    (skill_dir / "unrelated.txt").write_text("keep local edits")

    (skill_dir / "setup.sh").write_text("printf tampered > activation-result\n")
    request = {
        "protocol_version": 1,
        "skill": "demo",
        "skill_dir": str(skill_dir),
        "workspace": str(workspace),
        "source_revision": source_revision,
        "commands": [],
    }
    encoded = base64.b64encode(json.dumps(request).encode()).decode()
    script = Path(__file__).parents[1] / "sandbox" / "carapace-skill-activator"

    result = subprocess.run(
        [script, "--request-base64", encoded],
        cwd=skill_dir,
        env={**os.environ, "GIT_REPO_URL": str(remote if fetch_state == "missing" else tmp_path / "secret-token")},
        check=False,
        capture_output=True,
        text=True,
    )

    if fetch_state == "unreachable":
        assert result.returncode != 0
        assert "failed to fetch source revision" in result.stdout
        assert "secret-token" not in result.stdout + result.stderr
        assert not (skill_dir / "activation-result").exists()
        assert (skill_dir / "setup.sh").read_text() == "printf tampered > activation-result\n"
        return

    assert result.returncode == 0, result.stderr
    assert (skill_dir / "activation-result").read_text() == "committed"
    assert (skill_dir / "setup.sh").read_text() == "printf committed > activation-result\n"
    assert "setup.sh completed." in result.stdout
    assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=workspace) == head_before
    assert (skill_dir / "unrelated.txt").read_text() == "keep local edits"
