/* eslint-disable import/first -- the global mock must be installed before the module under test is imported */
class MockWebSocket {
  static instances: MockWebSocket[] = [];
  url: string;
  onmessage: ((event: { data: string }) => void) | null = null;
  send = jest.fn();
  close = jest.fn();

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  emit(data: unknown): void {
    this.onmessage?.({ data: typeof data === "string" ? data : JSON.stringify(data) });
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
});
