---
name: implement-dev-changes
description: Orchestrate a dev change for The Long Night end-to-end — explore, plan, branch, implement (+ tests), /test, optional /qa, commit, push, open a PR, work the review feedback, then pre-deploy checks, merge (only on your explicit OK), and verify the build + prod deploy. Composes the atomic skills and pauses at every human gate. Use for fixes, features, vulnerability fixes, and tooling/dependency upgrades.
---

# Implement a dev change, end to end

> 🚦 **Orchestrator — runs in the main context so you see and steer every step.** It **composes** the
> atomic skills (`/test`, `/qa`, `/prod-logs`) instead of reimplementing them, and it **stops at the
> human gates**: plan approval, the optional QA call, and the **merge**. Branch pushes and opening the
> PR are done for you (they publish no image — only a merge to `master` triggers a deploy). The merge
> itself happens **only when you explicitly say so in the conversation** ("we're good to merge"); it is
> never done unprompted.

Works for any change — **fix, feature, vulnerability fix, or tooling/dependency upgrade**; the phases
are the same, only the emphasis shifts (a dep bump leans on `/test audit`; a UI change leans on `/qa`).

## Phases

**0 — Frame & precondition.** Restate the goal in one line and classify it (fix / feature / vuln /
upgrade). Confirm a clean working tree (`git status`); surface anything dirty before starting.

**1 — Explore.** For anything beyond a one-file change, dispatch the built-in **Explore** agent
(read-only fan-out) to map the relevant files/functions and how the change fits; for a small localized
change, grep/read inline. Report what you found. **Don't edit yet.**

**2 — Plan (gate).** Enter plan mode and draft the **smallest** change that does the job — call out
anything that forces a `src/` change or a new dependency (justify it; deps must be CVE-/necessity-driven
per CLAUDE.md), and list the tests you'll add or extend. Refine with the user and get explicit approval
before writing code.

**3 — Branch.** `git fetch origin`, then create `<type>/<short-kebab-desc>` (`fix/…`, `feat/…`, `ci/…`,
`chore/…`) **from `origin/master`**. Never implement on `master`. (Your branch is safe from the
deploy-watcher while you work — no image publishes until a merge.)

**4 — Implement (+ tests).** Make the change following repo conventions (camelCase, minimal deps,
inline-CSS/table emails — see CLAUDE.md). Add/extend `tests/` for the new behavior (the suite covers
only safely-importable modules — don't import `api.py`/`app.py`). Keep the diff tight; check in early.

**5 — `/test`.** Run **`/test`** until green; also run **`/test audit`** if you touched dependencies.
(It owns the `IMAGE_TAG=test` ephemeral-container mechanics — don't reinvent them.)

**6 — `/qa` (optional — the user decides).** QA is **always optional**: ask the user whether to run it
(or follow their standing call for this change). When they want it, drive the sandbox with **`/qa`**
(`open`/`tick`/`close`/`restart`/`status`) and browser-test as needed; pass the `GIFT_CARD_*` trio if
the prize is in scope. For changes with no runtime surface (pure docs/tests/CI), note that QA doesn't
apply. Fix any findings and re-run.
> `/qa` builds from your **working tree** with `IMAGE_TAG=qa`, which the deploy-watcher ignores (it only
> acts on `:latest`) — so it exercises the uncommitted change directly and won't trigger a redeploy.
> You'll commit *after* this. Just don't merge to `master` mid-session (a concurrent deploy would
> `git reset --hard` and wipe uncommitted work); for a long QA iteration, a throwaway WIP commit on the
> branch is a cheap safety net.

**7 — Self-review + commit (verified code only).** Now that `/test` (and any `/qa`) is green, do a
deliberate pass over the **full diff** (`git diff`) for bugs, scope creep, leftover debug, and missed
doc/`VERSION` updates — bump `VERSION` in the `*.env.example` templates if app behavior changed (and
remind the user to bump the real env file in the repo dir on the Pi — you can't see it). Stage
**explicitly by name** — never `git add -A`/`-u`, never stage `api.env`/`app.env`/`serviceAccountKey.json`.
Commit with the repo's `Co-Authored-By` trailer.

**8 — Push + open PR.** Push the branch and open a **non-draft** PR against `master` with `gh` (so the
CI auto-review runs immediately — drafts are skipped). Summarize the change and link the PR.

**9 — Work the review loop.** Watch `gh pr checks` (CI `test` + `audit`) and the inline auto-review
comments (`gh pr view --comments`). Address real findings with follow-up commits — re-run `/test` (and
`/qa` if you touched runtime code) first, same verify-then-commit order. For anything on the
**accepted-trade-offs list in CLAUDE.md**, don't "fix" it — note it's settled. A local **`/code-review`**
pass first is fine; `/ultrareview` is user-triggered/billed — you can't launch it. Loop until checks are
green and the review is clean.
> If the PR edits `.github/workflows/claude-review.yml`, expect the `401 Workflow validation failed`
> self-review failure — it's by design (an accepted trade-off); such workflow changes merge on their own
> first.

**10 — Pre-deploy checks.** Before recommending a merge, verify (report results; don't silently fix):
- working tree clean on the PR branch; `git log --oneline origin/master..HEAD` shows exactly what will
  deploy;
- **no secrets** staged/tracked — `git ls-files api.env app.env serviceAccountKey.json` prints nothing,
  `git diff --cached --name-only` is clean;
- `VERSION` bumped in the `*.env.example` templates if behavior changed (and remind about the real env
  file on the Pi — you can't see it);
- `/test` green on the final state.

**11 — Merge (gated on your explicit OK).** Present the pre-deploy results and the PR, and ask whether
to merge. **Merge only if the user affirmatively says so in this turn** (e.g. "yes, merge it") —
`gh pr merge --merge --delete-branch` (repo history shows merge commits; use `--squash` if preferred).
If they don't, **stop and hand off** the merge. Never merge, push, or deploy unprompted. The merge to
`master` is the deploy trigger.

**12 — Verify the build + prod deploy.** First check what CI did: if the change touched **only**
docs/CI config (`**.md` / `.claude/` / `.github/`), CI's `changes` gate **skips the publish build** —
nothing redeploys, so just confirm `test` + `audit` passed and the merge landed, and you're done.
Otherwise give CI a few minutes to build & publish the arm64 image plus one watcher interval, then
confirm the whole chain:
- CI **publish** job succeeded (`gh run list` / `gh run view` on `master`);
- the Pi watcher deployed it — `tail Logs/deploy-watcher.log` shows "new image detected — deploying" /
  "deploy complete"; `docker compose -f docker-compose-prod.yml ps` shows both `Up`; `docker inspect`
  shows the GHCR `:latest` image; the deployed `VERSION` matches; no startup tracebacks (or just run
  **`/prod-logs`**). Expect the watcher to have moved the local checkout onto `master`.

Report success plainly, or quote the errors if it didn't come up cleanly.

**Done when:** PR merged → CI published the image → the watcher deployed it → both containers up on the
expected `VERSION`.
