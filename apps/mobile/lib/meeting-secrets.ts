import { getSecureItem, setSecureItem } from "./platform-storage";

/**
 * Local-only cache of a meeting's password and host PIN — the backend
 * deliberately never stores either in plaintext (Argon2id-hashed, same
 * "P0-equivalent" treatment as the DITSALA Code — see backend
 * Meeting.password_hash/host_pin_hash), and the host PIN is only ever
 * returned once, in the create_meeting response. Without this, closing
 * the "Meeting scheduled" screen loses both forever — a real UX gap for
 * a host who wants to check or re-share them later.
 *
 * This is the deliberately-scoped fix: remember what *this device*
 * already saw in plaintext (it typed the password itself; the PIN came
 * back once over the wire to it) via the same Keychain/Keystore-backed
 * storage `lib/session.ts` already uses for the access/refresh tokens —
 * never sent to or re-derivable from the backend. A host viewing "My
 * meetings" from a different device won't see them here; that's the
 * real, disclosed boundary of a purely local cache, not a bug.
 */

const STORAGE_KEY = "ditsala.meeting_secrets";

export interface MeetingSecret {
  meetingId: string;
  title: string;
  password: string | null;
  hostPin: string | null;
  savedAt: string;
}

type SecretsMap = Record<string, MeetingSecret>;

async function readAll(): Promise<SecretsMap> {
  const raw = await getSecureItem(STORAGE_KEY);
  if (!raw) return {};
  try {
    return JSON.parse(raw) as SecretsMap;
  } catch {
    return {};
  }
}

async function writeAll(map: SecretsMap): Promise<void> {
  await setSecureItem(STORAGE_KEY, JSON.stringify(map));
}

export async function saveMeetingSecret(
  secret: Omit<MeetingSecret, "savedAt">
): Promise<void> {
  const all = await readAll();
  all[secret.meetingId] = { ...secret, savedAt: new Date().toISOString() };
  await writeAll(all);
}

export async function getMeetingSecret(meetingId: string): Promise<MeetingSecret | null> {
  const all = await readAll();
  return all[meetingId] ?? null;
}

export async function getMeetingSecrets(
  meetingIds: string[]
): Promise<Record<string, MeetingSecret>> {
  const all = await readAll();
  const result: Record<string, MeetingSecret> = {};
  for (const id of meetingIds) {
    const found = all[id];
    if (found) result[id] = found;
  }
  return result;
}

export async function deleteMeetingSecret(meetingId: string): Promise<void> {
  const all = await readAll();
  if (!(meetingId in all)) return;
  delete all[meetingId];
  await writeAll(all);
}
