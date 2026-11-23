#!/usr/bin/env python3
"""Exercise locally loaded images in an isolated, disposable Compose project."""

from __future__ import annotations

import io
import json
import os
import re
import subprocess
import tarfile
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
    assert push.returncode != 0 and "Push rejected: Session not found" in push.stderr, push.stderr
    assert run(*execute, "-C", repo, "rev-parse", "HEAD") == before


def assert_bitwarden() -> str:
    docker = [
        "docker",
        "run",
        "--rm",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,mode=1777",
        "--network=none",
        "-e",
        "BW_NOINTERACTION=true",
    ]
    image = "carapace-bitwarden-cli:local"
    cli = [*docker, "--entrypoint", "bw", image]
    version = run(*cli, "--version")
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), version
    status = json.loads(run(*cli, "status"))
    assert status["status"] == "unauthenticated", status
    password = run(*cli, "generate", "--uppercase", "--lowercase", "--number", "--length", "32")
    assert re.fullmatch(r"[A-Za-z0-9]{32}", password)
    server = "https://vault.example.invalid"
    configured = run(
        *docker,
        "--entrypoint",
        "sh",
        image,
        "-c",
        'bw config server "$1" >/dev/null && bw config server',
        "config-smoke",
        server,
    )
    assert configured == server, configured
    rejected = subprocess.run(
        [*cli, "serve", "--hostname", "127.0.0.1", "--port", "8087"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert rejected.returncode != 0 and "You are not logged in" in rejected.stderr, rejected.stderr
    return version


SANDBOX_SMOKE = r"""
set -euo pipefail
command -v cgate getent > /dev/null
! compgen -G '/bin/python*' > /dev/null || { ls /bin/python*; exit 1; }
# The server's start-up egress probe needs bash's /dev/tcp, timeout and getent.
timeout 5 bash -c 'exec 3<>/dev/tcp/example.com/80'
getent hosts example.com > /dev/null
python=$(realpath "$(command -v python3)")
[[ $python == /root/.local/share/uv/python/cpython-3.14.* ]] || { echo "python3 is $python"; exit 1; }
[[ $(UV_PYTHON_DOWNLOADS=never uv python find) == "$python" ]]
mkdir /tmp/py && cd /tmp/py
printf '[project]\nname = "smoke"\nversion = "0"\ndependencies = ["numpy"]\n' > pyproject.toml
UV_PYTHON_DOWNLOADS=never uv sync --quiet
uv run python -c 'import numpy; assert numpy.ones(3).sum() == 3'
mkdir /tmp/js && cd /tmp/js && npm init -y > /dev/null
npm install --package-lock-only --silent sharp
npm ci --silent
node -e 'require("sharp")({create: {width: 1, height: 1, channels: 3, background: "red"}}).png().toBuffer()'
curl -fsSL "https://github.com/sharkdp/fd/releases/download/v10.2.0/fd-v10.2.0-$(uname -m)-unknown-linux-gnu.tar.gz" \
  | tar -xz --no-same-owner -C /tmp
file -L /tmp/fd-*/fd | grep -q "dynamically linked, interpreter /lib"
/tmp/fd-*/fd --version > /dev/null
[[ $(nix run nixpkgs#hello) == "Hello, world!" ]]
"""


def assert_sandbox() -> None:
    # Kubernetes runs sandboxes as root without capabilities; Docker mode adds them back.
    docker = ["docker", "run", "--rm", "--cap-drop=ALL", "--security-opt=no-new-privileges", "--memory=2g"]
    image = "carapace-sandbox:local"
    # The registry entry is final and the image holds its store path, so nixpkgs resolves without
    # any network. Only the lite image for local Mac builds, which leaves the source out, skips this.
    if os.environ.get("CARAPACE_SMOKE_SANDBOX_LITE") == "1":
        print("CARAPACE_SMOKE_SANDBOX_LITE=1: skipping the offline nixpkgs check")
    else:
        offline = run(*docker, "--network=none", image, "nix", "eval", "--raw", "nixpkgs#hello.name")
        assert offline.startswith("hello-"), offline
    run(*docker, image, "bash", "-c", SANDBOX_SMOKE)


# A skill flake without inputs builds offline: /bin/sh inside the Nix build sandbox is Nix's own shell.
BUILDER_SMOKE_FLAKE = b"""{
  outputs = { self }: {
    packages = builtins.listToAttrs (map (system: {
      name = system;
      value.default = derivation {
        name = "smoke-skill";
        inherit system;
        builder = "/bin/sh";
        args = [ "-c" "echo smoke > $out" ];
      } // { passthru.carapace.commands.smoke.description = "Smoke"; };
    }) [ "x86_64-linux" "aarch64-linux" ]);
  };
}
"""


def skill_archive(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


def put_build(url: str, token: str, archive: bytes) -> dict:
    req = urllib.request.Request(url, data=archive, method="PUT", headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=300) as response:
        return json.loads(response.read())


def assert_builder_cache(container: str, api: str, token: str, store_path: str) -> None:
    """The cache serves the built path, signed with the key the API advertises to the server."""
    info_request = urllib.request.Request(api + "/info", headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(info_request, timeout=15) as response:
        key_name = json.loads(response.read())["cache_public_keys"][0].split(":", 1)[0]
    assert key_name == "carapace-builder-1", key_name
    cache = "http://" + run("docker", "port", container, "8331")
    assert b"StoreDir: /nix/store" in request(cache + "/nix-cache-info")[0]
    narinfo = request(f"{cache}/{store_path.removeprefix('/nix/store/')[:32]}.narinfo")[0].decode()
    assert f"StorePath: {store_path}\n" in narinfo and "Sig: carapace-builder-1:" in narinfo, narinfo
    nar_url = next(line.removeprefix("URL: ") for line in narinfo.splitlines() if line.startswith("URL: "))
    assert request(f"{cache}/{nar_url}")[0], nar_url


def assert_builder() -> str:
    image = "carapace-builder:local"
    token = "builder-smoke-token"
    volume = f"carapace-smoke-builder-{uuid.uuid4().hex[:10]}"
    run("docker", "volume", "create", volume)
    container = ""
    try:
        run("docker", "run", "--rm", "-v", f"{volume}:/mnt/nix", image, "/bin/carapace-builder-init")
        # The Compose settings for the Nix build sandbox (see docker-compose.yml).
        container = run(
            *("docker", "run", "-d", "-p", "127.0.0.1::8330", "-p", "127.0.0.1::8331"),
            *("-e", f"CARAPACE_BUILDER_TOKEN={token}"),
            *("--security-opt", "seccomp=unconfined", "--security-opt", "apparmor=unconfined"),
            *("--security-opt", "systempaths=unconfined", "-v", f"{volume}:/nix", image),
        )
        base = "http://" + run("docker", "port", container, "8330")
        eventually(lambda: request(base + "/healthz"))
        url = base + "/builds/" + "5" * 40
        archive = skill_archive(
            {"flake.nix": BUILDER_SMOKE_FLAKE, "flake.lock": b'{"nodes":{"root":{}},"root":"root","version":7}'}
        )
        built = put_build(url, token, archive)
        assert built["state"] == "succeeded", built
        assert built["metadata"] == {"commands": {"smoke": {"description": "Smoke"}}}, built
        assert put_build(url, token, b"stored results need no archive") == built
        assert_builder_cache(container, base, token, built["store_paths"][0])
        processes = run("docker", "top", container, "-eo", "pid,euid,cmd").splitlines()[1:]
        api = [line.split()[1] for line in processes if line.endswith("/bin/carapace-builder")]
        assert api == ["999"], processes
        harmonia = [line.split()[1] for line in processes if line.endswith("harmonia-cache")]
        assert harmonia == ["998"], processes
        return built["store_paths"][0]
    except BaseException:
        if container:
            subprocess.run(["docker", "logs", container], check=False)
        raise
    finally:
        if container:
            subprocess.run(["docker", "rm", "-f", container], check=True, capture_output=True)
        subprocess.run(["docker", "volume", "rm", volume], check=True, capture_output=True)


def main() -> None:
    architecture = run("docker", "info", "--format", "{{.Architecture}}")
    assert architecture in ("aarch64", "arm64", "x86_64", "amd64"), architecture
    expected = "arm64" if architecture in ("aarch64", "arm64") else "amd64"
    for image in ("carapace", "carapace-frontend", "carapace-bitwarden-cli", "carapace-sandbox", "carapace-builder"):
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
    project = f"carapace-smoke-{uuid.uuid4().hex[:10]}"
    # The server creates sandboxes through the host's Docker daemon, which resolves their workspace bind
    # mounts on the host: the data directory needs a host path, as CARAPACE_HOST_DATA_DIR in
    # docker-compose.yml. A volume's mountpoint is one, and the daemon owns its cleanup.
    data_volume = run("docker", "volume", "create", f"{project}-data")
    host_data_dir = run("docker", "volume", "inspect", "--format", "{{.Mountpoint}}", data_volume)
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
                            "volumes": [
                                f"{data_volume}:/var/lib/carapace",
                                "/var/run/docker.sock:/var/run/docker.sock",
                            ],
                            "environment": {
                                "CARAPACE_TOKEN": "carapace-smoke-password",
                                "CARAPACE_HOST_DATA_DIR": host_data_dir,
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
                    "volumes": {data_volume: {"external": True}},
                    "networks": {"carapace-sandbox": {"internal": True}},
                }
            )
        )
        compose = ["docker", "compose", "-p", project, "-f", str(compose_file)]
        try:
            run(*compose, "up", "-d")
            server = "http://" + run(*compose, "port", "server", "8321")
            body, _ = eventually(
                lambda: request(
                    server + "/api/auth/login", {"username": "admin", "password": "carapace-smoke-password"}
                )
            )
            assert json.loads(body)["user"]["username"] == "admin", body
            assert "Sandbox egress self-test passed" in run(*compose, "logs", "--no-color", "server")
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
            version = assert_bitwarden()
            assert_sandbox()
            assert_builder()
            print(
                f"PASS {expected}: authenticated server readiness, sandbox egress self-test, default/override CSP, "
                f"effective UID 999, read-only roots, Bitwarden CLI {version} offline commands and serve rejection, "
                "sandbox python-build-standalone, native wheels and npm addons, nix-ld, offline nixpkgs, "
                "builder sandbox probe, build and stored result with the API unprivileged, signed builder cache"
            )
        except BaseException:
            subprocess.run([*compose, "logs", "--no-color"], check=False)
            raise
        finally:
            subprocess.run([*compose, "down", "--volumes", "--remove-orphans"], check=True)
            subprocess.run(["docker", "volume", "rm", data_volume], check=True)


if __name__ == "__main__":
    main()
