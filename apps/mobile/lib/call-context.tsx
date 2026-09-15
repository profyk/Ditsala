/**
 * App-wide call state (docs/DITSALA_MASTER_SPEC.md §27) — mounted once at
 * the root layout (like `OnboardingProvider`) so an incoming call can
 * interrupt whatever screen the user is on. Uses expo-router's imperative
 * `router` singleton rather than the `useRouter()` hook: this provider
 * wraps the root `<Stack>`, so it renders *outside* the navigation
 * context the hook needs, but the imperative API works from anywhere.
 */

import { router } from "expo-router";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type PropsWithChildren,
} from "react";
import type { MediaStream } from "react-native-webrtc";

import { callsApi, type CallType, type IceServer } from "./calls-api";
import { CallSession, type CallConnectionState } from "./call-session";
import { type MessagingWsEvent, messagingSocket } from "./messaging-ws";
import { getAccessToken } from "./session";

interface IncomingCall {
  callId: string;
  conversationId: string;
  callType: CallType;
  fromUserId: string;
}

interface ActiveCall {
  callId: string;
  callType: CallType;
  isInitiator: boolean;
  connectionState: CallConnectionState;
  localStream: MediaStream | null;
  remoteStream: MediaStream | null;
  muted: boolean;
}

interface CallContextValue {
  incomingCall: IncomingCall | null;
  activeCall: ActiveCall | null;
  startCall: (conversationId: string, callType: CallType) => Promise<void>;
  answerIncomingCall: () => Promise<void>;
  declineIncomingCall: () => Promise<void>;
  endActiveCall: () => Promise<void>;
  toggleMute: () => void;
  switchMedia: (callType: CallType) => Promise<void>;
}

const CallContext = createContext<CallContextValue | null>(null);

export function CallProvider({ children }: PropsWithChildren) {
  const [incomingCall, setIncomingCall] = useState<IncomingCall | null>(null);
  const [activeCall, setActiveCall] = useState<ActiveCall | null>(null);
  const sessionRef = useRef<CallSession | null>(null);
  const iceServersRef = useRef<IceServer[]>([]);
  const activeCallRef = useRef<ActiveCall | null>(null);
  const incomingCallRef = useRef<IncomingCall | null>(null);
  activeCallRef.current = activeCall;
  incomingCallRef.current = incomingCall;

  const endLocalSession = useCallback(() => {
    sessionRef.current?.end();
    sessionRef.current = null;
    setActiveCall(null);
  }, []);

  const handleEvent = useCallback(
    (event: MessagingWsEvent) => {
      if (event.type === "call.ringing") {
        setIncomingCall({
          callId: event.call_id,
          conversationId: event.conversation_id,
          callType: event.call_type,
          fromUserId: event.from_user_id,
        });
        router.push("/calls/incoming");
      } else if (event.type === "call.answered") {
        setActiveCall((prev) =>
          prev && prev.callId === event.call_id
            ? { ...prev, connectionState: "connected" }
            : prev
        );
      } else if (event.type === "call.declined" || event.type === "call.ended") {
        if (activeCallRef.current?.callId === event.call_id) {
          endLocalSession();
          router.back();
        }
        if (incomingCallRef.current?.callId === event.call_id) {
          setIncomingCall(null);
        }
      } else if (event.type === "call.media_changed") {
        setActiveCall((prev) =>
          prev && prev.callId === event.call_id ? { ...prev, callType: event.call_type } : prev
        );
      }
    },
    [endLocalSession]
  );

  useEffect(() => messagingSocket.onEvent(handleEvent), [handleEvent]);

  async function ensureIceServers(token: string): Promise<IceServer[]> {
    if (iceServersRef.current.length === 0) {
      const { ice_servers } = await callsApi.getIceServers(token);
      iceServersRef.current = ice_servers;
    }
    return iceServersRef.current;
  }

  function makeSession(
    token: string,
    callId: string,
    isInitiator: boolean,
    iceServers: IceServer[]
  ): CallSession {
    return new CallSession(
      { accessToken: token, callId, isInitiator, iceServers },
      {
        onLocalStream: (stream) =>
          setActiveCall((prev) => (prev ? { ...prev, localStream: stream } : prev)),
        onRemoteStream: (stream) =>
          setActiveCall((prev) => (prev ? { ...prev, remoteStream: stream } : prev)),
        onConnectionStateChange: (connectionState) => {
          if (connectionState === "failed" || connectionState === "ended") {
            endLocalSession();
          } else {
            setActiveCall((prev) => (prev ? { ...prev, connectionState } : prev));
          }
        },
      }
    );
  }

  async function startCall(conversationId: string, callType: CallType): Promise<void> {
    const token = await getAccessToken();
    if (!token) return;
    const iceServers = await ensureIceServers(token);
    const call = await callsApi.initiateCall(token, conversationId, callType);

    const session = makeSession(token, call.id, true, iceServers);
    sessionRef.current = session;
    setActiveCall({
      callId: call.id,
      callType,
      isInitiator: true,
      connectionState: "connecting",
      localStream: null,
      remoteStream: null,
      muted: false,
    });
    router.push("/calls/active");
    await session.start(callType);
  }

  async function answerIncomingCall(): Promise<void> {
    const call = incomingCall;
    if (!call) return;
    const token = await getAccessToken();
    if (!token) return;
    const iceServers = await ensureIceServers(token);

    const session = makeSession(token, call.callId, false, iceServers);
    sessionRef.current = session;
    setActiveCall({
      callId: call.callId,
      callType: call.callType,
      isInitiator: false,
      connectionState: "connecting",
      localStream: null,
      remoteStream: null,
      muted: false,
    });
    setIncomingCall(null);
    router.replace("/calls/active");
    await session.start(call.callType);
    await callsApi.answerCall(token, call.callId);
  }

  async function declineIncomingCall(): Promise<void> {
    const call = incomingCall;
    if (!call) return;
    setIncomingCall(null);
    router.back();
    const token = await getAccessToken();
    if (token) await callsApi.declineCall(token, call.callId).catch(() => undefined);
  }

  async function endActiveCall(): Promise<void> {
    const call = activeCall;
    if (!call) return;
    endLocalSession();
    router.back();
    const token = await getAccessToken();
    if (token) await callsApi.endCall(token, call.callId).catch(() => undefined);
  }

  function toggleMute(): void {
    if (!activeCall || !sessionRef.current) return;
    const nextMuted = !activeCall.muted;
    sessionRef.current.setMuted(nextMuted);
    setActiveCall((prev) => (prev ? { ...prev, muted: nextMuted } : prev));
  }

  async function switchMedia(callType: CallType): Promise<void> {
    if (!activeCall || !sessionRef.current) return;
    const token = await getAccessToken();
    if (!token) return;
    await sessionRef.current.setVideoEnabled(callType === "video");
    await callsApi.switchMedia(token, activeCall.callId, callType);
    setActiveCall((prev) => (prev ? { ...prev, callType } : prev));
  }

  return (
    <CallContext.Provider
      value={{
        incomingCall,
        activeCall,
        startCall,
        answerIncomingCall,
        declineIncomingCall,
        endActiveCall,
        toggleMute,
        switchMedia,
      }}
    >
      {children}
    </CallContext.Provider>
  );
}

export function useCall(): CallContextValue {
  const ctx = useContext(CallContext);
  if (!ctx) throw new Error("useCall must be used within a CallProvider");
  return ctx;
}
