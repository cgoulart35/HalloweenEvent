---
name: preflight
description: Prepare and verify a production deploy of The Long Night. Explains the CI-build + in-repo image-watcher deploy, runs pre-flight checks, and hands off the trigger (merge to master) to the user — it never pushes, merges, or deploys on its own.
---

# Prepare & verify a production deploy

> 🚦 **The user controls prod deploys.** This skill **prepares** and **verifies** a deploy. It must
> **never** push, merge, `git pull`, or deploy autonomously. Do the pre-flight, hand the user the
> exact trigger, wait for them to do it, then verify.

## How deploying actually works (so you verify the right things)

HalloweenEvent has its **own self-contained CD** — it no longer uses GitProjectUpdateHandler:

1. New commits land on **`origin/master`** (the user pushes, or merges a PR).
2. CI (`.github/workflows/ci.yml`) runs `test` + `audit`, then the **`publish`** job builds native
   **arm64** images and pushes them to **GHCR**: `ghcr.io/cgoulart35/halloweenevent-{api,webapp}`
   (`:latest` + `:<short-sha>`, public packages).
3. On the Pi, **`scripts/deploy-watcher.sh`** (started at boot from `/etc/rc.local`) polls GHCR and,
   when a new image digest appears, runs **`scripts/deploy.sh`**: `git checkout -f master` +
   `git reset --hard origin/master`, then `docker compose -f docker-compose-prod.yml pull && up -d`.

The trigger is the **published image, not the commit** — a deploy can't happen until CI finishes
building & pushing. (So after the user merges, expect a few minutes for CI plus one watcher interval.)

Implications you must respect:
- **Secrets live persistently in the repo dir on the Pi** (`api.env`, `app.env`,
  `serviceAccountKey.json` in `~/Code/HalloweenEvent/`, all gitignored). They're injected at runtime
  and survive `git reset --hard` (gitignored files aren't touched). To change a deployed secret, edit
  the file on the Pi directly, then redeploy. Secrets are **never** baked into the image —
  `.dockerignore` already excludes them.
- **Never commit real secrets.** Only `*.env.example` templates are tracked. Stage files **explicitly
  by name** — never `git add -A` / `git add -u`.

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
   `api.env.example` / `app.env.example` (and remind the user to bump the real env files in the repo
   dir on the Pi — you can't see those).

5. **Tests green:** run **`/test`** and report the result before recommending a deploy.

## Hand off the trigger (do not run it yourself)

Tell the user exactly what to do, and let them do it:
- If everything is already committed on `master`: `git push origin master`.
- If the change is in a PR: merge the PR to `master` (e.g. via GitHub).

Then CI builds & pushes the image and the Pi's watcher pulls it automatically. **Do not** push or
merge unless the user explicitly tells you to in this turn. Leave local `master` as-is — **do not**
`git pull` (the watcher does the reset/pull on the Pi).

## Verify after the user deploys

Give it time for **CI to build & push** (a few minutes) **plus** one watcher interval, then:

```bash
tail -n 30 Logs/deploy-watcher.log          # look for "new image detected — deploying" / "deploy complete"
docker compose -f docker-compose-prod.yml ps
docker inspect --format '{{.Config.Image}}' HalloweenEventApi_prod   # expect ghcr.io/cgoulart35/halloweenevent-api:latest
docker compose -f docker-compose-prod.yml logs --tail=30 halloween-api-prod
docker compose -f docker-compose-prod.yml logs --tail=30 halloween-webapp-prod
```

Confirm: both containers `running`/`Up`, the image is the GHCR one, no startup tracebacks, and the
deployed `VERSION` matches what you expect. (You can also just run **`/prod-logs`**.) Report success
plainly, or quote the errors if it didn't come up cleanly.
