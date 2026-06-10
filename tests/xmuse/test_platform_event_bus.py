import asyncio
import json

import pytest

from xmuse_core.platform.event_bus import EventBus


@pytest.fixture
def bus():
    return EventBus()


@pytest.mark.asyncio
async def test_subscribe_and_publish(bus):
    received = []
    bus.subscribe("lane_dispatched", lambda payload: received.append(payload))
    await bus.publish("lane_dispatched", {"lane_id": "lane-1"})
    assert received == [{"lane_id": "lane-1"}]


@pytest.mark.asyncio
async def test_multiple_subscribers(bus):
    results = []
    bus.subscribe("lane_gated", lambda p: results.append(("a", p)))
    bus.subscribe("lane_gated", lambda p: results.append(("b", p)))
    await bus.publish("lane_gated", {"lane_id": "x"})
    assert len(results) == 2


@pytest.mark.asyncio
async def test_no_subscribers_does_not_raise(bus):
    await bus.publish("unknown_event", {})


@pytest.mark.asyncio
async def test_async_handler(bus):
    received = []

    async def handler(payload):
        await asyncio.sleep(0)
        received.append(payload)

    bus.subscribe("test", handler)
    await bus.publish("test", {"x": 1})
    assert received == [{"x": 1}]


@pytest.mark.asyncio
async def test_publish_appends_audit_event_log(tmp_path):
    path = tmp_path / "audit_events.json"
    audited_bus = EventBus(audit_log_path=path)

    await audited_bus.publish("lane_dispatched", {"lane_id": "lane-1"})

    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data["events"]) == 1
    assert data["events"][0]["event_type"] == "lane_dispatched"
    assert data["events"][0]["metadata"] == {"lane_id": "lane-1"}
    assert data["events"][0]["timestamp"]
    assert data["events"][0]["event_id"].startswith("evt-")
