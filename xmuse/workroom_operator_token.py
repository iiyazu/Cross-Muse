"""The running Workroom generation's operator token file.

Contract ``main_window_control_v1`` section 3: the Workroom writes the token it
generated for this generation to ``<root>/runtime/operator-token`` (file 0600,
directory 0700) so a local operator client run by the same user, such as
``xmuse-workroom pair``, can issue a plugin grant without the Web Workroom. The
file is removed when the generation stops; a new generation writes a new token,
which invalidates every grant issued under the old one.
"""

from __future__ import annotations

import os
from contextlib import suppress
from pathlib import Path

_FILE_MODE = 0o600
_DIR_MODE = 0o700


class OperatorTokenFileError(Exception):
    """Stable failure reading the operator token file."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def write_operator_token(path: Path, token: str) -> None:
    """Atomically replace the token file with mode 0600."""

    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, _DIR_MODE)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with suppress(FileNotFoundError):
        temporary.unlink()
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, _FILE_MODE)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(token)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        with suppress(FileNotFoundError):
            temporary.unlink()
        raise


def remove_operator_token(path: Path) -> None:
    with suppress(FileNotFoundError):
        path.unlink()


def read_operator_token(path: Path) -> str:
    """Read the token; refuse a symlink or a file other users can read.

    Opened with ``O_NOFOLLOW`` and checked with ``fstat`` on the open file, so
    a symlink swapped in after a check is never followed.
    """

    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        raise OperatorTokenFileError("workroom_not_running") from None
    except OSError:
        # ELOOP: the final component is a symlink.
        raise OperatorTokenFileError("operator_token_file_unsafe") from None
    with os.fdopen(fd, "r", encoding="utf-8") as handle:
        info = os.fstat(handle.fileno())
        if info.st_mode & 0o077 or info.st_uid != os.getuid():
            raise OperatorTokenFileError("operator_token_file_unsafe")
        token = handle.read().strip()
    if not token:
        raise OperatorTokenFileError("workroom_not_running")
    return token
