---
name: test
description: Run the pytest suite for The Long Night (or a single test / a dependency CVE audit) the correct way — in an ephemeral container on the webapp image. Use when asked to run the tests, check that tests pass, run a specific test, or audit dependencies for CVEs.
argument-hint: "[-k filter | tests/test_x.py::test_y | audit]"
---

# Run the tests (or a CVE audit)

pytest is **not** baked into the Docker images (they install only `requirements.txt`). Tests run in
an **ephemeral container** built from the **webapp** image — the only one that installs `libgl1`,
which `cv2` needs for the QR-decode test. `requirements-dev.txt` (pytest + pip-audit) is installed on
the fly. Tests run entirely against an in-memory `FakeDB` and `conftest.py` drops any `EVENT_ROOT`
override, so they **never touch a real database or send email** — safe to run anytime.

**Arguments** (`$ARGUMENTS`):
- empty → run the **whole suite**.
- `audit` → run **pip-audit** instead of pytest (dependency CVE scan).
- anything else → passed straight to pytest, e.g. `-k perform_fight`, `-x`, or a node id like
  `tests/test_queries.py::test_perform_fight_happy_path`.

## Steps

1. **Build the webapp image** (fast if cached — needed so the ephemeral container exists).
   The `IMAGE_TAG=test` prefix is **REQUIRED, on every command below**: it tags the build
   `…-webapp:test` instead of `:latest`. The deploy-watcher on this host treats any local change
   to the `:latest` image IDs as a newly published image and responds with `deploy.sh` — a hard
   `git checkout -f master && git reset --hard origin/master` plus redeploy — which **wipes
   uncommitted work within one poll interval**. The `:test` tag is invisible to its detector:

   ```bash
   IMAGE_TAG=test docker compose -f docker-compose-prod.yml build halloween-webapp-prod
   ```

2. **Run.** Pick one based on the arguments:

   - **Whole suite** (no args):
     ```bash
     IMAGE_TAG=test docker compose -f docker-compose-prod.yml run --rm --no-deps --entrypoint sh \
       halloween-webapp-prod -c "pip install -q -r requirements-dev.txt && python -m pytest -q"
     ```

   - **Filtered / single test** (append the user's pytest args inside the quotes):
     ```bash
     IMAGE_TAG=test docker compose -f docker-compose-prod.yml run --rm --no-deps --entrypoint sh \
       halloween-webapp-prod -c "pip install -q -r requirements-dev.txt && python -m pytest -q -k perform_fight"
     ```
     (replace `-k perform_fight` with whatever was requested, e.g.
     `tests/test_lifecycle.py::test_rollover_archives_then_reopens`)

   - **CVE audit** (arg was `audit`):
     ```bash
     IMAGE_TAG=test docker compose -f docker-compose-prod.yml run --rm --no-deps --entrypoint sh \
       halloween-webapp-prod -c "pip install -q -r requirements-dev.txt && pip-audit"
     ```

3. **Report the outcome faithfully.** State pass/fail counts; if anything failed, quote the failing
   test(s) and the assertion/traceback — don't claim green unless pytest exited 0. For `audit`, list
   any vulnerable packages with the advisory IDs and fixed versions.

## Notes

- `--rm` cleans up the container; `--no-deps` keeps the API container from starting alongside it.
- The `run` commands need the same `IMAGE_TAG=test` as the build so they use the just-built `:test`
  image (it exists locally, so compose won't try to pull it from GHCR).
- The suite deliberately covers only safely-importable code (`queries`, `eventstate`, `lifecycle`,
  `security`, the dependency set, the cv2 QR round-trip). `api.py` / `app.py` aren't imported because
  they call `app.run()` / Firebase init at import time — don't add tests that import them.
- If the run errors before collecting tests, it's almost always a missing `app.env` (the `run`
  command loads it via `env_file`) — confirm `app.env` exists in the repo root.
