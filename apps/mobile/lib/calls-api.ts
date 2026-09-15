/**
 * Backend API client for WebRTC call signaling
 * (docs/DITSALA_MASTER_SPEC.md §27). REST carries call state changes and
 * outbound signaling (SDP/ICE); the relayed signal itself arrives back
 * over `lib/messaging-ws.ts`'s shared socket as a `call.signal` event —
 * see that file's module docstring for why one socket carries both.
 */

import { request } from "./api";

export type CallType = "voice" | "video";
export type CallStatus = "ringing" | "active" | "ended" | "missed" | "declined";

export interface Call {
  id: string;
  conversation_id: string | null;
  initiator_user_id: string;
  type: CallType;
  status: CallStatus;
  started_at: string | null;
  ended_at: string | null;
}

export interface IceServer {
  urls: string;
  username?: string;
  credential?: string;
}

export const callsApi = {
  getIceServers: (accessToken: string) =>
    request<{ ice_servers: IceServer[] }>("/calls/ice-servers", {
      method: "GET",
      token: accessToken,
    }),

  initiateCall: (accessToken: string, conversationId: string, callType: CallType) =>
    request<Call>("/calls", {
      token: accessToken,
      body: { conversation_id: conversationId, call_type: callType },
    }),

  answerCall: (accessToken: string, callId: string) =>
    request<Call>(`/calls/${callId}/answer`, { method: "POST", token: accessToken }),

  declineCall: (accessToken: string, callId: string) =>
    request<Call>(`/calls/${callId}/decline`, { method: "POST", token: accessToken }),

  endCall: (accessToken: string, callId: string) =>
    request<Call>(`/calls/${callId}/end`, { method: "POST", token: accessToken }),

  switchMedia: (accessToken: string, callId: string, callType: CallType) =>
    request<Call>(`/calls/${callId}/switch-media`, {
      token: accessToken,
      body: { call_type: callType },
    }),

  sendSignal: (accessToken: string, callId: string, payload: Record<string, unknown>) =>
    request<void>(`/calls/${callId}/signal`, { token: accessToken, body: { payload } }),

  listCalls: (accessToken: string) =>
    request<Call[]>("/calls", { method: "GET", token: accessToken }),
};
