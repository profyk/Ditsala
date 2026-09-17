import "react-native-get-random-values";

import {
  encryptDirectMessage,
  encryptGroupMessage,
  generateIdentity,
  generateSenderKey,
  generateSignedPrekey,
  utf8ToBytes,
} from "./e2ee";
import {
  packDirectEnvelope,
  packGroupEnvelope,
  unpackDirectEnvelope,
  unpackGroupEnvelope,
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
