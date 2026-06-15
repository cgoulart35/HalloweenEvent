#!/usr/bin/env bash
# Deterministic wrapper for the /test skill -- runs the suite the one correct way so the
# safety flags can't be forgotten. Builds the webapp image as :test (the deploy-watcher
# only ever acts on :latest, so a :test build is invisible to it -- it never triggers a
# redeploy or a git reset of the checkout) and runs pytest in an ephemeral container with
# requirements-dev.txt installed on the fly. Tests run against an in-memory FakeDB, so
# this never touches a real database or sends email.
#
#   scripts/test.sh                                              # whole suite
#   scripts/test.sh -k perform_fight                             # any pytest args pass through
#   scripts/test.sh tests/test_queries.py::test_perform_fight_happy_path
#   scripts/test.sh audit                                        # pip-audit CVE scan instead
set -euo pipefail
cd "$(dirname "$0")/.."
export IMAGE_TAG=test

compose() { docker compose -f docker-compose-prod.yml "$@"; }

compose build halloween-webapp-prod

if [ "${1:-}" = "audit" ]; then
  run="pip install -q -r requirements-dev.txt && pip-audit"
else
  run="pip install -q -r requirements-dev.txt && python -m pytest -q $*"
fi

compose run --rm --no-deps --entrypoint sh halloween-webapp-prod -c "$run"
