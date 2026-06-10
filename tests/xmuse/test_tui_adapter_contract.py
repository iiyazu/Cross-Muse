"""Adapter contract tests (Task 11: TUI-ADAPTER-CONTRACT-TESTS).

Covers send, participants, conversation list, fallback, worklist envelope.
"""

from xmuse.tui.adapter.xmuse_adapter import (
    XmuseAdapter,
    _build_features,
    _build_health,
)


def test_send_message_contract_api_path(monkeypatch, tmp_path):
    adapter = XmuseAdapter(tmp_path, chat_api_base_url="http://test")
    sent = []
    monkeypatch.setattr(adapter, "_send_message_via_chat_api",
                        lambda c, a, r, co: sent.append((c, a, r, co)) or "msg-1")
    result = adapter.send_message("conv-1", "user", "user", "hello")
    assert result == "msg-1"
    assert sent == [("conv-1", "user", "user", "hello")]


def test_send_message_contract_fallback_path(monkeypatch, tmp_path):
    adapter = XmuseAdapter(tmp_path, chat_api_base_url="http://test")
    monkeypatch.setattr(adapter, "_send_message_via_chat_api", lambda c, a, r, co: None)
    from xmuse_core.chat.store import ChatStore
    chat = ChatStore(tmp_path / "chat.db")
    conv = chat.create_conversation("test")
    result = adapter.send_message(conv.id, "user", "user", "hello")
    assert result is not None


def test_get_participants_contract(monkeypatch, tmp_path):
    adapter = XmuseAdapter(tmp_path, chat_api_base_url="http://test")
    monkeypatch.setattr(adapter, "_get_participants_via_chat_api",
                        lambda c: [{"role": "architect"}])
    result = adapter.get_participants("conv-1")
    assert len(result) == 1
    assert result[0]["role"] == "architect"


def test_get_participants_fallback(monkeypatch, tmp_path):
    adapter = XmuseAdapter(tmp_path, chat_api_base_url="http://test")
    monkeypatch.setattr(adapter, "_get_participants_via_chat_api", lambda c: None)
    result = adapter.get_participants("conv-1")
    assert isinstance(result, list)


def test_list_conversations_contract(tmp_path):
    adapter = XmuseAdapter(tmp_path)
    result = adapter.list_conversations()
    assert isinstance(result, list)


def test_build_features_contract():
    lanes = [
        {"plan_feature_id": "F1", "status": "merged"},
        {"plan_feature_id": "F1", "status": "dispatched"},
    ]
    features = _build_features(lanes)
    assert features["F1"]["total"] == 2
    assert features["F1"]["merged"] == 1


def test_build_health_contract():
    lanes = [
        {"status": "merged"},
        {"status": "dispatched"},
        {"status": "failed"},
    ]
    health = _build_health(lanes)
    assert health["live"] == 1
    assert health["merged"] == 1
    assert health["failed"] == 1


async def test_adapter_poll_worklist_envelope_isolation(monkeypatch, tmp_path):
    adapter = XmuseAdapter(tmp_path)

    class FakeEnvelope:
        def __init__(self, data):
            self._data = data
        def model_dump(self, mode="json"):
            return self._data

    payloads = [
        FakeEnvelope({"projection_revision": 1, "items": [], "run_health": {"counts": {}}}),
        FakeEnvelope({"projection_revision": 1, "items": [], "run_health": {"counts": {}}}),
    ]

    monkeypatch.setattr(
        "xmuse_core.platform.read_envelopes.build_tui_worklist_envelope",
        lambda *a, **kw: payloads.pop(0),
    )

    first, _ = await adapter.poll_worklist_envelope("conv-a")
    second, _ = await adapter.poll_worklist_envelope("conv-a")
    assert first is not None
    assert second is None  # same fingerprint = None
