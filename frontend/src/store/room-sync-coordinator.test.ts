import { describe, expect, it, vi } from "vitest";

import {
  createRoomSyncCoordinator,
  ROOM_SYNC_CHANNELS
} from "./room-sync-coordinator";

describe("room sync coordinator", () => {
  it("owns four independent timers and rejects stale epochs", async () => {
    vi.useFakeTimers();
    const runs = vi.fn();
    const coordinator = createRoomSyncCoordinator();

    const epochs = Object.fromEntries(
      ROOM_SYNC_CHANNELS.map((channel) => [channel, coordinator.restart(channel)])
    );
    for (const channel of ROOM_SYNC_CHANNELS) {
      expect(coordinator.schedule(channel, epochs[channel], 10, () => runs(channel))).toBe(true);
    }
    const staleRoomEpoch = epochs.room;
    const currentRoomEpoch = coordinator.restart("room");
    expect(coordinator.schedule("room", staleRoomEpoch, 10, () => runs("stale"))).toBe(false);
    expect(coordinator.schedule("room", currentRoomEpoch, 20, () => runs("room"))).toBe(true);

    await vi.advanceTimersByTimeAsync(10);
    expect(runs.mock.calls.map(([channel]) => channel)).toEqual([
      "operations",
      "execution",
      "memory"
    ]);
    await vi.advanceTimersByTimeAsync(10);
    expect(runs).toHaveBeenLastCalledWith("room");
    vi.useRealTimers();
  });

  it("replaces only the scheduled timer for the same channel", async () => {
    vi.useFakeTimers();
    const runs = vi.fn();
    const coordinator = createRoomSyncCoordinator();
    const roomEpoch = coordinator.restart("room");
    const operationsEpoch = coordinator.restart("operations");

    coordinator.schedule("room", roomEpoch, 10, () => runs("old-room"));
    coordinator.schedule("operations", operationsEpoch, 10, () => runs("operations"));
    coordinator.schedule("room", roomEpoch, 20, () => runs("new-room"));

    await vi.advanceTimersByTimeAsync(20);
    expect(runs.mock.calls.map(([channel]) => channel)).toEqual(["operations", "new-room"]);
    vi.useRealTimers();
  });

  it("deduplicates requests by key and releases the key after settlement", async () => {
    let resolve!: (value: string) => void;
    const task = vi.fn(() => new Promise<string>((done) => { resolve = done; }));
    const coordinator = createRoomSyncCoordinator();

    const first = coordinator.singleFlight("operations", task);
    const duplicate = coordinator.singleFlight("operations", task);
    expect(duplicate).toBe(first);
    expect(task).toHaveBeenCalledTimes(1);
    resolve("ready");
    await expect(first).resolves.toBe("ready");

    await expect(coordinator.singleFlight("operations", async () => "again")).resolves.toBe("again");
  });

  it("aborts a keyed request without allowing its cleanup to erase a replacement", async () => {
    let rejectOld!: (error: Error) => void;
    const coordinator = createRoomSyncCoordinator();
    const oldRequest = coordinator.singleFlight("room:1", (signal) => {
      expect(signal.aborted).toBe(false);
      return new Promise<string>((_resolve, reject) => { rejectOld = reject; });
    });

    expect(coordinator.abortRequest("room:1")).toBe(true);
    const replacement = coordinator.singleFlight("room:1", async () => "new");
    rejectOld(new Error("old request stopped"));
    await expect(oldRequest).rejects.toThrow("old request stopped");
    await expect(replacement).resolves.toBe("new");
    expect(coordinator.abortRequest("missing")).toBe(false);
  });

  it("teardown invalidates epochs, clears timers, and aborts every request", async () => {
    vi.useFakeTimers();
    const runs = vi.fn();
    const aborted: string[] = [];
    const coordinator = createRoomSyncCoordinator();
    const epoch = coordinator.restart("room");
    coordinator.schedule("room", epoch, 10, runs);
    const requests = ["operations", "execution"].map((key) =>
      coordinator.singleFlight(key, (signal) => new Promise<string>((_resolve, reject) => {
        signal.addEventListener("abort", () => {
          aborted.push(key);
          reject(new Error(`${key} aborted`));
        });
      }))
    );
    const rejectionAssertions = requests.map(async (request) =>
      expect(request).rejects.toThrow("aborted")
    );

    coordinator.teardown();
    expect(coordinator.isCurrent("room", epoch)).toBe(false);
    await vi.runAllTimersAsync();
    expect(runs).not.toHaveBeenCalled();
    expect(aborted).toEqual(["operations", "execution"]);
    await Promise.all(rejectionAssertions);
    vi.useRealTimers();
  });

  it("reports timer failures without embedding a retry policy", async () => {
    vi.useFakeTimers();
    const onTimerError = vi.fn();
    const coordinator = createRoomSyncCoordinator({ onTimerError });
    const epoch = coordinator.restart("memory");
    coordinator.schedule("memory", epoch, 1, async () => {
      throw new Error("memory offline");
    });

    await vi.runAllTimersAsync();
    expect(onTimerError).toHaveBeenCalledWith(expect.objectContaining({ message: "memory offline" }), "memory");
    expect(vi.getTimerCount()).toBe(0);
    vi.useRealTimers();
  });
});
