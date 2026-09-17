/**
 * Persists this device's E2EE key material (docs/adr/0013) via
 * lib/platform-storage.ts — Keychain (iOS) / Keystore (Android) /
 * localStorage (web), the same backing store lib/session.ts already
 * trusts for tokens — and orchestrates registering/replenishing keys
 * with the backend.
 *
 * Each value is kept small and stored under its own key rather than one
 * big JSON blob: SecureStore has historically had a ~2048-byte per-value
 * limit on Android, unverified in this no-device environment, so this
 * plays it safe rather than assume a single large blob always fits.
 */

import nacl from "tweetnacl";

import { messagingApi } from "../messaging-api";
import { deleteSecureItem, getSecureItem, setSecureItem } from "../platform-storage";
import {
  type DeviceIdentity,
  type SignedPrekey,
  fromBase64,
  generateIdentity,
  generateOneTimePrekeys,
  generateSignedPrekey,
  packIdentityPublicKey,
  toBase64,
  unpackIdentityPublicKey,
  verifySignedPrekey,
} from "./e2ee";

const IDENTITY_KEY = "ditsala.e2ee.identity";
const REGISTRATION_ID_KEY = "ditsala.e2ee.registrationId";
const SIGNED_PREKEY_KEY = "ditsala.e2ee.signedPrekey";
const OTPK_INDEX_KEY = "ditsala.e2ee.otpkIndex";
const OTPK_PREFIX = "ditsala.e2ee.otpk.";
const REGISTERED_FLAG_KEY = "ditsala.e2ee.registeredWithBackend";

const ONE_TIME_PREKEY_BATCH_SIZE = 20;
const ONE_TIME_PREKEY_REPLENISH_THRESHOLD = 5;

interface StoredKeyPair {
  publicKey: string;
  secretKey: string;
}

interface StoredIdentity {
  box: StoredKeyPair;
  sign: StoredKeyPair;
}

interface StoredSignedPrekey {
  keyId: number;
  publicKey: string;
  secretKey: string;
  signature: string;
}

function serializeIdentity(identity: DeviceIdentity): StoredIdentity {
  return {
    box: { publicKey: toBase64(identity.box.publicKey), secretKey: toBase64(identity.box.secretKey) },
    sign: {
      publicKey: toBase64(identity.sign.publicKey),
      secretKey: toBase64(identity.sign.secretKey),
    },
  };
}

function deserializeIdentity(stored: StoredIdentity): DeviceIdentity {
  return {
    box: { publicKey: fromBase64(stored.box.publicKey), secretKey: fromBase64(stored.box.secretKey) },
    sign: {
      publicKey: fromBase64(stored.sign.publicKey),
      secretKey: fromBase64(stored.sign.secretKey),
    },
  };
}

/** Loads this device's identity keypairs, generating and persisting a
 * new one on first use. Never re-generated after that — a changed
 * identity key is exactly what §23's safety-number re-verification
 * gates on, so this must stay stable across app restarts. */
export async function ensureDeviceIdentity(): Promise<DeviceIdentity> {
  const existing = await getSecureItem(IDENTITY_KEY);
  if (existing) {
    return deserializeIdentity(JSON.parse(existing) as StoredIdentity);
  }
  const identity = generateIdentity();
  await setSecureItem(IDENTITY_KEY, JSON.stringify(serializeIdentity(identity)));
  return identity;
}

async function ensureRegistrationId(): Promise<number> {
  const existing = await getSecureItem(REGISTRATION_ID_KEY);
  if (existing) return Number(existing);
  // Housekeeping value only (distinguishes a reinstall to the backend),
  // not a secret — still drawn from the same CSPRNG as everything else
  // here rather than Math.random(), to avoid mixing weak and strong
  // randomness practices in the same module.
  const id = new DataView(nacl.randomBytes(4).buffer).getUint32(0) % 0x3fff;
  await setSecureItem(REGISTRATION_ID_KEY, String(id));
  return id;
}

async function loadSignedPrekey(): Promise<SignedPrekey | null> {
  const raw = await getSecureItem(SIGNED_PREKEY_KEY);
  if (!raw) return null;
  const stored = JSON.parse(raw) as StoredSignedPrekey;
  return {
    keyId: stored.keyId,
    publicKey: fromBase64(stored.publicKey),
    secretKey: fromBase64(stored.secretKey),
    signature: fromBase64(stored.signature),
  };
}

async function saveSignedPrekey(prekey: SignedPrekey): Promise<void> {
  const stored: StoredSignedPrekey = {
    keyId: prekey.keyId,
    publicKey: toBase64(prekey.publicKey),
    secretKey: toBase64(prekey.secretKey),
    signature: toBase64(prekey.signature),
  };
  await setSecureItem(SIGNED_PREKEY_KEY, JSON.stringify(stored));
}

async function loadOneTimePrekeyIndex(): Promise<number[]> {
  const raw = await getSecureItem(OTPK_INDEX_KEY);
  return raw ? (JSON.parse(raw) as number[]) : [];
}

async function saveOneTimePrekeyIndex(keyIds: number[]): Promise<void> {
  await setSecureItem(OTPK_INDEX_KEY, JSON.stringify(keyIds));
}

/**
 * Registers (once) or tops up (as needed) this device's keys with the
 * backend — identity key, a signed prekey if none exists yet, and a
 * fresh batch of one-time prekeys whenever the local pool runs low.
 * Safe to call on every app launch: each step is a real no-op when
 * there's nothing to do.
 */
export async function registerWithBackend(accessToken: string): Promise<void> {
  const identity = await ensureDeviceIdentity();
  const registrationId = await ensureRegistrationId();
  const alreadyRegistered = await getSecureItem(REGISTERED_FLAG_KEY);

  if (!alreadyRegistered) {
    await messagingApi.registerIdentityKey(
      accessToken,
      packIdentityPublicKey(identity),
      registrationId
    );
    await setSecureItem(REGISTERED_FLAG_KEY, "true");
  }

  let signedPrekey = await loadSignedPrekey();
  if (!signedPrekey) {
    signedPrekey = generateSignedPrekey(identity.sign, 1);
    await messagingApi.uploadSignedPrekey(
      accessToken,
      signedPrekey.keyId,
      signedPrekey.publicKey,
      signedPrekey.signature
    );
    await saveSignedPrekey(signedPrekey);
  }

  const existingOtpkIds = await loadOneTimePrekeyIndex();
  if (existingOtpkIds.length < ONE_TIME_PREKEY_REPLENISH_THRESHOLD) {
    const nextKeyId = existingOtpkIds.length
      ? Math.max(...existingOtpkIds) + 1
      : signedPrekey.keyId + 1;
    const freshKeys = generateOneTimePrekeys(ONE_TIME_PREKEY_BATCH_SIZE, nextKeyId);
    await Promise.all(
      freshKeys.map((k) => setSecureItem(`${OTPK_PREFIX}${k.keyId}`, toBase64(k.secretKey)))
    );
    await messagingApi.uploadOneTimePrekeys(
      accessToken,
      freshKeys.map((k) => ({ keyId: k.keyId, publicKey: k.publicKey }))
    );
    await saveOneTimePrekeyIndex([...existingOtpkIds, ...freshKeys.map((k) => k.keyId)]);
  }
}

/**
 * Finds the local secret key for a prekey id an incoming message was
 * encrypted against — the current signed prekey, or a one-time prekey
 * (consumed and deleted on lookup: once used, gone, for real forward
 * secrecy on that specific message even if this device is later
 * compromised).
 */
export async function findLocalPrekeySecret(prekeyId: number): Promise<Uint8Array | null> {
  const signedPrekey = await loadSignedPrekey();
  if (signedPrekey && signedPrekey.keyId === prekeyId) {
    return signedPrekey.secretKey;
  }

  const raw = await getSecureItem(`${OTPK_PREFIX}${prekeyId}`);
  if (!raw) return null;
  const secretKey = fromBase64(raw);

  await deleteSecureItem(`${OTPK_PREFIX}${prekeyId}`);
  const index = await loadOneTimePrekeyIndex();
  await saveOneTimePrekeyIndex(index.filter((id) => id !== prekeyId));

  return secretKey;
}

export interface RemotePrekey {
  prekeyId: number;
  prekeyPublicKey: Uint8Array;
  identityBoxPublicKey: Uint8Array;
}

/**
 * Fetches and verifies another device's prekey bundle — a failed
 * signature check means the server (or a MITM) substituted a key, and
 * this throws rather than silently trusting it.
 */
export async function fetchVerifiedPrekey(
  accessToken: string,
  userId: string,
  deviceId: string
): Promise<RemotePrekey> {
  const bundle = await messagingApi.getPrekeyBundle(accessToken, userId, deviceId);
  const { boxPublicKey, signPublicKey } = unpackIdentityPublicKey(bundle.identityKey);

  const verified = verifySignedPrekey(
    bundle.signedPrekeyPublic,
    bundle.signedPrekeySignature,
    signPublicKey
  );
  if (!verified) {
    throw new Error("This device's signed prekey failed signature verification — refusing to use it.");
  }

  // Prefer the one-time prekey when the server had one to hand out —
  // it gives this session's opening message an extra, single-use DH
  // term beyond the signed prekey alone.
  if (bundle.oneTimePrekeyId !== null && bundle.oneTimePrekeyPublic !== null) {
    return {
      prekeyId: bundle.oneTimePrekeyId,
      prekeyPublicKey: bundle.oneTimePrekeyPublic,
      identityBoxPublicKey: boxPublicKey,
    };
  }
  return {
    prekeyId: bundle.signedPrekeyId,
    prekeyPublicKey: bundle.signedPrekeyPublic,
    identityBoxPublicKey: boxPublicKey,
  };
}

export interface RemoteDeviceAndPrekey extends RemotePrekey {
  deviceId: string;
}

/**
 * Real multi-device fan-out (docs/adr/0013): every device of this user
 * that has completed key registration, each with its own verified
 * prekey — a sender distributes a Sender Key to each one, so every
 * device the recipient is signed into can decrypt, not just whichever
 * one registered keys most recently. A device whose bundle fails to
 * fetch or verify is skipped (logged via the thrown error being
 * swallowed here) rather than failing the whole send — one stale
 * device shouldn't block a message from reaching every other one.
 */
export async function fetchVerifiedPrekeysForAllDevices(
  accessToken: string,
  userId: string
): Promise<RemoteDeviceAndPrekey[]> {
  const deviceIds = await messagingApi.listDevicesForUser(accessToken, userId);
  const results: RemoteDeviceAndPrekey[] = [];
  for (const deviceId of deviceIds) {
    try {
      const prekey = await fetchVerifiedPrekey(accessToken, userId, deviceId);
      results.push({ ...prekey, deviceId });
    } catch {
      // Skip this one device rather than failing the whole distribution.
    }
  }
  return results;
}
