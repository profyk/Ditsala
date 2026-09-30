/**
 * High-level "send/receive a chat message" operations — wires together
 * lib/crypto/e2ee.ts (the primitives), keystore.ts (this device's keys
 * and other devices' verified prekeys), wire.ts (envelope encoding),
 * and messaging-api.ts (the actual REST calls). Screens call this
 * module, never e2ee.ts directly.
 *
 * Every conversation — direct or group — uses the same Sender Key
 * design: this device generates one symmetric key per conversation and
 * distributes it (via a 1:1-encrypted envelope) to every device of
 * every other member, then encrypts actual messages with that one key.
 * Unifying direct and group under Sender Keys, rather than a separate
 * pairwise scheme for direct messages, is what gives a direct
 * conversation real multi-device fan-out for free: any device that has
 * decrypted the distribution message can decrypt every later message,
 * not just whichever single device happened to receive it.
 */

import * as SecureStore from "expo-secure-store";

import { type Conversation, type ConversationMember, messagingApi } from "../messaging-api";
import {
  bytesToUtf8,
  decryptDirectMessage,
  decryptGroupMessage,
  decryptMedia,
  encryptDirectMessage,
  encryptGroupMessage,
  encryptMedia,
  fromBase64,
  generateSenderKey,
  toBase64,
  utf8ToBytes,
} from "./e2ee";
import { ensureDeviceIdentity, fetchVerifiedPrekeysForAllDevices, findLocalPrekeySecret } from "./keystore";
import {
  type MediaKeyPayload,
  packDirectEnvelope,
  packGroupEnvelope,
  packMediaKeyPayload,
  unpackDirectEnvelope,
  unpackGroupEnvelope,
  unpackMediaKeyPayload,
} from "./wire";

const SENDER_KEY_PREFIX = "ditsala.e2ee.senderKey.";

async function loadOwnSenderKey(conversationId: string): Promise<Uint8Array | null> {
  const raw = await SecureStore.getItemAsync(`${SENDER_KEY_PREFIX}${conversationId}`);
  return raw ? fromBase64(raw) : null;
}

async function saveOwnSenderKey(conversationId: string, key: Uint8Array): Promise<void> {
  await SecureStore.setItemAsync(`${SENDER_KEY_PREFIX}${conversationId}`, toBase64(key));
}

/**
 * Ensures this device has a Sender Key for the conversation, generating
 * and distributing a fresh one — individually encrypted to every
 * device of every other member — the first time it's needed. Cached
 * locally after that, so this is a one-time cost per conversation
 * (until a member's device roster changes — see docs/SECURITY_GAPS.md's
 * note on redistributing to newly added devices).
 */
async function ensureOwnSenderKeyDistributed(
  accessToken: string,
  conversation: Conversation,
  members: ConversationMember[],
  ownUserId: string
): Promise<Uint8Array> {
  const existing = await loadOwnSenderKey(conversation.id);
  if (existing) return existing;

  const senderKey = generateSenderKey();
  const identity = await ensureDeviceIdentity();

  const others = members.filter((m) => m.user_id !== ownUserId);
  await Promise.all(
    others.map(async (member) => {
      const recipientDevices = await fetchVerifiedPrekeysForAllDevices(
        accessToken,
        member.user_id
      );
      await Promise.all(
        recipientDevices.map(async (recipientDevice) => {
          const envelope = encryptDirectMessage({
            plaintext: senderKey,
            senderIdentity: identity,
            recipientPrekeyId: recipientDevice.prekeyId,
            recipientPrekeyPublicKey: recipientDevice.prekeyPublicKey,
          });
          await messagingApi.uploadSenderKey(
            accessToken,
            conversation.id,
            recipientDevice.deviceId,
            packDirectEnvelope(envelope)
          );
        })
      );
    })
  );

  await saveOwnSenderKey(conversation.id, senderKey);
  return senderKey;
}

/** Recovers another device's Sender Key for this conversation from its
 * distribution message addressed to us, decrypting it with our own
 * identity + whichever prekey it targeted. */
async function resolveSenderKeyFor(
  accessToken: string,
  conversationId: string,
  senderDeviceId: string
): Promise<Uint8Array | null> {
  const cacheKey = `${SENDER_KEY_PREFIX}${conversationId}.${senderDeviceId}`;
  const cached = await SecureStore.getItemAsync(cacheKey);
  if (cached) return fromBase64(cached);

  const allDistributions = await messagingApi.listSenderKeys(accessToken, conversationId);
  const distribution = allDistributions.find((d) => d.deviceId === senderDeviceId);
  if (!distribution) return null;

  const envelope = unpackDirectEnvelope(distribution.distributionMessageRef);
  const prekeySecret = await findLocalPrekeySecret(envelope.recipientPrekeyId);
  if (!prekeySecret) return null;

  const senderKey = decryptDirectMessage({ envelope, recipientPrekeySecretKey: prekeySecret });
  if (!senderKey) return null;

  await SecureStore.setItemAsync(cacheKey, toBase64(senderKey));
  return senderKey;
}

/** Encrypts plaintext for sending — the caller still calls
 * `messagingApi.sendMessage` with the returned bytes as `ciphertext`. */
export async function encryptOutgoingMessage(
  accessToken: string,
  conversation: Conversation,
  members: ConversationMember[],
  ownUserId: string,
  plaintext: string
): Promise<Uint8Array> {
  const senderKey = await ensureOwnSenderKeyDistributed(accessToken, conversation, members, ownUserId);
  return packGroupEnvelope(encryptGroupMessage(utf8ToBytes(plaintext), senderKey));
}

/**
 * Decrypts a received message. Returns `null` (never throws) on
 * failure — a message this device can't decrypt (the distribution
 * message hasn't arrived yet, corrupted data, etc.) should render as
 * "couldn't decrypt this message," not crash the chat.
 */
export async function decryptIncomingMessage(
  accessToken: string,
  conversation: Conversation,
  senderDeviceId: string | null,
  ciphertext: Uint8Array
): Promise<string | null> {
  try {
    if (!senderDeviceId) return null;
    const senderKey = await resolveSenderKeyFor(accessToken, conversation.id, senderDeviceId);
    if (!senderKey) return null;
    const plaintext = decryptGroupMessage(unpackGroupEnvelope(ciphertext), senderKey);
    return plaintext ? bytesToUtf8(plaintext) : null;
  } catch {
    return null;
  }
}

export interface EncryptedOutgoingMedia {
  // Goes as the Message's own `ciphertext` — the media's decryption key,
  // Sender-Key-encrypted like any other message.
  messageCiphertext: Uint8Array;
  // Goes to `messagingApi.requestMediaUpload`/the presigned upload URL —
  // opaque bytes, the server never has the key to open them.
  mediaCiphertext: Uint8Array;
}

/** Encrypts any binary media (voice note, image, or video — the crypto
 * doesn't care which) with a fresh one-time media key (`encryptMedia`),
 * then wraps that key + nonce + duration + mime type as the message's
 * own Sender-Key-encrypted payload — the same "media key travels as a
 * message" design `e2ee.ts`'s own "Media" section describes. `durationMs`
 * is meaningful for voice/video and `0` for a still image; `mimeType`
 * (e.g. "image/jpeg", "video/mp4", "audio/m4a") is what the recipient
 * actually uses to decide how to render, not the message's own
 * `content_type` (which only distinguishes "media" from "voice_note" at
 * the message-list level). */
export async function encryptOutgoingMedia(
  accessToken: string,
  conversation: Conversation,
  members: ConversationMember[],
  ownUserId: string,
  mediaBytes: Uint8Array,
  durationMs: number,
  mimeType: string
): Promise<EncryptedOutgoingMedia> {
  const senderKey = await ensureOwnSenderKeyDistributed(accessToken, conversation, members, ownUserId);
  const media = encryptMedia(mediaBytes);
  const payload = packMediaKeyPayload({ key: media.key, nonce: media.nonce, durationMs, mimeType });
  return {
    messageCiphertext: packGroupEnvelope(encryptGroupMessage(payload, senderKey)),
    mediaCiphertext: media.ciphertext,
  };
}

/** Recovers a media message's key/nonce/duration from the message's own
 * ciphertext — call this first, then decrypt the downloaded blob with
 * `decryptMediaBytes`. Returns `null` (never throws), same contract as
 * `decryptIncomingMessage`. */
export async function decryptIncomingMediaKey(
  accessToken: string,
  conversation: Conversation,
  senderDeviceId: string | null,
  messageCiphertext: Uint8Array
): Promise<MediaKeyPayload | null> {
  try {
    if (!senderDeviceId) return null;
    const senderKey = await resolveSenderKeyFor(accessToken, conversation.id, senderDeviceId);
    if (!senderKey) return null;
    const payload = decryptGroupMessage(unpackGroupEnvelope(messageCiphertext), senderKey);
    return payload ? unpackMediaKeyPayload(payload) : null;
  } catch {
    return null;
  }
}

/** Decrypts the downloaded, still-encrypted media blob once its key has
 * been recovered via `decryptIncomingMediaKey`. */
export function decryptMediaBytes(ciphertext: Uint8Array, keyPayload: MediaKeyPayload): Uint8Array | null {
  return decryptMedia(ciphertext, keyPayload.nonce, keyPayload.key);
}
