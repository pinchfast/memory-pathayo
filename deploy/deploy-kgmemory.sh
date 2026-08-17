#!/usr/bin/env bash
# Deploy kgmemory API to Cloud Run (run from memory-pinchfast repo root)
# Usage: ./deploy/deploy-kgmemory.sh
set -euo pipefail

PROJECT_ID="closeloopai"
REGION="us-central1"
REGISTRY="us-central1-docker.pkg.dev/${PROJECT_ID}/closeloop"
ENV_FILE="${1:-deploy/env/kgmemory-api.yaml}"

echo "[1/3] Building kgmemory API image..."
docker build -t "${REGISTRY}/kgmemory:latest" .

echo "[2/3] Pushing image..."
docker push "${REGISTRY}/kgmemory:latest"

echo "[3/3] Deploying to Cloud Run..."
gcloud run deploy kgmemory-api \
  --image="${REGISTRY}/kgmemory:latest" \
  --region="${REGION}" \
  --port=8080 \
  --timeout=300 \
  --min-instances=0 \
  --max-instances=3 \
  --memory=1Gi \
  --cpu=1 \
  --allow-unauthenticated \
  --env-vars-file="${ENV_FILE}" \
  --project="${PROJECT_ID}"

KG_URL=$(gcloud run services describe kgmemory-api --region="${REGION}" --format="value(status.url)" --project="${PROJECT_ID}")
echo ""
echo "Deployed: ${KG_URL}"
echo "Health: $(curl -s --max-time 15 "${KG_URL}/v1/health/")"
