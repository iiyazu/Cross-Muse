# xmuse/tui/widgets/feature_row.py
from __future__ import annotations

from textual.message import Message
from textual.widgets import DataTable


class FeatureTable(DataTable):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._data: dict = {}

    def on_mount(self) -> None:
        self.add_columns("Feature", "Progress", "Lanes", "Status")

    def update_data(self, features: dict) -> None:
        if features == self._data:
            return
        self._data = features
        self.clear()
        if not features:
            return
        for fid in sorted(features):
            ft = features[fid]
            ratio = f"{ft['merged']}/{ft['total']}" if ft['total'] else "\u2014"
            status = "\u2705" if ft['total'] > 0 and ft['merged'] == ft['total'] else \
                     "\U0001f504" if ft['total'] > 0 else "\u23f3"
            self.add_row(fid, _progress_bar(ft), ratio, status)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.post_message(FeatureClicked(str(event.value)))


class FeatureClicked(Message):
    def __init__(self, feature_id: str) -> None:
        super().__init__()
        self.feature_id = feature_id


def _progress_bar(ft: dict) -> str:
    total = ft.get("total", 0)
    merged = ft.get("merged", 0)
    if total == 0:
        return "[dim]\u2014[/dim]"
    filled = "\u2588" * merged
    empty = "\u2591" * (total - merged)
    return f"[#a3be8c]{filled}[/#a3be8c][dim #616e88]{empty}[/dim #616e88]"
