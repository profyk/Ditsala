# ADR 0003: Mobile app in the pnpm workspace, and the Smile ID native-SDK gap

Status: Accepted (Phase 2)

## Context

`apps/mobile` was scaffolded with `create-expo-app` (which uses npm internally) but the kickoff prompt locks in "pnpm workspaces + Turborepo for the TS apps" for the whole monorepo, `apps/mobile` included. React Native's tooling ecosystem is npm/yarn-first, and pnpm's default symlinked `node_modules` has historically broken native-module autolinking, which walks `node_modules` expecting a flat structure.

Separately: docs/DITSALA_MASTER_SPEC.md §12 requires the Smile ID mobile SDK to drive KYC capture natively (camera-only, talks to Smile ID directly once the backend issues it a token). That SDK is a native library requiring its own Expo config plugin — the same category of native-module work as the libsignal integration (§6), which the spec already calls out as needing "a native Expo module with a config plugin."

## Decisions

**Mobile joined the pnpm workspace**, not kept as an isolated npm project. Fix for the historical pnpm/RN friction: `.npmrc` sets `node-linker=hoisted` (flattens `node_modules` back to an npm/yarn-classic-like structure) and `metro.config.js` sets `resolver.unstable_enableSymlinks = true` plus explicit `watchFolders`/`nodeModulesPaths` covering the workspace root — Metro needs to know to watch and resolve files outside the app's own directory to see `packages/ui-tokens`. This lets `apps/mobile` consume `@ditsala/ui-tokens` via a normal `workspace:*` dependency instead of a hand-maintained relative path.

**The KYC screens (`app/onboarding/kyc-document.tsx`, `kyc-liveness.tsx`) request real backend jobs/tokens but have no native capture UI to launch them into.** The Smile ID native SDK integration is not built — it needs a config plugin and native iOS/Android build tooling this environment doesn't have (no Xcode, no Android Studio, no EAS build access). Building it without the ability to compile or run it against a real device would produce unverifiable native code, which is worse than being explicit about the gap. The screens are written so a real Smile ID SDK call drops in exactly where the comment says it should — `onboardingApi.startKycDocument`/`startKycLiveness` return the real token/job_id today, unused by anything, which the SDK integration will consume.

## Consequences

- Nothing in this ADR has been runtime-verified (no simulator, no device, no EAS build available here) beyond `tsc --noEmit`, ESLint, and Jest component tests passing. The pnpm+Metro monorepo wiring should be smoke-tested with an actual `expo start`/EAS dev build on a machine that has one, before this is trusted for real development.
- Until the Smile ID SDK lands, a real user cannot progress past `pending_kyc_document` through the app UI alone — the "Check status" button on those two screens exists so a webhook result delivered by any other means (e.g., a manually-triggered test job during integration testing) is picked up, but there's no in-app capture path yet. This is a feature-completeness gap, not a security gap (no security control is weakened or bypassed) — tracked here and in `CLAUDE.md`, not `docs/SECURITY_GAPS.md`.
