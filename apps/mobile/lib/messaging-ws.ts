/**
 * WebSocket client for the realtime transport
 * (docs/DITSALA_MASTER_SPEC.md §18-21, §27) — delivers `message.new`,
 * `message.edited`, `message.deleted`, `message.delivered`/`.read`,
 * `typing`, and (§27) `call.*` signaling events from
 * backend/app/api/v1/routers/messaging.py's `messaging_ws`. The same
 * connection carries both message and call events — one socket, not two,
 * so reconnect/backoff logic only has to live in one place.
 *
 * Auto-reconnects with exponential backoff on an unexpected close (poor
 * connectivity is the normal case on this network, not the exception) —
 * never on an intentional `disconnect()`. Message/circle/onboarding
 * plumbing (`lib/messaging-api.ts`) is pure REST and needs no such
 * handling of its own; this is the one long-lived connection in the app.
 */

import { BASE_URL } from "./api";

export type MessagingWsEvent =
  | { type: "message.new"; conversation_id: string; message_id: string }
  | { type: "message.edited"; conversation_id: string; message_id: string }
  | { type: "message.deleted"; conversation_id: string; message_id: string }
  | { type: "message.delivered"; conversation_id: string; message_id: string; user_id: string }
  | { type: "message.read"; conversation_id: string; message_id: string; user_id: string }
  | { type: "typing"; conversation_id: string; user_id: string }
  | {
      type: "call.ringing";
      call_id: string;
      conversation_id: string;
      call_type: "voice" | "video";
      from_user_id: string;
    }
  | { type: "call.answered"; call_id: string }
  | { type: "call.declined"; call_id: string }
  | { type: "call.ended"; call_id: string }
  | {
      type: "call.media_changed";
      call_id: string;
      call_type: "voice" | "video";
      changed_by_user_id: string;
    }
  | {
      type: "call.signal";
      call_id: string;
      from_user_id: string;
      payload: Record<string, unknown>;
    };

export type ConnectionState = "connecting" | "open" | "reconnecting" | "closed";

type Listener = (event: MessagingWsEvent) => void;
type StateListener = (state: ConnectionState) => void;

const INITIAL_RECONNECT_DELAY_MS = 1000;
const MAX_RECONNECT_DELAY_MS = 30_000;

function isMessagingWsEvent(value: unknown): value is MessagingWsEvent {
  return (
    typeof value === "object" &&
    value !== null &&
    "type" in value &&
    typeof (value as { type: unknown }).type === "string"
  );
}

export class MessagingSocket {
  private socket: WebSocket | null = null;
  private listeners = new Set<Listener>();
  private stateListeners = new Set<StateListener>();
  private accessToken: string | null = null;
  private intentionalDisconnect = false;
  private reconnectDelayMs = INITIAL_RECONNECT_DELAY_MS;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private _state: ConnectionState = "closed";

  get state(): ConnectionState {
    return this._state;
  }

  private setState(state: ConnectionState): void {
    this._state = state;
    for (const listener of this.stateListeners) listener(state);
  }

  connect(accessToken: string): void {
    this.accessToken = accessToken;
    this.intentionalDisconnect = false;
    this.reconnectDelayMs = INITIAL_RECONNECT_DELAY_MS;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.setState("connecting");
    this.open();
  }

  private open(): void {
    if (!this.accessToken) return;
    const wsUrl = BASE_URL.replace(/^http/, "ws");
    const socket = new WebSocket(
      `${wsUrl}/api/v1/messaging/ws?token=${encodeURIComponent(this.accessToken)}`
    );
    this.socket = socket;

    socket.onopen = () => {
      this.reconnectDelayMs = INITIAL_RECONNECT_DELAY_MS;
      this.setState("open");
    };
    socket.onmessage = (event: { data: string }) => {
      let parsed: unknown;
      try {
        parsed = JSON.parse(event.data);
      } catch {
        return; // malformed frame — drop it, don't crash the socket
      }
      if (isMessagingWsEvent(parsed)) {
        for (const listener of this.listeners) listener(parsed);
      }
    };
    socket.onclose = () => {
      if (this.intentionalDisconnect) {
        this.setState("closed");
        return;
      }
      this.setState("reconnecting");
      this.reconnectTimer = setTimeout(() => {
        this.reconnectDelayMs = Math.min(this.reconnectDelayMs * 2, MAX_RECONNECT_DELAY_MS);
        this.open();
      }, this.reconnectDelayMs);
    };
  }

  disconnect(): void {
    this.intentionalDisconnect = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.socket?.close();
    this.socket = null;
    this.setState("closed");
  }

  /** Returns an unsubscribe function. */
  onEvent(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /** Returns an unsubscribe function — lets UI show a "reconnecting…" banner. */
  onStateChange(listener: StateListener): () => void {
    this.stateListeners.add(listener);
    return () => this.stateListeners.delete(listener);
  }

  sendTyping(conversationId: string): void {
    this.socket?.send(JSON.stringify({ type: "typing", conversation_id: conversationId }));
  }
}

/** One shared connection for the whole app — messaging and calls both
 * ride it, so there's a single reconnect/backoff state machine to reason
 * about, matching how `connection_manager` is a single per-process
 * instance on the backend. */
export const messagingSocket = new MessagingSocket();
