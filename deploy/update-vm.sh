#!/usr/bin/env bash
# Update code on Compute Engine VM and restart FalkorDB + SAQ worker
# Usage: ./deploy/update-vm.sh
set -euo pipefail

PROJECT_ID="closeloopai"
ZONE="us-central1-a"
VM_NAME="falkordb-worker"

echo "[1/4] Packaging kgmemory source..."
tar czf /tmp/kgmemory-src.tar.gz \
  --exclude='.venv' \
  --exclude='.git' \
  --exclude='__pycache__' \
  --exclude='.env' \
  --exclude='*.pyc' \
  kgmemory pyproject.toml uv.lock manage.py gunicorn.conf.py docker-compose.worker.yml Dockerfile

echo "[2/4] Copying to VM..."
gcloud compute scp /tmp/kgmemory-src.tar.gz "${VM_NAME}:~/kgmemory-src.tar.gz" \
  --zone="${ZONE}" --project="${PROJECT_ID}"

echo "[3/4] Updating code and rebuilding on VM..."
gcloud compute ssh "${VM_NAME}" --zone="${ZONE}" --project="${PROJECT_ID}" --command='
cd ~/memory-pinchfast
tar xzf ~/kgmemory-src.tar.gz
sudo docker compose -f docker-compose.worker.yml up -d --build
'

echo "[4/4] Checking status..."
gcloud compute ssh "${VM_NAME}" --zone="${ZONE}" --project="${PROJECT_ID}" --command='
sudo docker compose -f docker-compose.worker.yml ps
'

echo ""
echo "VM updated. FalkorDB + worker restarted."
