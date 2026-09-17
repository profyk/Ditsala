/**
 * Backend API client for E2EE messaging (docs/DITSALA_MASTER_SPEC.md
 * §6, §18-21). This is the non-crypto plumbing only — key bytes, ciphertext,
 * and Sender Key distribution messages all pass through as opaque
 * Uint8Array here; a real libsignal binding produces/consumes them once
 * the native module exists (see docs/adr/0005-e2ee-native-module-gap.md).
 * No message composer or chat UI calls this yet, deliberately.
 */

import { base64ToBytes, bytesToBase64 } from "./base64";
import { request } from "./api";

export interface PrekeyBundle {
  identityKey: Uint8Array;
  registrationId: number;
  signedPrekeyId: number;
  signedPrekeyPublic: Uint8Array;
  signedPrekeySignature: Uint8Array;
  oneTimePrekeyId: number | null;
  oneTimePrekeyPublic: Uint8Array | null;
}

export interface Conversation {
  id: string;
  type: "direct" | "group";
  title: string | null;
  disappearing_timer_seconds: number | null;
  last_message_at: string | null;
}

export interface ConversationMember {
  user_id: string;
  display_name: string;
  avatar_url: string | null;
  role: "member" | "admin";
  joined_at: string;
}

export interface Message {
  id: string;
  conversation_id: string;
  sender_device_id: string | null;
  ciphertext: Uint8Array;
  content_type: "text" | "media" | "voice_note" | "reaction" | "system";
  client_message_id: string;
  reply_to_message_id: string | null;
  edited_at: string | null;
  deleted_at: string | null;
  expires_at: string | null;
  created_at: string;
}

interface RawMessage extends Omit<Message, "ciphertext"> {
  ciphertext: string;
}

function fromRawMessage(raw: RawMessage): Message {
  return { ...raw, ciphertext: base64ToBytes(raw.ciphertext) };
}

export const messagingApi = {
  // --- key registration ---

  registerIdentityKey: (
    accessToken: string,
    publicIdentityKey: Uint8Array,
    registrationId: number
  ) =>
    request<void>("/messaging/keys/identity", {
      token: accessToken,
      body: {
        public_identity_key: bytesToBase64(publicIdentityKey),
        registration_id: registrationId,
      },
    }),

  uploadSignedPrekey: (
    accessToken: string,
    keyId: number,
    publicKey: Uint8Array,
    signature: Uint8Array
  ) =>
    request<void>("/messaging/keys/signed-prekey", {
      token: accessToken,
      body: {
        key_id: keyId,
        public_key: bytesToBase64(publicKey),
        signature: bytesToBase64(signature),
      },
    }),

  uploadOneTimePrekeys: (
    accessToken: string,
    keys: { keyId: number; publicKey: Uint8Array }[]
  ) =>
    request<void>("/messaging/keys/one-time-prekeys", {
      token: accessToken,
      body: {
        keys: keys.map((k) => ({ key_id: k.keyId, public_key: bytesToBase64(k.publicKey) })),
      },
    }),

  getPrimaryDevice: async (accessToken: string, userId: string): Promise<string> => {
    const raw = await request<{ device_id: string }>(
      `/messaging/keys/primary-device/${userId}`,
      { method: "GET", token: accessToken }
    );
    return raw.device_id;
  },

  listDevicesForUser: async (accessToken: string, userId: string): Promise<string[]> => {
    const raw = await request<{ device_ids: string[] }>(`/messaging/keys/devices/${userId}`, {
      method: "GET",
      token: accessToken,
    });
    return raw.device_ids;
  },

  getPrekeyBundle: async (
    accessToken: string,
    userId: string,
    deviceId: string
  ): Promise<PrekeyBundle> => {
    const raw = await request<{
      identity_key: string;
      registration_id: number;
      signed_prekey_id: number;
      signed_prekey_public: string;
      signed_prekey_signature: string;
      one_time_prekey_id: number | null;
      one_time_prekey_public: string | null;
    }>(`/messaging/keys/prekey-bundle/${userId}/${deviceId}`, {
      method: "GET",
      token: accessToken,
    });
    return {
      identityKey: base64ToBytes(raw.identity_key),
      registrationId: raw.registration_id,
      signedPrekeyId: raw.signed_prekey_id,
      signedPrekeyPublic: base64ToBytes(raw.signed_prekey_public),
      signedPrekeySignature: base64ToBytes(raw.signed_prekey_signature),
      oneTimePrekeyId: raw.one_time_prekey_id,
      oneTimePrekeyPublic: raw.one_time_prekey_public
        ? base64ToBytes(raw.one_time_prekey_public)
        : null,
    };
  },

  // --- conversations ---

  startDirectConversation: (accessToken: string, otherUserId: string) =>
    request<Conversation>("/messaging/conversations/direct", {
      token: accessToken,
      body: { other_user_id: otherUserId },
    }),

  createGroupConversation: (accessToken: string, memberIds: string[], title?: string) =>
    request<Conversation>("/messaging/conversations/group", {
      token: accessToken,
      body: { member_ids: memberIds, title: title ?? null },
    }),

  listConversations: (accessToken: string) =>
    request<Conversation[]>("/messaging/conversations", { method: "GET", token: accessToken }),

  renameGroupConversation: (accessToken: string, conversationId: string, title: string) =>
    request<Conversation>(`/messaging/conversations/${conversationId}/title`, {
      method: "PATCH",
      token: accessToken,
      body: { title },
    }),

  listConversationMembers: (accessToken: string, conversationId: string) =>
    request<ConversationMember[]>(`/messaging/conversations/${conversationId}/members`, {
      method: "GET",
      token: accessToken,
    }),

  setDisappearingTimer: (accessToken: string, conversationId: string, seconds: number | null) =>
    request<Conversation>(`/messaging/conversations/${conversationId}/disappearing-timer`, {
      method: "PATCH",
      token: accessToken,
      body: { seconds },
    }),

  setMuted: (accessToken: string, conversationId: string, mutedUntil: string | null) =>
    request<void>(`/messaging/conversations/${conversationId}/muted`, {
      method: "PATCH",
      token: accessToken,
      body: { muted_until: mutedUntil },
    }),

  setArchived: (accessToken: string, conversationId: string, value: boolean) =>
    request<void>(`/messaging/conversations/${conversationId}/archived`, {
      method: "PATCH",
      token: accessToken,
      body: { value },
    }),

  setPinned: (accessToken: string, conversationId: string, value: boolean) =>
    request<void>(`/messaging/conversations/${conversationId}/pinned`, {
      method: "PATCH",
      token: accessToken,
      body: { value },
    }),

  // --- messages ---

  sendMessage: async (
    accessToken: string,
    conversationId: string,
    payload: {
      ciphertext: Uint8Array;
      contentType: Message["content_type"];
      clientMessageId: string;
      replyToMessageId?: string;
    }
  ): Promise<Message> => {
    const raw = await request<RawMessage>(`/messaging/conversations/${conversationId}/messages`, {
      token: accessToken,
      body: {
        ciphertext: bytesToBase64(payload.ciphertext),
        content_type: payload.contentType,
        client_message_id: payload.clientMessageId,
        reply_to_message_id: payload.replyToMessageId ?? null,
      },
    });
    return fromRawMessage(raw);
  },

  listMessages: async (
    accessToken: string,
    conversationId: string,
    options: { before?: string; limit?: number } = {}
  ): Promise<Message[]> => {
    const params = new URLSearchParams();
    if (options.before) params.set("before", options.before);
    if (options.limit) params.set("limit", String(options.limit));
    const query = params.toString() ? `?${params.toString()}` : "";
    const raw = await request<RawMessage[]>(
      `/messaging/conversations/${conversationId}/messages${query}`,
      { method: "GET", token: accessToken }
    );
    return raw.map(fromRawMessage);
  },

  editMessage: async (
    accessToken: string,
    messageId: string,
    newCiphertext: Uint8Array
  ): Promise<Message> => {
    const raw = await request<RawMessage>(`/messaging/messages/${messageId}`, {
      method: "PATCH",
      token: accessToken,
      body: { ciphertext: bytesToBase64(newCiphertext) },
    });
    return fromRawMessage(raw);
  },

  deleteMessage: (accessToken: string, messageId: string) =>
    request<void>(`/messaging/messages/${messageId}`, { method: "DELETE", token: accessToken }),

  markReceipt: (accessToken: string, messageId: string, status: "delivered" | "read") =>
    request<void>(`/messaging/messages/${messageId}/receipts`, {
      token: accessToken,
      body: { status },
    }),

  // --- groups: Sender Keys ---

  uploadSenderKey: (
    accessToken: string,
    conversationId: string,
    recipientDeviceId: string,
    distributionMessageRef: Uint8Array
  ) =>
    request<void>(`/messaging/conversations/${conversationId}/sender-keys`, {
      token: accessToken,
      body: {
        recipient_device_id: recipientDeviceId,
        distribution_message_ref: bytesToBase64(distributionMessageRef),
      },
    }),

  listSenderKeys: async (
    accessToken: string,
    conversationId: string
  ): Promise<{ deviceId: string; distributionMessageRef: Uint8Array }[]> => {
    const raw = await request<{ device_id: string; distribution_message_ref: string }[]>(
      `/messaging/conversations/${conversationId}/sender-keys`,
      { method: "GET", token: accessToken }
    );
    return raw.map((r) => ({
      deviceId: r.device_id,
      distributionMessageRef: base64ToBytes(r.distribution_message_ref),
    }));
  },

  // --- media ---

  requestMediaUpload: (
    accessToken: string,
    payload: { contentHash: string; encryptedSizeBytes: number; contentType: string }
  ) =>
    request<{ media_object_id: string; upload_url: string }>("/messaging/media/upload", {
      token: accessToken,
      body: {
        content_hash: payload.contentHash,
        encrypted_size_bytes: payload.encryptedSizeBytes,
        content_type: payload.contentType,
      },
    }),

  getMediaDownloadUrl: (accessToken: string, mediaObjectId: string) =>
    request<{ download_url: string }>(`/messaging/media/${mediaObjectId}/download`, {
      method: "GET",
      token: accessToken,
    }),
};
