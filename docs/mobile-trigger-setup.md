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
   it to **24 hours**. There's no clock-time picker — the interval is anchored to
   whenever you enable/save it, so turn it on right at the time of day you want it
   to keep firing (e.g. enable it at 6:30 AM local to have it fire around 6:30 AM
   every day after that). If it ever misses a cycle it resyncs to a new anchor time,
   so expect some drift over weeks rather than exact daily precision.

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
