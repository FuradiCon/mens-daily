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
