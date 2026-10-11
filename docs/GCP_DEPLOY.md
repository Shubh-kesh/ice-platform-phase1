# GCP Deploy — UAT (ice-spark-build)

**Scope:** UAT-only deploy of the ICE platform on GCP.
**Project:** `ice-spark-build` · **Region:** `asia-south1` · **IaC:** Terraform
**Demo data:** Kashi Kunj pack · **Domain:** none yet (Cloud Run default URLs)

Source of truth is the code. Related: `docs/PHASE4_IMPLEMENTATION_PLAN.md`,
`docs/P4.2_INFRASTRUCTURE_DECISION_REPORT.md`, `docs/demo/KASHI_KUNJ_DEMO_RUNBOOK.md`.

---

## 1. Architecture (UAT)

```
GitHub (claude-development → main)
  ├─ ci.yml  (P4.1, exists): ruff/mypy/pytest + tsc/vite build + oxlint
  └─ cd.yml  (this plan): WIF → build/push → migrate → deploy → smoke
         │
Artifact Registry (asia-south1): ice-backend, ice-frontend
         │
Cloud Run (uat, min-instances 0):
  ├─ ice-backend-uat  → gunicorn x1 uvicorn, $PORT (injected), /health + /ready
  └─ ice-frontend-uat → nginx static (VITE_API_URL baked at build)
Cloud SQL PG16 db-f1-micro, 10 GB (public IP for UAT — no connector cost;
  password + TLS guarded, authorized-network scoped — see module header)
Secret Manager: uat/SECRET_KEY, uat/POSTGRES_PASSWORD (empty GOOGLE_* = disabled)
```

Free-tier design: NO VPC connector (~$25/mo), NO Memorystore (~$35+/mo, and the
app has zero Redis references), NO private-services networking (this is what
required the Service Networking API). Cloud Run's generous free quota covers
demo traffic; Artifact Registry stays under its 0.5 GB free grant. The only
paid line is Cloud SQL db-f1-micro + 10 GB disk (~$10–15/mo in asia-south1,
often covered by trial credit) — there is no free managed Postgres.

Google Sign-In: **OFF** in UAT initially (password logins for the demo).
AI Copilot: **OFF** (`ICE_AI_ENABLED=false`). No custom domain yet.

---

## 2. One-time bootstrap (operator, ~30 min)

```bash
export GCP_PROJECT=ice-spark-build GCP_REGION=asia-south1 UAT_TF_STATE_BUCKET=ice-spark-build-tfstate
gcloud auth login
gcloud config set project $GCP_PROJECT
gcloud services enable run.googleapis.com sqladmin.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  cloudbuild.googleapis.com iamcredentials.googleapis.com
# NOTE: servicenetworking, vpcaccess and redis APIs are intentionally NOT
# enabled — the UAT module uses public-IP Cloud SQL and no Memorystore.

# Terraform state bucket (versioned, single source of truth for state)
gcloud storage buckets create gs://$UAT_TF_STATE_BUCKET --location=$GCP_REGION \
  --uniform-bucket-level-access
gcloud storage buckets update gs://$UAT_TF_STATE_BUCKET --versioning

# GitHub Actions → GCP auth (Workload Identity Federation, no long-lived keys)
export GH_REPO="YOUR_GH_ORG/ice-platform-phase1"   # e.g. anomalyco/ice-platform-phase1
gcloud iam workload-identity-pools create gh-pool --location=global \
  --display-name="GitHub Actions pool"
export WIF_POOL=$(gcloud iam workload-identity-pools describe gh-pool \
  --location=global --format='value(name)')
gcloud iam workload-identity-pools providers create-oidc gh-provider \
  --location=global --workload-identity-pool=gh-pool \
  --display-name="GitHub OIDC" --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-condition="assertion.repository=='$GH_REPO'"
gcloud iam service-accounts create uat-deployer --display-name="UAT deployer (CI)"
export DEPLOYER_SA=$(gcloud iam service-accounts describe uat-deployer@$GCP_PROJECT.iam.gserviceaccount.com --format='value(email)')
gcloud iam service-accounts add-iam-policy-binding $DEPLOYER_SA --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/$WIF_POOL/attribute.repository/$GH_REPO"
# Least-privilege deploy roles (narrow further per your policy):
for R in roles/run.admin roles/artifactregistry.writer roles/cloudsql.admin \
         roles/secretmanager.admin \
         roles/iam.serviceAccountUser roles/storage.admin; do
  gcloud projects add-iam-policy-binding $GCP_PROJECT \
    --member="serviceAccount:$DEPLOYER_SA" --role="$R" --condition=None >/dev/null
done
echo "WIF provider: projects/$(gcloud config get-value project --format='value(core.project)' --quiet)/locations/global/workloadIdentityPools/gh-pool/providers/gh-provider"
# → paste these two values as GitHub Actions variables/secrets:
#   vars/GCP_PROJECT=ice-spark-build  vars/GCP_REGION=asia-south1
#   vars/GCP_WIF_PROVIDER=<provider resource name>  vars/GCP_DEPLOYER_SA=<sa email>
```

---

## 3. Secrets (Secret Manager, per-env `uat/`)

```bash
export GCP_PROJECT=ice-spark-build
openssl rand -hex 48 | tr -d '\n' > /tmp/secret_key   # 96-hex-char SECRET_KEY

gcloud secrets create uat-SECRET_KEY --replication-policy=automatic --data-file=/tmp/secret_key; shred -u /tmp/secret_key
gcloud secrets create uat-POSTGRES_PASSWORD --replication-policy=automatic --data-file=<(openssl rand -base64 24 | tr -d '\n')
# Non-secret config stays in Terraform tfvars (see infra/terraform/environments/uat/uat.tfvars):
#   POSTGRES_USER=ice_app, POSTGRES_DB=ice_uat (wired by the module; no REDIS_* —
#   the app has zero Redis references, Memorystore arrives with P4.4 if ever needed)
# Google OAuth stays EMPTY in UAT (Google surfaces disabled until a domain exists):
#   GOOGLE_CLIENT_ID="", GOOGLE_CLIENT_SECRET=""
# Runtime mounts secrets as env vars on the Cloud Run service (see terraform module).
# Rotation: create new version → disable old → redeploy revision (runbook §8).
```

`git grep` must never show a production secret — CI fails on `SECRET_KEY`/password hits outside `.env.example`/docs placeholders.

---

## 4. Provision UAT (`infra/terraform/`)

```bash
cd infra/terraform/environments/uat
terraform init -backend-config="bucket=ice-spark-build-tfstate"
terraform plan -var-file=uat.tfvars -out=uat.plan
terraform apply uat.plan     # creates VPC+connector, Cloud SQL, Memorystore, AR, Cloud Run (placeholder image), secrets bindings
```

First apply uses a placeholder image (`gcr.io/cloudrun/hello`); real builds are
then recorded as pinned tags in `uat.tfvars` so later applies never revert a
deploy. `cd.yml` replaces the tags on every push to `main`. Cloud SQL PITR +
automated backups are enabled by the module **before** any data lands.
The CD smoke probes the SPA at `/` (not `/healthz`): edge caches were observed
holding a stale 404 on the probe path across revisions during UAT boot.

---

## 5. CD — push to deploy (`../.github/workflows/cd.yml`)

Trigger: push to `main` (or manual `workflow_dispatch`). Flow per run:

1. WIF auth → GCP (`ice-spark-build`, `asia-south1`).
2. Build + push: `ice-backend:<sha>` (existing `backend/Dockerfile`, non-root,
   gunicorn x2) and `ice-frontend:<sha>` (`frontend/Dockerfile`, nginx SPA
   fallback, `VITE_API_URL=<backend-run-url>/api/v1` baked at build).
3. Pre-deploy backup: on-demand Cloud SQL backup (tagged `pre-<sha>`).
4. Migrate: `alembic upgrade head` from a Cloud Run job / Cloud Shell with the
   Serverless VPC connector (never at container boot in UAT/prod — entrypoint
   migration stays **dev-only**; UAT entrypoint skips it via `ICE_RUN_MIGRATIONS=false`).
5. Deploy both revisions (traffic 100% on success, previous revision kept).
6. Smoke: `/health` + `/ready` → password login → `GET /projects` → create/read
   one site-log + one stock movement on a canary project → rollback on failure.

Rollback: `gcloud run services update-traffic <svc> --to-revisions <prev>=100`
(+ PITR restore only if data itself is corrupt — see §8).

---

## 6. Seed the UAT demo (Kashi Kunj pack)

```bash
# From any machine with VPC access (Cloud Shell with connector, or CI job):
export API=https://<ice-backend-uat-url>/api/v1 ICE_KASHI_DEMO=true
export ICE_KASHI_DEMO_PASSWORD='<DemoPass123-style, 8+upper+digit>'
cd backend
python -m app.demo.kashi_kunj seed    # builds PRJ-2026-0001 + 4 users + POs/invoices/notifications
python -m app.demo.kashi_kunj verify  # expect "DEMO READY" (42 checks)
```

Hand the client: UAT frontend URL + the 4 role logins + `docs/USER_GUIDE.md`
+ `docs/demo/KASHI_KUNJ_DEMO_RUNBOOK.md`. Safety: the pack refuses
`ENVIRONMENT=production` and requires `ICE_KASHI_DEMO=true`.

---

## 7. Local dev (unchanged)

```bash
cp backend/.env.example backend/.env   # fill SECRET_KEY + POSTGRES_* (dev only)
docker compose up --build               # postgres + redis + backend :8000 (migrations + optional seed on boot)
cd frontend && npm ci && npm run dev    # :5173, VITE_API_URL=http://localhost:8000/api/v1
cd backend && pytest -q                 # needs postgres up
```

---

## 8. Operations cheat-sheet

| Task | Command |
|---|---|
| Logs | `gcloud run services logs read ice-backend-uat --region=asia-south1` |
| Rollback app | `gcloud run services update-traffic ice-backend-uat --to-revisions <PREV>=100 --region=asia-south1` |
| On-demand DB backup | `gcloud sql backups create --instance=ice-uat-db` |
| Restore (new instance, drilled in staging first) | `gcloud sql backups restore <ID> --restore-instance=ice-uat-restore --backup-instance=ice-uat-db` |
| Rotate SECRET_KEY | new version → `gcloud run services update ice-backend-uat --update-secrets=SECRET_KEY=uat-SECRET_KEY:latest` |
| Custom domain (later) | map domain → update `BACKEND_CORS_ORIGINS` + `GOOGLE_REDIRECT_URI=https://<domain>/google/callback` in tfvars → apply → redeploy frontend |

Cost order (asia-south1, UAT idle): Cloud Run ~$0 at demo traffic (free quota);
Artifact Registry + logs negligible. Single paid line: Cloud SQL db-f1-micro +
10 GB PD (~$10–15/mo — no free tier for managed Postgres; trial credit usually
covers it). Everything else in this module is free-tier eligible.

## 9. What this deploy deliberately defers

Custom domain + TLS cert mapping, Google OAuth prod client, Sentry/Cloud Logging
JSON + alerts, Redis-backed distributed rate limiter (P4.4), last-admin guard +
`pip-audit`/`npm audit` gates (P4.5), production env + prod Compose variant,
load test. Each is a separate milestone on top of this UAT rail.
