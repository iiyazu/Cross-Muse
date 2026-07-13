from __future__ import annotations

from pathlib import Path

import pytest

from tests.xmuse.room_fixtures import RoomTestStore
from xmuse.chat_api import create_app as create_chat_app
from xmuse.room_mcp_server import create_app as create_mcp_app
from xmuse_core.runtime.data_guard import DATA_OPERATION_JOURNAL_NAME


def test_every_authority_entrypoint_refuses_an_incomplete_data_operation(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runtime"
    root.mkdir()
    (root / DATA_OPERATION_JOURNAL_NAME).write_text(
        '{"schema_version":"xmuse_data_operation/v1","phase":"installed"}\n',
        encoding="utf-8",
    )
    error = "xmuse_data_operation_incomplete"

    with pytest.raises(RuntimeError, match=error):
        RoomTestStore(root / "chat.db")
    with pytest.raises(RuntimeError, match=error):
        create_chat_app(root)
    with pytest.raises(RuntimeError, match=error):
        create_mcp_app(root)
    assert not (root / "chat.db").exists()
