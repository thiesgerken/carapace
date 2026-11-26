"""The Nix commands the builder runs, each as a throwaway subprocess talking to the daemon.

Evaluation happens in these client processes, which run as the unprivileged API user: they
never see the cache signing key, and the daemon does not trust them, so a flake cannot turn
settings like the build sandbox off.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from .models import BuildResult
from .skill_dir import SkillFileError, checked_skill_dir, list_files, read_file

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
        raise RuntimeError(
            "The Nix build sandbox is not effective; see docs/builder.md for what the host must allow "
            f"(user namespaces, e.g. kernel.apparmor_restrict_unprivileged_userns on Ubuntu):\n{_tail(stderr)}"
        )


async def collect_garbage() -> str:
    """Delete every store path no GC root keeps alive; the daemon allows this for untrusted users."""
    code, stdout, stderr = await _run("nix-store", "--gc")
    if code != 0:
        raise RuntimeError(f"nix-store --gc failed: {_tail(stderr)}")
    return _tail(stdout + stderr)


@dataclass(frozen=True, slots=True)
class _SkillDocs:
    skill_dir: str | None = None
    skill_md: str | None = None
    skill_files: list[str] = field(default_factory=list)


_NO_DOCS = _SkillDocs()


def _failed(key: str, skill: str, log: str, docs: _SkillDocs = _NO_DOCS) -> BuildResult:
    return BuildResult(
        key=key,
        skill=skill,
        state="failed",
        log_tail=_tail(log),
        skill_dir=docs.skill_dir,
        skill_md=docs.skill_md,
        skill_files=docs.skill_files,
    )


def _skill_docs(metadata: object) -> _SkillDocs:
    """The skill directory the metadata names, its SKILL.md and its file list."""
    skill_dir = checked_skill_dir(metadata)
    if skill_dir is None:
        return _SkillDocs()
    try:
        skill_md: str | None = read_file(skill_dir, "SKILL.md").decode()
    except FileNotFoundError:
        skill_md = None
    return _SkillDocs(skill_dir=skill_dir, skill_md=skill_md, skill_files=list_files(skill_dir))


async def build_skill(source: Path, key: str, skill: str, system: str, roots: Path) -> BuildResult:
    """Build `packages.<system>.<skill>` of the skills flake in `source` and read its metadata.

    Only that attribute is evaluated, so a broken skill does not stop the others' builds.
    """
    if not (source / "flake.lock").is_file():
        return _failed(key, skill, "skills/flake.lock is missing. The builder never writes lock files; commit one.")
    package = f"path:{source}#packages.{system}.{skill}"
    # The metadata first: it fails fast on a mistake in the declarations, before any build runs.
    code, stdout, eval_log = await _run(
        "nix", "eval", "--json", "--no-update-lock-file", package, "--apply", "p: p.passthru.carapace or null"
    )
    if code != 0:
        return _failed(key, skill, eval_log)
    metadata = json.loads(stdout)
    try:
        docs = _skill_docs(metadata)
    except (SkillFileError, OSError, UnicodeDecodeError) as exc:
        return _failed(key, skill, f"Cannot read the skill directory: {exc}")
    code, stdout, build_log = await _run(
        "nix",
        "build",
        "--no-update-lock-file",
        "--print-build-logs",
        "--json",
        # A GC root per key, under the builder's state, keeps the outputs until GC drops it.
        "--out-link",
        str(roots / key),
        package,
    )
    if code != 0:
        return _failed(key, skill, build_log, docs)
    store_paths = [path for built in json.loads(stdout) for path in built["outputs"].values()]
    return BuildResult(
        key=key,
        skill=skill,
        state="succeeded",
        store_paths=store_paths,
        metadata=metadata,
        log_tail=_tail(build_log),
        skill_dir=docs.skill_dir,
        skill_md=docs.skill_md,
        skill_files=docs.skill_files,
    )
