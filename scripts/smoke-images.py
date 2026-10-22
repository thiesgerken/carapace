#!/usr/bin/env python3
"""Exercise locally loaded images in an isolated, disposable Compose project."""

from __future__ import annotations

import json
import subprocess
import tempfile
import time
import urllib.request
import uuid
from collections.abc import Callable
from pathlib import Path


def run(*args: str) -> str:
    return subprocess.check_output(args, text=True).strip()


def eventually[T](operation: Callable[[], T], timeout: int = 120) -> T:
    deadline = time.monotonic() + timeout
    while True:
        try:
            return operation()
        except (AssertionError, OSError):
            if time.monotonic() >= deadline:
                raise
            time.sleep(1)


def request(url: str, payload: dict[str, str] | None = None) -> tuple[bytes, str]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json"} if payload is not None else {},
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        return response.read(), response.headers.get("Content-Security-Policy", "")


def assert_hardened(container: str) -> None:
    config = json.loads(run("docker", "inspect", container))[0]
    assert config["Config"]["User"] == "999:999", config["Config"]["User"]
    assert config["HostConfig"]["ReadonlyRootfs"], container
    assert config["HostConfig"]["CapDrop"] == ["ALL"], container
    assert any(option.startswith("no-new-privileges") for option in config["HostConfig"]["SecurityOpt"])
    assert config["State"]["Running"], config["State"]
    processes = run("docker", "top", container, "-eo", "pid,euid").splitlines()[1:]
    assert processes and all(process.split()[1] == "999" for process in processes), processes


def assert_push_gated(container: str) -> None:
    repo = "/var/lib/carapace/knowledges/admin"
    execute = ["docker", "exec", container, "git"]
    before = run(*execute, "-C", repo, "rev-parse", "HEAD")
    run(*execute, "clone", repo, "/tmp/push-smoke")
    run(
        *execute,
        "-C",
        "/tmp/push-smoke",
        "-c",
        "user.name=Image Smoke",
        "-c",
        "user.email=smoke@example.invalid",
        "commit",
        "--allow-empty",
        "-m",
        "Runtime gate smoke",
    )
    push = subprocess.run(
        [
            "docker",
            "exec",
            "-e",
            "CARAPACE_SESSION_ID=smoke-no-session",
            "-e",
            "CARAPACE_DEFAULT_BRANCH=main",
            "-e",
            "CARAPACE_API_PORT=8320",
            container,
            "git",
            "-C",
            "/tmp/push-smoke",
            "push",
            "origin",
            "HEAD:main",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert push.returncode != 0 and "DENIED by sentinel: Session not found" in push.stderr, push.stderr
    assert run(*execute, "-C", repo, "rev-parse", "HEAD") == before


def main() -> None:
    architecture = run("docker", "info", "--format", "{{.Architecture}}")
    assert architecture in ("aarch64", "arm64", "x86_64", "amd64"), architecture
    expected = "arm64" if architecture in ("aarch64", "arm64") else "amd64"
    for image in ("carapace", "carapace-frontend", "carapace-bitwarden-cli", "carapace-sandbox"):
        actual = run("docker", "image", "inspect", f"{image}:local", "--format", "{{.Architecture}}")
        assert actual == expected, (image, actual, expected)

    hardened = {
        "read_only": True,
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "tmpfs": ["/tmp:rw,nosuid,nodev,mode=1777"],
    }
    socket_gid = run(
        "docker",
        "run",
        "--rm",
        "-v",
        "/var/run/docker.sock:/var/run/docker.sock",
        "carapace-sandbox:local",
        "stat",
        "-c",
        "%g",
        "/var/run/docker.sock",
    )
    with tempfile.TemporaryDirectory(prefix="carapace-smoke-") as directory:
        state = Path(directory)
        state.chmod(0o755)
        snippet = state / "img-src.conf"
        snippet.write_text("set $csp_img_src \"img-src 'self' data: blob: https://images.example.invalid\";\n")
        compose_file = state / "compose.json"
        compose_file.write_text(
            json.dumps(
                {
                    "services": {
                        "server": {
                            **hardened,
                            "image": "carapace:local",
                            "ports": ["127.0.0.1::8321"],
                            "group_add": [socket_gid],
                            "volumes": ["data:/var/lib/carapace", "/var/run/docker.sock:/var/run/docker.sock"],
                            "environment": {
                                "CARAPACE_TOKEN": "carapace-smoke-password",
                                "CARAPACE_DATABASE_URL": "postgresql+psycopg://carapace:carapace@postgres:5432/carapace",
                                "CARAPACE_CACHE_REDIS_URL": "redis://redis:6379/0",
                                "CARAPACE_SANDBOX_BASE_IMAGE": "carapace-sandbox:local",
                                "CARAPACE_SANDBOX_NETWORK_NAME": "carapace-sandbox",
                                "CARAPACE_SANDBOX_WARM_POOL_SIZE": "0",
                                "CARAPACE_SANDBOX_CLEANUP_ORPHANS_ON_STARTUP": "false",
                            },
                            "depends_on": {
                                "postgres": {"condition": "service_healthy"},
                                "redis": {"condition": "service_healthy"},
                            },
                            "networks": ["default", "carapace-sandbox"],
                        },
                        "frontend": {**hardened, "image": "carapace-frontend:local", "ports": ["127.0.0.1::8080"]},
                        "frontend-extra": {
                            **hardened,
                            "image": "carapace-frontend:local",
                            "ports": ["127.0.0.1::8080"],
                            "volumes": [f"{snippet}:/etc/nginx/csp.d/img-src.conf:ro"],
                        },
                        "postgres": {
                            "image": (
                                "postgres:18-alpine@sha256:"
                                "77f585114c32fbca283dc835b0596f4e52b51b4c6662d7810b2f4084f60a1873"
                            ),
                            "environment": {
                                "POSTGRES_DB": "carapace",
                                "POSTGRES_USER": "carapace",
                                "POSTGRES_PASSWORD": "carapace",
                            },
                            "healthcheck": {
                                "test": ["CMD", "pg_isready", "-U", "carapace"],
                                "interval": "2s",
                                "retries": 30,
                            },
                        },
                        "redis": {
                            "image": (
                                "redis:8-alpine@sha256:3811787313eba226a2ef38658c6ccb91cd5e110edc89c37767de373120a0e5a0"
                            ),
                            "healthcheck": {"test": ["CMD", "redis-cli", "ping"], "interval": "2s", "retries": 30},
                        },
                    },
                    "volumes": {"data": {}},
                    "networks": {"carapace-sandbox": {"internal": True}},
                }
            )
        )
        compose = ["docker", "compose", "-p", f"carapace-smoke-{uuid.uuid4().hex[:10]}", "-f", str(compose_file)]
        try:
            run(*compose, "up", "-d")
            server = "http://" + run(*compose, "port", "server", "8321")
            body, _ = eventually(
                lambda: request(
                    server + "/api/auth/login", {"username": "admin", "password": "carapace-smoke-password"}
                )
            )
            assert json.loads(body)["user"]["username"] == "admin", body
            assert_push_gated(run(*compose, "ps", "-q", "server"))
            for service, policy in (
                ("frontend", "img-src 'self' data: blob:"),
                ("frontend-extra", "img-src 'self' data: blob: https://images.example.invalid"),
            ):
                frontend = "http://" + run(*compose, "port", service, "8080")
                html, csp = eventually(lambda frontend=frontend: request(frontend + "/"))
                assert b"<html" in html, service
                assert csp == policy, (service, csp)
            for service in ("server", "frontend", "frontend-extra"):
                assert_hardened(run(*compose, "ps", "-q", service))
            version = run(
                "docker",
                "run",
                "--rm",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--tmpfs",
                "/tmp:rw,nosuid,nodev,mode=1777",
                "--entrypoint",
                "bw",
                "carapace-bitwarden-cli:local",
                "--version",
            )
            assert version == "2026.4.2", version
            print(
                f"PASS {expected}: authenticated server readiness, default/override CSP, "
                f"effective UID 999, read-only roots, Bitwarden CLI {version}"
            )
        except BaseException:
            subprocess.run([*compose, "logs", "--no-color"], check=False)
            raise
        finally:
            subprocess.run([*compose, "down", "--volumes", "--remove-orphans"], check=True)


if __name__ == "__main__":
    main()
