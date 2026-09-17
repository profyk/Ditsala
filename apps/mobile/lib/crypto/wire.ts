/**
 * Wire encoding — packs an `EncryptedEnvelope`/`GroupEnvelope` (several
 * separate fields: nonce, ephemeral key, etc.) into the single opaque
 * `bytes` blob `Message.ciphertext` actually is on the backend, and
 * back. A version byte leads every payload so a future format change
 * doesn't need a backend migration — old and new clients can tell which
 * shape they're looking at.
 */

import type { EncryptedEnvelope, GroupEnvelope } from "./e2ee";

const DIRECT_ENVELOPE_VERSION = 1;
const GROUP_ENVELOPE_VERSION = 1;

const PREKEY_ID_BYTES = 4;
const PUBLIC_KEY_BYTES = 32;
const NONCE_BYTES = 24;

function concatBytes(chunks: Uint8Array[]): Uint8Array {
  const total = chunks.reduce((sum, c) => sum + c.length, 0);
  const result = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    result.set(chunk, offset);
    offset += chunk.length;
  }
  return result;
}

function uint32ToBytes(value: number): Uint8Array {
  const bytes = new Uint8Array(4);
  new DataView(bytes.buffer).setUint32(0, value, false);
  return bytes;
}

function bytesToUint32(bytes: Uint8Array, offset: number): number {
  return new DataView(bytes.buffer, bytes.byteOffset + offset, 4).getUint32(0, false);
}

export function packDirectEnvelope(envelope: EncryptedEnvelope): Uint8Array {
  return concatBytes([
    new Uint8Array([DIRECT_ENVELOPE_VERSION]),
    uint32ToBytes(envelope.recipientPrekeyId),
    envelope.ephemeralPublicKey,
    envelope.senderIdentityBoxPublicKey,
    envelope.nonce,
    envelope.ciphertext,
  ]);
}

export function unpackDirectEnvelope(bytes: Uint8Array): EncryptedEnvelope {
  const version = bytes[0];
  if (version !== DIRECT_ENVELOPE_VERSION) {
    throw new Error(`Unsupported direct-message envelope version: ${version}.`);
  }
  let offset = 1;
  const recipientPrekeyId = bytesToUint32(bytes, offset);
  offset += PREKEY_ID_BYTES;
  const ephemeralPublicKey = bytes.slice(offset, offset + PUBLIC_KEY_BYTES);
  offset += PUBLIC_KEY_BYTES;
  const senderIdentityBoxPublicKey = bytes.slice(offset, offset + PUBLIC_KEY_BYTES);
  offset += PUBLIC_KEY_BYTES;
  const nonce = bytes.slice(offset, offset + NONCE_BYTES);
  offset += NONCE_BYTES;
  const ciphertext = bytes.slice(offset);

  return { ciphertext, nonce, senderIdentityBoxPublicKey, ephemeralPublicKey, recipientPrekeyId };
}

export function packGroupEnvelope(envelope: GroupEnvelope): Uint8Array {
  return concatBytes([new Uint8Array([GROUP_ENVELOPE_VERSION]), envelope.nonce, envelope.ciphertext]);
}

export function unpackGroupEnvelope(bytes: Uint8Array): GroupEnvelope {
  const version = bytes[0];
  if (version !== GROUP_ENVELOPE_VERSION) {
    throw new Error(`Unsupported group-message envelope version: ${version}.`);
  }
  const nonce = bytes.slice(1, 1 + NONCE_BYTES);
  const ciphertext = bytes.slice(1 + NONCE_BYTES);
  return { nonce, ciphertext };
}
