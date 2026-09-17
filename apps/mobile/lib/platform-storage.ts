import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";

/**
 * expo-secure-store (Keychain/Keystore) has no functioning web
 * implementation — its web module is a literal empty object, so calling
 * any method on it throws at runtime ("X is not a function"), not at
 * build time. Every module in this app that persists something locally
 * (lib/session.ts, lib/crypto/keystore.ts) goes through this instead of
 * calling SecureStore directly, so the native/web split lives in one
 * place. `localStorage` on web is a real, disclosed security tradeoff
 * versus Keychain/Keystore (readable by any JS on the page, vulnerable
 * to XSS) — the standard fallback every Expo-web app in this situation
 * uses, not a weaker choice made carelessly.
 */

const isWeb = Platform.OS === "web";

export async function setSecureItem(key: string, value: string): Promise<void> {
  if (isWeb) {
    window.localStorage.setItem(key, value);
    return;
  }
  await SecureStore.setItemAsync(key, value);
}

export async function getSecureItem(key: string): Promise<string | null> {
  if (isWeb) {
    return window.localStorage.getItem(key);
  }
  return SecureStore.getItemAsync(key);
}

export async function deleteSecureItem(key: string): Promise<void> {
  if (isWeb) {
    window.localStorage.removeItem(key);
    return;
  }
  await SecureStore.deleteItemAsync(key);
}
