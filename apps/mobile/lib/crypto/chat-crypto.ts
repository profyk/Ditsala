/**
 * High-level "send/receive a chat message" operations — wires together
 * lib/crypto/e2ee.ts (the primitives), keystore.ts (this device's keys
 * and other devices' verified prekeys), wire.ts (envelope encoding),
 * and messaging-api.ts (the actual REST calls). Screens call this
 * module, never e2ee.ts directly.
 */

import * as SecureStore from "expo-secure-store";

import { type Conversation, type ConversationMember, messagingApi } from "../messaging-api";
import {
  bytesToUtf8,
  decryptDirectMessage,
  decryptGroupMessage,
  encryptDirectMessage,
  encryptGroupMessage,
  fromBase64,
  generateSenderKey,
  toBase64,
  utf8ToBytes,
} from "./e2ee";
import { ensureDeviceIdentity, fetchVerifiedPrekeyForUser, findLocalPrekeySecret } from "./keystore";
import { packDirectEnvelope, packGroupEnvelope, unpackDirectEnvelope, unpackGroupEnvelope } from "./wire";

const SENDER_KEY_PREFIX = "ditsala.e2ee.senderKey.";

async function loadOwnSenderKey(conversationId: string): Promise<Uint8Array | null> {
  const raw = await SecureStore.getItemAsync(`${SENDER_KEY_PREFIX}${conversationId}`);
  return raw ? fromBase64(raw) : null;
}

async function saveOwnSenderKey(conversationId: string, key: Uint8Array): Promise<void> {
  await SecureStore.setItemAsync(`${SENDER_KEY_PREFIX}${conversationId}`, toBase64(key));
}

/** Ensures this device has a Sender Key for the conversation, generating
 * and distributing a fresh one (encrypted individually to every other
 * member's device) the first time it's needed. */
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
      const recipientPrekey = await fetchVerifiedPrekeyForUser(accessToken, member.user_id);
      const envelope = encryptDirectMessage({
        plaintext: senderKey,
        senderIdentity: identity,
        recipientPrekeyId: recipientPrekey.prekeyId,
        recipientPrekeyPublicKey: recipientPrekey.prekeyPublicKey,
      });
      await messagingApi.uploadSenderKey(
        accessToken,
        conversation.id,
        recipientPrekey.deviceId,
        packDirectEnvelope(envelope)
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
  const plaintextBytes = utf8ToBytes(plaintext);

  if (conversation.type === "group") {
    const senderKey = await ensureOwnSenderKeyDistributed(
      accessToken,
      conversation,
      members,
      ownUserId
    );
    return packGroupEnvelope(encryptGroupMessage(plaintextBytes, senderKey));
  }

  const recipient = members.find((m) => m.user_id !== ownUserId);
  if (!recipient) throw new Error("Direct conversation has no other member to encrypt to.");
  const identity = await ensureDeviceIdentity();
  const recipientPrekey = await fetchVerifiedPrekeyForUser(accessToken, recipient.user_id);
  const envelope = encryptDirectMessage({
    plaintext: plaintextBytes,
    senderIdentity: identity,
    recipientPrekeyId: recipientPrekey.prekeyId,
    recipientPrekeyPublicKey: recipientPrekey.prekeyPublicKey,
  });
  return packDirectEnvelope(envelope);
}

/**
 * Decrypts a received message. Returns `null` (never throws) on
 * failure — a message this device can't decrypt (wrong prekey already
 * consumed by another of the sender's messages, corrupted data, etc.)
 * should render as "couldn't decrypt this message," not crash the chat.
 */
export async function decryptIncomingMessage(
  accessToken: string,
  conversation: Conversation,
  senderDeviceId: string | null,
  ciphertext: Uint8Array
): Promise<string | null> {
  try {
    if (conversation.type === "group") {
      if (!senderDeviceId) return null;
      const senderKey = await resolveSenderKeyFor(accessToken, conversation.id, senderDeviceId);
      if (!senderKey) return null;
      const plaintext = decryptGroupMessage(unpackGroupEnvelope(ciphertext), senderKey);
      return plaintext ? bytesToUtf8(plaintext) : null;
    }

    const envelope = unpackDirectEnvelope(ciphertext);
    const prekeySecret = await findLocalPrekeySecret(envelope.recipientPrekeyId);
    if (!prekeySecret) return null;
    const plaintext = decryptDirectMessage({ envelope, recipientPrekeySecretKey: prekeySecret });
    return plaintext ? bytesToUtf8(plaintext) : null;
  } catch {
    return null;
  }
}
