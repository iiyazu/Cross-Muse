"""Shared probe for tests that start a real bubblewrap sandbox."""

from __future__ import annotations

import functools
import shutil
import subprocess


@functools.cache
def bwrap_usable() -> bool:
    """Return True only when bubblewrap can actually create a namespace here.

    An installed ``bwrap`` is not enough: inside xmuse's own gate sandbox (the
    ``backend_pytest`` gate runs bwrap with ``--disable-userns``) a nested sandbox
    fails with ENOSPC, so tests that need a real sandbox must skip there.
    """

    bwrap = shutil.which("bwrap")
    if bwrap is None:
        return False
    try:
        result = subprocess.run(
            [bwrap, "--ro-bind", "/", "/", "true"],
            capture_output=True,
            timeout=15,
            check=False,
        )
    except OSError:
        return False
    return result.returncode == 0
