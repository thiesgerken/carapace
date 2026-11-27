import assert from "node:assert/strict";
import test from "node:test";
import { useEffect } from "react";
import { useWebSocket } from "./use-websocket";
import {
  flushReact,
  installDom,
  renderReact,
  runInAct,
} from "../../test/react-test-utils";

type TimerTask = {
  id: number;
  delay: number;
  callback: () => void;
};

class FakeWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;
  static instances: FakeWebSocket[] = [];

  readonly url: string;
  readyState = FakeWebSocket.CONNECTING;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  sentMessages: string[] = [];
  closeCalls = 0;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  send(data: string): void {
    this.sentMessages.push(data);
  }

  close(): void {
    this.closeCalls += 1;
    this.readyState = FakeWebSocket.CLOSED;
  }

  open(): void {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
  }

  emitMessage(data: string): void {
    this.onmessage?.({ data });
  }

  emitClose(): void {
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.();
  }
}

function installFakeTimers(): {
  runTimers: (delay?: number) => void;
  restore: () => void;
} {
  const originalSetTimeout = globalThis.setTimeout;
  const originalClearTimeout = globalThis.clearTimeout;
  const tasks: TimerTask[] = [];
  let nextId = 1;

  Object.defineProperty(globalThis, "setTimeout", {
    configurable: true,
    writable: true,
    value: ((callback: TimerHandler, delay?: number) => {
      const task: TimerTask = {
        id: nextId++,
        delay: typeof delay === "number" ? delay : 0,
        callback: () => {
          if (typeof callback === "function") {
            callback();
          }
        },
      };
      tasks.push(task);
      return task.id;
    }) as typeof globalThis.setTimeout,
  });

  Object.defineProperty(globalThis, "clearTimeout", {
    configurable: true,
    writable: true,
    value: ((handle: number) => {
      const index = tasks.findIndex((task) => task.id === handle);
      if (index >= 0) {
        tasks.splice(index, 1);
      }
    }) as typeof globalThis.clearTimeout,
  });

  return {
    runTimers(delay) {
      const ready = tasks
        .filter((task) => delay == null || task.delay === delay)
        .sort((left, right) => left.id - right.id);
      for (const task of ready) {
        const index = tasks.findIndex((entry) => entry.id === task.id);
        if (index >= 0) {
          tasks.splice(index, 1);
          task.callback();
        }
      }
    },
    restore() {
      Object.defineProperty(globalThis, "setTimeout", {
        configurable: true,
        writable: true,
        value: originalSetTimeout,
      });
      Object.defineProperty(globalThis, "clearTimeout", {
        configurable: true,
        writable: true,
        value: originalClearTimeout,
      });
    },
  };
}

function HookHarness({
  url,
  onMessage,
  onDisconnect,
  onReconnect,
  stateRef,
}: {
  url: string | null;
  onMessage: (message: unknown) => void;
  onDisconnect?: () => void;
  onReconnect?: () => void;
  stateRef: {
    current: {
      status: string;
      send: (message: unknown) => void;
    } | null;
  };
}) {
  const state = useWebSocket(url, onMessage as never, onDisconnect, onReconnect);

  useEffect(() => {
    stateRef.current = state as {
      status: string;
      send: (message: unknown) => void;
    };
  }, [state, stateRef]);

  return null;
}

test("useWebSocket connects, sends messages, parses server payloads, and reconnects after disconnect", async () => {
  const restoreDom = installDom();
  const timers = installFakeTimers();
  const originalWebSocket = globalThis.WebSocket;
  const messages: unknown[] = [];
  let disconnectCount = 0;
  let reconnectCount = 0;

  try {
    FakeWebSocket.instances = [];
    Object.defineProperty(globalThis, "WebSocket", {
      configurable: true,
      writable: true,
      value: FakeWebSocket as unknown as typeof WebSocket,
    });

    const stateRef = { current: null as { status: string; send: (message: unknown) => void } | null };
    const view = await renderReact(
      <HookHarness
        url="wss://carapace.example.test/ws"
        onMessage={(message) => messages.push(message)}
        onDisconnect={() => {
          disconnectCount += 1;
        }}
        onReconnect={() => {
          reconnectCount += 1;
        }}
        stateRef={stateRef}
      />,
    );

    await runInAct(() => {
      timers.runTimers(0);
    });
    await flushReact();

    assert.equal(FakeWebSocket.instances.length, 1);
    const firstSocket = FakeWebSocket.instances[0];
    assert.equal(stateRef.current?.status, "connecting");

    await runInAct(() => {
      firstSocket?.open();
    });
    await flushReact();
    assert.equal(stateRef.current?.status, "connected");
    assert.equal(reconnectCount, 0, "the first connection is no reconnect");

    stateRef.current?.send({ kind: "user", content: "hello" });
    assert.deepEqual(firstSocket?.sentMessages, [JSON.stringify({ kind: "user", content: "hello" })]);

    await runInAct(() => {
      firstSocket?.emitMessage('{"type":"assistant_message"}');
      firstSocket?.emitMessage("not json");
    });
    await flushReact();
    assert.deepEqual(messages, [{ type: "assistant_message" }]);

    await runInAct(() => {
      firstSocket?.emitClose();
    });
    await flushReact();
    assert.equal(disconnectCount, 1);
    assert.equal(stateRef.current?.status, "connecting");

    await runInAct(() => {
      timers.runTimers(500);
    });
    await flushReact();
    assert.equal(FakeWebSocket.instances.length, 2);

    const secondSocket = FakeWebSocket.instances[1];
    await runInAct(() => {
      secondSocket?.open();
    });
    await flushReact();
    assert.equal(stateRef.current?.status, "connected");
    assert.equal(reconnectCount, 1, "the caller catches up on what the dropped connection missed");

    await view.unmount();
    assert.equal(secondSocket?.closeCalls, 1);
  } finally {
    Object.defineProperty(globalThis, "WebSocket", {
      configurable: true,
      writable: true,
      value: originalWebSocket,
    });
    timers.restore();
    restoreDom();
  }
});

test("useWebSocket does not connect when url is null", async () => {
  const restoreDom = installDom();
  const timers = installFakeTimers();
  const originalWebSocket = globalThis.WebSocket;

  try {
    FakeWebSocket.instances = [];
    Object.defineProperty(globalThis, "WebSocket", {
      configurable: true,
      writable: true,
      value: FakeWebSocket as unknown as typeof WebSocket,
    });

    const stateRef = { current: null as { status: string; send: (message: unknown) => void } | null };
    const view = await renderReact(
      <HookHarness
        url={null}
        onMessage={() => undefined}
        stateRef={stateRef}
      />,
    );

    await runInAct(() => {
      timers.runTimers(0);
    });
    await flushReact();

    assert.equal(FakeWebSocket.instances.length, 0);
    assert.equal(stateRef.current?.status, "disconnected");

    await view.unmount();
  } finally {
    Object.defineProperty(globalThis, "WebSocket", {
      configurable: true,
      writable: true,
      value: originalWebSocket,
    });
    timers.restore();
    restoreDom();
  }
});
