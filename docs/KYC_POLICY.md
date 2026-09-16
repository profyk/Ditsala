# DITSALA KYC & Identity Verification Policy

*Explains identity verification (KYC) processing, biometric consent, manual review, and the appeal path — see docs/DITSALA_MASTER_SPEC.md §9-15, §28.2, §33 for the underlying engineering spec.*

## 1. Why we verify identity

DITSALA is an identity-verified communications app: every account belongs to a real, unique, verified person before it can message anyone. This is the product's core trust guarantee, not an incidental compliance step.

## 2. What verification involves

During signup, after you verify your email and phone number, you're asked to:

1. **Capture your government-issued ID document** (a South African or Botswana-issued ID, or another accepted document type).
2. **Complete a liveness check** — a short, guided selfie capture that confirms a real person is present, not a photo or a video replay.

Both steps are processed by **Smile ID**, our identity-verification partner, using their Document Verification, Enhanced KYC, and SmartSelfie products.

## 3. Biometric consent

Your ID photo and liveness selfie are "special personal information" (POPIA) / sensitive personal data (Botswana DPA), and are treated accordingly:

- Consent for biometric capture is captured **separately** from DITSALA's general terms of service, immediately before the capture screen opens — never bundled into a blanket "I agree" at signup.
- The consent screen states plainly what's being captured, why (identity verification only), and that DITSALA does not retain the image (see §4).
- You can decline at this step, but you will not be able to complete account creation — verified identity is not an optional feature of DITSALA.

## 4. What we keep — and what we don't

**We never store your ID document photo or liveness selfie.** They are transmitted to Smile ID for verification and DITSALA retains only:

- A reference to Smile ID's own verification job (`smile_id_job_id`).
- The verification **outcome**: pass/fail and a confidence score (`result_summary`) — never the imagery itself.

Our contract with Smile ID caps *their* retention of your enrollment image to the lifetime of your DITSALA account plus a bounded window after account deletion (target: 30 days), specified as a binding data processing agreement term rather than left to their default retention.

## 5. If verification doesn't pass

A failed or inconclusive verification places your account in **manual review**, not automatic rejection. A member of our trust & safety team reviews the case — this review requires a logged, specific justification before any reviewer can see your verification detail, and every access is auditable.

Manual review resolves one of three ways:

- **Approved** — your account is activated normally.
- **Recapture requested** — you're asked to redo the document or liveness capture (common causes: glare, blur, an expired document).
- **Rejected** — your account cannot be activated with the submitted identity information.

## 6. Appeal path

If your account is rejected and you believe this was in error, you can request a second review through the in-app support channel. Include what you believe went wrong (e.g., a document type you believe should be accepted, or a technical issue during capture). A rejection is not necessarily final — a second manual review can reverse it, but repeated verification attempts from the same identity information that continue to fail may result in the account remaining rejected.

## 7. Recovery re-verification

If you lose access to your device, account recovery (§33, see `ACCOUNT_RECOVERY.md`) requires a fresh liveness check matched **1:1 against your existing Smile ID enrollment** (SmartSelfie Authentication) — not a document re-capture, and not DITSALA re-supplying any stored image, since none is stored. This confirms the person recovering the account is the same person who originally verified it.
