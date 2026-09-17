import { deleteSecureItem, getSecureItem, setSecureItem } from "./platform-storage";

/**
 * The real session (§16) — distinct from lib/onboarding-context.tsx's
 * in-memory onboarding token, which never reaches this durable storage.
 * Backed by Keychain (iOS) / Keystore (Android) / localStorage (web) via
 * lib/platform-storage.ts — see that module for why web needs its own
 * path.
 */

const ACCESS_TOKEN_KEY = "ditsala.access_token";
const REFRESH_TOKEN_KEY = "ditsala.refresh_token";
const IDENTITY_KEY = "ditsala.identity";

/** ADR 0014 — the login identifier (phone for `normal`, email for `vip`)
 * and account tier, cached locally so a `normal`-tier PIN unlock
 * (lib/api.ts's `authApi.loginStart`) never has to ask the user to
 * retype their phone number, and so the UI can gate tier-specific
 * affordances (e.g. hiding logout for `normal`) without a network call. */
export interface StoredIdentity {
  identifier: string;
  accountTier: string;
}

export async function saveSession(accessToken: string, refreshToken: string): Promise<void> {
  await setSecureItem(ACCESS_TOKEN_KEY, accessToken);
  await setSecureItem(REFRESH_TOKEN_KEY, refreshToken);
}

export async function getAccessToken(): Promise<string | null> {
  return getSecureItem(ACCESS_TOKEN_KEY);
}

export async function getRefreshToken(): Promise<string | null> {
  return getSecureItem(REFRESH_TOKEN_KEY);
}

export async function saveAccessToken(accessToken: string): Promise<void> {
  await setSecureItem(ACCESS_TOKEN_KEY, accessToken);
}

export async function clearSession(): Promise<void> {
  await deleteSecureItem(ACCESS_TOKEN_KEY);
  await deleteSecureItem(REFRESH_TOKEN_KEY);
  await deleteSecureItem(IDENTITY_KEY);
}

export async function hasStoredSession(): Promise<boolean> {
  return (await getRefreshToken()) !== null;
}

export async function saveIdentity(identifier: string, accountTier: string): Promise<void> {
  await setSecureItem(IDENTITY_KEY, JSON.stringify({ identifier, accountTier }));
}

export async function getIdentity(): Promise<StoredIdentity | null> {
  const raw = await getSecureItem(IDENTITY_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as StoredIdentity;
  } catch {
    return null;
  }
}
