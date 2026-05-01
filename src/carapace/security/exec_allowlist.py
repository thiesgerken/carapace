from __future__ import annotations

import re
from typing import Any

_EXEC_PATH_SEGMENT = r"[A-Za-z0-9_:@%+=,-][A-Za-z0-9_:@%+=.,-]*"
_EXEC_WORKSPACE_PATH = rf"/workspace(?:/{_EXEC_PATH_SEGMENT})+/?"
_EXEC_RELATIVE_PATH = (
    rf"(?:\.|{_EXEC_PATH_SEGMENT}(?:/{_EXEC_PATH_SEGMENT})*|" + rf"\./{_EXEC_PATH_SEGMENT}(?:/{_EXEC_PATH_SEGMENT})*)/?"
)
_EXEC_PATH = rf"(?:{_EXEC_WORKSPACE_PATH}|{_EXEC_RELATIVE_PATH})"
_EXEC_NEEDLE = r"[^\s'\";&|<>`$(){}\[\]\\\n\r*?~]+"
_UNSAFE_EXEC_SHELL_RE = re.compile(r"""[;&|<>`$(){}\[\]\\\n\r'\"*?~]""")
_AUTO_ALLOWED_EXEC_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("ls", re.compile(rf"^\s*(?:/bin/ls|/usr/bin/ls|ls)(?:\s+-[A-Za-z]+)*(?:\s+{_EXEC_PATH})*\s*$")),
    ("cat", re.compile(rf"^\s*(?:/bin/cat|/usr/bin/cat|cat)(?:\s+{_EXEC_PATH})+\s*$")),
    (
        "head",
        re.compile(rf"^\s*(?:/usr/bin/head|head)(?:\s+-n\s+[0-9]+)?(?:\s+{_EXEC_PATH})+\s*$"),
    ),
    (
        "tail",
        re.compile(rf"^\s*(?:/usr/bin/tail|tail)(?:\s+-n\s+[0-9]+)?(?:\s+{_EXEC_PATH})+\s*$"),
    ),
    ("wc", re.compile(rf"^\s*(?:/usr/bin/wc|wc)\s+-l(?:\s+{_EXEC_PATH})+\s*$")),
    ("file", re.compile(rf"^\s*(?:/usr/bin/file|file)(?:\s+-b)?(?:\s+{_EXEC_PATH})+\s*$")),
    (
        "grep",
        re.compile(
            r"^\s*(?:/bin/grep|/usr/bin/grep|grep)(?=.*(?:^|\s)-[A-Za-z]*F[A-Za-z]*(?:\s|$))(?:\s+-[A-Za-z]+)*"
            + rf"(?:\s+--)?\s+{_EXEC_NEEDLE}(?:\s+{_EXEC_PATH})+\s*$"
        ),
    ),
    (
        "rg",
        re.compile(
            r"^\s*(?:/usr/bin/rg|rg)(?=.*(?:^|\s)-[A-Za-z]*F[A-Za-z]*(?:\s|$))(?:\s+-[A-Za-z]+)*"
            + rf"(?:\s+--)?\s+{_EXEC_NEEDLE}(?:\s+{_EXEC_PATH})+\s*$"
        ),
    ),
)


def match_auto_allowed_exec(args: dict[str, Any]) -> str | None:
    if args.get("contexts"):
        return None

    command = args.get("command")
    if not isinstance(command, str):
        return None

    if _UNSAFE_EXEC_SHELL_RE.search(command):
        return None

    stripped = command.strip()
    for label, pattern in _AUTO_ALLOWED_EXEC_PATTERNS:
        if pattern.fullmatch(stripped):
            return label
    return None
