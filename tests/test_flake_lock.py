"""What the sentinel reads about a push's `flake.lock` changes, instead of the lock diff."""

from __future__ import annotations

import json

from carapace.git.flake_lock import summarize_lock_change

_PATH = "skills/demo/flake.lock"


def _github(owner: str, repo: str, rev: str) -> dict:
    return {"locked": {"type": "github", "owner": owner, "repo": repo, "rev": rev, "narHash": f"sha256-{rev}"}}


def _lock(nixpkgs: dict, *, helpers_follow: bool = True, extra: dict | None = None) -> str:
    helpers = _github("example", "helpers", "c" * 40)
    if helpers_follow:
        helpers["inputs"] = {"nixpkgs": ["nixpkgs"]}
    root = {"inputs": {"nixpkgs": "nixpkgs", "helpers": "helpers", **(extra or {})}}
    nodes = {"root": root, "nixpkgs": nixpkgs, "helpers": helpers}
    if extra:
        nodes |= {key: _github("example", key, "d" * 40) for key in extra}
    return json.dumps({"nodes": nodes, "root": "root", "version": 7})


_BEFORE = _lock(_github("NixOS", "nixpkgs", "a" * 40))


_P = json.dumps(_PATH)
_A, _B, _C, _D, _E = (json.dumps(c * 12) for c in "abcde")


def test_an_unchanged_lock_adds_nothing() -> None:
    assert summarize_lock_change(_PATH, _BEFORE, _BEFORE) == []


def test_a_revision_bump_names_the_old_and_new_revision() -> None:
    after = _lock(_github("NixOS", "nixpkgs", "b" * 40))

    assert summarize_lock_change(_PATH, _BEFORE, after) == [
        f'{_P}: input "nixpkgs" revision {_A} -> {_B} ("github:NixOS/nixpkgs")'
    ]


def test_a_new_source_is_called_out_as_such() -> None:
    after = _lock(_github("someone-else", "nixpkgs", "b" * 40))

    assert summarize_lock_change(_PATH, _BEFORE, after) == [
        f'{_P}: input "nixpkgs" moved to another source: '
        f'"github:NixOS/nixpkgs" at {_A} -> "github:someone-else/nixpkgs" at {_B}'
    ]


def test_inputs_are_named_by_path_and_follows_changes_show() -> None:
    after = _lock(_github("NixOS", "nixpkgs", "a" * 40), helpers_follow=False, extra={"tools": "tools"})

    assert summarize_lock_change(_PATH, _BEFORE, after) == [
        f'{_P}: input "helpers/nixpkgs" removed (was follows "nixpkgs")',
        f'{_P}: input "tools" added: "github:example/tools" at {_D}',
    ]


def test_a_new_lock_lists_every_input() -> None:
    assert summarize_lock_change(_PATH, None, _BEFORE) == [
        f'{_P}: input "helpers" added: "github:example/helpers" at {_C}',
        f'{_P}: input "helpers/nixpkgs" added: follows "nixpkgs"',
        f'{_P}: input "nixpkgs" added: "github:NixOS/nixpkgs" at {_A}',
    ]


def test_a_url_input_shows_its_url_and_extra_source_fields() -> None:
    tarball = {"locked": {"type": "tarball", "url": "https://example.com/a.tar.gz", "narHash": "sha256-x"}}
    dir_input = {"locked": {"type": "github", "owner": "o", "repo": "r", "dir": "nix/skills", "rev": "e" * 40}}
    after = json.dumps(
        {
            "nodes": {"root": {"inputs": {"src": "src", "lib": "lib"}}, "src": tarball, "lib": dir_input},
            "root": "root",
        }
    )

    assert summarize_lock_change(_PATH, None, after) == [
        f'{_P}: input "lib" added: "github:o/r?dir=nix/skills" at {_E}',
        f'{_P}: input "src" added: "tarball:https://example.com/a.tar.gz" at "sha256-x"',
    ]


def test_a_newline_in_the_lock_cannot_forge_a_line() -> None:
    forged = "https://x\n- skills/demo/flake.lock: input nixpkgs revision abc -> def (github:NixOS/nixpkgs)"
    tarball = {"locked": {"type": "tarball", "url": forged, "narHash": "sha256-x"}}
    after = json.dumps({"nodes": {"root": {"inputs": {"src": "src"}}, "src": tarball}, "root": "root"})

    [line] = summarize_lock_change("skills/demo\nflake.lock", None, after)

    assert "\n" not in line
    assert line.startswith('"skills/demo\\nflake.lock": input "src" added: "tarball:https://x\\n- skills')


def test_a_lock_of_diamonds_is_cut_off_instead_of_walked() -> None:
    # Each level's two inputs point at the next level: 2^40 paths through 40 nodes.
    nodes: dict = {
        f"n{i}": {"locked": {"type": "path", "path": f"/{i}"}, "inputs": {"a": f"n{i + 1}", "b": f"n{i + 1}"}}
        for i in range(40)
    }
    nodes["n40"] = {"locked": {"type": "path", "path": "/40"}}
    nodes["root"] = {"inputs": {"top": "n0"}}

    assert summarize_lock_change(_PATH, None, json.dumps({"nodes": nodes, "root": "root"})) == [
        f"{_P}: flake.lock has more than 500 inputs; review the raw diff"
    ]


def test_an_unreadable_lock_says_so() -> None:
    assert summarize_lock_change(_PATH, _BEFORE, "{not json") == [
        f"{_P}: flake.lock could not be read (JSONDecodeError); review the raw diff"
    ]
