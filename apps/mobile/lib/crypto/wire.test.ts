import "react-native-get-random-values";

import {
  encryptDirectMessage,
  encryptGroupMessage,
  encryptMedia,
  generateIdentity,
  generateSenderKey,
  generateSignedPrekey,
  utf8ToBytes,
} from "./e2ee";
import {
  packDirectEnvelope,
  packGroupEnvelope,
  packMediaKeyPayload,
  unpackDirectEnvelope,
  unpackGroupEnvelope,
  unpackMediaKeyPayload,
} from "./wire";

describe("direct envelope wire encoding", () => {
  it("round-trips every field losslessly", () => {
    const sender = generateIdentity();
    const recipient = generateIdentity();
    const prekey = generateSignedPrekey(recipient.sign, 7);

    const envelope = encryptDirectMessage({
      plaintext: utf8ToBytes("hello"),
      senderIdentity: sender,
      recipientPrekeyId: prekey.keyId,
      recipientPrekeyPublicKey: prekey.publicKey,
    });

    const packed = packDirectEnvelope(envelope);
    const unpacked = unpackDirectEnvelope(packed);

    expect(unpacked.recipientPrekeyId).toBe(envelope.recipientPrekeyId);
    expect(unpacked.ephemeralPublicKey).toEqual(envelope.ephemeralPublicKey);
    expect(unpacked.senderIdentityBoxPublicKey).toEqual(envelope.senderIdentityBoxPublicKey);
    expect(unpacked.nonce).toEqual(envelope.nonce);
    expect(unpacked.ciphertext).toEqual(envelope.ciphertext);
  });

  it("handles a large prekey id spanning all four bytes", () => {
    const sender = generateIdentity();
    const recipient = generateIdentity();
    const prekey = generateSignedPrekey(recipient.sign, 0xdeadbeef);

    const envelope = encryptDirectMessage({
      plaintext: utf8ToBytes("x"),
      senderIdentity: sender,
      recipientPrekeyId: prekey.keyId,
      recipientPrekeyPublicKey: prekey.publicKey,
    });

    expect(unpackDirectEnvelope(packDirectEnvelope(envelope)).recipientPrekeyId).toBe(0xdeadbeef);
  });

  it("rejects an envelope with an unknown version byte", () => {
    const sender = generateIdentity();
    const recipient = generateIdentity();
    const prekey = generateSignedPrekey(recipient.sign, 1);
    const envelope = encryptDirectMessage({
      plaintext: utf8ToBytes("hi"),
      senderIdentity: sender,
      recipientPrekeyId: prekey.keyId,
      recipientPrekeyPublicKey: prekey.publicKey,
    });
    const packed = packDirectEnvelope(envelope);
    packed[0] = 99;

    expect(() => unpackDirectEnvelope(packed)).toThrow("Unsupported");
  });
});

describe("group envelope wire encoding", () => {
  it("round-trips nonce and ciphertext", () => {
    const senderKey = generateSenderKey();
    const envelope = encryptGroupMessage(utf8ToBytes("group hello"), senderKey);

    const unpacked = unpackGroupEnvelope(packGroupEnvelope(envelope));

    expect(unpacked.nonce).toEqual(envelope.nonce);
    expect(unpacked.ciphertext).toEqual(envelope.ciphertext);
  });
});

describe("media key payload wire encoding", () => {
  it("round-trips key, nonce, duration, and mime type losslessly", () => {
    const media = encryptMedia(utf8ToBytes("fake audio bytes"));
    const payload = packMediaKeyPayload({
      key: media.key,
      nonce: media.nonce,
      durationMs: 4321,
      mimeType: "audio/m4a",
    });

    const unpacked = unpackMediaKeyPayload(payload);

    expect(unpacked.key).toEqual(media.key);
    expect(unpacked.nonce).toEqual(media.nonce);
    expect(unpacked.durationMs).toBe(4321);
    expect(unpacked.mimeType).toBe("audio/m4a");
  });

  it("handles a duration spanning all four bytes", () => {
    const media = encryptMedia(utf8ToBytes("x"));
    const payload = packMediaKeyPayload({
      key: media.key,
      nonce: media.nonce,
      durationMs: 0xdeadbeef,
      mimeType: "video/mp4",
    });

    expect(unpackMediaKeyPayload(payload).durationMs).toBe(0xdeadbeef);
  });

  it("handles an empty mime type", () => {
    const media = encryptMedia(utf8ToBytes("x"));
    const payload = packMediaKeyPayload({ key: media.key, nonce: media.nonce, durationMs: 0, mimeType: "" });

    expect(unpackMediaKeyPayload(payload).mimeType).toBe("");
  });

  it("rejects a payload with an unknown version byte", () => {
    const media = encryptMedia(utf8ToBytes("x"));
    const payload = packMediaKeyPayload({
      key: media.key,
      nonce: media.nonce,
      durationMs: 1,
      mimeType: "image/jpeg",
    });
    payload[0] = 99;

    expect(() => unpackMediaKeyPayload(payload)).toThrow("Unsupported");
  });
});
