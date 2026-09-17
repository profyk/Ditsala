# DITSALA CI/CD

Pipeline overview, required secrets, and one-time setup for every deploy target.

## 1. Pipeline shape

```
push/PR ──► CI (.github/workflows/ci.yml)
              lint + typecheck + test, backend and web workspace
              (Postgres/Redis as GitHub-hosted service containers)

backend (Railway) ─── native GitHub integration, deploys on every push to main
apps/admin (Vercel) ── native GitHub integration, deploys on every push to main
apps/mobile web (Vercel) ── native GitHub integration, deploys on every push to main
apps/meet (Vercel) ─── native GitHub integration, deploys on every push to main

mobile-eas-build.yml   ─── manual dispatch (platform + profile)
mobile-eas-submit.yml  ─── manual dispatch (separate from build, on purpose)
backend-deploy-aws.yml ─── manual dispatch (replica/backup path — see §4)
```

Railway and Vercel each deploy `backend`, `apps/admin`, `apps/mobile` (web export), and `apps/meet` directly via their own native GitHub integration — connected once in each platform's dashboard, not through a GitHub Actions workflow in this repo. This repo previously had custom `backend-deploy-railway.yml`/`admin-deploy.yml`/`mobile-vercel-deploy.yml` workflows duplicating that same push-to-deploy behavior with their own secrets; they were removed since a native integration already does the same job — running both just double-deploys on every push, the same reasoning `apps/meet` was built under from the start (see §6a). If any of these targets ever needs CI-gated deploys (waiting on `ci.yml` to pass before deploying, or a manual-approval gate), disable that target's native auto-deploy in its platform dashboard first, then add a workflow triggered on `workflow_run` of `CI` completing successfully — don't run both at once.

`backend-deploy-aws.yml` and the two EAS mobile workflows remain `workflow_dispatch`-only (manually triggered from the Actions tab or `gh workflow run`), since they're either backup infrastructure or actions with real-world consequences (an EAS submit can trigger app store review) that shouldn't fire automatically.

## 2. Database migrations

There is no separate "run migrations" workflow — `backend/entrypoint.sh` runs `alembic upgrade head` before starting `uvicorn` on every container boot, on both Railway and AWS. This means a deploy that includes a new migration applies it automatically, in order, before the new code starts serving traffic. Point `DATABASE_URL` (see §3) at your Supabase project's **Session Pooler** connection string (not the direct-connection hostname — see `CLAUDE.md`'s note on why: it's IPv6-only and often unreachable).

## 3. Backend — Railway (primary)

Deploys automatically on every push to `main`, via Railway's native GitHub integration (Project Settings → connected repo). Set environment variables **on that specific service** in the Railway dashboard: `DATABASE_URL` (Supabase pooler URL), `JWT_SECRET`, `NATIONAL_ID_PEPPER`, plus every provider credential `backend/.env.example` lists (Smile ID, Twilio, Resend, S3). No GitHub secret is needed for this path.

## 4. Backend — AWS ECS (replica/backup)

This is the backup/replica path behind an Application Load Balancer, deployed manually via `.github/workflows/backend-deploy-aws.yml` — promote to it deliberately, rather than dual-deploying on every push.

**One-time setup** (`af-south-1` — AWS's Cape Town region, closest to this product's market):
1. **ECR**: create a repository named `ditsala-backend`.
2. **Secrets Manager**: store `DATABASE_URL`, `JWT_SECRET`, `NATIONAL_ID_PEPPER` as secrets under the `ditsala/` prefix (matching `infra/aws/ecs-task-definition.json`'s `secrets` block) — never as plain task-definition environment variables.
3. **IAM**: create `ditsala-ecs-execution-role` (needs `AmazonECSTaskExecutionRolePolicy` + `secretsmanager:GetSecretValue` on the secrets above) and `ditsala-ecs-task-role` (the app's own runtime permissions — none needed yet beyond the defaults). Replace the `<ACCOUNT_ID>`/`<REGION>` placeholders in `infra/aws/ecs-task-definition.json` with real values.
4. **Networking**: a VPC with at least two subnets, an Application Load Balancer with an HTTPS listener and a target group health-checking `/api/v1/health`, and an ECS cluster (`ditsala-cluster`) running the Fargate launch type.
5. **ECS service**: create `ditsala-backend-service` in that cluster, attached to the ALB target group, initially from the task definition template (register it once manually with real values filled in — the workflow renders and re-registers new revisions of it from then on).
6. **GitHub OIDC**: rather than long-lived AWS access keys, create an IAM OIDC identity provider trusting `token.actions.githubusercontent.com`, and a role (trust policy scoped to this repo) with permission to push to ECR and update the ECS service. Store its ARN as the `AWS_DEPLOY_ROLE_ARN` secret — the workflow uses `aws-actions/configure-aws-credentials`'s `role-to-assume`, so no static AWS keys ever live in GitHub.

**Deploy**: `gh workflow run backend-deploy-aws.yml` (or trigger from the Actions tab), optionally passing an `image_tag` input.

## 5. Admin panel — Vercel

Deploys automatically on every push to `main`, via Vercel's native GitHub integration (a Vercel project pointed at `apps/admin` as its root directory). Set the admin app's environment variables directly in the Vercel dashboard (`NEXT_PUBLIC_API_URL` pointing at the backend's public URL, plus anything else `apps/admin/.env.example` lists). No GitHub secret is needed for this path.

## 6. Mobile — EAS (build + submit + web hosting)

`apps/mobile/eas.json` defines three build profiles (`development`, `preview`, `production`) — see that file for the API base URL each targets. The project is already linked (`@profy/ditsala`, ID in `app.json`'s `extra.eas.projectId`).

**One-time setup:**
1. ~~Create an Expo account/organization, run `eas init`~~ — already done; project is `@profy/ditsala`.
2. Generate an Expo access token (expo.dev → Account Settings → Access Tokens) and add it as the `EXPO_TOKEN` secret — needed by both mobile build/submit workflows below.
3. **iOS submission**: add `EXPO_APPLE_ID` and `EXPO_APPLE_APP_SPECIFIC_PASSWORD` (an [app-specific password](https://support.apple.com/en-us/102654), not your real Apple ID password) as secrets. EAS also needs your Apple Team ID and an App Store Connect app already created — `eas submit` prompts for these interactively the first time; run it once locally to cache the answers, or supply them via `eas.json`'s `submit.production.ios` block once you know the exact values.
4. **Android submission**: create a Google Play service account with release-manager permissions, download its JSON key, base64-encode it (`base64 -w0 service-account.json`), and store the result as the `GOOGLE_PLAY_SERVICE_ACCOUNT_KEY_B64` secret — the submit workflow decodes it to a file at runtime and deletes it afterward.

**Web hosting — Vercel, not EAS Hosting**: the same Expo Router app exports to a real static web build (`expo export --platform web`, verified locally — 924 modules bundled, Expo's web platform resolution swaps out native-only deps like `react-native-webrtc` rather than failing). Deploys automatically on every push to `main`, via Vercel's native GitHub integration (a **separate Vercel project from `apps/admin`**, root directory `apps/mobile`, using `apps/mobile/vercel.json`'s `outputDirectory: "dist"` and its `buildCommand` running the export). No GitHub secret is needed for this path.

(An earlier pass deployed this same web export to EAS Hosting at `ditsala.expo.app` — that path is removed in favor of Vercel.)

**Build**: `gh workflow run mobile-eas-build.yml -f platform=all -f profile=preview` (or from the Actions tab).

**Submit**: `gh workflow run mobile-eas-submit.yml -f platform=ios` — deliberately a separate, explicit action from building.

## 6a. Ditsala Meet — Vercel

`apps/meet` (Next.js App Router) is live at **https://ditsala-meet.vercel.app**, connected via Vercel's native GitHub integration — the same pattern §3/§5/§6 now all use, not a special case anymore. `apps/meet`'s environment variables (`NEXT_PUBLIC_MEET_API_BASE_URL` pointing at the backend's public URL) are set directly in the Vercel dashboard. `apps/mobile`'s `EXPO_PUBLIC_MEET_WEB_BASE_URL` (`.env`/`.env.example`) points at `https://ditsala-meet.vercel.app` — update it if the Meet project ever moves to a custom domain.

## 7. Secrets reference

| Secret | Used by | Purpose |
|---|---|---|
| `AWS_DEPLOY_ROLE_ARN` | backend-deploy-aws | OIDC role assumed for ECR push + ECS deploy |
| `EXPO_TOKEN` | mobile-eas-build, mobile-eas-submit | EAS CLI auth |
| `EXPO_APPLE_ID`, `EXPO_APPLE_APP_SPECIFIC_PASSWORD` | mobile-eas-submit | App Store Connect submission |
| `GOOGLE_PLAY_SERVICE_ACCOUNT_KEY_B64` | mobile-eas-submit | Google Play submission |

Backend (Railway), admin panel (Vercel), mobile web (Vercel), and Meet (Vercel) need no GitHub secrets at all — each platform holds its own deploy credentials and environment variables, set once in that platform's dashboard.

## 8. What CI itself already covers

`ci.yml` runs on every push/PR: backend lint (ruff) + type-check (mypy) + `alembic upgrade head` + pytest, all against GitHub-hosted Postgres/Redis containers — and the web workspace's lint/typecheck/test via Turborepo. It runs independently of the native deploy integrations above — a broken build/lint/test doesn't block Railway/Vercel from deploying, since they trigger on the push itself rather than on `ci.yml`'s result. Keep an eye on both: a red `ci.yml` run means main has a real problem even though the app it deployed still looks "live."
