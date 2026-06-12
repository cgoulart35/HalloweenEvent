#!/bin/sh
# Deploy current prod images from GHCR. Matches origin/master; gitignored secrets are untouched.
# Run on-demand (Dev/QA redeploy) or by scripts/deploy-watcher.sh when a new image is published.
set -u
cd "$(dirname "$0")/.." || exit 1
COMPOSE="docker compose -f docker-compose-prod.yml"

git fetch origin master --quiet
git checkout -f master --quiet            # switch to master even if a dev left us on another branch (-f discards tracked dev edits)
git reset --hard origin/master --quiet    # match remote exactly; gitignored secrets (api.env/app.env/serviceAccountKey.json) untouched

$COMPOSE pull
$COMPOSE up -d                            # recreates only the containers whose image changed
docker image prune -f
