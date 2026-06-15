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

1. **Run the wrapper.** `scripts/test.sh` does the whole thing deterministically — builds the
   webapp image as `:test`, then runs pytest (or pip-audit) in an ephemeral container with
   `requirements-dev.txt` installed on the fly. Pick the form from `$ARGUMENTS`:

   ```bash
   bash scripts/test.sh                  # whole suite
   bash scripts/test.sh -k perform_fight # any pytest args pass straight through
   bash scripts/test.sh tests/test_lifecycle.py::test_rollover_archives_then_reopens
   bash scripts/test.sh audit            # pip-audit CVE scan instead of pytest
   ```

   The `:test` tag is the safety rail and is **baked into the script** (not optional): the
   deploy-watcher on this host treats any local change to the `:latest` image IDs as a newly
   published image and responds with `deploy.sh` — a hard `git checkout -f master &&
   git reset --hard origin/master` plus redeploy — which **wipes uncommitted work within one poll
   interval**. The `:test` tag is invisible to its detector, so the wrapper can never trigger that.

2. **Report the outcome faithfully.** State pass/fail counts; if anything failed, quote the failing
   test(s) and the assertion/traceback — don't claim green unless pytest exited 0. For `audit`, list
   any vulnerable packages with the advisory IDs and fixed versions.

## Notes

- The mechanics live in `scripts/test.sh`: it `cd`s to the repo root, sets `IMAGE_TAG=test`,
  builds, then runs with `--rm` (cleans up the container) and `--no-deps` (keeps the API container
  from starting alongside it). Read it if you need to see exactly what runs.
- The suite deliberately covers only safely-importable code (`queries`, `eventstate`, `lifecycle`,
  `security`, the dependency set, the cv2 QR round-trip). `api.py` / `app.py` aren't imported because
  they call `app.run()` / Firebase init at import time — don't add tests that import them.
- If the run errors before collecting tests, it's almost always a missing `app.env` (the `run`
  command loads it via `env_file`) — confirm `app.env` exists in the repo root.
