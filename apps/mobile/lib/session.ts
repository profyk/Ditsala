import * as SecureStore from "expo-secure-store";

/**
 * The real session (§16) — distinct from lib/onboarding-context.tsx's
 * in-memory onboarding token, which never reaches this durable storage.
 * SecureStore is backed by Keychain (iOS) / Keystore (Android).
 */

const ACCESS_TOKEN_KEY = "ditsala.access_token";
const REFRESH_TOKEN_KEY = "ditsala.refresh_token";

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
}

export async function hasStoredSession(): Promise<boolean> {
  return (await getRefreshToken()) !== null;
}
