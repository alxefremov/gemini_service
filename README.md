# Gemini Workshop Gateway

Proxy service for workshops: students call the Gemini API through your project, with per-user quotas. Tokens are optional; a student can just pass their email to `/chat`.

## Architecture
- FastAPI on Cloud Run, running under the project’s service account.
- Firestore collection `users/{email}` stores `request_limit`, `requests_used`, `concurrency_cap`, `active_streams`, `alias`, `blocked`.
- JWT (HS256) from `/token` contains email + limits, default TTL 60 minutes.
- `/chat` debits quota, checks active streams, calls Gemini (`APP_MODEL_ID`), and streams text.

## Requirements
- Google Cloud project with billing enabled and Gemini API allowed in the chosen region (`us-central1` / `europe-west1` etc.).
- Project ID (top bar in GCP console).
- Google Cloud CLI (`gcloud`) installed and authenticated: `gcloud init`.
- Python 3.11+ locally (only for helper commands); scripts handle the rest.

### Values you need
- `PROJECT_ID` — e.g. `my-workshop-123`.
- `REGION` — pick near users (e.g. `europe-west4` for Berlin) or `us-central1` for max Gemini quotas.
- `TOKEN_SECRET` — random string (see step 7).

## Full CLI setup (from scratch)
Copy/paste blocks and replace `<...>` with your values.

**0. Install gcloud (macOS / Linux)**
```bash
brew install google-cloud-sdk           # macOS
# Debian/Ubuntu: sudo apt-get install google-cloud-sdk
gcloud version
```

**1. Login and pick account**
```bash
gcloud init          # auth and default account
```

**2. Create a new project**
```bash
PROJECT_ID=my-gemini-ws-$(date +%y%m%d)-$RANDOM
gcloud projects create "$PROJECT_ID" --name="Gemini Workshop" --set-as-default
```

**2.1 Enable base services for billing**
```bash
gcloud services enable serviceusage.googleapis.com cloudbilling.googleapis.com
```

**3. Link billing**
- Find billing account ID (`XXXXXX-XXXXXX-XXXXXX`):
```bash
gcloud beta billing accounts list
```
- Link:
```bash
BILLING_ACCOUNT=<your_billing_id>
gcloud beta billing projects link "$PROJECT_ID" --billing-account="$BILLING_ACCOUNT"
```

**4. Choose region**
```bash
REGION=europe-west4   # or us-central1, europe-west3
```

**5. Prepare project folder**
- If code is already local: `cd /path/to/gemini_service`
- Otherwise: `git clone <repo_url> gemini_service && cd gemini_service`

**6. Enable APIs and create Firestore**
```bash
chmod +x scripts/setup.sh scripts/deploy.sh
PROJECT_ID="$PROJECT_ID" REGION="$REGION" bash scripts/setup.sh
```

**7. Generate token secret**
```bash
export TOKEN_SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
```

**7.1 If your org enforces an `environment` tag**
- Easiest: ask an admin for a ready `tagValues/XXXX` and bind it:
```bash
gcloud resource-manager tags bindings create \
  --tag-value="tagValues/XXXX" \
  --parent="//cloudresourcemanager.googleapis.com/projects/$PROJECT_ID"
```
- If you can read org tags:
```bash
ORG_ID=<your_org_id>  # gcloud organizations list
gcloud resource-manager tags keys list --parent=organizations/$ORG_ID
gcloud resource-manager tags values list --parent=tagKeys/ID
```
- If you’re an org admin and need to create:
```bash
gcloud components update
ORG_ID=<your_org_id>
gcloud resource-manager tags keys create environment --parent=organizations/$ORG_ID
ENV_KEY=$(gcloud resource-manager tags keys list --parent=organizations/$ORG_ID --filter="shortName=environment" --format="value(name)")
gcloud resource-manager tags values create development --parent="$ENV_KEY"
ENV_VALUE=$(gcloud resource-manager tags values list --parent="$ENV_KEY" --filter="shortName=development" --format="value(name)")
gcloud resource-manager tags bindings create \
  --tag-value="$ENV_VALUE" \
  --parent="//cloudresourcemanager.googleapis.com/projects/$PROJECT_ID"
```
- If you hit PERMISSION_DENIED: switch to an admin account (`gcloud auth list`, `gcloud config set account <admin>`), ensure roles `resourcemanager.tagViewer/tagAdmin/tagUser`, or ask an org owner to bind the tag.

**8. Deploy to Cloud Run**
```bash
PROJECT_ID="$PROJECT_ID" \
REGION="$REGION" \
TOKEN_SECRET="$TOKEN_SECRET" \
scripts/deploy.sh
```
Take note of the `Service URL` from output.

Note: first deploy will create an Artifact Registry repo `cloud-run-source-deploy` in the region — answer `Y`.
The script builds via Dockerfile (Cloud Build) and deploys the built image to Cloud Run.

**9. Quick health check**
```bash
curl https://<SERVICE_URL>/health
```
Expected: `{"status":"ok"}`.

## Quickstart (short version)
Run from repo root:
1) `gcloud init && gcloud config set project <PROJECT_ID>`
2) `PROJECT_ID=<PROJECT_ID> REGION=<REGION> scripts/setup.sh`
3) `export TOKEN_SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(32))")`
4) `PROJECT_ID=<PROJECT_ID> REGION=<REGION> TOKEN_SECRET=$TOKEN_SECRET scripts/deploy.sh`
5) `curl https://<SERVICE_URL>/health`

## Student access
- Students can call `/chat` with just their email in the body (no token needed), plus optional model params.
- Token flow still available via `/token`.

Example `/chat` without token:
```bash
curl -N -X POST https://<SERVICE_URL>/chat \
  -H "Content-Type: application/json" \
  -d '{"email":"student@uni.de","messages":[{"role":"user","content":"Hello Gemini!"}],"model":"gemini-2.0-flash-001","stream":true,"temperature":0.3,"top_p":0.95,"top_k":40}'
```

## Admin operations (require admin email or admin token)
- Register users:
```bash
curl -X POST https://<SERVICE_URL>/register \
  -H "Content-Type: application/json" \
  -H "X-Admin-Email: btc.esmt.workshop@gmail.com" \
  -d '{"users":[{"email":"alice@uni.de","alias":"Alice","request_limit":15000,"concurrency_cap":1},{"email":"bob@uni.de"}]}'
```
- Get user: `GET /user/{email}`
- Delete user: `DELETE /user/{email}`

Full API reference: `docs/API.md`.

## Quotas
- `APP_DEFAULT_REQUEST_LIMIT` — requests per new user (default 15000).
- `APP_DEFAULT_CONCURRENCY_CAP` — parallel streams per user (pick `floor(project_rpm / (participants + safety_margin))`).
- You can override per user in `/register`.

## Local run
```bash
export GOOGLE_CLOUD_PROJECT=<project>
export APP_TOKEN_SECRET=local-dev-secret
uvicorn app.main:app --reload --port 8000
```
Requires ADC: `gcloud auth application-default login`.

## Redeploy
- Change code → run `scripts/deploy.sh` again with the same vars.

## Blocking / resetting quotas
- Block user: set `blocked=true` in Firestore `users/<email>`.
- Reset usage: set `requests_used=0` manually or via a scheduled job (not included).

## Important env vars
- `APP_PROJECT_ID`, `APP_LOCATION`, `APP_MODEL_ID`, `APP_TOKEN_SECRET`, `APP_TOKEN_TTL_MINUTES`, `APP_DEFAULT_REQUEST_LIMIT`, `APP_DEFAULT_CONCURRENCY_CAP`, `APP_ALLOW_REGISTRATION_ENDPOINT`, `APP_ADMIN_EMAILS`.
