#!/bin/sh
# Poll GHCR for new prod images and redeploy when one appears.
# Started at boot from /etc/rc.local (see scripts/start.sh). Detection here; mutation in deploy.sh.
set -u
cd "$(dirname "$0")/.." || exit 1
COMPOSE="docker compose -f docker-compose-prod.yml"
INTERVAL="${DEPLOY_POLL_INTERVAL:-120}"

log() { echo "$(date '+%F %T') deploy-watcher: $*"; }
# Local image IDs for every image referenced by the prod compose file (single source of truth).
ids() { for i in $($COMPOSE config --images); do docker image inspect -f '{{.Id}}' "$i" 2>/dev/null; done; }

log "started (interval=${INTERVAL}s)"
while true; do
  before="$(ids)"
  $COMPOSE pull --quiet 2>/dev/null       # registry poll: downloads only if a :latest tag moved
  after="$(ids)"
  if [ "$before" != "$after" ]; then
    log "new image detected — deploying"
    if sh scripts/deploy.sh; then
      log "deploy complete"
      # The deploy did `git reset --hard origin/master`, which may have rewritten THIS script
      # (and deploy.sh). Re-exec so we keep polling with the latest version, not a half-read file.
      exec sh "$0"
    else
      log "deploy FAILED — retrying next interval"
    fi
  fi
  sleep "$INTERVAL"
done
