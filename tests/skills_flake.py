"""skills/flake.nix and the lock `nix flake lock` would write for it, for tests that need listed skills."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path


def write_skills_flake(skills_dir: Path, local: list[str] | dict[str, str], external: Sequence[str] = ()) -> None:
    """List *local* as `path:` inputs (a dict maps a name to its directory) and *external* as GitHub flakes."""
    directories = local if isinstance(local, dict) else {name: name for name in local}
    nodes: dict[str, object] = {
        "nixpkgs": {"locked": {"type": "github", "owner": "NixOS", "repo": "nixpkgs", "rev": "0" * 40}},
        "carapace": {"locked": {"type": "github", "owner": "thiesgerken", "repo": "carapace", "rev": "1" * 40}},
    }
    nodes |= {name: {"locked": {"type": "path", "path": f"./{directory}"}} for name, directory in directories.items()}
    nodes |= {
        name: {"locked": {"type": "github", "owner": "someone", "repo": name, "rev": "2" * 40}} for name in external
    }
    nodes["root"] = {"inputs": {name: name for name in nodes}}
    skills_dir.mkdir(parents=True, exist_ok=True)
    (skills_dir / "flake.nix").write_text("{ outputs = _: { }; }\n")
    (skills_dir / "flake.lock").write_text(json.dumps({"nodes": nodes, "root": "root", "version": 7}))
