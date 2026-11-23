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

# Real locks are small trees joined by `follows`. The walk enumerates paths, not nodes, so a crafted lock
# of diamonds would have exponentially many; past this many the sentinel gets the raw diff instead.
_MAX_INPUTS = 500


class _TooManyInputsError(Exception):
    pass


def _q(text: str) -> str:
    """A string from the pushed lock, quoted: a newline in it must not forge a line of this block."""
    return json.dumps(text)


def summarize_lock_change(path: str, old: str | None, new: str | None) -> list[str]:
    """One line per input that was added, removed, moved to another source, or bumped to another revision."""
    before, after = _inputs(old), _inputs(new)
    lock = _q(path)
    if isinstance(before, str) or isinstance(after, str):
        return [f"{lock}: {before if isinstance(before, str) else after}"]
    lines: list[str] = []
    for name in sorted(before.keys() | after.keys()):
        was, now = before.get(name), after.get(name)
        if was == now:
            continue
        prefix = f"{lock}: input {_q(name)}"
        if was is None:
            lines.append(f"{prefix} added: {_describe(now)}")
        elif now is None:
            lines.append(f"{prefix} removed (was {_describe(was)})")
        elif isinstance(was, _Input) and isinstance(now, _Input) and was.source == now.source:
            lines.append(f"{prefix} revision {_q(was.revision)} -> {_q(now.revision)} ({_q(now.source)})")
        elif isinstance(was, _Input) and isinstance(now, _Input):
            lines.append(f"{prefix} moved to another source: {_describe(was)} -> {_describe(now)}")
        else:
            lines.append(f"{prefix} changed: {_describe(was)} -> {_describe(now)}")
    return lines


def _describe(entry: _Input | tuple[str, ...] | None) -> str:
    match entry:
        case _Input(source=source, revision=revision):
            return f"{_q(source)} at {_q(revision)}"
        case tuple() as follows:
            return f"follows {_q('/'.join(follows))}" if follows else "follows the root flake"
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
            if len(found) >= _MAX_INPUTS:
                raise _TooManyInputsError
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
    except _TooManyInputsError:
        return f"flake.lock has more than {_MAX_INPUTS} inputs; review the raw diff"
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
