/**
 * Web -> app registration handoff (business-model kickoff prompt, Feature
 * 2): this web app never creates a DITSALA account itself — "Register"
 * always routes here instead of a web sign-up form. Store URLs are
 * env-configured, not hardcoded, since the app isn't in either store yet;
 * when unset, the UI says so honestly rather than linking to a guessed
 * or placeholder URL (same "refuse until configured" principle
 * `VipUpgradeService._get_pricing` already uses for a missing config value).
 */

export const APP_STORE_URL = process.env.NEXT_PUBLIC_APP_STORE_URL || null;
export const PLAY_STORE_URL = process.env.NEXT_PUBLIC_PLAY_STORE_URL || null;
// ditsala:// — apps/mobile's own deep-link scheme (app.json), used to try
// opening an already-installed app before falling back to a store badge.
export const APP_DEEPLINK_SCHEME = process.env.NEXT_PUBLIC_APP_DEEPLINK_SCHEME || "ditsala://";

export type DetectedPlatform = "ios" | "android" | "desktop";

export function detectPlatform(userAgent: string): DetectedPlatform {
  const ua = userAgent.toLowerCase();
  if (/iphone|ipad|ipod/.test(ua)) return "ios";
  if (/android/.test(ua)) return "android";
  return "desktop";
}

export function storeUrlFor(platform: DetectedPlatform): string | null {
  if (platform === "ios") return APP_STORE_URL;
  if (platform === "android") return PLAY_STORE_URL;
  return null;
}
