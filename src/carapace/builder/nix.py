"""The Nix commands the builder runs, each as a throwaway subprocess talking to the daemon.

Evaluation happens in these client processes, which run as the unprivileged API user: they
never see the cache signing key, and the daemon does not trust them, so a flake cannot turn
settings like the build sandbox off.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from .models import BuildResult

LOG_TAIL_CHARS = 16_000

# Inside the build sandbox /bin/sh is Nix's sandbox shell and the store database is not mounted.
# Without the sandbox the builder would run the image's /bin/sh, see /nix/var and fail.
_SANDBOX_PROBE = """
{ system, nonce }:
derivation {
  name = "carapace-builder-sandbox-probe";
  inherit system nonce;
  builder = "/bin/sh";
  args = [ "-c" "test ! -e /nix/var/nix/db && echo > $out" ];
}
"""


async def _run(*args: str) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    assert process.returncode is not None
    return process.returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace")


def _tail(log: str) -> str:
    return log[-LOG_TAIL_CHARS:]


async def current_system() -> str:
    code, stdout, stderr = await _run("nix", "config", "show", "system")
    if code != 0:
        raise RuntimeError(f"Cannot read the Nix system: {_tail(stderr)}")
    return stdout.strip()


async def verify_sandbox(system: str) -> None:
    """Build a fresh probe derivation; fails unless the daemon enforces the build sandbox."""
    code, _, stderr = await _run(
        "nix",
        "build",
        "--no-link",
        "--expr",
        _SANDBOX_PROBE,
        "--argstr",
        "system",
        system,
        # A new derivation every start, so the probe really builds instead of hitting the store.
        "--argstr",
        "nonce",
        str(time.time_ns()),
    )
    if code != 0:
        raise RuntimeError(f"The Nix build sandbox is not effective:\n{_tail(stderr)}")


def _failed(tree: str, log: str) -> BuildResult:
    return BuildResult(tree=tree, state="failed", log_tail=_tail(log))


async def build_skill(source: Path, tree: str, system: str, roots: Path) -> BuildResult:
    """Build `packages.<system>.default` of the skill flake in `source` and read its metadata."""
    if not (source / "flake.lock").is_file():
        return _failed(tree, "flake.lock is missing. The builder never writes lock files; commit one with the skill.")
    package = f"path:{source}#packages.{system}.default"
    code, stdout, build_log = await _run(
        "nix",
        "build",
        "--no-update-lock-file",
        "--print-build-logs",
        "--json",
        # A GC root per tree, under the builder's state, keeps the outputs until GC drops it.
        "--out-link",
        str(roots / tree),
        package,
    )
    if code != 0:
        return _failed(tree, build_log)
    store_paths = [path for built in json.loads(stdout) for path in built["outputs"].values()]
    code, stdout, eval_log = await _run(
        "nix", "eval", "--json", "--no-update-lock-file", package, "--apply", "p: p.passthru.carapace or null"
    )
    if code != 0:
        return _failed(tree, build_log + eval_log)
    return BuildResult(
        tree=tree, state="succeeded", store_paths=store_paths, metadata=json.loads(stdout), log_tail=_tail(build_log)
    )
