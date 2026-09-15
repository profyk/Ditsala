# services/

Adapters for external providers, each behind an interface defined in the corresponding `domain/` module (`KycProvider`, `OtpProvider`, `EmailProvider`, per `docs/DITSALA_MASTER_SPEC.md` §3.4). Every interface gets a real adapter and a `Sandbox*` adapter using the provider's own test mode — selected by env var only, never a hand-rolled fake (`services/factory.py` does the selection).

`email/`, `otp/`, and `kyc/` are built (Phase 2) — see `domain/onboarding/interfaces.py` for the Protocols. `push/`, `storage/`, and `realtime/` are still empty, landing with Phase 4 (media/push) and Phase 6 (WebRTC/coturn signalling).
