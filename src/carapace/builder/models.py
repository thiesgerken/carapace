"""Wire format between the Carapace server and the skill builder."""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, StringConstraints

# A Git tree hash, SHA-1 or SHA-256 object format.
TreeHash = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}([0-9a-f]{24})?$")]

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


class BuildResult(BaseModel):
    tree: TreeHash
    state: Literal["succeeded", "failed"]
    # Every output of `packages.<system>.default`; empty for a failed build.
    store_paths: list[str] = []
    # `passthru.carapace` of that package as JSON, defined by `mkSkill`; None when absent.
    metadata: Any = None
    # The end of the evaluation and build output, for showing why a build failed.
    log_tail: str = ""


class BuilderInfo(BaseModel):
    # The Nix system the builder builds for, e.g. `x86_64-linux`.
    system: str
    # What sandboxes trust for paths from the builder's cache: its own key and the upstreams'.
    cache_public_keys: list[str]
