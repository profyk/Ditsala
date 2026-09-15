/**
 * WebRTC peer connection lifecycle for a single call
 * (docs/DITSALA_MASTER_SPEC.md §27) — media is peer-to-peer, DTLS-SRTP
 * end-to-end, with coturn as TURN relay only (`GET /calls/ice-servers`).
 * This is real react-native-webrtc usage, not a stub: offer/answer/ICE
 * negotiation, local/remote stream wiring, mute, and the voice<->video
 * switch (§27, "clients can switch anytime") via track add/remove +
 * renegotiation are all implemented against the library's actual API.
 *
 * Not implemented: "polite peer" glare resolution for two simultaneous
 * renegotiations colliding (the W3C Perfect Negotiation pattern) — with
 * only two participants and switch-media as the sole renegotiation
 * trigger (a deliberate user action, never automatic), a collision needs
 * both sides to hit "switch" within the same round trip, an edge case
 * left for the same follow-up pass that puts this in front of a real
 * device (see docs/adr/0007-calls-native-module-verification-gap.md).
 */

import {
  mediaDevices,
  MediaStream,
  RTCIceCandidate,
  RTCPeerConnection,
  RTCSessionDescription,
} from "react-native-webrtc";

import { callsApi, type CallType, type IceServer } from "./calls-api";
import { messagingSocket, type MessagingWsEvent } from "./messaging-ws";

export type CallConnectionState = "connecting" | "connected" | "failed" | "ended";

interface CallSessionCallbacks {
  onLocalStream?: (stream: MediaStream | null) => void;
  onRemoteStream?: (stream: MediaStream | null) => void;
  onConnectionStateChange?: (state: CallConnectionState) => void;
}

interface SignalPayload {
  kind: "offer" | "answer" | "ice-candidate";
  sdp?: string;
  candidate?: { candidate: string; sdpMid: string | null; sdpMLineIndex: number | null };
}

export class CallSession {
  private pc: RTCPeerConnection | null = null;
  private localStream: MediaStream | null = null;
  private unsubscribeWs: (() => void) | null = null;
  private readonly accessToken: string;
  private readonly callId: string;
  private readonly isInitiator: boolean;
  private readonly iceServers: IceServer[];
  private readonly callbacks: CallSessionCallbacks;

  constructor(
    opts: { accessToken: string; callId: string; isInitiator: boolean; iceServers: IceServer[] },
    callbacks: CallSessionCallbacks = {}
  ) {
    this.accessToken = opts.accessToken;
    this.callId = opts.callId;
    this.isInitiator = opts.isInitiator;
    this.iceServers = opts.iceServers;
    this.callbacks = callbacks;
  }

  async start(callType: CallType): Promise<void> {
    this.localStream = await mediaDevices.getUserMedia({
      audio: true,
      video: callType === "video" ? { facingMode: "user" } : false,
    });
    this.callbacks.onLocalStream?.(this.localStream);

    const pc = new RTCPeerConnection({ iceServers: this.iceServers });
    this.pc = pc;
    for (const track of this.localStream.getTracks()) {
      pc.addTrack(track, this.localStream);
    }

    // The `on<event>` setters, not `addEventListener` — react-native-webrtc's
    // event-target-shim types the latter's generic overloads in a way
    // that doesn't resolve cleanly under this project's TS config, a
    // known friction with that shim library. The setters are typed with
    // a generic `Event<string>`, so the richer per-event fields
    // (`.candidate`, `.streams`) still need a narrow, local cast below.
    pc.onicecandidate = (event: unknown) => {
      const candidate = (event as { candidate: RTCIceCandidate | null }).candidate;
      if (candidate) {
        void callsApi.sendSignal(this.accessToken, this.callId, {
          kind: "ice-candidate",
          candidate: candidate.toJSON(),
        });
      }
    };
    pc.ontrack = (event: unknown) => {
      const streams = (event as { streams: MediaStream[] }).streams;
      this.callbacks.onRemoteStream?.(streams[0] ?? null);
    };
    pc.onconnectionstatechange = () => {
      switch (pc.connectionState) {
        case "connected":
          this.callbacks.onConnectionStateChange?.("connected");
          break;
        case "failed":
        case "disconnected":
          this.callbacks.onConnectionStateChange?.("failed");
          break;
        case "closed":
          this.callbacks.onConnectionStateChange?.("ended");
          break;
      }
    };

    this.unsubscribeWs = messagingSocket.onEvent((event) => {
      void this.handleSignalEvent(event);
    });

    if (this.isInitiator) {
      await this.sendOffer();
    }
  }

  private async sendOffer(): Promise<void> {
    if (!this.pc) return;
    const offer = await this.pc.createOffer({});
    await this.pc.setLocalDescription(offer);
    await callsApi.sendSignal(this.accessToken, this.callId, {
      kind: "offer",
      sdp: offer.sdp,
    });
  }

  private async handleSignalEvent(event: MessagingWsEvent): Promise<void> {
    if (event.type !== "call.signal" || event.call_id !== this.callId || !this.pc) return;
    const payload = event.payload as unknown as SignalPayload;

    if (payload.kind === "offer" && payload.sdp) {
      await this.pc.setRemoteDescription(
        new RTCSessionDescription({ sdp: payload.sdp, type: "offer" })
      );
      const answer = await this.pc.createAnswer();
      await this.pc.setLocalDescription(answer);
      await callsApi.sendSignal(this.accessToken, this.callId, {
        kind: "answer",
        sdp: answer.sdp,
      });
    } else if (payload.kind === "answer" && payload.sdp) {
      await this.pc.setRemoteDescription(
        new RTCSessionDescription({ sdp: payload.sdp, type: "answer" })
      );
    } else if (payload.kind === "ice-candidate" && payload.candidate) {
      await this.pc.addIceCandidate(new RTCIceCandidate(payload.candidate));
    }
  }

  setMuted(muted: boolean): void {
    this.localStream?.getAudioTracks().forEach((track) => {
      track.enabled = !muted;
    });
  }

  isVideoEnabled(): boolean {
    return (this.localStream?.getVideoTracks().length ?? 0) > 0;
  }

  /** §27: switch a live call between voice and video — adds/removes the
   * local video track and renegotiates. Caller is responsible for also
   * telling the backend via `callsApi.switchMedia` so the other side's UI
   * updates (this method only handles the media/SDP side). */
  async setVideoEnabled(enabled: boolean): Promise<void> {
    if (!this.localStream || !this.pc) return;
    const currentlyEnabled = this.isVideoEnabled();
    if (enabled === currentlyEnabled) return;

    if (enabled) {
      const stream = await mediaDevices.getUserMedia({ video: { facingMode: "user" } });
      const [videoTrack] = stream.getVideoTracks();
      this.localStream.addTrack(videoTrack);
      this.pc.addTrack(videoTrack, this.localStream);
    } else {
      for (const track of this.localStream.getVideoTracks()) {
        this.localStream.removeTrack(track);
        track.stop();
        const sender = this.pc.getSenders().find((s) => s.track?.id === track.id);
        if (sender) this.pc.removeTrack(sender);
      }
    }
    this.callbacks.onLocalStream?.(this.localStream);
    // Whoever changes their own tracks renegotiates — not gated on which
    // side placed the original call, since either party can toggle video.
    await this.sendOffer();
  }

  end(): void {
    this.unsubscribeWs?.();
    this.unsubscribeWs = null;
    this.localStream?.getTracks().forEach((track) => track.stop());
    this.localStream = null;
    this.pc?.close();
    this.pc = null;
    this.callbacks.onLocalStream?.(null);
    this.callbacks.onRemoteStream?.(null);
  }
}
