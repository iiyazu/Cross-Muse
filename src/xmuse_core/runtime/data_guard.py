from __future__ import annotations

import os
from pathlib import Path

DATA_OPERATION_JOURNAL_NAME = ".xmuse-data-operation.json"


def assert_data_operation_complete(authority_root: str | Path) -> None:
    """Fail closed while a crash-recoverable authority replacement is unfinished."""

    root = Path(authority_root).expanduser().resolve()
    journal = root / DATA_OPERATION_JOURNAL_NAME
    if os.path.lexists(journal):
        raise RuntimeError(
            "xmuse_data_operation_incomplete: recover the local authority data before startup"
        )


__all__ = ["DATA_OPERATION_JOURNAL_NAME", "assert_data_operation_complete"]
