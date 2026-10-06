"""SQLite connections whose ``with`` block also closes them.

``sqlite3.Connection.__exit__`` only commits or rolls back; the connection stays
open until garbage collection, which Python 3.13 reports as a ``ResourceWarning``.
Pass ``factory=ClosingConnection`` to ``sqlite3.connect`` for connections that are
used as ``with connect(...) as conn:`` and never reused after the block.
"""

from __future__ import annotations

import sqlite3
from types import TracebackType
from typing import Literal


class ClosingConnection(sqlite3.Connection):
    def __exit__(
        self,
        type: type[BaseException] | None,
        value: BaseException | None,
        traceback: TracebackType | None,
        /,
    ) -> Literal[False]:
        try:
            return super().__exit__(type, value, traceback)
        finally:
            self.close()
