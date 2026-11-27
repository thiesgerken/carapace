"""Wire format between the Carapace server and the skill builder."""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, StringConstraints

# A sha256 over everything a skill's build depends on, computed by the server (`skill_builds.build_key`).
BuildKey = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
# An attribute of `packages.<system>` in skills/flake.nix. It ends up in a flake reference, so no dots or quotes.
SKILL_NAME_PATTERN = r"[A-Za-z_][A-Za-z0-9_'-]*"
SkillName = Annotated[str, StringConstraints(pattern=f"^{SKILL_NAME_PATTERN}$")]

# Sandboxes reach the builder's binary cache under this name through their session proxy, which
# maps it to the cache listener (`.internal` is reserved for private use, so it never collides).
CACHE_HOST = "cache.carapace.internal"

# The only requests the cache listener answers and the proxy forwards: the cache info, narinfos
# (Nix base32 store hashes), and NARs, the builder's own or an upstream's. NAR names are Nix base32
# hashes too (32 characters from harmonia, 52 for an upstream's sha256): a sandbox-chosen name goes
# on to the upstreams, so its length bounds what a request can carry there.
_BASE32 = "[0-9a-df-np-sv-z]"
_CACHE_PATH = re.compile(
    rf"^/(nix-cache-info|{_BASE32}{{32}}\.narinfo|(upstream/[0-9]+/)?nar/{_BASE32}{{32,52}}\.nar(\.(xz|zst|bz2|br))?)$"
)


def cache_path_allowed(path: str) -> bool:
    """Whether *path* (without query) is one of the binary cache requests."""
    return _CACHE_PATH.fullmatch(path) is not None


class UpstreamCache(BaseModel):
    url: str
    public_key: str


class SettingDeclaration(BaseModel):
    """A setting a skill declares (`mkSkill { settings }`), independent of any instance's value."""

    type: Literal["str", "int", "bool"]
    description: str = ""
    # None when the setting has no default; Nix's str, int and bool admit no null.
    default: str | int | bool | None = None


class BuildResult(BaseModel):
    key: BuildKey
    skill: SkillName
    state: Literal["succeeded", "failed"]
    # Every output of `packages.<system>.<skill>`; empty for a failed build.
    store_paths: list[str] = []
    # `manifests.<system>.<skill>` of the skills flake as JSON, written by `skillsFlake`; None when absent.
    metadata: Any = None
    # Its `skillDir`, the skill directory in the store, and what is in it, read right after the evaluation,
    # so a failed build has them too. None and empty for a package from helpers without `src`.
    skill_dir: str | None = None
    skill_md: str | None = None
    skill_files: list[str] = []
    # The end of the evaluation and build output, for showing why a build failed.
    log_tail: str = ""
    # The package's setting declarations, evaluated without this instance's values, so they are there when
    # the manifest fails for a missing or wrong value; None when the package itself does not evaluate.
    declared_settings: dict[str, SettingDeclaration] | None = None


class InputUpdate(BaseModel):
    # The lock `nix flake update <input>` writes for the skills flake; None when that failed.
    lock: str | None = None
    # The end of its output, for showing why it failed.
    log_tail: str = ""


class UpdatedLocks(BaseModel):
    # Per input of skills/flake.nix that was asked about.
    inputs: dict[SkillName, InputUpdate]


class Roots(BaseModel):
    # The build keys of the skills at the current heads of all knowledge repos.
    keys: list[BuildKey]


class GcResult(BaseModel):
    # Keys whose results and GC roots were dropped because no head referenced them for the grace period.
    dropped: list[str]
    log_tail: str


class BuilderInfo(BaseModel):
    # The Nix system the builder builds for, e.g. `x86_64-linux`.
    system: str
    # What sandboxes trust for paths from the builder's cache: its own key and the upstreams'.
    cache_public_keys: list[str]
