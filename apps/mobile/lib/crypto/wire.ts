/**
 * Wire encoding — packs an `EncryptedEnvelope`/`GroupEnvelope` (several
 * separate fields: nonce, ephemeral key, etc.) into the single opaque
 * `bytes` blob `Message.ciphertext` actually is on the backend, and
 * back. A version byte leads every payload so a future format change
 * doesn't need a backend migration — old and new clients can tell which
 * shape they're looking at.
 */

import { bytesToUtf8, type EncryptedEnvelope, type GroupEnvelope, utf8ToBytes } from "./e2ee";

const DIRECT_ENVELOPE_VERSION = 1;
const GROUP_ENVELOPE_VERSION = 1;
// v2 added `mimeType` (image/video messages need to know how to render
// what they downloaded; voice notes now send "audio/m4a" too, for
// consistency) — this is the first version bump this format has needed,
// same session it shipped in, so no backend migration or compatibility
// shim for v1 payloads.
const MEDIA_KEY_PAYLOAD_VERSION = 2;

const PREKEY_ID_BYTES = 4;
const PUBLIC_KEY_BYTES = 32;
const NONCE_BYTES = 24;
const MEDIA_KEY_BYTES = 32;
const DURATION_MS_BYTES = 4;

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

/**
 * A voice note (or any future media message) is sent as two parts: the
 * encrypted audio bytes go through the ordinary media upload/download
 * pipeline (opaque to the server either way), while the small symmetric
 * key + nonce that decrypts it — plus playback metadata the recipient
 * needs before ever downloading anything — travels as the *message's
 * own* ciphertext, i.e. Sender-Key-encrypted exactly like a text message
 * (see chat-crypto.ts's `encryptOutgoingVoiceNote`/`decryptIncomingVoiceNoteKey`).
 * This payload is that plaintext, before it gets wrapped in a
 * GroupEnvelope.
 */
export interface MediaKeyPayload {
  key: Uint8Array;
  nonce: Uint8Array;
  durationMs: number;
  mimeType: string;
}

export function packMediaKeyPayload(payload: MediaKeyPayload): Uint8Array {
  const mimeTypeBytes = utf8ToBytes(payload.mimeType);
  if (mimeTypeBytes.length > 255) throw new Error("mimeType too long to pack.");
  return concatBytes([
    new Uint8Array([MEDIA_KEY_PAYLOAD_VERSION]),
    payload.key,
    payload.nonce,
    uint32ToBytes(payload.durationMs),
    new Uint8Array([mimeTypeBytes.length]),
    mimeTypeBytes,
  ]);
}

export function unpackMediaKeyPayload(bytes: Uint8Array): MediaKeyPayload {
  const version = bytes[0];
  if (version !== MEDIA_KEY_PAYLOAD_VERSION) {
    throw new Error(`Unsupported media-key payload version: ${version}.`);
  }
  let offset = 1;
  const key = bytes.slice(offset, offset + MEDIA_KEY_BYTES);
  offset += MEDIA_KEY_BYTES;
  const nonce = bytes.slice(offset, offset + NONCE_BYTES);
  offset += NONCE_BYTES;
  const durationMs = bytesToUint32(bytes, offset);
  offset += DURATION_MS_BYTES;
  const mimeTypeLength = bytes[offset];
  offset += 1;
  const mimeType = bytesToUtf8(bytes.slice(offset, offset + mimeTypeLength));
  return { key, nonce, durationMs, mimeType };
}
