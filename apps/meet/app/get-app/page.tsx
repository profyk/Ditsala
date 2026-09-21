"use client";

import { useEffect, useState } from "react";

import {
  APP_DEEPLINK_SCHEME,
  type DetectedPlatform,
  detectPlatform,
  storeUrlFor,
} from "@/lib/app-install";

/**
 * The only thing "Register"/"Create account" ever does on this site
 * (business-model kickoff prompt, Feature 2) — account creation, KYC, and
 * DITSALA Code setup all happen inside the mobile app, never here. This
 * page never collects an email, phone number, or password; it only helps
 * someone get the app onto their device.
 */
export default function GetAppPage() {
  const [platform, setPlatform] = useState<DetectedPlatform | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const detected = detectPlatform(navigator.userAgent);
    setPlatform(detected);
    if (detected !== "desktop") {
      // Best-effort: if DITSALA is already installed, this hands off to
      // it immediately. If nothing responds, the visitor just stays on
      // this page and uses the store badge below — there's no reliable
      // cross-browser way to detect whether the attempt "failed", so this
      // is deliberately a try-then-stay pattern, not a hard redirect.
      window.location.href = `${APP_DEEPLINK_SCHEME}open`;
    }
  }, []);

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard access can be denied by the browser — the link is
      // already visible on-screen either way, so this just silently
      // no-ops rather than showing an alert for a non-critical action.
    }
  }

  const storeUrl = platform ? storeUrlFor(platform) : null;

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 px-4 py-16 text-center">
      <h1 className="font-display text-3xl text-text-primary">Get the DITSALA app</h1>
      <p className="max-w-sm text-text-secondary">
        Creating your account, verifying your identity, and setting your DITSALA Code all
        happen in the app — there&apos;s no sign-up on the web.
      </p>

      {storeUrl ? (
        <a
          href={storeUrl}
          className="rounded bg-accent px-6 py-3 font-medium text-background hover:bg-accent-pressed"
        >
          {platform === "ios" ? "Download on the App Store" : "Get it on Google Play"}
        </a>
      ) : (
        <p className="rounded border border-border bg-surface px-4 py-3 text-sm text-text-tertiary">
          The DITSALA app isn&apos;t published to app stores yet — check back soon.
        </p>
      )}

      <div className="flex flex-col items-center gap-2">
        <p className="text-xs uppercase tracking-widest text-text-tertiary">
          On a computer? Send this link to your phone
        </p>
        <button
          type="button"
          onClick={copyLink}
          className="rounded border border-border bg-surface px-4 py-2 text-sm text-text-primary hover:bg-surface-raised"
        >
          {copied ? "Link copied" : "Copy link"}
        </button>
      </div>
    </main>
  );
}
