from __future__ import annotations

import io
import os
import tarfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from carapace.builder import app as builder_app
from carapace.builder import client as builder_client
from carapace.builder import nix
from carapace.builder import store as builder_store
from carapace.builder.client import BuilderClient, BuilderSystemMismatchError, BuilderUnavailableError
from carapace.builder.models import BuilderInfo, BuildResult, FetchCredential, InputUpdate
from carapace.builder.store import SkillStore
from carapace.models.user import UserGitConfig

TOKEN = "builder-test-token"
KEY = "0123456789abcdef" * 4
OTHER_KEY = "89abcdef01234567" * 4
GRACE = timedelta(hours=24)
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def archive(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


@pytest.fixture
def builds(monkeypatch: pytest.MonkeyPatch) -> list[set[str]]:
    """Replace the Nix build: record the files each build saw and succeed."""
    seen: list[set[str]] = []

    async def fake_build(
        source: Path, key: str, skill: str, system: str, roots: Path, credential: FetchCredential | None
    ) -> BuildResult:
        seen.append({path.name for path in source.iterdir()})
        (roots / key).symlink_to(f"/nix/store/{key}-skill")
        return BuildResult(
            key=key, skill=skill, state="succeeded", store_paths=[f"/nix/store/{key}-skill"], metadata={"a": 1}
        )

    monkeypatch.setattr(nix, "build_skill", fake_build)
    return seen


@pytest.fixture
def api(tmp_path: Path) -> TestClient:
    store = SkillStore(tmp_path, GRACE)
    return TestClient(builder_app.create_app(TOKEN, store, "x86_64-linux", ["carapace-builder-1:AAAA"]))


def test_requires_the_token(api: TestClient) -> None:
    assert api.get("/info").status_code == 401
    assert api.get("/info", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert api.get("/info", headers=AUTH).json() == {
        "system": "x86_64-linux",
        "cache_public_keys": ["carapace-builder-1:AAAA"],
    }
    assert api.get("/healthz").status_code == 200


def test_a_key_is_built_once_and_then_answered_from_the_stored_result(api: TestClient, builds: list[set[str]]) -> None:
    assert api.get(f"/builds/{KEY}", headers=AUTH).status_code == 404
    body = archive({"flake.nix": b"{}", "flake.lock": b"{}", "weather/flake.nix": b"{}"})

    first = api.put(f"/builds/{KEY}?skill=weather", headers=AUTH, files={"archive": body})
    second = api.put(f"/builds/{KEY}?skill=weather", headers=AUTH, files={"archive": b"not even an archive"})

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json() == api.get(f"/builds/{KEY}", headers=AUTH).json()
    assert (first.json()["skill"], first.json()["store_paths"]) == ("weather", [f"/nix/store/{KEY}-skill"])
    assert builds == [{"flake.nix", "flake.lock", "weather"}]


@pytest.mark.parametrize("skill", ["", "weather.default", 'a"b', "-flag"])
def test_rejects_names_that_are_no_flake_attribute(api: TestClient, builds: list[set[str]], skill: str) -> None:
    body = archive({"flake.nix": b"{}"})
    assert api.put(f"/builds/{KEY}", headers=AUTH, params={"skill": skill}, files={"archive": body}).status_code == 422
    assert builds == []


def test_rejects_bad_keys_and_archives(api: TestClient, builds: list[set[str]]) -> None:
    assert api.put("/builds/not-a-key?skill=weather", headers=AUTH, files={"archive": b""}).status_code == 422
    assert api.put(f"/builds/{KEY}", headers=AUTH, files={"archive": archive({"flake.nix": b"{}"})}).status_code == 422
    assert api.put(f"/builds/{KEY}?skill=weather", headers=AUTH, files={"archive": b"garbage"}).status_code == 400
    escaping = archive({"../outside": b"x"})
    assert api.put(f"/builds/{KEY}?skill=weather", headers=AUTH, files={"archive": escaping}).status_code == 400
    assert builds == []


async def test_a_missing_lock_file_fails_without_running_nix(tmp_path: Path) -> None:
    (tmp_path / "flake.nix").write_text("{}")

    result = await nix.build_skill(tmp_path, KEY, "weather", "x86_64-linux", tmp_path / "roots", None)

    assert result.state == "failed"
    assert "flake.lock is missing" in result.log_tail


def test_failed_builds_are_stored(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def failing_build(
        source: Path, key: str, skill: str, system: str, roots: Path, credential: FetchCredential | None
    ) -> BuildResult:
        return BuildResult(key=key, skill=skill, state="failed", log_tail="error: boom")

    monkeypatch.setattr(nix, "build_skill", failing_build)
    api.put(f"/builds/{KEY}?skill=weather", headers=AUTH, files={"archive": archive({"flake.nix": b"{}"})})

    stored = api.get(f"/builds/{KEY}", headers=AUTH).json()
    assert stored["state"] == "failed"
    assert stored["log_tail"] == "error: boom"


@pytest.mark.parametrize(
    ("machine", "system"), [("x86_64", "x86_64-linux"), ("AMD64", "x86_64-linux"), ("arm64", "aarch64-linux")]
)
def test_sandboxes_are_linux_on_the_servers_cpu(monkeypatch: pytest.MonkeyPatch, machine: str, system: str) -> None:
    monkeypatch.setattr(builder_client.platform, "machine", lambda: machine)
    assert builder_client.sandbox_system() == system


async def test_the_client_refuses_a_builder_for_another_system(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(builder_client, "sandbox_system", lambda: "x86_64-linux")
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        return httpx.Response(200, json=BuilderInfo(system="aarch64-linux", cache_public_keys=[]).model_dump())

    client = BuilderClient("http://builder", TOKEN, 5)
    client._client = httpx.AsyncClient(base_url="http://builder", transport=httpx.MockTransport(handler))

    with pytest.raises(BuilderSystemMismatchError, match="aarch64-linux"):
        await client.get(KEY)
    assert requests == ["/info"]


async def test_every_sandbox_gets_the_builders_current_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(builder_client, "sandbox_system", lambda: "x86_64-linux")
    keys = iter([["carapace-builder-1:AAAA", "cache.nixos.org-1:BBBB"], ["carapace-builder-1:CCCC"]])

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=BuilderInfo(system="x86_64-linux", cache_public_keys=next(keys)).model_dump())

    client = BuilderClient("http://builder", TOKEN, 5)
    client._client = httpx.AsyncClient(base_url="http://builder", transport=httpx.MockTransport(handler))

    first = await client.sandbox_nix_config()
    # A wiped builder volume means a new key, picked up by the next sandbox.
    second = await client.sandbox_nix_config()

    assert "substituters = http://cache.carapace.internal\n" in first
    assert "trusted-public-keys = carapace-builder-1:AAAA cache.nixos.org-1:BBBB\n" in first
    assert "trusted-public-keys = carapace-builder-1:CCCC\n" in second


async def test_a_sandbox_does_not_start_while_the_builder_has_not_answered() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = BuilderClient("http://builder", TOKEN, 5)
    client._client = httpx.AsyncClient(base_url="http://builder", transport=httpx.MockTransport(handler))

    with pytest.raises(BuilderUnavailableError, match="configured but unreachable"):
        await client.sandbox_nix_config()


def test_a_failed_build_is_retried_on_request(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    states = iter(["failed", "succeeded"])
    attempts: list[str] = []

    async def flaky_build(
        source: Path, key: str, skill: str, system: str, roots: Path, credential: FetchCredential | None
    ) -> BuildResult:
        attempts.append(key)
        return BuildResult(key=key, skill=skill, state=next(states))

    monkeypatch.setattr(nix, "build_skill", flaky_build)
    body = archive({"flake.nix": b"{}"})

    assert api.put(f"/builds/{KEY}?skill=weather", headers=AUTH, files={"archive": body}).json()["state"] == "failed"
    assert api.put(f"/builds/{KEY}?skill=weather", headers=AUTH, files={"archive": body}).json()["state"] == "failed"
    assert (
        api.put(f"/builds/{KEY}?skill=weather&retry=true", headers=AUTH, files={"archive": body}).json()["state"]
        == "succeeded"
    )
    # A success is never rebuilt, retry or not.
    assert (
        api.put(f"/builds/{KEY}?skill=weather&retry=true", headers=AUTH, files={"archive": body}).json()["state"]
        == "succeeded"
    )
    assert attempts == [KEY, KEY]


def test_gc_drops_a_key_only_after_no_head_referenced_it_for_the_grace_period(
    api: TestClient, builds: list[set[str]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = [datetime(2026, 11, 1, tzinfo=UTC)]
    monkeypatch.setattr(builder_store, "_now", lambda: clock[0])
    collections: list[None] = []

    async def collect_garbage() -> str:
        collections.append(None)
        return "2 store paths deleted, 1.0 KiB freed"

    monkeypatch.setattr(nix, "collect_garbage", collect_garbage)
    body = archive({"flake.nix": b"{}"})
    for key in (KEY, OTHER_KEY):
        api.put(f"/builds/{key}?skill=weather", headers=AUTH, files={"archive": body})
    assert api.put("/roots", headers=AUTH, json={"keys": [KEY]}).status_code == 204

    # OTHER_KEY was never referenced, but its grace period only starts now.
    assert api.post("/gc", headers=AUTH).json()["dropped"] == []

    clock[0] += GRACE - timedelta(minutes=1)
    api.put("/roots", headers=AUTH, json={"keys": [KEY]})
    assert api.post("/gc", headers=AUTH).json()["dropped"] == []

    clock[0] += timedelta(minutes=2)
    assert api.post("/gc", headers=AUTH).json()["dropped"] == [OTHER_KEY]

    assert api.get(f"/builds/{OTHER_KEY}", headers=AUTH).status_code == 404
    assert not (tmp_path / "roots" / OTHER_KEY).is_symlink()
    assert api.get(f"/builds/{KEY}", headers=AUTH).status_code == 200
    assert (tmp_path / "roots" / KEY).is_symlink()
    assert len(collections) == 3


def test_roots_and_gc_require_the_token(api: TestClient) -> None:
    assert api.put("/roots", json={"keys": []}).status_code == 401
    assert api.post("/gc").status_code == 401
    assert api.put("/roots", headers=AUTH, json={"keys": ["not-a-key"]}).status_code == 422


def test_an_update_check_answers_per_input_and_stores_nothing(
    api: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: list[tuple[str, set[str]]] = []

    async def fake_update(
        source: Path, name: str, out: Path, store: Path, credential: FetchCredential | None
    ) -> InputUpdate:
        seen.append((name, {path.name for path in source.iterdir()}))
        # A throwaway store next to the source, read-only as Nix leaves its paths, and removed after.
        assert store.parent == source.parent
        (store / "nix" / "store" / f"{name}-source").mkdir(parents=True)
        (store / "nix" / "store" / f"{name}-source").chmod(0o555)
        if name == "broken":
            return InputUpdate(log_tail="error: cannot fetch")
        return InputUpdate(lock=f'{{"updated": "{name}"}}')

    monkeypatch.setattr(nix, "update_input", fake_update)
    body = archive({"flake.nix": b"{}", "flake.lock": b"{}", "weather/flake.nix": b"{}"})

    response = api.post("/updates?input=weather&input=broken", headers=AUTH, files={"archive": body})

    assert response.status_code == 200
    assert response.json() == {
        "inputs": {
            "weather": {"lock": '{"updated": "weather"}', "log_tail": ""},
            "broken": {"lock": None, "log_tail": "error: cannot fetch"},
        }
    }
    assert seen == [
        ("weather", {"flake.nix", "flake.lock", "weather"}),
        ("broken", {"flake.nix", "flake.lock", "weather"}),
    ]
    assert not list((tmp_path / "work").iterdir())


def test_an_update_check_takes_only_flake_attributes(api: TestClient) -> None:
    body = archive({"flake.nix": b"{}"})
    assert api.post("/updates?input=a.b", headers=AUTH, files={"archive": body}).status_code == 422
    assert api.post("/updates", files={"archive": body}).status_code in (401, 403)


CREDENTIAL = FetchCredential(host="git.example.org", token="ghp_s3cret")


def test_the_fetch_credential_reaches_only_the_nix_runs_of_its_request(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    builds: list[FetchCredential | None] = []
    updates: list[FetchCredential | None] = []

    async def fake_build(
        source: Path, key: str, skill: str, system: str, roots: Path, credential: FetchCredential | None
    ) -> BuildResult:
        builds.append(credential)
        return BuildResult(key=key, skill=skill, state="failed")

    async def fake_update(
        source: Path, name: str, out: Path, store: Path, credential: FetchCredential | None
    ) -> InputUpdate:
        updates.append(credential)
        return InputUpdate()

    monkeypatch.setattr(nix, "build_skill", fake_build)
    monkeypatch.setattr(nix, "update_input", fake_update)
    body = archive({"flake.nix": b"{}"})
    form = {"fetch_credential": CREDENTIAL.model_dump_json()}

    api.put(f"/builds/{KEY}?skill=weather", headers=AUTH, files={"archive": body}, data=form)
    api.put(f"/builds/{OTHER_KEY}?skill=weather", headers=AUTH, files={"archive": body})
    api.post("/updates?input=weather", headers=AUTH, files={"archive": body}, data=form)

    assert builds == [CREDENTIAL, None]
    assert updates == [CREDENTIAL]
    # Stored results are shared between users: nothing of the token in them.
    assert "s3cret" not in api.get(f"/builds/{KEY}", headers=AUTH).text


def test_an_invalid_fetch_credential_is_refused_without_quoting_it(api: TestClient, builds: list[set[str]]) -> None:
    form = {"fetch_credential": '{"host": "git.example.org", "token": "s3cret\\nsandbox = false"}'}

    response = api.put(f"/builds/{KEY}?skill=weather", headers=AUTH, files={"archive": archive({})}, data=form)

    assert response.status_code == 422
    assert "s3cret" not in response.text
    assert builds == []


async def test_the_client_sends_the_credential_in_the_body_not_the_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(builder_client, "sandbox_system", lambda: "x86_64-linux")
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/info":
            return httpx.Response(200, json=BuilderInfo(system="x86_64-linux", cache_public_keys=[]).model_dump())
        sent.append(request)
        if request.url.path == "/updates":
            return httpx.Response(200, json={"inputs": {}})
        return httpx.Response(200, json=BuildResult(key=KEY, skill="weather", state="failed").model_dump())

    client = BuilderClient("http://builder", TOKEN, 5)
    client._client = httpx.AsyncClient(base_url="http://builder", transport=httpx.MockTransport(handler))

    await client.build(KEY, "weather", b"archive", CREDENTIAL)
    await client.check_updates(b"archive", ["weather"], CREDENTIAL)

    assert [request.url.path for request in sent] == [f"/builds/{KEY}", "/updates"]
    for request in sent:
        assert "s3cret" not in str(request.url)
        assert b"ghp_s3cret" in request.content


@pytest.mark.parametrize(
    ("remote", "token", "expected"),
    [
        ("https://github.com/alice/knowledge.git", "ghp_x", FetchCredential(host="github.com", token="ghp_x")),
        ("https://git.lan:3000/alice/knowledge", "tok", FetchCredential(host="git.lan:3000", token="tok")),
        ("https://user@git.lan/alice/knowledge", "tok", FetchCredential(host="git.lan", token="tok")),
        # The token is for HTTPS: never sent in the clear, nor to an SSH remote's host.
        ("http://git.lan/alice/knowledge", "tok", None),
        ("git@github.com:alice/knowledge.git", "tok", None),
        ("https://github.com/alice/knowledge.git", None, None),
        ("", None, None),
    ],
)
def test_the_fetch_credential_is_the_knowledge_remotes_token_for_its_host(
    remote: str, token: str | None, expected: FetchCredential | None
) -> None:
    assert builder_client.knowledge_remote_credential(UserGitConfig(remote=remote, token=token)) == expected


@pytest.mark.parametrize(("host", "access_tokens"), [("github.com", True), ("git.example.org", False)])
async def test_a_credential_reaches_git_for_its_host_only_and_never_the_log(host: str, access_tokens: bool) -> None:
    credential = FetchCredential(host=host, token="ghp_s3cret")
    show_env = 'echo "$GIT_CONFIG_KEY_0|$GIT_CONFIG_VALUE_0|$NIX_CONFIG" >&2; echo "$GIT_CONFIG_COUNT"'

    code, stdout, stderr = await nix._run("sh", "-c", show_env, credential=credential)
    _, unauthenticated, _ = await nix._run("sh", "-c", show_env)

    assert code == 0
    assert stdout == "1\n"
    key, header, nix_config = stderr.strip().split("|")
    assert key == f"http.https://{host}/.extraHeader"
    assert header == "Authorization: Basic <redacted>"
    assert nix_config.endswith("access-tokens = github.com=<redacted>") is access_tokens
    assert "s3cret" not in stderr
    # The next invocation, and the builder's own environment, never see it.
    assert unauthenticated == "\n"
    assert "GIT_CONFIG_COUNT" not in os.environ


async def test_an_update_check_fetches_with_a_cache_of_its_own(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A shared fetcher cache would answer a failed fetch of a private repo with the clone another user fetched."""
    runs: list[dict[str, str] | None] = []

    async def run(*args: str, credential: FetchCredential | None = None, env: dict[str, str] | None = None):
        runs.append(env)
        return 1, "", "error: cannot fetch"

    monkeypatch.setattr(nix, "_run", run)

    await nix.update_input(tmp_path / "skills", "weather", tmp_path / "out.lock", tmp_path / "store", None)

    assert runs == [{"XDG_CACHE_HOME": str(tmp_path / "store" / "cache")}]
