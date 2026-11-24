from __future__ import annotations

import io
import tarfile
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from carapace.builder import app as builder_app
from carapace.builder import client as builder_client
from carapace.builder import nix
from carapace.builder.client import BuilderClient, BuilderSystemMismatchError, BuilderUnavailableError
from carapace.builder.models import BuilderInfo, BuildResult

TOKEN = "builder-test-token"
TREE = "0123456789abcdef0123456789abcdef01234567"
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

    async def fake_build(source: Path, tree: str, system: str, roots: Path) -> BuildResult:
        seen.append({path.name for path in source.iterdir()})
        return BuildResult(tree=tree, state="succeeded", store_paths=[f"/nix/store/{tree}-skill"], metadata={"a": 1})

    monkeypatch.setattr(nix, "build_skill", fake_build)
    return seen


@pytest.fixture
def api(tmp_path: Path) -> TestClient:
    return TestClient(builder_app.create_app(TOKEN, tmp_path, "x86_64-linux", ["carapace-builder-1:AAAA"]))


def test_requires_the_token(api: TestClient) -> None:
    assert api.get("/info").status_code == 401
    assert api.get("/info", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert api.get("/info", headers=AUTH).json() == {
        "system": "x86_64-linux",
        "cache_public_keys": ["carapace-builder-1:AAAA"],
    }
    assert api.get("/healthz").status_code == 200


def test_a_tree_is_built_once_and_then_answered_from_the_stored_result(api: TestClient, builds: list[set[str]]) -> None:
    assert api.get(f"/builds/{TREE}", headers=AUTH).status_code == 404
    body = archive({"flake.nix": b"{}", "flake.lock": b"{}"})

    first = api.put(f"/builds/{TREE}", headers=AUTH, content=body)
    second = api.put(f"/builds/{TREE}", headers=AUTH, content=b"not even an archive")

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json() == api.get(f"/builds/{TREE}", headers=AUTH).json()
    assert first.json()["store_paths"] == [f"/nix/store/{TREE}-skill"]
    assert builds == [{"flake.nix", "flake.lock"}]


def test_rejects_bad_trees_and_archives(api: TestClient, builds: list[set[str]]) -> None:
    assert api.put("/builds/not-a-tree", headers=AUTH, content=b"").status_code == 422
    assert api.put(f"/builds/{TREE}", headers=AUTH, content=b"garbage").status_code == 400
    escaping = archive({"../outside": b"x"})
    assert api.put(f"/builds/{TREE}", headers=AUTH, content=escaping).status_code == 400
    assert builds == []


async def test_a_missing_lock_file_fails_without_running_nix(tmp_path: Path) -> None:
    (tmp_path / "flake.nix").write_text("{}")

    result = await nix.build_skill(tmp_path, TREE, "x86_64-linux", tmp_path / "roots")

    assert result.state == "failed"
    assert "flake.lock is missing" in result.log_tail


def test_failed_builds_are_stored(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def failing_build(source: Path, tree: str, system: str, roots: Path) -> BuildResult:
        return BuildResult(tree=tree, state="failed", log_tail="error: boom")

    monkeypatch.setattr(nix, "build_skill", failing_build)
    api.put(f"/builds/{TREE}", headers=AUTH, content=archive({"flake.nix": b"{}"}))

    stored = api.get(f"/builds/{TREE}", headers=AUTH).json()
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
        await client.get(TREE)
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
