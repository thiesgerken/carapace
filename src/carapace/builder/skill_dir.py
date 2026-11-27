"""A built skill's directory in the store: its SKILL.md, its file list and single files, for the server.

The directory's path comes from the skill's own metadata (`passthru.carapace.skillDir`), so a flake picks
it. Only a top-level store path is accepted, and no symlink is followed on the way to a file: otherwise a
skill could point the builder at its state, its token or anything else it can read.
"""

from __future__ import annotations

import errno
import os
import re
import stat
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import PurePosixPath

# Nix base32 leaves out e, o, t and u; the name part as Nix allows it.
_STORE_PATH = re.compile(r"/nix/store/[0-9a-df-np-sv-z]{32}-[A-Za-z0-9+\-._?=]+")
MAX_FILE_BYTES = 1024 * 1024
MAX_FILES = 2000


class SkillFileError(ValueError):
    """A path that is not a readable file of the skill directory."""


def checked_skill_dir(metadata: object) -> str | None:
    """`skillDir` of *metadata* when it names a store path; None for metadata without one (older helpers)."""
    skill_dir = metadata.get("skillDir") if isinstance(metadata, dict) else None
    if skill_dir is None:
        return None
    if not isinstance(skill_dir, str) or not _STORE_PATH.fullmatch(skill_dir):
        raise SkillFileError(f"skillDir must be a store path, not {skill_dir!r}")
    return skill_dir


def relative_parts(path: str) -> tuple[str, ...]:
    """The components of *path* when it stays inside the skill directory."""
    parts = PurePosixPath(path).parts
    if not parts or parts[0] == "/" or any(part in (".", "..") for part in parts):
        raise SkillFileError(f"{path!r} is not a relative path inside the skill")
    return parts


def read_file(skill_dir: str, path: str) -> bytes:
    """The content of *path*, relative to *skill_dir*. Raises ``FileNotFoundError`` or ``SkillFileError``."""
    parts = relative_parts(path)
    with _directory(skill_dir) as fd:
        opened: list[int] = []
        try:
            for part in parts[:-1]:
                fd = _open(part, os.O_DIRECTORY, fd)
                opened.append(fd)
            file_fd = _open(parts[-1], 0, fd)
        finally:
            for directory in opened:
                os.close(directory)
    info = os.fstat(file_fd)
    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE_BYTES:
        os.close(file_fd)
        reason = "is not a file" if not stat.S_ISREG(info.st_mode) else f"is larger than {MAX_FILE_BYTES} bytes"
        raise SkillFileError(f"{path} {reason}")
    with os.fdopen(file_fd, "rb") as file:
        return file.read()


def list_files(skill_dir: str) -> list[str]:
    """Every regular file under *skill_dir*, relative and sorted; symlinks are left out, not followed."""
    files: list[str] = []
    with _directory(skill_dir) as fd:
        for root, _dirs, names, root_fd in os.fwalk(".", dir_fd=fd, follow_symlinks=False):
            for name in names:
                if stat.S_ISREG(os.stat(name, dir_fd=root_fd, follow_symlinks=False).st_mode):
                    files.append(os.path.normpath(os.path.join(root, name)))
                    if len(files) > MAX_FILES:
                        raise SkillFileError(f"the skill directory has more than {MAX_FILES} files")
    return sorted(files)


@contextmanager
def _directory(skill_dir: str) -> Generator[int]:
    if not _STORE_PATH.fullmatch(skill_dir):
        raise SkillFileError(f"{skill_dir!r} is not a store path")
    fd = _open(skill_dir, os.O_DIRECTORY, None)
    try:
        yield fd
    finally:
        os.close(fd)


def _open(name: str, flags: int, dir_fd: int | None) -> int:
    try:
        return os.open(name, os.O_RDONLY | os.O_NOFOLLOW | flags, dir_fd=dir_fd)
    except OSError as exc:
        # O_NOFOLLOW reports a symlink as ELOOP, O_DIRECTORY one to a file as ENOTDIR.
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            raise SkillFileError(f"{name} is a symlink or not a directory") from exc
        raise
