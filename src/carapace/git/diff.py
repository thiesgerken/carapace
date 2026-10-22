from __future__ import annotations

import re
from codecs import escape_decode

_DIFF_PATHS = re.compile(r'^diff --git ("(?:\\.|[^"\\])*"|a/.*?) ("(?:\\.|[^"\\])*"|b/.*)$')
_SAME_PATH = re.compile(r"^diff --git a/(.*) b/\1$")


def _unquote_path(path: str) -> str:
    if path.startswith('"') and path.endswith('"'):
        # Git quotes paths with C escapes, including octal-encoded UTF-8 bytes.
        return escape_decode(path[1:-1].encode())[0].decode(errors="surrogateescape")
    return path


def touched_paths(diff: str) -> set[str]:
    paths: set[str] = set()
    for line in diff.split("\n"):
        if line.startswith(("--- ", "+++ ")):
            path = _unquote_path(line[4:].split("\t", 1)[0])
            if path != "/dev/null":
                paths.add(path[2:] if path.startswith(("a/", "b/")) else path)
        elif line.startswith(("rename from ", "rename to ", "copy from ", "copy to ")):
            paths.add(_unquote_path(line.split(" ", 2)[2]))
        elif match := _SAME_PATH.fullmatch(line):
            paths.add(match.group(1))
        elif match := _DIFF_PATHS.fullmatch(line):
            paths.add(_unquote_path(match.group(1)).removeprefix("a/"))
            paths.add(_unquote_path(match.group(2)).removeprefix("b/"))
    return paths
