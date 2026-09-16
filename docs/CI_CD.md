# DITSALA CI/CD

Pipeline overview, required secrets, and one-time setup for every deploy target. This is a runbook for provisioning real infrastructure — no staging/production environment has actually been stood up from this repository yet (same caveat `DOCUMENTATION.md` makes for the broader deployment runbook). Every workflow below is real, valid GitHub Actions YAML (every `.yml`/`.json` file this doc references has been parsed and confirmed syntactically valid); what's missing is the infrastructure and credentials on the other end, which only you can provision (this environment has no cloud account access).

**Not verified**: `backend/Dockerfile` has not actually been built — Docker isn't installed in this environment (the same constraint `CLAUDE.md`'s "Local dev" section already documents for `infra/docker-compose.yml`). It follows `uv`'s documented multi-stage Docker pattern and was checked line by line against this project's real `pyproject.toml`/`uv.lock`, but "the syntax is correct and follows the documented pattern" is not the same claim as "this image has been built and run" — build it once (`docker build -t ditsala-backend backend/`) and smoke-test it locally before trusting it in a real deploy.

## 1. Pipeline shape

```
push/PR ──► CI (.github/workflows/ci.yml)
              │  lint + typecheck + test, backend and web workspace
              │  (Postgres/Redis as GitHub-hosted service containers)
              │
              ▼ (on success, main only)
   ┌──────────┴───────────┬─────────────────────┐
   ▼                      ▼                      ▼
backend-deploy-railway  admin-deploy          (backend-deploy-aws:
  (automatic)             (automatic,           manual only — see §4)
                           Vercel)

mobile-vercel-deploy.yml (automatic, push to apps/mobile/**)
mobile-eas-build.yml   ─── manual dispatch (platform + profile)
mobile-eas-submit.yml  ─── manual dispatch (separate from build, on purpose)
```

`backend-deploy-railway.yml`, `admin-deploy.yml`, and `mobile-vercel-deploy.yml` all trigger automatically (the first two on `workflow_run` of `CI` completing successfully on `main`; the mobile one on a plain `push` touching `apps/mobile/**`, since it has no backend-specific CI job of its own to gate on) — a broken build/lint/test never reaches the two `workflow_run`-gated deploy steps. `backend-deploy-aws.yml` and the two EAS mobile workflows are `workflow_dispatch`-only (manually triggered from the Actions tab or `gh workflow run`), since they're either backup infrastructure, or actions with real-world consequences (an EAS submit can trigger app store review) that shouldn't fire automatically.

## 2. Database migrations

There is no separate "run migrations" workflow — `backend/entrypoint.sh` runs `alembic upgrade head` before starting `uvicorn` on every container boot, on both Railway and AWS. This means a deploy that includes a new migration applies it automatically, in order, before the new code starts serving traffic. Point `DATABASE_URL` (see §3) at your Supabase project's **Session Pooler** connection string (not the direct-connection hostname — see `CLAUDE.md`'s note on why: it's IPv6-only and often unreachable).

## 3. Backend — Railway (primary)

**One-time setup:**
1. Create a Railway project, add a service pointed at this repo's `backend/` directory (Railway auto-detects `railway.json` there for build/deploy config). **Don't rely on whatever name Railway auto-assigns it** — the workflow targets the service by ID (see step 4), not by name, specifically because Railway generates its own service name when you first connect a repo, and a deploy silently landing on the wrong same-project service (with none of your configured variables) is a real failure mode this project hit once already.
2. Set environment variables **on that specific service**: `DATABASE_URL` (Supabase pooler URL), `JWT_SECRET`, `NATIONAL_ID_PEPPER`, plus every provider credential `backend/.env.example` lists (Smile ID, Twilio, Resend, S3).
3. Generate a Railway API token (Project Settings → Tokens) and add it to the GitHub repo as the `RAILWAY_TOKEN` secret.
4. Find that service's ID: open it in the Railway dashboard and copy the UUID from the URL (`railway.app/project/<project-id>/service/<service-id>`), or run `railway status` from a `railway link`-ed local checkout. Add it as the `RAILWAY_SERVICE_ID` secret.
5. Create a GitHub Actions **environment** named `production` (Settings → Environments) — used by every deploy workflow below, so you can gate it with required reviewers later if you want a manual approval step before deploys.

**Deploy**: automatic, via `.github/workflows/backend-deploy-railway.yml`, after every successful `CI` run on `main`. If you ever see it deploying successfully but the app still behaves like it has no environment variables set, the first thing to check is whether `RAILWAY_SERVICE_ID` actually points at the same service you configured variables on — that mismatch is the one failure mode this setup can't validate for you.

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

**One-time setup:**
1. Create a Vercel project pointed at `apps/admin`, or run `vercel link` once locally from that directory to generate `.vercel/project.json` (don't commit it — it's gitignored).
2. Set the admin app's environment variables in the Vercel dashboard (`NEXT_PUBLIC_API_URL` pointing at the backend's public URL, plus anything else `apps/admin/.env.example` lists).
3. Create a Vercel access token (Account Settings → Tokens) and add three GitHub secrets: `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID` (the latter two come from `.vercel/project.json` after linking).

**Deploy**: automatic, via `.github/workflows/admin-deploy.yml`, after every successful `CI` run on `main`.

## 6. Mobile — EAS (build + submit + web hosting)

`apps/mobile/eas.json` defines three build profiles (`development`, `preview`, `production`) — see that file for the API base URL each targets. The project is already linked (`@profy/ditsala`, ID in `app.json`'s `extra.eas.projectId`).

**One-time setup:**
1. ~~Create an Expo account/organization, run `eas init`~~ — already done; project is `@profy/ditsala`.
2. Generate an Expo access token (expo.dev → Account Settings → Access Tokens) and add it as the `EXPO_TOKEN` secret — needed by all three mobile workflows below.
3. **iOS submission**: add `EXPO_APPLE_ID` and `EXPO_APPLE_APP_SPECIFIC_PASSWORD` (an [app-specific password](https://support.apple.com/en-us/102654), not your real Apple ID password) as secrets. EAS also needs your Apple Team ID and an App Store Connect app already created — `eas submit` prompts for these interactively the first time; run it once locally to cache the answers, or supply them via `eas.json`'s `submit.production.ios` block once you know the exact values.
4. **Android submission**: create a Google Play service account with release-manager permissions, download its JSON key, base64-encode it (`base64 -w0 service-account.json`), and store the result as the `GOOGLE_PLAY_SERVICE_ACCOUNT_KEY_B64` secret — the submit workflow decodes it to a file at runtime and deletes it afterward.

**Web hosting — Vercel, not EAS Hosting** (`mobile-vercel-deploy.yml`): the same Expo Router app exports to a real static web build (`expo export --platform web`, verified locally — 924 modules bundled, Expo's web platform resolution swaps out native-only deps like `react-native-webrtc` rather than failing) and deploys to Vercel via `apps/mobile/vercel.json` (`outputDirectory: "dist"`, `buildCommand` runs the export). This is a **separate Vercel project from `apps/admin`** — one-time setup:
1. Create a second Vercel project pointed at this repo with root directory `apps/mobile` (or `vercel link` locally from `apps/mobile`).
2. Add its project ID as the `VERCEL_MOBILE_PROJECT_ID` secret (reuses the same `VERCEL_TOKEN`/`VERCEL_ORG_ID` as the admin deploy).

Triggers automatically on every push to `main` touching `apps/mobile/**`.

(An earlier pass deployed this same web export to EAS Hosting at `ditsala.expo.app` — that path is removed in favor of Vercel.)

**Build**: `gh workflow run mobile-eas-build.yml -f platform=all -f profile=preview` (or from the Actions tab).

**Submit**: `gh workflow run mobile-eas-submit.yml -f platform=ios` — deliberately a separate, explicit action from building.

## 6a. Ditsala Meet — Vercel

`apps/meet` (Next.js App Router) is already live at **https://ditsala-meet.vercel.app**, deployed manually the first time (Vercel auto-detects a plain Next.js app, so no `apps/meet/vercel.json` was needed the way `apps/mobile`'s static export required one). `.github/workflows/meet-vercel-deploy.yml` wires up the same automatic, CI-gated deploy the admin panel gets:

**One-time setup:**
1. If `apps/meet` was connected to Vercel via its own GitHub integration (auto-deploy on push) rather than a one-off `vercel deploy`, either disable that integration or accept that both it and this workflow will deploy on every push to main — redundant, not harmful, but worth picking one.
2. Add the project's ID as the `VERCEL_MEET_PROJECT_ID` secret (reuses the same `VERCEL_TOKEN`/`VERCEL_ORG_ID` as the admin/mobile deploys) — find it in the Vercel dashboard's project settings, or via `vercel link` locally from `apps/meet`.
3. Set `apps/meet`'s environment variables in the Vercel dashboard (`NEXT_PUBLIC_MEET_API_BASE_URL` pointing at the backend's public URL).

**Deploy**: automatic, via `meet-vercel-deploy.yml`, after every successful `CI` run on `main`.

`apps/mobile`'s `EXPO_PUBLIC_MEET_WEB_BASE_URL` (`.env`/`.env.example`) already points at `https://ditsala-meet.vercel.app` — update it if the Meet project is ever moved to a custom domain.

## 7. Secrets reference

| Secret | Used by | Purpose |
|---|---|---|
| `RAILWAY_TOKEN` | backend-deploy-railway | Railway CLI auth |
| `RAILWAY_SERVICE_ID` | backend-deploy-railway | Targets the exact service by ID, not by a guessed name |
| `AWS_DEPLOY_ROLE_ARN` | backend-deploy-aws | OIDC role assumed for ECR push + ECS deploy |
| `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID` | admin-deploy | Vercel CLI auth + admin project targeting |
| `VERCEL_MOBILE_PROJECT_ID` | mobile-vercel-deploy | Same token/org, different (mobile web) Vercel project |
| `VERCEL_MEET_PROJECT_ID` | meet-vercel-deploy | Same token/org, different (Ditsala Meet) Vercel project |
| `EXPO_TOKEN` | mobile-eas-build, mobile-eas-submit | EAS CLI auth |
| `EXPO_APPLE_ID`, `EXPO_APPLE_APP_SPECIFIC_PASSWORD` | mobile-eas-submit | App Store Connect submission |
| `GOOGLE_PLAY_SERVICE_ACCOUNT_KEY_B64` | mobile-eas-submit | Google Play submission |

None of these exist in this repository or environment — every workflow above will fail at the relevant step until its secrets are added in **GitHub repo Settings → Environments → production → Secrets** (preferred, since every deploy workflow targets the `production` environment) or **Settings → Secrets and variables → Actions** for a repo-wide secret.

## 8. What CI itself already covers

`ci.yml` (unchanged by this work) runs on every push/PR: backend lint (ruff) + type-check (mypy) + `alembic upgrade head` + pytest, all against GitHub-hosted Postgres/Redis containers — and the web workspace's lint/typecheck/test via Turborepo. This is what every deploy workflow above gates on.
