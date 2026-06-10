"""Tests for TUI participant cache (Task 4: TUI-PARTICIPANT-CACHE)."""

from xmuse.tui.adapter.xmuse_adapter import XmuseAdapter


def test_participant_cache_returns_cached(monkeypatch, tmp_path):
    adapter = XmuseAdapter(tmp_path)
    call_count = 0

    def _fake_api(conv_id):
        nonlocal call_count
        call_count += 1
        return [{"role": "architect", "participant_id": "p-1"}]

    monkeypatch.setattr(adapter, "_get_participants_via_chat_api", _fake_api)

    first = adapter.get_participants("conv-1")
    second = adapter.get_participants("conv-1")

    assert first == [{"role": "architect", "participant_id": "p-1"}]
    assert second == first
    assert call_count == 1  # second call uses cache


def test_participant_cache_expires(monkeypatch, tmp_path):
    adapter = XmuseAdapter(tmp_path)
    adapter._participant_cache_ttl_s = 0  # immediate expiry
    call_count = 0

    def _fake_api(conv_id):
        nonlocal call_count
        call_count += 1
        return [{"role": "architect", "participant_id": "p-1"}]

    monkeypatch.setattr(adapter, "_get_participants_via_chat_api", _fake_api)

    adapter.get_participants("conv-1")
    adapter.get_participants("conv-1")

    assert call_count == 2  # cache expired


def test_refresh_participants_bypasses_cache(monkeypatch, tmp_path):
    adapter = XmuseAdapter(tmp_path)
    call_count = 0
    responses = [
        [{"role": "architect", "participant_id": "p-1"}],
        [{"role": "review", "participant_id": "p-2"}],
    ]

    def _fake_api(conv_id):
        nonlocal call_count
        result = responses[call_count]
        call_count += 1
        return result

    monkeypatch.setattr(adapter, "_get_participants_via_chat_api", _fake_api)

    first = adapter.get_participants("conv-1")
    second = adapter.refresh_participants("conv-1")

    assert first == [{"role": "architect", "participant_id": "p-1"}]
    assert second == [{"role": "review", "participant_id": "p-2"}]


def test_participant_cache_per_conversation(monkeypatch, tmp_path):
    adapter = XmuseAdapter(tmp_path)
    calls: list[str] = []

    def _fake_api(conv_id):
        calls.append(conv_id)
        return [{"role": "architect", "participant_id": f"p-{conv_id}"}]

    monkeypatch.setattr(adapter, "_get_participants_via_chat_api", _fake_api)

    adapter.get_participants("conv-1")
    adapter.get_participants("conv-2")
    adapter.get_participants("conv-1")

    assert calls == ["conv-1", "conv-2"]
