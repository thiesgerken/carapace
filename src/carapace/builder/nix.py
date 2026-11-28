"""The Nix commands the builder runs, each as a throwaway subprocess talking to the daemon.

Evaluation happens in these client processes, which run as the unprivileged API user: they
never see the cache signing key, and the daemon does not trust them, so a flake cannot turn
settings like the build sandbox off.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger
from pydantic import ValidationError

from .models import BuildResult, FetchCredential, InputUpdate, SkillDeclarations
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

# The skill directory of an input's `locked` attributes (JSON) in the lock before and after an update, both as
# store paths. Copied under one fixed name, a directory's store path is a hash of its contents alone, so equal
# paths mean the update leaves the directory as it is, whatever else moved in the repository.
# `dir` (`?dir=` of the flake reference) is a flake attribute, not a fetcher's: fetchTree refuses it.
_SKILL_DIRS = """
{ before, after }:
let
  skillDir = attrs:
    let
      locked = builtins.fromJSON attrs;
      tree = builtins.fetchTree (removeAttrs locked [ "dir" ]);
    in
    builtins.path {
      name = "skill";
      path = if locked ? dir then "${tree}/${locked.dir}" else tree.outPath;
    };
in
[ (skillDir before) (skillDir after) ]
"""


def _basic_auth(credential: FetchCredential) -> str:
    # The username the server's knowledge remote uses too; GitHub and Gitea ignore it next to a token.
    return base64.b64encode(f"x-access-token:{credential.token}".encode()).decode()


def _fetch_env(credential: FetchCredential) -> dict[str, str]:
    """The environment that lets one nix invocation's fetchers authenticate to *credential*'s host, and no other.

    Nix fetches `git+https` inputs with the git CLI, which ignores Nix's `access-tokens` and `netrc-file`, so a
    header scoped to the host reaches git through its environment config. `github:` inputs go through GitHub's API,
    which takes `access-tokens` only. Other hosts get no `access-tokens`: Nix's GitLab fetcher would print a token
    without a "PAT:" prefix in a warning.
    """
    remote = f"http.https://{credential.host}/"
    env = {
        "GIT_CONFIG_COUNT": "2",
        "GIT_CONFIG_KEY_0": f"{remote}.extraHeader",
        "GIT_CONFIG_VALUE_0": f"Authorization: Basic {_basic_auth(credential)}",
        # Git sends the header on every request it makes itself, also to the base URL a redirect moved it to.
        "GIT_CONFIG_KEY_1": f"{remote}.followRedirects",
        "GIT_CONFIG_VALUE_1": "false",
    }
    if credential.host == "github.com":
        env["NIX_CONFIG"] = "\n".join(
            filter(None, [os.environ.get("NIX_CONFIG"), f"access-tokens = github.com={credential.token}"])
        )
    return env


def _redacted(log: str, credential: FetchCredential | None) -> str:
    if credential is None:
        return log
    return log.replace(credential.token, "<redacted>").replace(_basic_auth(credential), "<redacted>")


async def _run(
    *args: str, credential: FetchCredential | None = None, env: dict[str, str] | None = None
) -> tuple[int, str, str]:
    """Run a command with *env* added; with *credential*, its fetchers may use it and its stderr never shows it."""
    added = {**(env or {}), **(_fetch_env(credential) if credential else {})}
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, **added} if added else None,
    )
    stdout, stderr = await process.communicate()
    assert process.returncode is not None
    return process.returncode, stdout.decode(errors="replace"), _redacted(stderr.decode(errors="replace"), credential)


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


# Nix's message for a file a skill's flake reads that is not in what it got, e.g. an override's text kept
# outside skills/<attr>/. It names the builder's copy, while the same build works in the user's checkout.
# Path coercion (`"${./x}"`, an `extraFiles` value) and `builtins.readFile` word it differently.
_MISSING_SOURCE_PATH = re.compile(
    r"(?:path|opening file) '/nix/store/[0-9a-df-np-sv-z]{32}-source/[^']*'"
    r"(?: does not exist|: No such file or directory)"
)
_ARCHIVE_HINT = (
    "\nIf that path is in your skills/ directory: the builder gets only skills/flake.nix, flake.lock, config.json, "
    "the skill's own directory and skills/<attribute>/. Keep an override's files in skills/<attribute>/ "
    "(docs/sharing-skills.md)."
)


def _failure_log(log: str) -> str:
    """The end of *log*, with the archive hint when Nix missed a path of a source it got."""
    return _tail(log) + (_ARCHIVE_HINT if _MISSING_SOURCE_PATH.search(log) else "")


def _failed(
    key: str,
    skill: str,
    log: str,
    docs: _SkillDocs = _NO_DOCS,
    declarations: SkillDeclarations | None = None,
    metadata: object = None,
) -> BuildResult:
    return BuildResult(
        key=key,
        skill=skill,
        state="failed",
        metadata=metadata,
        log_tail=_failure_log(log),
        skill_dir=docs.skill_dir,
        skill_md=docs.skill_md,
        skill_files=docs.skill_files,
        declarations=declarations,
    )


async def _declarations(
    source: Path, system: str, skill: str, credential: FetchCredential | None
) -> SkillDeclarations | None:
    """What the package declares, which needs no values: what the Knowledge view offers to configure.

    None when it does not evaluate, in which case the manifest's evaluation fails too and its log says why,
    or when it is not what `SkillDeclarations` describes.
    """
    code, stdout, _ = await _run(
        "nix",
        "eval",
        "--json",
        "--no-update-lock-file",
        f"path:{source}#packages.{system}.{skill}.passthru.carapace",
        "--apply",
        "c: { inherit (c) settings credentials; }",
        credential=credential,
    )
    if code != 0:
        return None
    try:
        return SkillDeclarations.model_validate_json(stdout)
    except ValidationError as exc:
        # Helpers newer than this builder (another setting type, say): the form waits, the build goes on.
        logger.warning(f"Skill {skill} declares what this builder cannot read: {exc}")
        return None


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


async def build_skill(
    source: Path, key: str, skill: str, system: str, roots: Path, credential: FetchCredential | None
) -> BuildResult:
    """Build `packages.<system>.<skill>` of the skills flake in `source` and read its manifest.

    *credential* is what fetching its inputs may use (`_fetch_env`).

    Only that attribute is evaluated, so a broken skill does not stop the others' builds. A skill that
    skills/config.json turns off is not built: its manifest says so and nothing else.
    """
    if not (source / "flake.lock").is_file():
        return _failed(key, skill, "skills/flake.lock is missing. The builder never writes lock files; commit one.")
    declarations = await _declarations(source, system, skill, credential)
    # The manifest first: it fails fast on a mistake in the declarations or settings, before any build runs.
    code, stdout, eval_log = await _run(
        "nix",
        "eval",
        "--json",
        "--no-update-lock-file",
        f"path:{source}#manifests.{system}.{skill}",
        credential=credential,
    )
    if code != 0:
        missing = "does not provide attribute 'manifests" in eval_log
        return _failed(key, skill, (_NO_MANIFESTS if missing else "") + eval_log, declarations=declarations)
    metadata = json.loads(stdout)
    if isinstance(metadata, dict) and metadata.get("enable") is False:
        return BuildResult(key=key, skill=skill, state="succeeded", metadata=metadata, declarations=declarations)
    package = f"path:{source}#packages.{system}.{skill}"
    # The skill directory alone, which only copies files: its SKILL.md is readable before the commands build.
    # A manifest that names none leaves the docs empty, and the server reports that.
    if isinstance(metadata, dict) and "skillDir" in metadata:
        code, _, dir_log = await _run(
            "nix",
            "build",
            "--no-update-lock-file",
            "--no-link",
            f"{package}.skillDir",
            credential=credential,
        )
        if code != 0:
            return _failed(key, skill, dir_log, declarations=declarations, metadata=metadata)
    try:
        docs = _skill_docs(metadata)
    except (SkillFileError, OSError, UnicodeDecodeError) as exc:
        return _failed(
            key, skill, f"Cannot read the skill directory: {exc}", declarations=declarations, metadata=metadata
        )
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
        credential=credential,
    )
    if code != 0:
        return _failed(key, skill, build_log, docs, declarations, metadata)
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
        declarations=declarations,
    )


async def update_input(
    source: Path, name: str, out: Path, store: Path, credential: FetchCredential | None
) -> InputUpdate:
    """The lock of the skills flake in *source* after `nix flake update <name>`, written to *out*, not *source*.

    Only that input moves, so nixpkgs and carapace stay as locked, and one input that cannot be fetched
    does not hide the others' updates. An input pinned to a rev or tag never moves.

    Fetches go to the throwaway *store*, not the daemon's: an update locks whatever a local skill's
    flake.nix names, unlocked `path:/…` inputs included, and the shared store is what the binary cache
    serves. Builds never fetch those, since they refuse to change the lock.

    Nix's fetcher cache goes there too. When a fetch fails, Nix falls back to the Git clone it cached
    and locks its newest commit, so with a shared cache a user without access to a private repository
    would get the head another user's token fetched, knowing nothing but its URL.

    For an input from elsewhere that moved, the skill directories before and after are compared in the
    same store (`_SKILL_DIRS`): a repository's new commit need not touch the skill.
    """
    code, _, log = await _run_in(
        store,
        "nix",
        "flake",
        "update",
        name,
        "--flake",
        f"path:{source}",
        "--output-lock-file",
        str(out),
        credential=credential,
    )
    if code != 0:
        return InputUpdate(log_tail=_tail(log))
    lock = out.read_text()
    before, after = _locked((source / "flake.lock").read_text(), name), _locked(lock, name)
    if after["type"] == "path":
        return InputUpdate(lock=lock, log_tail=_tail(log))
    if before == after:
        return InputUpdate(lock=lock, log_tail=_tail(log), skill_dir_changed=False)
    if before["type"] == "path":
        # A local skill whose input now names a flake elsewhere: no locked directory to compare with.
        return InputUpdate(lock=lock, log_tail=_tail(log), skill_dir_changed=True)
    code, stdout, eval_log = await _run_in(
        store,
        "nix",
        "eval",
        "--json",
        "--expr",
        _SKILL_DIRS,
        "--argstr",
        "before",
        json.dumps(before),
        "--argstr",
        "after",
        json.dumps(after),
        credential=credential,
    )
    if code != 0:
        return InputUpdate(log_tail=_tail(log + eval_log))
    dir_before, dir_after = json.loads(stdout)
    return InputUpdate(lock=lock, log_tail=_tail(log), skill_dir_changed=dir_before != dir_after)


async def _run_in(store: Path, *args: str, credential: FetchCredential | None) -> tuple[int, str, str]:
    """Run a nix command with *store* as its store and fetcher cache (`update_input` says why)."""
    return await _run(*args, "--store", str(store), credential=credential, env={"XDG_CACHE_HOME": str(store / "cache")})


def _locked(lock_text: str, name: str) -> dict[str, object]:
    """The `locked` attributes of the skills flake's input *name* in a flake.lock."""
    lock = json.loads(lock_text)
    nodes = lock["nodes"]
    return nodes[nodes[lock["root"]]["inputs"][name]]["locked"]
