# Security Gaps

Living document of features shipped behind an interface because they couldn't yet be built to the docs/DITSALA_MASTER_SPEC.md §7 standard, per the kickoff prompt's Working Rule 6. Not a bug tracker — an explicit register of known, deliberate gaps, closed out as they're resolved.

## Open

### DITSALA Code breach-corpus check (spec §15)

**What's missing:** §15 calls for rejecting DITSALA Codes found in a common-password/breach-corpus dataset at signup. `core/security.py::validate_ditsala_code_strength` currently only checks structural rules (length ≥ 8, contains a digit) — it does not check against any breach corpus.

**Why:** No such dataset or service is wired up. A real implementation needs either a local breach-corpus wordlist (e.g., a filtered subset of Have I Been Pwned's Pwned Passwords list) or a k-anonymity API call to a service like HIBP — both require infrastructure/vendor decisions not yet made, and using a live third-party API to check a value derived from a not-yet-hashed secret needs care (HIBP's k-anonymity model, sending only a truncated hash prefix, is the only acceptable approach — never send or log the plaintext code to a third party).

**Tracked for:** Phase 2 follow-up or Phase 8 hardening, whichever lands first. Close this entry by wiring `validate_ditsala_code_strength` to a real breach-corpus check and removing this section.

### Smile ID adapter field/endpoint accuracy (spec §12)

**What's missing:** `services/kyc/smile_id.py` implements Smile ID's documented HMAC partner-signing scheme faithfully, but exact endpoint paths and response field names (`ResultCode`, `PartnerParams`, etc.) have not been verified against a live Smile ID account or current API reference — this was written without vendor credentials (see `CLAUDE.md` "Phase 2" notes).

**Why:** No Smile ID partner account exists in this environment to test against, and Smile ID's API has product-specific variations (Document Verification, Enhanced KYC, SmartSelfie Authentication/Registration) that may differ from what's modeled.

**Tracked for:** Before Phase 2 goes live against production or sandbox credentials — re-verify every field/endpoint against Smile ID's current partner API docs, then remove this section.

## Resolved

_(none yet)_
