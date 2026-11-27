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

from .models import BuildResult, InputUpdate, SettingDeclaration
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


def _failed(
    key: str,
    skill: str,
    log: str,
    docs: _SkillDocs = _NO_DOCS,
    declared: dict[str, SettingDeclaration] | None = None,
) -> BuildResult:
    return BuildResult(
        key=key,
        skill=skill,
        state="failed",
        log_tail=_tail(log),
        skill_dir=docs.skill_dir,
        skill_md=docs.skill_md,
        skill_files=docs.skill_files,
        declared_settings=declared,
    )


async def _declared_settings(source: Path, system: str, skill: str) -> dict[str, SettingDeclaration] | None:
    """The package's setting declarations, which need no values: what the Knowledge view offers to set.

    None when they do not evaluate; the manifest's evaluation then fails too and its log says why.
    """
    code, stdout, _ = await _run(
        "nix",
        "eval",
        "--json",
        "--no-update-lock-file",
        f"path:{source}#packages.{system}.{skill}.passthru.carapace.settings",
    )
    if code != 0:
        return None
    return {name: SettingDeclaration.model_validate(value) for name, value in json.loads(stdout).items()}


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


_NO_MANIFESTS = (
    "skills/flake.nix has no manifests for its skills: write its outputs with carapace.lib.skillsFlake "
    '(docs/skill-flakes.md, "The skills flake").\n'
)


async def build_skill(source: Path, key: str, skill: str, system: str, roots: Path) -> BuildResult:
    """Build `packages.<system>.<skill>` of the skills flake in `source` and read its manifest.

    Only that attribute is evaluated, so a broken skill does not stop the others' builds. A skill that
    skills/config.json turns off is not built: its manifest says so and nothing else.
    """
    if not (source / "flake.lock").is_file():
        return _failed(key, skill, "skills/flake.lock is missing. The builder never writes lock files; commit one.")
    declared = await _declared_settings(source, system, skill)
    # The manifest first: it fails fast on a mistake in the declarations or settings, before any build runs.
    code, stdout, eval_log = await _run(
        "nix", "eval", "--json", "--no-update-lock-file", f"path:{source}#manifests.{system}.{skill}"
    )
    if code != 0:
        missing = "does not provide attribute 'manifests" in eval_log
        return _failed(key, skill, (_NO_MANIFESTS if missing else "") + eval_log, declared=declared)
    metadata = json.loads(stdout)
    if isinstance(metadata, dict) and metadata.get("enable") is False:
        return BuildResult(key=key, skill=skill, state="succeeded", metadata=metadata, declared_settings=declared)
    package = f"path:{source}#packages.{system}.{skill}"
    try:
        docs = _skill_docs(metadata)
    except (SkillFileError, OSError, UnicodeDecodeError) as exc:
        return _failed(key, skill, f"Cannot read the skill directory: {exc}", declared=declared)
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
        return _failed(key, skill, build_log, docs, declared)
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
        declared_settings=declared,
    )


async def update_input(source: Path, name: str, out: Path, store: Path) -> InputUpdate:
    """The lock of the skills flake in *source* after `nix flake update <name>`, written to *out*, not *source*.

    Only that input moves, so nixpkgs and carapace stay as locked, and one input that cannot be fetched
    does not hide the others' updates. An input pinned to a rev or tag never moves.

    Fetches go to the throwaway *store*, not the daemon's: an update locks whatever a local skill's
    flake.nix names, unlocked `path:/…` inputs included, and the shared store is what the binary cache
    serves. Builds never fetch those, since they refuse to change the lock.
    """
    code, _, log = await _run(
        "nix",
        "flake",
        "update",
        name,
        "--flake",
        f"path:{source}",
        "--output-lock-file",
        str(out),
        "--store",
        str(store),
    )
    if code != 0:
        return InputUpdate(log_tail=_tail(log))
    return InputUpdate(lock=out.read_text(), log_tail=_tail(log))
