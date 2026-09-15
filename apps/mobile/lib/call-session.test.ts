/* eslint-disable import/first -- jest.mock must precede the imports it mocks */
const mockGetUserMedia = jest.fn();
const mockSendSignal = jest.fn();

// Everything the mock needs must be defined *inside* the factory: babel
// downlevels `class` to a `var`-hoisted IIFE, so a same-file "Mock"-
// prefixed class declared outside the factory is still `undefined` at
// the point jest's hoisted `jest.mock()` call actually invokes this
// factory (which happens before the rest of the file's `var`
// initializers have run) — a real hoisting-order trap, not the usual
// "reference an out-of-scope variable" case the mock-prefix rule covers.
jest.mock("react-native-webrtc", () => {
  class MockTrack {
    kind: "audio" | "video";
    id: string;
    enabled = true;
    stopped = false;
    constructor(kind: "audio" | "video") {
      this.kind = kind;
      this.id = `${kind}-${Math.random()}`;
    }
    stop(): void {
      this.stopped = true;
    }
  }

  class MockMediaStream {
    private tracks: MockTrack[];
    constructor(tracks: MockTrack[]) {
      this.tracks = tracks;
    }
    getTracks(): MockTrack[] {
      return this.tracks;
    }
    getAudioTracks(): MockTrack[] {
      return this.tracks.filter((t) => t.kind === "audio");
    }
    getVideoTracks(): MockTrack[] {
      return this.tracks.filter((t) => t.kind === "video");
    }
    addTrack(track: MockTrack): void {
      this.tracks.push(track);
    }
    removeTrack(track: MockTrack): void {
      this.tracks = this.tracks.filter((t) => t !== track);
    }
  }

  class MockRTCPeerConnection {
    static instances: MockRTCPeerConnection[] = [];
    onicecandidate: ((event: unknown) => void) | null = null;
    ontrack: ((event: unknown) => void) | null = null;
    onconnectionstatechange: (() => void) | null = null;
    connectionState = "new";
    senders: { track: MockTrack | null }[] = [];
    createOffer = jest.fn(async () => ({ sdp: "offer-sdp", type: "offer" }));
    createAnswer = jest.fn(async () => ({ sdp: "answer-sdp", type: "answer" }));
    setLocalDescription = jest.fn(async () => undefined);
    setRemoteDescription = jest.fn(async () => undefined);
    addIceCandidate = jest.fn(async () => undefined);
    close = jest.fn();

    constructor() {
      MockRTCPeerConnection.instances.push(this);
    }

    addTrack(track: MockTrack): { track: MockTrack } {
      const sender = { track };
      this.senders.push(sender);
      return sender;
    }

    getSenders(): { track: MockTrack | null }[] {
      return this.senders;
    }

    removeTrack(sender: { track: MockTrack | null }): void {
      this.senders = this.senders.filter((s) => s !== sender);
    }
  }

  class MockRTCIceCandidate {
    info: unknown;
    constructor(info: unknown) {
      this.info = info;
    }
  }

  class MockRTCSessionDescription {
    info: unknown;
    constructor(info: unknown) {
      this.info = info;
    }
  }

  return {
    mediaDevices: { getUserMedia: (c: unknown) => mockGetUserMedia(c) },
    MediaStream: MockMediaStream,
    RTCIceCandidate: MockRTCIceCandidate,
    RTCPeerConnection: MockRTCPeerConnection,
    RTCSessionDescription: MockRTCSessionDescription,
    __MockTrack: MockTrack,
  };
});

jest.mock("./calls-api", () => ({
  callsApi: { sendSignal: (...args: unknown[]) => mockSendSignal(...args) },
}));

import { RTCPeerConnection } from "react-native-webrtc";

import { CallSession } from "./call-session";
import { messagingSocket } from "./messaging-ws";

const MockRTCPeerConnection = RTCPeerConnection as any;
const MockTrack = (jest.requireMock("react-native-webrtc") as any).__MockTrack;

beforeEach(() => {
  MockRTCPeerConnection.instances = [];
  mockGetUserMedia.mockReset();
  mockSendSignal.mockReset();
  mockGetUserMedia.mockImplementation(
    async (constraints: { audio?: boolean; video?: boolean | object }) => {
      const tracks = [];
      if (constraints.audio) tracks.push(new MockTrack("audio"));
      if (constraints.video) tracks.push(new MockTrack("video"));
      const { MediaStream } = jest.requireMock("react-native-webrtc") as {
        MediaStream: new (tracks: unknown[]) => unknown;
      };
      return new MediaStream(tracks);
    }
  );
});

let activeSessions: CallSession[] = [];

afterEach(() => {
  for (const session of activeSessions) session.end();
  activeSessions = [];
});

function makeSession(isInitiator: boolean) {
  const session = new CallSession(
    {
      accessToken: "token",
      callId: "call-1",
      isInitiator,
      iceServers: [{ urls: "stun:stun.example.com" }],
    },
    {}
  );
  activeSessions.push(session);
  return session;
}

function emitToSession(event: unknown): void {
  const listeners = Array.from(
    (messagingSocket as unknown as { listeners: Set<(e: unknown) => void> }).listeners
  );
  for (const listener of listeners) listener(event);
}

/** Flushes enough microtask ticks for handleSignalEvent's multi-await
 * chain (setRemoteDescription -> createAnswer -> setLocalDescription ->
 * sendSignal) to fully settle. */
async function flushAsync(): Promise<void> {
  for (let i = 0; i < 8; i++) await Promise.resolve();
}

describe("CallSession.start", () => {
  it("acquires only an audio track for a voice call", async () => {
    const session = makeSession(true);
    await session.start("voice");
    expect(mockGetUserMedia).toHaveBeenCalledWith({ audio: true, video: false });
  });

  it("acquires audio and video tracks for a video call", async () => {
    const session = makeSession(true);
    await session.start("video");
    expect(mockGetUserMedia).toHaveBeenCalledWith({
      audio: true,
      video: { facingMode: "user" },
    });
    expect(session.isVideoEnabled()).toBe(true);
  });

  it("sends an offer immediately when it's the initiator", async () => {
    const session = makeSession(true);
    await session.start("voice");
    expect(mockSendSignal).toHaveBeenCalledWith(
      "token",
      "call-1",
      expect.objectContaining({ kind: "offer", sdp: "offer-sdp" })
    );
  });

  it("does not send an offer when it isn't the initiator", async () => {
    const session = makeSession(false);
    await session.start("voice");
    expect(mockSendSignal).not.toHaveBeenCalled();
  });

  it("relays a local ICE candidate as it's generated", async () => {
    const session = makeSession(true);
    await session.start("voice");
    mockSendSignal.mockClear();

    const pc = MockRTCPeerConnection.instances[0];
    pc.onicecandidate?.({ candidate: { toJSON: () => ({ candidate: "cand-1" }) } });

    expect(mockSendSignal).toHaveBeenCalledWith(
      "token",
      "call-1",
      expect.objectContaining({ kind: "ice-candidate", candidate: { candidate: "cand-1" } })
    );
  });

  it("ignores a null ICE candidate (end-of-candidates marker)", async () => {
    const session = makeSession(true);
    await session.start("voice");
    mockSendSignal.mockClear();

    MockRTCPeerConnection.instances[0].onicecandidate?.({ candidate: null });
    expect(mockSendSignal).not.toHaveBeenCalled();
  });
});

describe("CallSession signal handling", () => {
  it("answers an incoming offer for this call", async () => {
    const session = makeSession(false);
    await session.start("voice");
    mockSendSignal.mockClear();

    emitToSession({
      type: "call.signal",
      call_id: "call-1",
      from_user_id: "other",
      payload: { kind: "offer", sdp: "remote-offer-sdp" },
    });
    await flushAsync();

    const pc = MockRTCPeerConnection.instances[0];
    expect(pc.setRemoteDescription).toHaveBeenCalled();
    expect(pc.createAnswer).toHaveBeenCalled();
    expect(mockSendSignal).toHaveBeenCalledWith(
      "token",
      "call-1",
      expect.objectContaining({ kind: "answer", sdp: "answer-sdp" })
    );
  });

  it("ignores a signal for a different call id", async () => {
    const session = makeSession(false);
    await session.start("voice");
    const pc = MockRTCPeerConnection.instances[0];

    emitToSession({
      type: "call.signal",
      call_id: "some-other-call",
      from_user_id: "other",
      payload: { kind: "offer", sdp: "x" },
    });
    await Promise.resolve();
    expect(pc.setRemoteDescription).not.toHaveBeenCalled();
  });
});

describe("CallSession.setMuted", () => {
  it("disables and re-enables the local audio track", async () => {
    const session = makeSession(true);
    await session.start("voice");
    const pc = MockRTCPeerConnection.instances[0];
    const audioTrack = pc.senders[0].track;

    session.setMuted(true);
    expect(audioTrack.enabled).toBe(false);
    session.setMuted(false);
    expect(audioTrack.enabled).toBe(true);
  });
});

describe("CallSession.setVideoEnabled (§27 voice<->video switch)", () => {
  it("adds a video track and renegotiates when turning video on during a voice call", async () => {
    const session = makeSession(false); // even a non-initiator can trigger this
    await session.start("voice");
    mockSendSignal.mockClear();
    expect(session.isVideoEnabled()).toBe(false);

    await session.setVideoEnabled(true);

    expect(session.isVideoEnabled()).toBe(true);
    const pc = MockRTCPeerConnection.instances[0];
    expect(pc.createOffer).toHaveBeenCalled();
    expect(mockSendSignal).toHaveBeenCalledWith(
      "token",
      "call-1",
      expect.objectContaining({ kind: "offer" })
    );
  });

  it("removes the video track and stops it when turning video off", async () => {
    const session = makeSession(true);
    await session.start("video");
    const pc = MockRTCPeerConnection.instances[0];
    const videoSenderTrack = pc.senders.find(
      (s: { track: { kind: string } | null }) => s.track?.kind === "video"
    )?.track;

    await session.setVideoEnabled(false);

    expect(session.isVideoEnabled()).toBe(false);
    expect(videoSenderTrack.stopped).toBe(true);
    expect(
      pc.senders.some((s: { track: { kind: string } | null }) => s.track?.kind === "video")
    ).toBe(false);
  });

  it("is a no-op when already in the requested state", async () => {
    const session = makeSession(true);
    await session.start("voice");
    mockSendSignal.mockClear();

    await session.setVideoEnabled(false); // already off
    expect(mockSendSignal).not.toHaveBeenCalled();
  });
});

describe("CallSession.end", () => {
  it("stops local tracks and closes the peer connection", async () => {
    const session = makeSession(true);
    await session.start("video");
    const pc = MockRTCPeerConnection.instances[0];
    const tracks = pc.senders.map((s: { track: { stopped: boolean } | null }) => s.track);

    session.end();

    expect(pc.close).toHaveBeenCalled();
    for (const track of tracks) expect(track.stopped).toBe(true);
  });

  it("unsubscribes from the realtime socket so late signals are ignored", async () => {
    const session = makeSession(false);
    await session.start("voice");
    const pc = MockRTCPeerConnection.instances[0];
    session.end();

    emitToSession({
      type: "call.signal",
      call_id: "call-1",
      from_user_id: "other",
      payload: { kind: "offer", sdp: "late-offer" },
    });
    await Promise.resolve();
    expect(pc.setRemoteDescription).not.toHaveBeenCalled();
  });
});
