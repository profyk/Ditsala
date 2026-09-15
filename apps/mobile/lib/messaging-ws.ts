/**
 * WebSocket client for the realtime messaging transport
 * (docs/DITSALA_MASTER_SPEC.md §18-21) — delivers `message.new`,
 * `message.edited`, `message.deleted`, `message.delivered`/`.read`, and
 * `typing` events from backend/app/api/v1/routers/messaging.py's
 * `messaging_ws`. Plumbing only, per ADR 0005 — nothing here decrypts
 * anything; a real chat UI (Phase 4's remaining scope, once the native
 * libsignal module exists) is what will consume these events.
 */

import { BASE_URL } from "./api";

export type MessagingWsEvent =
  | { type: "message.new"; conversation_id: string; message_id: string }
  | { type: "message.edited"; conversation_id: string; message_id: string }
  | { type: "message.deleted"; conversation_id: string; message_id: string }
  | { type: "message.delivered"; conversation_id: string; message_id: string; user_id: string }
  | { type: "message.read"; conversation_id: string; message_id: string; user_id: string }
  | { type: "typing"; conversation_id: string; user_id: string };

type Listener = (event: MessagingWsEvent) => void;

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

  connect(accessToken: string): void {
    const wsUrl = BASE_URL.replace(/^http/, "ws");
    this.socket = new WebSocket(
      `${wsUrl}/api/v1/messaging/ws?token=${encodeURIComponent(accessToken)}`
    );
    this.socket.onmessage = (event: { data: string }) => {
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
  }

  disconnect(): void {
    this.socket?.close();
    this.socket = null;
  }

  /** Returns an unsubscribe function. */
  onEvent(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  sendTyping(conversationId: string): void {
    this.socket?.send(JSON.stringify({ type: "typing", conversation_id: conversationId }));
  }
}
