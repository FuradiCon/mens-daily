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

## 2. Install and configure HTTP Request Shortcuts

1. Install **HTTP Request Shortcuts** (by Waboodoo) from the Play Store.
2. Create a new shortcut with:
   - Method: `POST`
   - URL: `https://api.github.com/repos/FuradiCon/mens-daily/actions/workflows/daily-update.yml/dispatches`
   - Headers:
     - `Authorization: Bearer <paste your token from step 1>`
     - `Accept: application/vnd.github+json`
     - `Content-Type: application/json`
   - Request body (JSON): `{"ref": "master"}`
3. Open the shortcut's **Trigger & Execution Settings** → **Run repeatedly** → set
   it to **24 hours**. There's no clock-time picker — the schedule is anchored to a
   moment in time, so set it at the time of day you want it firing.

### How the repeat interval actually works

Verified against the app's source (`GetNextRepetitionTimeUseCase`, `Execution.kt`,
`ExecutionWorker.kt`) rather than inferred from the docs, because the behavior is
not documented publicly:

- **Scheduled runs keep the original anchor.** Each repeat carries its `triggeredAt`
  forward, and the next fire is computed as `anchor + interval × (N+1)` — a fixed
  grid. Timing does not drift, and a reboot recreates the schedule rather than
  dropping it (app v3.31.0+).
- **A manual tap re-anchors the whole schedule to that moment.** Running the shortcut
  by hand deletes the pending repeat and creates a new one anchored at "now"
  (`scheduleRepetitionIfNeeded(params.triggeredAt ?: Instant.now())`, where a manual
  launch supplies no `triggeredAt`). So tapping the shortcut at midnight moves the
  daily slot to midnight — no need to toggle the setting off and back on.
- Fire times are rounded to the nearest **5 minutes**.
- Edge case: if the computed next fire lands less than **20% of the interval** away,
  it skips one cycle. On a 24h interval that is a ~4.8h dead zone. A manual tap never
  hits it, since that always schedules a full interval out.

## 3. Make Samsung's battery management leave it alone

One UI aggressively kills background schedules unless you exempt the app:

1. Settings → Apps → HTTP Request Shortcuts → Battery → set to **Unrestricted**.
2. Settings → Battery and device care → Background usage limits → make sure
   HTTP Request Shortcuts is **not** listed under "Sleeping apps" or "Deep sleeping apps"
   (remove it if it is).

## 4. Test it

1. In HTTP Request Shortcuts, tap the shortcut to fire it manually right now.
2. Go to https://github.com/FuradiCon/mens-daily/actions and confirm a new
   "Daily Verse Update" run appears, triggered by `workflow_dispatch`.
3. If nothing appears: double check the token has Actions "Read and write" on the
   right repo, and that the URL/body match step 2 exactly.
