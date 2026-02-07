#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-}"
REGION="${REGION:-us-central1}"
SERVICE_NAME="${SERVICE_NAME:-gemini-workshop-gateway}"
TOKEN_SECRET="${TOKEN_SECRET:-}"
MODEL_ID="${MODEL_ID:-gemini-2.0-flash-001}"
TOKEN_TTL_MIN="${TOKEN_TTL_MIN:-60}"
DEFAULT_LIMIT="${DEFAULT_LIMIT:-15000}"
DEFAULT_CONCURRENCY="${DEFAULT_CONCURRENCY:-1}"

if [[ -z "${PROJECT_ID}" || -z "${TOKEN_SECRET}" ]]; then
  echo "Usage: PROJECT_ID=your-project TOKEN_SECRET=random_string REGION=us-central1 scripts/deploy.sh"
  exit 1
fi

gcloud config set project "${PROJECT_ID}"

IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/cloud-run-source-deploy/${SERVICE_NAME}"

echo "Building container with Dockerfile..."
gcloud builds submit --tag "${IMAGE}" .

echo "Deploying to Cloud Run..."
gcloud run deploy "${SERVICE_NAME}" \
  --image "${IMAGE}" \
  --region "${REGION}" \
  --allow-unauthenticated \
  --set-env-vars "APP_PROJECT_ID=${PROJECT_ID},APP_LOCATION=${REGION},APP_MODEL_ID=${MODEL_ID},APP_TOKEN_SECRET=${TOKEN_SECRET},APP_TOKEN_TTL_MINUTES=${TOKEN_TTL_MIN},APP_DEFAULT_REQUEST_LIMIT=${DEFAULT_LIMIT},APP_DEFAULT_CONCURRENCY_CAP=${DEFAULT_CONCURRENCY}"
