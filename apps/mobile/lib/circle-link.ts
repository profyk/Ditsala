/**
 * Parses the `userId` out of a shared/scanned Circle add-contact link
 * (docs/DITSALA_MASTER_SPEC.md §22, "invite link" and "QR code" channels
 * are the same underlying link — QR is just that link encoded as an
 * image). Deliberately a plain regex, not the `URL` global: it needs to
 * run the same way in Jest as on-device, and a malformed/foreign QR code
 * should return null, never throw.
 */
export function extractContactUserId(scannedOrSharedText: string): string | null {
  const match = scannedOrSharedText.match(/[?&]userId=([^&]+)/);
  if (!match) return null;
  try {
    return decodeURIComponent(match[1]) || null;
  } catch {
    return null;
  }
}
