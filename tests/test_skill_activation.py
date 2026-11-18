from __future__ import annotations

import base64
import json
import os
import shlex
import shutil
import subprocess
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import urlsplit

import pytest

from carapace.git.store import GitStore
from carapace.models.skills import SkillCommandDecl
from carapace.sandbox.runtime import ExecResult, SkillActivationError, SkillActivationInputs, SkillFileCredential
from carapace.sandbox.skill_activation import SKILL_ACTIVATOR_PATH, SkillActivationRunner, SkillActivatorRequest

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
        kill_leftover_processes=AsyncMock(return_value=0),
        write_context_file_credentials=AsyncMock(),
        delete_context_file_credentials=AsyncMock(),
    )


def _response(payload: dict[str, object]) -> str:
    return json.dumps({"protocol_version": 1, **payload})


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
            ExecResult(stdout="", exit_code=0, output=""),
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
    assert activator_call.kwargs["workdir"] == "/workspace"
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
        (ExecResult(stdout="", exit_code=126, output=""), "missing or not executable"),
        (ExecResult(stdout="", exit_code=-1, output=""), "timed out after 600 seconds"),
        (ExecResult(exit_code=1, output="", stdout=_response({"error": "realization failed"})), "realization failed"),
        (ExecResult(stdout="", exit_code=0, output=_response({})), "invalid protocol response"),
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
    workspace = tmp_path.resolve() / "workspace"
    skill_dir = workspace / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: demo\n---\n")
    (skill_dir / "setup.sh").write_text("printf committed > activation-result\n")
    (skill_dir / "setup.sh").chmod(0o755)

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
        cwd=workspace,
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
    assert (skill_dir / "setup.sh").stat().st_mode & 0o777 == 0o755
    assert "setup.sh completed." in result.stdout
    assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=workspace) == head_before
    assert (skill_dir / "unrelated.txt").read_text() == "keep local edits"


def _git(workspace: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(workspace), *args], text=True).strip()


def _command_only_skill(tmp_path: Path) -> tuple[Path, SkillActivatorRequest]:
    workspace = tmp_path.resolve() / "repo"
    skill_dir = workspace / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("committed instructions\n")
    _git(workspace, "init", "-b", "main")
    _git(workspace, "config", "user.name", "Test")
    _git(workspace, "config", "user.email", "test@example.com")
    _git(workspace, "add", ".")
    _git(workspace, "commit", "-m", "skill")
    return workspace, SkillActivatorRequest(
        skill="demo",
        skill_dir=str(skill_dir),
        workspace=str(workspace),
        source_revision=_git(workspace, "rev-parse", "HEAD"),
        commands=[SkillCommandDecl(name="hello", command="echo hello")],
    )


def _run_official(request: SkillActivatorRequest) -> subprocess.CompletedProcess[str]:
    encoded = base64.b64encode(request.model_dump_json().encode()).decode()
    script = Path(__file__).parents[1] / "sandbox" / "carapace-skill-activator"
    return subprocess.run(
        [script, "--request-base64", encoded],
        cwd=request.workspace,
        env={**os.environ, "ACTIVATION_TEST_SECRET": "synthetic-secret"},
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("custom_hooks_path", [False, True])
def test_official_restoration_does_not_execute_hooks_or_filters(tmp_path: Path, custom_hooks_path: bool) -> None:
    workspace, request = _command_only_skill(tmp_path)
    hooks = workspace / ("custom-hooks" if custom_hooks_path else ".git/hooks")
    hooks.mkdir(exist_ok=True)
    hook = hooks / "post-checkout"
    hook.write_text('#!/bin/sh\nprintf "%s" "$ACTIVATION_TEST_SECRET" > hook-ran\n')
    hook.chmod(0o755)
    if custom_hooks_path:
        _git(workspace, "config", "core.hooksPath", str(hooks))
    (workspace / ".git/info/attributes").write_text("skills/demo/SKILL.md filter=attack\n")
    _git(workspace, "config", "filter.attack.smudge", 'printf "%s" "$ACTIVATION_TEST_SECRET" > filter-ran')
    skill_file = Path(request.skill_dir) / "SKILL.md"
    skill_file.write_text("tampered instructions")
    index_before = (workspace / ".git/index").read_bytes()

    result = _run_official(request)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["protocol_version"] == 1
    assert skill_file.read_text() == "committed instructions\n"
    assert not (workspace / "hook-ran").exists()
    assert not (workspace / "filter-ran").exists()
    assert "synthetic-secret" not in result.stdout + result.stderr
    assert (workspace / ".git/index").read_bytes() == index_before


@pytest.mark.parametrize("link_kind", ["file", "dangling_file", "file_to_directory", "skill", "skills", "workspace"])
def test_official_restoration_handles_symlinks(tmp_path: Path, link_kind: str) -> None:
    workspace, request = _command_only_skill(tmp_path)
    outside = tmp_path.resolve() / "outside"
    outside.mkdir()
    protected = outside / "protected"
    protected.write_text("do not overwrite")
    skill_file = Path(request.skill_dir) / "SKILL.md"
    if link_kind in {"file", "dangling_file", "file_to_directory"}:
        skill_file.unlink()
        target = protected if link_kind == "file" else outside / "missing"
        skill_file.symlink_to(outside if link_kind == "file_to_directory" else target)
    else:
        directory = {"skill": Path(request.skill_dir), "skills": workspace / "skills", "workspace": workspace}[
            link_kind
        ]
        moved = outside / "moved"
        directory.rename(moved)
        directory.symlink_to(moved, target_is_directory=True)

    result = _run_official(request)

    assert protected.read_text() == "do not overwrite"
    assert not (outside / "missing").exists()
    assert not list(outside.rglob(".carapace-restore.*"))
    if link_kind in {"file", "dangling_file"}:
        assert result.returncode == 0, result.stderr
        assert not skill_file.is_symlink()
        assert skill_file.read_text() == "committed instructions\n"
    else:
        assert result.returncode != 0
        assert "directory" in json.loads(result.stdout)["error"] or "symlink" in json.loads(result.stdout)["error"]


def test_official_restoration_rejects_committed_symlink(tmp_path: Path) -> None:
    workspace, request = _command_only_skill(tmp_path)
    skill_file = Path(request.skill_dir) / "SKILL.md"
    skill_file.unlink()
    skill_file.symlink_to("untrusted.md")
    _git(workspace, "commit", "-am", "symlink")
    request.source_revision = _git(workspace, "rev-parse", "HEAD")

    result = _run_official(request)

    assert result.returncode != 0
    assert "regular file" in json.loads(result.stdout)["error"]
    assert skill_file.is_symlink()
    assert not list(Path(request.skill_dir).glob(".carapace-restore.*"))


@pytest.mark.anyio
@pytest.mark.parametrize("session_exec", [False, True])
@pytest.mark.parametrize("stale", [False, True])
async def test_missing_skill_directory_in_both_exec_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, session_exec: bool, stale: bool
) -> None:
    remote, request = _command_only_skill(tmp_path)
    workspace = tmp_path.resolve() / "clone"
    if stale:
        # Clone before the skill exists; the required commit is absent locally.
        _git(remote, "checkout", "--orphan", "old")
        _git(remote, "rm", "-rf", ".")
        _git(
            remote, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "--allow-empty", "-m", "old"
        )
    subprocess.run(["git", "clone", "--single-branch", "--no-local", str(remote), str(workspace)], check=True)
    if stale:
        _git(remote, "checkout", "main")
    else:
        shutil.rmtree(workspace / "skills")
    assert not (workspace / "skills/demo").exists()
    shims = workspace / ".carapace/bin"
    monkeypatch.setattr("carapace.sandbox.skill_activation.SKILL_COMMAND_SHIM_DIR", str(shims))
    script = Path(__file__).parents[1] / "sandbox" / "carapace-skill-activator"

    async def execute(_target: object, command: str, **kwargs: object) -> ExecResult:
        assert kwargs["workdir"] == str(workspace)
        command = command.replace(SKILL_ACTIVATOR_PATH, shlex.quote(str(script)))
        result = subprocess.run(
            ["sh", "-c", command],
            cwd=str(kwargs["workdir"]),
            env={**os.environ, "GIT_REPO_URL": str(remote)},
            capture_output=True,
            text=True,
            check=False,
        )
        return ExecResult(exit_code=result.returncode, stdout=result.stdout, output=result.stdout + result.stderr)

    session_callback = AsyncMock(side_effect=execute)
    container_callback = AsyncMock(side_effect=execute)
    runner = SkillActivationRunner(
        knowledge_workdir=str(workspace),
        activator_timeout=600,
        get_activation_inputs=AsyncMock(return_value=SkillActivationInputs()),
        exec_in_session=session_callback,
        exec_in_container=container_callback,
        kill_leftover_processes=AsyncMock(return_value=0),
        write_context_file_credentials=AsyncMock(return_value=[]),
        delete_context_file_credentials=AsyncMock(),
    )
    messages = await runner.activate(
        SimpleNamespace(session_id="test"),
        "demo",
        request.source_revision,
        command_aliases=[("hello", "echo hello")],
        run_session_id="test" if session_exec else None,
    )
    assert messages == ["Command aliases registered: hello."]
    assert (workspace / "skills/demo/SKILL.md").read_text() == "committed instructions\n"
    assert subprocess.check_output([shims / "hello"], text=True).strip() == "hello"
    assert session_callback.await_count == (2 if session_exec else 0)
    assert container_callback.await_count == (0 if session_exec else 2)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "stdout,exit_code",
    [
        ("not json", 0),
        (_response({}) + _response({}), 0),
        ("noise\n" + _response({}), 0),
        (_response({"protocol_version": 2}), 0),
        (_response({"unexpected": True}), 0),
        (_response({"error": "safe failure"}), 0),
        (_response({"error": "safe failure"}), 1),
        (_response({"command_overrides": {"undeclared": "echo bad"}}), 0),
        ("", -1),
    ],
)
async def test_failure_diagnostics_are_bounded_and_not_model_facing(stdout: str, exit_code: int) -> None:
    diagnostics = "provider diagnostics " + "x" * 3000
    execute = AsyncMock(return_value=ExecResult(exit_code=exit_code, stdout=stdout, output=diagnostics))
    runner = _runner(exec_in_session=execute)
    with (
        patch("carapace.sandbox.skill_activation.logger.error") as log,
        pytest.raises(SkillActivationError) as error,
    ):
        await runner.activate(
            SimpleNamespace(session_id="test"), "demo", _SOURCE_REVISION, command_aliases=[], run_session_id="test"
        )
    assert diagnostics[:2000] in log.call_args.args[0]
    assert diagnostics[:2001] not in log.call_args.args[0]
    assert "provider diagnostics" not in str(error.value)
    execute.assert_awaited_once()


@pytest.fixture
def git_http_url(tmp_path: Path) -> Iterator[str]:
    """Serve the actual Git Smart HTTP backend, not local-file fetch semantics."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            url = urlsplit(self.path)
            result = subprocess.run(
                ["git", "http-backend"],
                env={
                    **os.environ,
                    "GIT_PROJECT_ROOT": str(tmp_path),
                    "GIT_HTTP_EXPORT_ALL": "1",
                    "PATH_INFO": url.path,
                    "QUERY_STRING": url.query,
                    "REQUEST_METHOD": self.command,
                    "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                    "GIT_PROTOCOL": self.headers.get("Git-Protocol", ""),
                },
                input=self.rfile.read(int(self.headers.get("Content-Length", "0"))),
                capture_output=True,
                check=True,
            )
            headers, body = result.stdout.split(b"\r\n\r\n", 1)
            self.send_response(200)
            for line in headers.decode().splitlines():
                name, value = line.split(":", 1)
                self.send_header(name, value.strip())
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            self.do_GET()

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}"
        finally:
            server.shutdown()
            thread.join()


@pytest.mark.anyio
@pytest.mark.parametrize("allow_reachable", [False, True])
async def test_official_activator_fetches_non_tip_revision_over_http(
    tmp_path: Path,
    git_http_url: str,
    monkeypatch: pytest.MonkeyPatch,
    allow_reachable: bool,
) -> None:
    remote, _ = _command_only_skill(tmp_path)
    await GitStore(remote).ensure_repo()
    if not allow_reachable:
        _git(remote, "config", "uploadpack.allowReachableSHA1InWant", "false")
    workspace = tmp_path.resolve() / "clone"
    subprocess.run(["git", "clone", str(remote), str(workspace)], check=True)
    # Select a new revision, then advance HEAD before the stale sandbox fetches it.
    skill_file = remote / "skills/demo/SKILL.md"
    skill_file.write_text("selected revision\n")
    _git(remote, "commit", "-am", "selected revision")
    selected = _git(remote, "rev-parse", "HEAD")
    skill_file.write_text("later revision\n")
    _git(remote, "commit", "-am", "later revision")
    head_before = _git(workspace, "rev-parse", "HEAD")
    monkeypatch.setenv("GIT_REPO_URL", f"{git_http_url}/repo")
    # Exercise the older protocol's unadvertised-object restriction as well.
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "protocol.version")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "0")
    result = _run_official(
        SkillActivatorRequest(
            skill="demo",
            skill_dir=str(workspace / "skills/demo"),
            workspace=str(workspace),
            source_revision=selected,
            commands=[SkillCommandDecl(name="hello", command="echo hello")],
        )
    )
    if not allow_reachable:
        assert result.returncode != 0
        assert "failed to fetch source revision" in json.loads(result.stdout)["error"]
        assert (workspace / "skills/demo/SKILL.md").read_text() == "committed instructions\n"
        return
    assert result.returncode == 0, result.stdout + result.stderr
    assert (workspace / "skills/demo/SKILL.md").read_text() == "selected revision\n"
    assert _git(workspace, "rev-parse", "HEAD") == head_before
    assert not (workspace / ".git/FETCH_HEAD").exists()


@pytest.mark.anyio
async def test_restart_activation_kills_leftovers_before_writing_file_credentials() -> None:
    """Skills rerun one after another on restart; an earlier activator's process must not see the next one's files."""
    calls: list[str] = []

    def record(name: str, result: object) -> object:
        calls.append(name)
        return result

    runner = SkillActivationRunner(
        knowledge_workdir="/workspace",
        activator_timeout=600,
        get_activation_inputs=AsyncMock(
            return_value=SkillActivationInputs(
                file_credentials=[SkillFileCredential(path=".config/token", value="secret")]
            )
        ),
        exec_in_session=AsyncMock(),
        exec_in_container=AsyncMock(
            side_effect=lambda *_a, **_kw: record("activator", ExecResult(exit_code=0, output="", stdout=_response({})))
        ),
        kill_leftover_processes=AsyncMock(side_effect=lambda _sc: record("kill", 0)),
        write_context_file_credentials=AsyncMock(side_effect=lambda *_a: record("write credentials", [])),
        delete_context_file_credentials=AsyncMock(),
    )

    await runner.activate(SimpleNamespace(session_id="session-1"), "web", _SOURCE_REVISION, command_aliases=[])

    assert calls == ["kill", "write credentials", "activator"]


def test_resolved_commands_are_unique_and_keep_declaration_order() -> None:
    runner = _runner(exec_in_session=AsyncMock())
    assert runner._resolved_commands([("one", "echo old"), ("two", "echo two"), ("one", "echo new")], {}) == [
        ("one", "echo new"),
        ("two", "echo two"),
    ]
