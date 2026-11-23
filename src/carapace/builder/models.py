"""Wire format between the Carapace server and the skill builder."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, StringConstraints

# A Git tree hash, SHA-1 or SHA-256 object format.
TreeHash = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}([0-9a-f]{24})?$")]


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
