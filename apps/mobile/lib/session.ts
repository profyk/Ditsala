import * as SecureStore from "expo-secure-store";

/**
 * The real session (§16) — distinct from lib/onboarding-context.tsx's
 * in-memory onboarding token, which never reaches this durable storage.
 * SecureStore is backed by Keychain (iOS) / Keystore (Android).
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
  await SecureStore.setItemAsync(ACCESS_TOKEN_KEY, accessToken);
  await SecureStore.setItemAsync(REFRESH_TOKEN_KEY, refreshToken);
}

export async function getAccessToken(): Promise<string | null> {
  return SecureStore.getItemAsync(ACCESS_TOKEN_KEY);
}

export async function getRefreshToken(): Promise<string | null> {
  return SecureStore.getItemAsync(REFRESH_TOKEN_KEY);
}

export async function saveAccessToken(accessToken: string): Promise<void> {
  await SecureStore.setItemAsync(ACCESS_TOKEN_KEY, accessToken);
}

export async function clearSession(): Promise<void> {
  await SecureStore.deleteItemAsync(ACCESS_TOKEN_KEY);
  await SecureStore.deleteItemAsync(REFRESH_TOKEN_KEY);
  await SecureStore.deleteItemAsync(IDENTITY_KEY);
}

export async function hasStoredSession(): Promise<boolean> {
  return (await getRefreshToken()) !== null;
}

export async function saveIdentity(identifier: string, accountTier: string): Promise<void> {
  await SecureStore.setItemAsync(IDENTITY_KEY, JSON.stringify({ identifier, accountTier }));
}

export async function getIdentity(): Promise<StoredIdentity | null> {
  const raw = await SecureStore.getItemAsync(IDENTITY_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as StoredIdentity;
  } catch {
    return null;
  }
}
