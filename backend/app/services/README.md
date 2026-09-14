# services/

Adapters for external providers, each behind an interface defined in the corresponding `domain/` module (`KycProvider`, `OtpProvider`, `EmailProvider`, per `docs/DITSALA_MASTER_SPEC.md` §3.4). Every interface gets a real adapter and a `Sandbox*` adapter using the provider's own test mode — selected by env var only, never a hand-rolled fake.

Real integrations land in Phase 2 (Smile ID, Twilio Verify, email provider) and Phase 6 (WebRTC/coturn signalling support, if anything provider-shaped is needed there). This directory is scaffolded now so the layering (§3.3) is established before those phases begin.
