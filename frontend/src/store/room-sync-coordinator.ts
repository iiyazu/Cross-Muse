export const ROOM_SYNC_CHANNELS = ["room", "operations", "execution", "memory"] as const;

export type RoomSyncChannel = (typeof ROOM_SYNC_CHANNELS)[number];

type TimerHandle = ReturnType<typeof setTimeout>;

type TimerScheduler = {
  setTimer: (callback: () => void, delayMs: number) => TimerHandle;
  clearTimer: (handle: TimerHandle) => void;
};

type RoomSyncCoordinatorOptions = Partial<TimerScheduler> & {
  onTimerError?: (error: unknown, channel: RoomSyncChannel) => void;
};

export type RoomSyncCoordinator = {
  restart: (channel: RoomSyncChannel) => number;
  epoch: (channel: RoomSyncChannel) => number;
  isCurrent: (channel: RoomSyncChannel, epoch: number) => boolean;
  schedule: (
    channel: RoomSyncChannel,
    epoch: number,
    delayMs: number,
    task: () => void | Promise<void>
  ) => boolean;
  cancelTimer: (channel: RoomSyncChannel) => void;
  singleFlight: <Result>(
    key: string,
    task: (signal: AbortSignal) => Promise<Result>
  ) => Promise<Result>;
  abortRequest: (key: string) => boolean;
  teardown: () => void;
};

/**
 * Owns synchronization mechanics without deciding when or what to poll.
 * Domain code remains responsible for delays, visibility policy and refresh work.
 */
export function createRoomSyncCoordinator(
  options: RoomSyncCoordinatorOptions = {}
): RoomSyncCoordinator {
  const scheduler: TimerScheduler = {
    setTimer: options.setTimer ?? ((callback, delayMs) => setTimeout(callback, delayMs)),
    clearTimer: options.clearTimer ?? ((handle) => clearTimeout(handle))
  };
  const epochs = new Map<RoomSyncChannel, number>(
    ROOM_SYNC_CHANNELS.map((channel) => [channel, 0])
  );
  const timers = new Map<RoomSyncChannel, TimerHandle>();
  const controllers = new Map<string, AbortController>();
  const inFlight = new Map<string, Promise<unknown>>();

  function cancelTimer(channel: RoomSyncChannel) {
    const timer = timers.get(channel);
    if (timer !== undefined) scheduler.clearTimer(timer);
    timers.delete(channel);
  }

  function restart(channel: RoomSyncChannel) {
    cancelTimer(channel);
    const nextEpoch = (epochs.get(channel) ?? 0) + 1;
    epochs.set(channel, nextEpoch);
    return nextEpoch;
  }

  function isCurrent(channel: RoomSyncChannel, epoch: number) {
    return epochs.get(channel) === epoch;
  }

  function schedule(
    channel: RoomSyncChannel,
    epoch: number,
    delayMs: number,
    task: () => void | Promise<void>
  ) {
    if (!isCurrent(channel, epoch)) return false;
    cancelTimer(channel);
    const timer = scheduler.setTimer(() => {
      if (timers.get(channel) === timer) timers.delete(channel);
      if (!isCurrent(channel, epoch)) return;
      try {
        void Promise.resolve(task()).catch((error: unknown) => {
          options.onTimerError?.(error, channel);
        });
      } catch (error) {
        options.onTimerError?.(error, channel);
      }
    }, Math.max(0, delayMs));
    timers.set(channel, timer);
    return true;
  }

  function singleFlight<Result>(
    key: string,
    task: (signal: AbortSignal) => Promise<Result>
  ): Promise<Result> {
    const existing = inFlight.get(key);
    if (existing) return existing as Promise<Result>;

    const controller = new AbortController();
    controllers.set(key, controller);
    let request: Promise<Result>;
    try {
      request = Promise.resolve(task(controller.signal));
    } catch (error) {
      request = Promise.reject(error);
    }
    const tracked = request.finally(() => {
      if (inFlight.get(key) !== tracked) return;
      inFlight.delete(key);
      controllers.delete(key);
    });
    inFlight.set(key, tracked);
    return tracked;
  }

  function abortRequest(key: string) {
    const controller = controllers.get(key);
    if (!controller) return false;
    controller.abort();
    controllers.delete(key);
    inFlight.delete(key);
    return true;
  }

  function teardown() {
    for (const channel of ROOM_SYNC_CHANNELS) restart(channel);
    for (const controller of controllers.values()) controller.abort();
    controllers.clear();
    inFlight.clear();
  }

  return {
    restart,
    epoch: (channel) => epochs.get(channel) ?? 0,
    isCurrent,
    schedule,
    cancelTimer,
    singleFlight,
    abortRequest,
    teardown
  };
}
