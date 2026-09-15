/* eslint-disable import/first -- the global mock must be installed before the module under test is imported */
class MockWebSocket {
  static instances: MockWebSocket[] = [];
  url: string;
  onmessage: ((event: { data: string }) => void) | null = null;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  send = jest.fn();
  close = jest.fn(() => this.onclose?.());

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  emit(data: unknown): void {
    this.onmessage?.({ data: typeof data === "string" ? data : JSON.stringify(data) });
  }

  emitOpen(): void {
    this.onopen?.();
  }

  /** Simulates the server/network dropping the connection (not a client-initiated close). */
  emitUnexpectedClose(): void {
    this.onclose?.();
  }
}

// @ts-expect-error -- test double, not a full WebSocket implementation
global.WebSocket = MockWebSocket;

import { MessagingSocket } from "./messaging-ws";

beforeEach(() => {
  MockWebSocket.instances = [];
});

describe("MessagingSocket.connect", () => {
  it("connects to the ws:// upgrade of BASE_URL with the token as a query param", () => {
    const socket = new MessagingSocket();
    socket.connect("my-access-token");

    expect(MockWebSocket.instances).toHaveLength(1);
    const url = MockWebSocket.instances[0].url;
    expect(url).toMatch(/^ws/);
    expect(url).toContain("/api/v1/messaging/ws?token=my-access-token");
  });
});

describe("MessagingSocket event dispatch", () => {
  it("delivers well-formed events to subscribed listeners", () => {
    const socket = new MessagingSocket();
    socket.connect("token");
    const received: unknown[] = [];
    socket.onEvent((event) => received.push(event));

    MockWebSocket.instances[0].emit({
      type: "message.new",
      conversation_id: "c1",
      message_id: "m1",
    });

    expect(received).toEqual([
      { type: "message.new", conversation_id: "c1", message_id: "m1" },
    ]);
  });

  it("drops malformed JSON without throwing", () => {
    const socket = new MessagingSocket();
    socket.connect("token");
    const listener = jest.fn();
    socket.onEvent(listener);

    expect(() => MockWebSocket.instances[0].emit("not json{{{")).not.toThrow();
    expect(listener).not.toHaveBeenCalled();
  });

  it("drops JSON that isn't a shaped event (no type field)", () => {
    const socket = new MessagingSocket();
    socket.connect("token");
    const listener = jest.fn();
    socket.onEvent(listener);

    MockWebSocket.instances[0].emit({ foo: "bar" });

    expect(listener).not.toHaveBeenCalled();
  });

  it("stops delivering events after unsubscribe", () => {
    const socket = new MessagingSocket();
    socket.connect("token");
    const listener = jest.fn();
    const unsubscribe = socket.onEvent(listener);
    unsubscribe();

    MockWebSocket.instances[0].emit({ type: "typing", conversation_id: "c1", user_id: "u1" });

    expect(listener).not.toHaveBeenCalled();
  });
});

describe("MessagingSocket.sendTyping", () => {
  it("sends a typing event for the given conversation", () => {
    const socket = new MessagingSocket();
    socket.connect("token");
    socket.sendTyping("c1");

    expect(MockWebSocket.instances[0].send).toHaveBeenCalledWith(
      JSON.stringify({ type: "typing", conversation_id: "c1" })
    );
  });

  it("does nothing if not connected", () => {
    const socket = new MessagingSocket();
    expect(() => socket.sendTyping("c1")).not.toThrow();
  });
});

describe("MessagingSocket.disconnect", () => {
  it("closes the underlying socket", () => {
    const socket = new MessagingSocket();
    socket.connect("token");
    socket.disconnect();

    expect(MockWebSocket.instances[0].close).toHaveBeenCalled();
  });

  it("is safe to call twice", () => {
    const socket = new MessagingSocket();
    socket.connect("token");
    socket.disconnect();
    expect(() => socket.disconnect()).not.toThrow();
  });

  it("does not reconnect after an intentional disconnect", () => {
    jest.useFakeTimers();
    const socket = new MessagingSocket();
    socket.connect("token");
    socket.disconnect();

    jest.advanceTimersByTime(60_000);
    expect(MockWebSocket.instances).toHaveLength(1);
    jest.useRealTimers();
  });
});

describe("MessagingSocket reconnection (poor network resilience)", () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  it("reports connection state transitions", () => {
    const socket = new MessagingSocket();
    const states: string[] = [];
    socket.onStateChange((state) => states.push(state));

    socket.connect("token");
    expect(states).toEqual(["connecting"]);

    MockWebSocket.instances[0].emitOpen();
    expect(states).toEqual(["connecting", "open"]);
  });

  it("reconnects with backoff after an unexpected close, not after an intentional one", () => {
    const socket = new MessagingSocket();
    socket.connect("token");
    MockWebSocket.instances[0].emitOpen();

    MockWebSocket.instances[0].emitUnexpectedClose();
    expect(socket.state).toBe("reconnecting");
    expect(MockWebSocket.instances).toHaveLength(1); // not yet — waiting out the backoff

    jest.advanceTimersByTime(1000);
    expect(MockWebSocket.instances).toHaveLength(2); // reconnected on a fresh socket
  });

  it("delivers events again once reconnected", () => {
    const socket = new MessagingSocket();
    const received: unknown[] = [];
    socket.onEvent((event) => received.push(event));
    socket.connect("token");
    MockWebSocket.instances[0].emitOpen();
    MockWebSocket.instances[0].emitUnexpectedClose();
    jest.advanceTimersByTime(1000);

    MockWebSocket.instances[1].emit({ type: "typing", conversation_id: "c1", user_id: "u1" });
    expect(received).toEqual([{ type: "typing", conversation_id: "c1", user_id: "u1" }]);
  });

  it("backs off exponentially across repeated drops", () => {
    const socket = new MessagingSocket();
    socket.connect("token");
    MockWebSocket.instances[0].emitOpen();

    MockWebSocket.instances[0].emitUnexpectedClose();
    jest.advanceTimersByTime(999);
    expect(MockWebSocket.instances).toHaveLength(1);
    jest.advanceTimersByTime(1);
    expect(MockWebSocket.instances).toHaveLength(2); // 1s backoff

    MockWebSocket.instances[1].emitUnexpectedClose();
    jest.advanceTimersByTime(1999);
    expect(MockWebSocket.instances).toHaveLength(2);
    jest.advanceTimersByTime(1);
    expect(MockWebSocket.instances).toHaveLength(3); // 2s backoff — doubled
  });

  it("resets the backoff delay after a successful reconnect", () => {
    const socket = new MessagingSocket();
    socket.connect("token");
    MockWebSocket.instances[0].emitOpen();
    MockWebSocket.instances[0].emitUnexpectedClose();
    jest.advanceTimersByTime(1000); // reconnects after 1s

    MockWebSocket.instances[1].emitOpen(); // successful reconnect resets backoff
    MockWebSocket.instances[1].emitUnexpectedClose();
    jest.advanceTimersByTime(999);
    expect(MockWebSocket.instances).toHaveLength(2);
    jest.advanceTimersByTime(1);
    expect(MockWebSocket.instances).toHaveLength(3); // back to 1s, not 2s
  });
});
