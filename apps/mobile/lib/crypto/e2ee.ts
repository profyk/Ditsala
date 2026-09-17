/**
 * Client-side E2EE — docs/adr/0013-nacl-e2ee-instead-of-libsignal.md.
 * Pure TweetNaCl (X25519 for key agreement, Ed25519 for signing prekeys,
 * XSalsa20-Poly1305 via secretbox for the actual message encryption).
 * The backend (domain/messaging/service.py) only ever sees the opaque
 * bytes this module produces — it never decrypts anything, unchanged
 * from the original Signal Protocol design this replaces.
 *
 * Import "react-native-get-random-values" once, early (see
 * app/_layout.tsx), before anything in this module runs — it's what
 * makes `nacl.randomBytes` a real CSPRNG on React Native instead of
 * throwing (tweetnacl has no built-in RN random source).
 */

import nacl from "tweetnacl";

import { base64ToBytes, bytesToBase64 } from "../base64";

export interface BoxKeyPair {
  publicKey: Uint8Array;
  secretKey: Uint8Array;
}

export interface SignKeyPair {
  publicKey: Uint8Array;
  secretKey: Uint8Array;
}

export interface DeviceIdentity {
  box: BoxKeyPair;
  sign: SignKeyPair;
}

export interface SignedPrekey {
  keyId: number;
  publicKey: Uint8Array;
  secretKey: Uint8Array;
  signature: Uint8Array;
}

export interface OneTimePrekey {
  keyId: number;
  publicKey: Uint8Array;
  secretKey: Uint8Array;
}

/** Generates a device's long-term identity: an X25519 keypair for key
 * agreement and a separate Ed25519 keypair for signing prekeys. NaCl's
 * box and sign keys are different curves, unlike Signal's XEdDSA trick
 * of reusing one Curve25519 key for both — see the ADR for why two
 * keys here is the simpler, equally real alternative. */
export function generateIdentity(): DeviceIdentity {
  return { box: nacl.box.keyPair(), sign: nacl.sign.keyPair() };
}

/** The wire format for `IdentityKey.public_identity_key` — 64 bytes,
 * the two public keys concatenated. No backend schema change needed:
 * that column has always just been opaque `bytes`. */
export function packIdentityPublicKey(identity: DeviceIdentity): Uint8Array {
  const packed = new Uint8Array(64);
  packed.set(identity.box.publicKey, 0);
  packed.set(identity.sign.publicKey, 32);
  return packed;
}

export interface UnpackedIdentityPublicKey {
  boxPublicKey: Uint8Array;
  signPublicKey: Uint8Array;
}

export function unpackIdentityPublicKey(packed: Uint8Array): UnpackedIdentityPublicKey {
  if (packed.length !== 64) {
    throw new Error(`Expected a 64-byte packed identity public key, got ${packed.length}.`);
  }
  return { boxPublicKey: packed.slice(0, 32), signPublicKey: packed.slice(32, 64) };
}

/** A rotating medium-term X25519 key, signed by the device's long-term
 * Ed25519 identity key — a recipient verifies this signature before
 * ever using the prekey, which is what stops a compromised/malicious
 * server from substituting its own key in a prekey bundle. */
export function generateSignedPrekey(identitySign: SignKeyPair, keyId: number): SignedPrekey {
  const keyPair = nacl.box.keyPair();
  const signature = nacl.sign.detached(keyPair.publicKey, identitySign.secretKey);
  return { keyId, publicKey: keyPair.publicKey, secretKey: keyPair.secretKey, signature };
}

export function verifySignedPrekey(
  prekeyPublicKey: Uint8Array,
  signature: Uint8Array,
  identitySignPublicKey: Uint8Array
): boolean {
  return nacl.sign.detached.verify(prekeyPublicKey, signature, identitySignPublicKey);
}

/** Single-use prekeys — each one lets exactly one new session get a
 * DH term that's discarded after first use, real forward secrecy for
 * that session's opening beyond what the signed prekey alone gives. */
export function generateOneTimePrekeys(count: number, startKeyId: number): OneTimePrekey[] {
  return Array.from({ length: count }, (_, i) => {
    const keyPair = nacl.box.keyPair();
    return { keyId: startKeyId + i, publicKey: keyPair.publicKey, secretKey: keyPair.secretKey };
  });
}

/** Combines two independent ECDH terms into one symmetric key via
 * SHA-512 (truncated to secretbox's 32-byte key length) — a standard
 * KDF-combiner pattern, not a novel cryptographic primitive. */
function deriveSharedKey(term1: Uint8Array, term2: Uint8Array): Uint8Array {
  const combined = new Uint8Array(term1.length + term2.length);
  combined.set(term1, 0);
  combined.set(term2, term1.length);
  return nacl.hash(combined).slice(0, nacl.secretbox.keyLength);
}

export interface EncryptedEnvelope {
  ciphertext: Uint8Array;
  nonce: Uint8Array;
  // Travel alongside the ciphertext so the recipient can recompute the
  // same derived key — see decryptDirectMessage.
  senderIdentityBoxPublicKey: Uint8Array;
  ephemeralPublicKey: Uint8Array;
  recipientPrekeyId: number;
}

/**
 * Session-less per-message encryption (the ADR's "X3DH-lite"): a fresh
 * ephemeral keypair every message gives forward secrecy per message
 * rather than per session; mixing in the sender's own long-term
 * identity key as a second DH term authenticates the sender (only they
 * could have produced a key the recipient can also derive).
 */
export function encryptDirectMessage(args: {
  plaintext: Uint8Array;
  senderIdentity: DeviceIdentity;
  recipientPrekeyId: number;
  recipientPrekeyPublicKey: Uint8Array;
}): EncryptedEnvelope {
  const ephemeral = nacl.box.keyPair();
  const term1 = nacl.box.before(args.recipientPrekeyPublicKey, ephemeral.secretKey);
  const term2 = nacl.box.before(args.recipientPrekeyPublicKey, args.senderIdentity.box.secretKey);
  const key = deriveSharedKey(term1, term2);

  const nonce = nacl.randomBytes(nacl.secretbox.nonceLength);
  const ciphertext = nacl.secretbox(args.plaintext, nonce, key);

  return {
    ciphertext,
    nonce,
    senderIdentityBoxPublicKey: args.senderIdentity.box.publicKey,
    ephemeralPublicKey: ephemeral.publicKey,
    recipientPrekeyId: args.recipientPrekeyId,
  };
}

/** Returns `null` (never throws) on a failed decryption — a wrong key,
 * tampered ciphertext, and "message wasn't for this device" all look
 * the same to the caller, matching secretbox.open's own contract. */
export function decryptDirectMessage(args: {
  envelope: EncryptedEnvelope;
  recipientPrekeySecretKey: Uint8Array;
}): Uint8Array | null {
  const { envelope, recipientPrekeySecretKey } = args;
  const term1 = nacl.box.before(envelope.ephemeralPublicKey, recipientPrekeySecretKey);
  const term2 = nacl.box.before(envelope.senderIdentityBoxPublicKey, recipientPrekeySecretKey);
  const key = deriveSharedKey(term1, term2);
  return nacl.secretbox.open(envelope.ciphertext, envelope.nonce, key);
}

// --- Groups: Sender Keys (a symmetric key per sending device, fanned
// out once via encryptDirectMessage rather than a DH per recipient per
// message) ---

export function generateSenderKey(): Uint8Array {
  return nacl.randomBytes(nacl.secretbox.keyLength);
}

export interface GroupEnvelope {
  ciphertext: Uint8Array;
  nonce: Uint8Array;
}

export function encryptGroupMessage(plaintext: Uint8Array, senderKey: Uint8Array): GroupEnvelope {
  const nonce = nacl.randomBytes(nacl.secretbox.nonceLength);
  return { ciphertext: nacl.secretbox(plaintext, nonce, senderKey), nonce };
}

export function decryptGroupMessage(
  envelope: GroupEnvelope,
  senderKey: Uint8Array
): Uint8Array | null {
  return nacl.secretbox.open(envelope.ciphertext, envelope.nonce, senderKey);
}

// --- Media: one random symmetric key per object, independent of any
// session/sender-key state — its key is itself delivered as a direct
// or group message (see the ADR's "Media" section). ---

export interface EncryptedMedia {
  ciphertext: Uint8Array;
  nonce: Uint8Array;
  key: Uint8Array;
}

export function encryptMedia(plaintext: Uint8Array): EncryptedMedia {
  const key = nacl.randomBytes(nacl.secretbox.keyLength);
  const nonce = nacl.randomBytes(nacl.secretbox.nonceLength);
  return { ciphertext: nacl.secretbox(plaintext, nonce, key), nonce, key };
}

export function decryptMedia(
  ciphertext: Uint8Array,
  nonce: Uint8Array,
  key: Uint8Array
): Uint8Array | null {
  return nacl.secretbox.open(ciphertext, nonce, key);
}

// --- Wire (base64) helpers — reuses the existing dependency-free
// base64 codec rather than pulling in tweetnacl-util for the same job. ---

export const toBase64 = bytesToBase64;
export const fromBase64 = base64ToBytes;

// Dependency-free UTF-8 codec — same caution as lib/base64.ts:
// TextEncoder/TextDecoder availability across Hermes/JSC hasn't been
// verified in this environment (no device/simulator here), so this
// doesn't assume either exists.
export function utf8ToBytes(text: string): Uint8Array {
  const bytes: number[] = [];
  for (let i = 0; i < text.length; i++) {
    let code = text.codePointAt(i)!;
    if (code > 0xffff) i++; // consumed a surrogate pair
    if (code < 0x80) {
      bytes.push(code);
    } else if (code < 0x800) {
      bytes.push(0xc0 | (code >> 6), 0x80 | (code & 0x3f));
    } else if (code < 0x10000) {
      bytes.push(0xe0 | (code >> 12), 0x80 | ((code >> 6) & 0x3f), 0x80 | (code & 0x3f));
    } else {
      bytes.push(
        0xf0 | (code >> 18),
        0x80 | ((code >> 12) & 0x3f),
        0x80 | ((code >> 6) & 0x3f),
        0x80 | (code & 0x3f)
      );
    }
  }
  return new Uint8Array(bytes);
}

export function bytesToUtf8(bytes: Uint8Array): string {
  let result = "";
  let i = 0;
  while (i < bytes.length) {
    const b0 = bytes[i];
    let codePoint: number;
    let length: number;
    if (b0 < 0x80) {
      codePoint = b0;
      length = 1;
    } else if ((b0 & 0xe0) === 0xc0) {
      codePoint = b0 & 0x1f;
      length = 2;
    } else if ((b0 & 0xf0) === 0xe0) {
      codePoint = b0 & 0x0f;
      length = 3;
    } else {
      codePoint = b0 & 0x07;
      length = 4;
    }
    for (let j = 1; j < length; j++) {
      codePoint = (codePoint << 6) | (bytes[i + j] & 0x3f);
    }
    result += String.fromCodePoint(codePoint);
    i += length;
  }
  return result;
}
