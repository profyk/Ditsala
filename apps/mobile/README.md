# @ditsala/mobile

Expo Router + NativeWind, per `docs/DITSALA_MASTER_SPEC.md`. Phase 2's onboarding flow is built here: `app/index.tsx` (welcome) → `app/onboarding/{signup,verify-email,verify-phone,kyc-document,kyc-liveness,next-of-kin,set-code,complete}.tsx`, wired to the real backend (`lib/api.ts`) with session state held in `lib/onboarding-context.tsx`.

## Known gap

The KYC screens request real backend jobs/tokens but have no native capture UI to launch them into — the Smile ID mobile SDK needs a config plugin and native iOS/Android build tooling not available in the environment this was built in. See `docs/adr/0003-mobile-pnpm-monorepo-and-kyc-sdk-gap.md`.

## Local dev

```
pnpm install          # from the repo root
cd apps/mobile
npx expo start        # or `npm run ios` / `npm run android` once a dev build exists
```

EAS development builds are the target per the locked decisions — Expo Go is not supported (Smile ID's native SDK, once integrated, won't run in it).

## Testing

```
npm run typecheck     # tsc --noEmit
npm run lint          # eslint (eslint-config-expo)
npm run test          # jest (jest-expo + React Native Testing Library)
```
