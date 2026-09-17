import "react-native-get-random-values";

import {
  bytesToUtf8,
  decryptDirectMessage,
  decryptGroupMessage,
  decryptMedia,
  encryptDirectMessage,
  encryptGroupMessage,
  encryptMedia,
  fromBase64,
  generateIdentity,
  generateOneTimePrekeys,
  generateSenderKey,
  generateSignedPrekey,
  packIdentityPublicKey,
  toBase64,
  unpackIdentityPublicKey,
  utf8ToBytes,
  verifySignedPrekey,
} from "./e2ee";

describe("utf8ToBytes / bytesToUtf8", () => {
  it("round-trips ASCII, accented, and emoji text", () => {
    for (const text of ["hello", "café", "DITSALA 🔒🚀", ""]) {
      expect(bytesToUtf8(utf8ToBytes(text))).toBe(text);
    }
  });
});

describe("toBase64 / fromBase64", () => {
  it("round-trips arbitrary bytes", () => {
    const bytes = generateIdentity().box.publicKey;
    expect(fromBase64(toBase64(bytes))).toEqual(bytes);
  });
});

describe("identity key packing", () => {
  it("packs and unpacks both public keys losslessly", () => {
    const identity = generateIdentity();
    const packed = packIdentityPublicKey(identity);
    expect(packed.length).toBe(64);

    const unpacked = unpackIdentityPublicKey(packed);
    expect(unpacked.boxPublicKey).toEqual(identity.box.publicKey);
    expect(unpacked.signPublicKey).toEqual(identity.sign.publicKey);
  });

  it("rejects a packed key of the wrong length", () => {
    expect(() => unpackIdentityPublicKey(new Uint8Array(32))).toThrow();
  });
});

describe("signed prekeys", () => {
  it("verifies a real signature and rejects a tampered one", () => {
    const identity = generateIdentity();
    const prekey = generateSignedPrekey(identity.sign, 1);

    expect(verifySignedPrekey(prekey.publicKey, prekey.signature, identity.sign.publicKey)).toBe(
      true
    );

    const tampered = new Uint8Array(prekey.publicKey);
    tampered[0] ^= 0xff;
    expect(verifySignedPrekey(tampered, prekey.signature, identity.sign.publicKey)).toBe(false);
  });

  it("rejects a signature from the wrong identity", () => {
    const identity = generateIdentity();
    const impostor = generateIdentity();
    const prekey = generateSignedPrekey(identity.sign, 1);

    expect(verifySignedPrekey(prekey.publicKey, prekey.signature, impostor.sign.publicKey)).toBe(
      false
    );
  });
});

describe("one-time prekeys", () => {
  it("generates the requested count with sequential key ids", () => {
    const keys = generateOneTimePrekeys(5, 100);
    expect(keys.map((k) => k.keyId)).toEqual([100, 101, 102, 103, 104]);
    // Every keypair is distinct — not accidentally reusing randomness.
    const uniquePublicKeys = new Set(keys.map((k) => toBase64(k.publicKey)));
    expect(uniquePublicKeys.size).toBe(5);
  });
});

describe("direct message encryption", () => {
  it("round-trips a message between sender and recipient", () => {
    const sender = generateIdentity();
    const recipient = generateIdentity();
    const recipientPrekey = generateSignedPrekey(recipient.sign, 1);
    const plaintext = utf8ToBytes("Meet me at the usual place, 6pm.");

    const envelope = encryptDirectMessage({
      plaintext,
      senderIdentity: sender,
      recipientPrekeyId: recipientPrekey.keyId,
      recipientPrekeyPublicKey: recipientPrekey.publicKey,
    });

    const decrypted = decryptDirectMessage({
      envelope,
      recipientPrekeySecretKey: recipientPrekey.secretKey,
    });

    expect(decrypted).not.toBeNull();
    expect(bytesToUtf8(decrypted!)).toBe("Meet me at the usual place, 6pm.");
  });

  it("fails to decrypt with the wrong prekey secret", () => {
    const sender = generateIdentity();
    const recipient = generateIdentity();
    const recipientPrekey = generateSignedPrekey(recipient.sign, 1);
    const wrongPrekey = generateSignedPrekey(recipient.sign, 2);

    const envelope = encryptDirectMessage({
      plaintext: utf8ToBytes("secret"),
      senderIdentity: sender,
      recipientPrekeyId: recipientPrekey.keyId,
      recipientPrekeyPublicKey: recipientPrekey.publicKey,
    });

    const decrypted = decryptDirectMessage({
      envelope,
      recipientPrekeySecretKey: wrongPrekey.secretKey,
    });

    expect(decrypted).toBeNull();
  });

  it("fails to decrypt if the ciphertext was tampered with", () => {
    const sender = generateIdentity();
    const recipient = generateIdentity();
    const recipientPrekey = generateSignedPrekey(recipient.sign, 1);

    const envelope = encryptDirectMessage({
      plaintext: utf8ToBytes("secret"),
      senderIdentity: sender,
      recipientPrekeyId: recipientPrekey.keyId,
      recipientPrekeyPublicKey: recipientPrekey.publicKey,
    });
    envelope.ciphertext[0] ^= 0xff;

    const decrypted = decryptDirectMessage({
      envelope,
      recipientPrekeySecretKey: recipientPrekey.secretKey,
    });
    expect(decrypted).toBeNull();
  });

  it("produces a different ephemeral key and ciphertext for each message", () => {
    const sender = generateIdentity();
    const recipient = generateIdentity();
    const recipientPrekey = generateSignedPrekey(recipient.sign, 1);
    const plaintext = utf8ToBytes("same message twice");

    const encryptOnce = () =>
      encryptDirectMessage({
        plaintext,
        senderIdentity: sender,
        recipientPrekeyId: recipientPrekey.keyId,
        recipientPrekeyPublicKey: recipientPrekey.publicKey,
      });

    const first = encryptOnce();
    const second = encryptOnce();

    expect(toBase64(first.ephemeralPublicKey)).not.toBe(toBase64(second.ephemeralPublicKey));
    expect(toBase64(first.ciphertext)).not.toBe(toBase64(second.ciphertext));
  });

  it("cannot be decrypted by an impostor claiming a different sender identity", () => {
    // Swapping in an attacker's identity public key should not let a
    // recipient derive the same key an honest sender would — the
    // recipient side has no way to detect this from decryption failing
    // alone, but it must genuinely fail rather than "still working."
    const sender = generateIdentity();
    const impostor = generateIdentity();
    const recipient = generateIdentity();
    const recipientPrekey = generateSignedPrekey(recipient.sign, 1);

    const envelope = encryptDirectMessage({
      plaintext: utf8ToBytes("secret"),
      senderIdentity: sender,
      recipientPrekeyId: recipientPrekey.keyId,
      recipientPrekeyPublicKey: recipientPrekey.publicKey,
    });
    envelope.senderIdentityBoxPublicKey = impostor.box.publicKey;

    const decrypted = decryptDirectMessage({
      envelope,
      recipientPrekeySecretKey: recipientPrekey.secretKey,
    });
    expect(decrypted).toBeNull();
  });
});

describe("group messaging (sender keys)", () => {
  it("round-trips a message encrypted under a shared sender key", () => {
    const senderKey = generateSenderKey();
    const envelope = encryptGroupMessage(utf8ToBytes("group announcement"), senderKey);

    const decrypted = decryptGroupMessage(envelope, senderKey);
    expect(bytesToUtf8(decrypted!)).toBe("group announcement");
  });

  it("fails with the wrong sender key", () => {
    const senderKey = generateSenderKey();
    const wrongKey = generateSenderKey();
    const envelope = encryptGroupMessage(utf8ToBytes("group announcement"), senderKey);

    expect(decryptGroupMessage(envelope, wrongKey)).toBeNull();
  });

  it("distributes a sender key to a member via direct-message encryption", () => {
    // The realistic flow: a group's sender key is itself sent as the
    // plaintext of a direct message to each member.
    const distributor = generateIdentity();
    const member = generateIdentity();
    const memberPrekey = generateSignedPrekey(member.sign, 1);
    const senderKey = generateSenderKey();

    const distribution = encryptDirectMessage({
      plaintext: senderKey,
      senderIdentity: distributor,
      recipientPrekeyId: memberPrekey.keyId,
      recipientPrekeyPublicKey: memberPrekey.publicKey,
    });
    const receivedKey = decryptDirectMessage({
      envelope: distribution,
      recipientPrekeySecretKey: memberPrekey.secretKey,
    });

    expect(receivedKey).toEqual(senderKey);

    const groupEnvelope = encryptGroupMessage(utf8ToBytes("hello group"), senderKey);
    expect(bytesToUtf8(decryptGroupMessage(groupEnvelope, receivedKey!)!)).toBe("hello group");
  });
});

describe("media encryption", () => {
  it("round-trips arbitrary binary content", () => {
    const fakeImageBytes = new Uint8Array(256).map((_, i) => i % 256);
    const { ciphertext, nonce, key } = encryptMedia(fakeImageBytes);

    const decrypted = decryptMedia(ciphertext, nonce, key);
    expect(decrypted).toEqual(fakeImageBytes);
  });

  it("fails with the wrong key", () => {
    const bytes = new Uint8Array([1, 2, 3, 4]);
    const { ciphertext, nonce } = encryptMedia(bytes);
    const wrongKey = generateSenderKey();

    expect(decryptMedia(ciphertext, nonce, wrongKey)).toBeNull();
  });
});
