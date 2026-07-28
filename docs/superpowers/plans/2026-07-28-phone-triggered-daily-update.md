# Phone-Triggered Daily Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a once-per-day publish guard to `generate_daily.py` and a written runbook for triggering the daily workflow from an Android phone, so the page updates reliably even when GitHub's own `schedule:` cron misses a day.

**Architecture:** A pure, unit-tested guard function (`already_published_today`) is called at the very top of `main()`, before any API keys are read or the Anthropic client is created. If `data.json` already has today's UTC date, the script exits immediately at zero cost. This makes it safe to trigger the same GitHub Actions workflow from multiple independent sources (GitHub's cron + a phone-based HTTP request) without ever risking a double-cost run. The phone side is documented as a runbook, not code — there's no repo-side artifact for "install an Android app," so it's delivered as a markdown doc the user follows once.

**Tech Stack:** Python 3.12 (stdlib `unittest`, no new dependency), existing `scripts/generate_daily.py`.

## Global Constraints

- Guard check must run before the `ANTHROPIC_API_KEY` check and before `anthropic.Anthropic(...)` client creation — a skip must cost nothing, not even a failed-auth attempt.
- No new third-party Python dependency — use stdlib `unittest`, matching the fact this repo has no existing test framework (only `anthropic` and `requests` in `requirements.txt`).
- Do not modify `.github/workflows/daily-update.yml` — the spec keeps GitHub's `schedule:` trigger unchanged as a backup.
- No "force regenerate" override/bypass flag — out of scope per the spec's YAGNI note; nothing today requires it.
- PAT used in the phone runbook must be a fine-grained token scoped to only `FuradiCon/mens-daily` with "Actions: write" permission — never a classic all-repo token.

---

### Task 1: Add and unit-test the once-per-day guard function

**Files:**
- Modify: `scripts/generate_daily.py` (add function after `load_json`, currently ending at line 120)
- Create: `tests/test_generate_daily.py`

**Interfaces:**
- Produces: `already_published_today(existing_entry: dict | None, today: str) -> bool` — later tasks (Task 2) call this from `main()`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_generate_daily.py`:

```python
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from generate_daily import already_published_today


class AlreadyPublishedTodayTest(unittest.TestCase):
    def test_true_when_entry_matches_today(self):
        self.assertTrue(already_published_today({"date": "2026-07-28"}, "2026-07-28"))

    def test_false_when_entry_is_a_different_day(self):
        self.assertFalse(already_published_today({"date": "2026-07-27"}, "2026-07-28"))

    def test_false_when_no_entry_exists(self):
        self.assertFalse(already_published_today(None, "2026-07-28"))

    def test_false_when_entry_has_no_date_field(self):
        self.assertFalse(already_published_today({}, "2026-07-28"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python tests/test_generate_daily.py -v`
Expected: `ImportError: cannot import name 'already_published_today' from 'generate_daily'`

- [ ] **Step 3: Implement the function**

In `scripts/generate_daily.py`, add immediately after the `load_json` function (after line 120, before `def recent_history_text(history):`):

```python
def already_published_today(existing_entry, today):
    """True if data.json's existing entry already covers `today` (YYYY-MM-DD).
    Backs the once-per-24h guard — makes it safe for GitHub's schedule trigger
    and the phone trigger to both fire on the same day without double cost."""
    return bool(existing_entry) and existing_entry.get("date") == today
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python tests/test_generate_daily.py -v`
Expected: `OK` with 4 tests passing.

- [ ] **Step 5: Commit**

```bash
git add scripts/generate_daily.py tests/test_generate_daily.py
git commit -m "Add once-per-day publish guard function with unit tests"
```

---

### Task 2: Wire the guard into `main()` and verify against real state

**Files:**
- Modify: `scripts/generate_daily.py:325-334` (top of `main()`)
- Modify: `scripts/generate_daily.py:402` (remove now-duplicate `today` assignment)

**Interfaces:**
- Consumes: `already_published_today(existing_entry, today)` from Task 1.

- [ ] **Step 1: Move `today` to the top of `main()` and add the guard**

Replace:

```python
def main():
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if not anthropic_key:
        print("ANTHROPIC_API_KEY is not set; aborting.", file=sys.stderr)
        sys.exit(1)
    youtube_api_key = os.environ.get("YOUTUBE_API_KEY")

    client = anthropic.Anthropic(api_key=anthropic_key)
    history = load_json(HISTORY_PATH, [])
    history_text = recent_history_text(history)
```

with:

```python
def main():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    existing_entry = load_json(DATA_PATH, None)
    if already_published_today(existing_entry, today):
        print(f"Already published for {today}; skipping (once-per-day guard).")
        sys.exit(0)

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if not anthropic_key:
        print("ANTHROPIC_API_KEY is not set; aborting.", file=sys.stderr)
        sys.exit(1)
    youtube_api_key = os.environ.get("YOUTUBE_API_KEY")

    client = anthropic.Anthropic(api_key=anthropic_key)
    history = load_json(HISTORY_PATH, [])
    history_text = recent_history_text(history)
```

- [ ] **Step 2: Remove the now-duplicate `today` assignment further down**

Replace:

```python
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    record_usage(today, run_usage, published=accepted is not None)
```

with:

```python
    record_usage(today, run_usage, published=accepted is not None)
```

- [ ] **Step 3: Verify with a deterministic, zero-cost local check**

Don't rely on `data.json`'s live prod state for this — it depends on whether today's
scheduled run has already landed locally, which isn't reproducible. Instead, back it
up, stamp it with today's date, run the script, then restore it:

Run (from repo root, Git Bash):
```bash
cp data.json data.json.bak
python -c "import json, datetime; d = json.load(open('data.json')); d['date'] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d'); json.dump(d, open('data.json', 'w'), indent=2)"
python scripts/generate_daily.py
mv data.json.bak data.json
```

Expected output from `python scripts/generate_daily.py`: `Already published for <today's date>; skipping (once-per-day guard).`, exit code 0.

Confirm the restore left the working tree clean:

Run: `git status --short`
Expected: no modifications to `data.json`, `history.json`, or `usage.json` — output is empty or shows only unrelated pre-existing changes (e.g. the untracked `SS.JPG` / `shift change july 27.txt` files already in this repo).

- [ ] **Step 4: Re-run the unit tests to confirm nothing broke**

Run: `python tests/test_generate_daily.py -v`
Expected: `OK` with 4 tests passing.

- [ ] **Step 5: Commit**

```bash
git add scripts/generate_daily.py
git commit -m "Wire once-per-day guard into main() so redundant triggers are free"
```

---

### Task 3: Write the phone-side trigger runbook

**Files:**
- Create: `docs/mobile-trigger-setup.md`

**Interfaces:**
- None — this is a standalone documentation file the user follows manually on their Galaxy S22. No other task depends on it.

- [ ] **Step 1: Write the runbook**

Create `docs/mobile-trigger-setup.md`:

```markdown
# Triggering the daily update from a Galaxy S22

Backup trigger for `FuradiCon/mens-daily`'s daily workflow, alongside GitHub's own
`schedule:` cron. Safe to run even if GitHub's trigger also fires the same day — the
script's once-per-day guard means only the first trigger of the day actually costs
anything.

## 1. Create a fine-grained GitHub token

1. Go to https://github.com/settings/personal-access-tokens/new (while logged into
   the FuradiCon-owning account).
2. Token name: `mens-daily-phone-trigger`.
3. Resource owner: `FuradiCon`.
4. Expiration: pick whatever you're comfortable renewing (e.g. 1 year).
5. Repository access: "Only select repositories" → `mens-daily`.
6. Permissions → Repository permissions → **Actions** → set to **Read and write**.
   Leave every other permission at "No access."
7. Generate token and copy it somewhere safe — GitHub only shows it once. You'll
   paste it into the app in step 2.

## 2. Install and configure HTTP Shortcuts

1. Install **HTTP Shortcuts** from the Play Store.
2. Create a new shortcut with:
   - Method: `POST`
   - URL: `https://api.github.com/repos/FuradiCon/mens-daily/actions/workflows/daily-update.yml/dispatches`
   - Headers:
     - `Authorization: Bearer <paste your token from step 1>`
     - `Accept: application/vnd.github+json`
     - `Content-Type: application/json`
   - Request body (JSON): `{"ref": "master"}`
3. Open the shortcut's settings → **Scheduling** → add a new daily schedule at
   whatever local time you want it to fire (e.g. 6:30 AM local).

## 3. Make Samsung's battery management leave it alone

One UI aggressively kills background schedules unless you exempt the app:

1. Settings → Apps → HTTP Shortcuts → Battery → set to **Unrestricted**.
2. Settings → Battery and device care → Background usage limits → make sure
   HTTP Shortcuts is **not** listed under "Sleeping apps" or "Deep sleeping apps"
   (remove it if it is).

## 4. Test it

1. In HTTP Shortcuts, tap the shortcut to fire it manually right now.
2. Go to https://github.com/FuradiCon/mens-daily/actions and confirm a new
   "Daily Verse Update" run appears, triggered by `workflow_dispatch`.
3. If nothing appears: double check the token has Actions "Read and write" on the
   right repo, and that the URL/body match step 2 exactly.
```

- [ ] **Step 2: Commit**

```bash
git add docs/mobile-trigger-setup.md
git commit -m "Add runbook for triggering the daily workflow from an Android phone"
```
