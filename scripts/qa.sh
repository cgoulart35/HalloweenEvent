#!/usr/bin/env bash
# Deterministic wrapper for the /qa skill -- drives the isolated sandbox season so the
# safety invariants are always set and can't be fat-fingered. It ALWAYS isolates via
# EVENT_ROOT=qa-halloween-event (real data is never read/written) and builds/runs as :qa
# (invisible to the deploy-watcher, which only acts on :latest), so QA can never touch
# prod data or trigger a redeploy. It does not edit api.env/app.env (the -e flags carry
# the sandbox config) -- only the optional browser-testing path in SKILL.md does that.
#
#   scripts/qa.sh build                 # (re)build the :qa api image -- run after code changes
#   scripts/qa.sh status                # safe, read-only; start here (default with no args)
#   scripts/qa.sh open --minutes 30     # seed past seasons + open a fresh one now
#   scripts/qa.sh tick                  # run reconcile once -> fire any due emails now
#   scripts/qa.sh close                 # force the window closed now (so tick sends results)
#   scripts/qa.sh restart --minutes 30  # archive current season + open a fresh one
#   scripts/qa.sh wipe                  # delete all sandbox nodes when done
#
# Env knobs:
#   QA_EMAIL=you@example.com   route ALL sandbox mail to you (EMAIL_OVERRIDE_RECIPIENT).
#                              Set this before any mail-sending subcommand (tick/restart).
#   GIFT_CARD_LABEL/CODE/YEAR  set all three (a FAKE code!) to QA the prize ON; omit for OFF.
set -euo pipefail
cd "$(dirname "$0")/.."
export IMAGE_TAG=qa

compose() { docker compose -f docker-compose-prod.yml "$@"; }
apiImage="ghcr.io/cgoulart35/halloweenevent-api:qa"

if [ "${1:-}" = "build" ]; then
  compose build halloween-api-prod
  exit 0
fi

# Auto-build once if the :qa image is missing, so a fresh session just works (a missing
# local :qa would otherwise make `compose run` try to pull it from GHCR, where it doesn't
# exist). Rebuild explicitly with `scripts/qa.sh build` after changing code.
if ! docker image inspect "$apiImage" >/dev/null 2>&1; then
  compose build halloween-api-prod
fi

# Default to the safe, read-only subcommand when none is given.
if [ "$#" -eq 0 ]; then
  set -- status
fi

compose run --rm --no-deps \
  -e EVENT_ROOT=qa-halloween-event \
  -e EMAIL_OVERRIDE_RECIPIENT="${QA_EMAIL:-}" \
  -e GIFT_CARD_LABEL="${GIFT_CARD_LABEL:-}" \
  -e GIFT_CARD_CODE="${GIFT_CARD_CODE:-}" \
  -e GIFT_CARD_YEAR="${GIFT_CARD_YEAR:-}" \
  --entrypoint sh halloween-api-prod \
  -c "python scripts/qa_lifecycle.py $*"
