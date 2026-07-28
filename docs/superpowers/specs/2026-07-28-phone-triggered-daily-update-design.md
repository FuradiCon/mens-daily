# Design: Phone-Triggered Daily Update + Once-Per-Day Guard

## Problem

GitHub Actions' `schedule:` cron trigger for `daily-update.yml` is best-effort and has
skipped firing entirely (observed 2026-07-28, ran ~6 hours late). This is a documented
GitHub limitation, not a config bug, and there's no way to make GitHub's own scheduler
more reliable.

## Solution

Add a second, more reliable trigger path from the user's Android phone (Galaxy S22),
running alongside the existing GitHub schedule, and make the pipeline itself refuse to
publish more than once per day regardless of which trigger fired it.

### 1. Once-per-day guard (`scripts/generate_daily.py`)

At the very top of `main()`, before the `ANTHROPIC_API_KEY` check or client setup:
read `data.json` and check whether its existing entry's `date` field already equals
today's UTC date (`YYYY-MM-DD`). If it matches, print a message to stdout and exit 0
immediately — no Anthropic API call, no web searches, no cost, no duplicate
`history.json` entry.

This makes "once per 24 hours" a property of the script itself, independent of trigger
source. It's what makes it safe to run two independent, uncoordinated triggers (GitHub's
cron + the phone) without risking double cost.

### 2. GitHub workflow — unchanged

`daily-update.yml` keeps its existing `schedule:` cron as a backup trigger. No YAML
changes needed; the guard above protects against it firing on the same day as the phone
trigger.

### 3. Phone-side trigger (Galaxy S22) — user-executed runbook, not code

Using the **HTTP Shortcuts** Android app (free, open source):

- A fine-grained GitHub PAT, scoped to only `FuradiCon/mens-daily` with "Actions: write"
  permission, created by the user in GitHub settings (not handled by Claude).
- One configured request in HTTP Shortcuts:
  - `POST https://api.github.com/repos/FuradiCon/mens-daily/actions/workflows/daily-update.yml/dispatches`
  - Header: `Authorization: Bearer <PAT>`
  - Header: `Accept: application/vnd.github+json`
  - Body: `{"ref":"master"}`
  - Scheduled via the app's built-in daily scheduler (Android AlarmManager-backed).
- Two Samsung-specific settings to make the schedule actually fire reliably:
  - Battery usage for HTTP Shortcuts set to "Unrestricted"
  - HTTP Shortcuts excluded from "Put unused apps to sleep" / auto-disable list

This part is a runbook Claude writes out step by step; the user performs the actual
phone configuration and PAT creation themselves.

## Out of scope (YAGNI, can revisit later)

- No manual "force regenerate today" override/input — if ever needed, could be added
  as a `workflow_dispatch` boolean input that bypasses the guard, but nothing today
  requires it.
- Not removing GitHub's own `schedule:` trigger — kept as a free backup now that the
  guard makes redundancy free.

## Testing

- Guard logic: run `generate_daily.py` twice in a row locally (or via two manual
  `workflow_dispatch` runs) and confirm the second run exits immediately without an
  Anthropic API call and without a duplicate `history.json` entry.
- Phone trigger: manually fire the HTTP Shortcuts request once and confirm a workflow
  run appears in GitHub Actions.
