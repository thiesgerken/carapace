"""Plain-text lines for the inputs a push changes in a `flake.lock`, so the sentinel need not read a lock diff.

Inputs are named by their path from the root flake (`carapace/uv2nix`), not by lock node keys, which Nix
renumbers (`nixpkgs_2`) whenever the graph changes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

# Fields of a locked reference that pin a revision rather than name a source.
_REVISION_FIELDS = frozenset({"rev", "narHash", "lastModified", "revCount", "shortRev"})
_FORGES = frozenset({"github", "gitlab", "sourcehut"})


@dataclass(frozen=True, slots=True)
class _Input:
    source: str
    revision: str


type _Inputs = dict[str, _Input | tuple[str, ...]]  # a locked input, or the path it follows


def summarize_lock_change(path: str, old: str | None, new: str | None) -> list[str]:
    """One line per input that was added, removed, moved to another source, or bumped to another revision."""
    before, after = _inputs(old), _inputs(new)
    if isinstance(before, str) or isinstance(after, str):
        return [f"{path}: {before if isinstance(before, str) else after}"]
    lines: list[str] = []
    for name in sorted(before.keys() | after.keys()):
        was, now = before.get(name), after.get(name)
        if was == now:
            continue
        if was is None:
            lines.append(f"{path}: input {name} added: {_describe(now)}")
        elif now is None:
            lines.append(f"{path}: input {name} removed (was {_describe(was)})")
        elif isinstance(was, _Input) and isinstance(now, _Input) and was.source == now.source:
            lines.append(f"{path}: input {name} revision {was.revision} -> {now.revision} ({now.source})")
        elif isinstance(was, _Input) and isinstance(now, _Input):
            lines.append(f"{path}: input {name} moved to another source: {_describe(was)} -> {_describe(now)}")
        else:
            lines.append(f"{path}: input {name} changed: {_describe(was)} -> {_describe(now)}")
    return lines


def _describe(entry: _Input | tuple[str, ...] | None) -> str:
    match entry:
        case _Input(source=source, revision=revision):
            return f"{source} at {revision}"
        case tuple() as follows:
            return f"follows {'/'.join(follows) or 'the root flake'}"
        case None:
            return "nothing"


def _inputs(text: str | None) -> _Inputs | str:
    """Every input reachable from the root, by path; a string says why the lock could not be read."""
    if text is None:
        return {}
    found: _Inputs = {}

    def walk(node: dict, prefix: tuple[str, ...], seen: frozenset[str]) -> None:
        for name, target in node.get("inputs", {}).items():
            path = (*prefix, name)
            if isinstance(target, list):
                found["/".join(path)] = tuple(target)
            elif target not in seen:
                child = lock["nodes"][target]
                found["/".join(path)] = _locked(child.get("locked", {}))
                walk(child, path, seen | {target})

    # A lock is whatever the push brings: the sentinel hears that it is malformed instead of the push failing.
    try:
        lock = json.loads(text)
        walk(lock["nodes"][lock["root"]], (), frozenset({lock["root"]}))
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as exc:
        return f"flake.lock could not be read ({type(exc).__name__}); review the raw diff"
    return found


def _locked(locked: dict) -> _Input:
    source_fields = {key: value for key, value in locked.items() if key not in _REVISION_FIELDS}
    kind = source_fields.pop("type", "?")
    if kind in _FORGES:
        base = f"{kind}:{source_fields.pop('owner', '?')}/{source_fields.pop('repo', '?')}"
    else:
        base = f"{kind}:{source_fields.pop('url', source_fields.pop('path', '?'))}"
    extras = "".join(f"?{key}={value}" for key, value in sorted(source_fields.items()))
    revision = locked.get("rev", "")[:12] or locked.get("narHash", "unpinned")
    return _Input(source=base + extras, revision=revision)
