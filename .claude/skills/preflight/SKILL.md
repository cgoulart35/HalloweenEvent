---
name: preflight
description: Prepare and verify a production deploy of The Long Night. Explains the webhook-driven deploy, runs pre-flight checks, and hands off the trigger to the user — it never pushes, merges, or deploys on its own.
---

# Prepare & verify a production deploy

> 🚦 **The user controls prod deploys.** This skill **prepares** and **verifies** a deploy. It must
> **never** push, merge, `git pull`, or run the deploy script autonomously. Do the pre-flight, hand
> the user the exact trigger command, wait for them to run it, then verify.

## How deploying actually works (so you verify the right things)

Deploys are **webhook-driven**, not run by hand:

1. New commits land on **`origin/master`** (the user pushes, or merges a PR).
2. The **GitProjectUpdateHandler** service on the Pi detects local `master` is behind, runs
   `git reset --hard` + `git pull` in this repo (**discarding any local working-tree edits**), then
   runs `~/Code/GitProjectUpdateHandler/Scripts/UpdateHalloweenEvent.sh`, which:
   - copies the **real** secrets (`serviceAccountKey.json`, `api.env`, `app.env`) from
     `~/Code/GitProjectUpdateHandler/Shared/HalloweenEvent/` into the repo, then
   - `docker compose -f docker-compose-prod.yml down && up -d --build`.

Implications you must respect:
- **Real env values live only in the Shared dir** and are copied in at deploy time. To change a
  deployed secret, edit the **Shared dir** files — editing the repo's `api.env`/`app.env` won't
  survive the deploy's `git reset --hard`. (Adding a *new* env var means updating both repos — ask
  the user; see the project's env-var notes.)
- **Never commit real secrets.** `api.env` / `app.env` / `serviceAccountKey.json` are gitignored;
  only the `*.env.example` templates are tracked. Stage files **explicitly by name** — never
  `git add -A` / `git add -u`.

## Pre-flight checks (do these; report results, don't fix silently)

1. **Branch & cleanliness:**
   ```bash
   git status
   git branch --show-current
   ```
   Deploys go out from `master`. If work is on a branch / in a PR, the trigger is merging that PR to
   `master` (not a direct push). Flag a dirty working tree.

2. **Local vs. origin:**
   ```bash
   git fetch origin
   git log --oneline origin/master..HEAD
   git log --oneline HEAD..origin/master
   ```
   Show the user what would (or wouldn't) deploy.

3. **No secrets tracked / staged** (must print nothing tracked):
   ```bash
   git ls-files api.env app.env serviceAccountKey.json
   git diff --cached --name-only
   ```
   If a real secret is staged or tracked, **stop** and alert the user.

4. **Version bump:** if app behavior changed, confirm `VERSION` was bumped in
   `api.env.example` / `app.env.example` (and, for the real deploy, in the Shared-dir env files —
   remind the user, since you can't see those).

5. **Tests green:** run **`/test`** and report the result before recommending a deploy.

## Hand off the trigger (do not run it yourself)

Tell the user exactly what to do, and let them do it:
- If everything is already committed on `master`: `git push origin master`.
- If the change is in a PR: merge the PR to `master` (e.g. via GitHub).

Then the GitProjectUpdateHandler webhook deploys automatically. **Do not** push or merge unless the
user explicitly tells you to in this turn. Leave local `master` as-is — **do not** `git pull`
(the webhook does the pull on the Pi).

## Verify after the user deploys

Once the user says the deploy ran (give it a moment for build + restart):

```bash
docker compose -f docker-compose-prod.yml ps
docker compose -f docker-compose-prod.yml logs --tail=30 halloween-api-prod
docker compose -f docker-compose-prod.yml logs --tail=30 halloween-webapp-prod
```

Confirm: both containers `running`/`Up`, no startup tracebacks, and the deployed `VERSION` matches
what you expect. (You can also just run **`/prod-logs`**.) Report success plainly, or quote the
errors if it didn't come up cleanly.
