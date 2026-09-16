# DITSALA Privacy Policy

*Last updated: Phase 8 (docs/DITSALA_MASTER_SPEC.md v1.0). This document is written for end users and covers what DITSALA collects, why, and what rights you have over it. It is governed by South Africa's Protection of Personal Information Act (POPIA) and Botswana's Data Protection Act, applied as a single global standard rather than jurisdiction-conditional rules.*

## 1. Who we are

DITSALA is a privacy-first, identity-verified communications app for South Africa and Botswana. This policy explains what personal information we collect through the app, why, who else sees it, and how long we keep it.

## 2. What we collect, and why

| Category | Examples | Why we collect it | Lawful basis |
|---|---|---|---|
| Identity information | Email, phone number, display name, date of birth | To create and secure your account, and to verify you're a real, unique person (§9-15 of our engineering spec) | Consent + contractual necessity |
| Biometric/KYC data | A photo of your ID document, a "liveness" selfie check | To verify your identity before you can message anyone, so DITSALA can offer identity-verified communication | Explicit, separately-captured consent (never bundled into general terms) |
| Next-of-kin details | A name, relationship, and phone number you provide | Used only for SOS emergency escalation and account recovery attestation — never for anything else | Consent |
| Location | GPS coordinates, only while you've actively started a location share, or during an SOS event | To let people you choose see where you are, and to notify your trusted contacts in an emergency | Consent (standing shares); vital-interest override during an active SOS event only |
| Device and usage metadata | Device model/platform, push token, login timestamps, IP-derived security signals | To keep your account secure (detect suspicious logins, rate-limit abuse) and deliver notifications | Legitimate interest in service integrity |
| Message content | Text, media you send in conversations | To deliver your messages | Contractual necessity — **and see §4 below: we cannot read it even if we wanted to** |

We do not collect more than the above. We do not sell personal information to anyone, ever.

## 3. What we do *not* keep

- **Your KYC document photo and liveness selfie are never stored by DITSALA, at any point, for any reason.** We forward them to our identity-verification partner (see §5) at the moment of verification and keep only the outcome (pass/fail, a confidence score) — never the image itself.
- We do not keep a plaintext copy of your DITSALA Code (your account's secret) anywhere. It is one-way hashed the same way a password would be, using Argon2id, an industry-standard algorithm designed to resist offline cracking attempts.
- We do not keep your national ID number — only a one-way cryptographic hash of it, used solely to prevent one person from creating multiple accounts.

## 4. Message content: DITSALA cannot read your messages

DITSALA messages are end-to-end encrypted using the Signal Protocol. Encryption and decryption happen only on your device and the device(s) of the people you're talking to. Our servers relay encrypted data (ciphertext) they cannot decrypt, and no support, engineering, or law-enforcement-response process at DITSALA has a path to decrypted message content — this is a hard architectural constraint, not a policy promise we could waive under pressure.

## 5. Who we share information with

We use a small number of specialist processors to run parts of the service. We never sell your data, and we only share what each processor strictly needs to do its job:

| Processor | What they receive | What they do |
|---|---|---|
| **Smile ID** | Your ID document photo, liveness selfie | Identity verification (document check, biometric match) |
| **Twilio** | Your phone number | Sends the one-time codes used to verify your phone number and, later, confirm your identity at login |
| **Resend** (email) | Your email address | Sends the one-time codes used to verify your email address |

All three are outside South Africa/Botswana. Where personal information crosses that border, we require a signed data processing agreement with each processor incorporating protections equivalent to POPIA's, before that processor is used with real user data — see §34.3 of our engineering spec for the full legal basis.

## 6. Your rights

You can ask us to:

- **Access** the personal information we hold about you.
- **Correct** information that's wrong or out of date.
- **Delete** your account and the data associated with it.

File a request in the app (Settings → Privacy → Request my data), and we will respond within **30 calendar days**. Deleting your account starts a 30-day grace period during which you can change your mind (Settings → reactivate); after that window, your data is permanently and irreversibly removed, except for a minimal audit record (see `DATA_RETENTION.md`) that no longer identifies you personally beyond an internal account reference.

## 7. Security

See `SECURITY.md` for how we protect your information technically and organizationally.

## 8. Contact

Questions about this policy, or to exercise your rights outside the app, can be raised through the in-app support channel.
