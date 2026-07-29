# Design: GoatCounter Page Views for the Steadfast Counter

## Problem

`scripts/record_traffic.py` pulls `repos/FuradiCon/mens-daily/traffic/views`. That
endpoint measures views of the **repository page on github.com** — people browsing the
code. It does not measure visits to the published GitHub Pages devotional site. GitHub
has never exposed Pages analytics.

Nobody browses the repo, so the endpoint returns zeros. Verified 2026-07-29 by calling
it directly:

```
{"count":0,"uniques":0,"views":[ ...14 days, every one count:0, uniques:0... ]}
```

`traffic.json` held 15 rows (`2026-07-13` → `2026-07-27`) with **zero non-zero rows in
its entire history**. The pipeline was working perfectly and faithfully recording
nothing. The `TRAFFIC_PAT` fix on 2026-07-27 was a real bug fix; it just revealed that
the data source underneath was the wrong thing entirely.

## Solution

Replace the data source with GoatCounter, a privacy-friendly analytics service that
actually measures visits to the site. Keep everything downstream identical.

Scope is **data source only**. Wiring the number into the Furadi Social Analytics
dashboard is a separate spec (see Out of Scope).

### 1. Collection — `index.html`

Add one script tag:

```html
<script data-goatcounter="https://furadi.goatcounter.com/count"
        async src="//gc.zgo.at/count.js"></script>
```

No cookies, so no consent banner obligation. Works on `github.io` domains.

### 2. Retrieval — `scripts/record_traffic.py`

Rewrite in place. The file keeps its name — it still records site traffic, only the
upstream changes. Git history on the file stays continuous.

- Base URL: `https://furadi.goatcounter.com/api/v0`
- Auth: `Authorization: Bearer $GOATCOUNTER_TOKEN`
- Fetch a **trailing 14-day window**, not just yesterday.

The trailing window is deliberate and carried over from the current script: if a daily
run is skipped — and runs do get skipped, which is why the phone trigger exists — the
next run backfills the gap instead of leaving a permanent hole. It costs one request
either way.

Day rows are `{"d": "YYYY-MM-DD", "views": N}`, sorted by date, trimmed to
`KEEP_DAYS = 180`. Existing upsert-by-date logic is preserved.

**`uniques` is dropped.** The original plan kept it, but probing the live API showed
GoatCounter exposes exactly one number per day — its docs call `total` "visitors," and it
is already de-duplicated by session. There is no pageviews-vs-uniques distinction to
fetch, so a second field would only have mirrored the first.

**The envelope does change.** `traffic.json` is currently a top-level JSON array, which
has nowhere to put the observability fields. It becomes an object:

```json
{
  "fetched_at": "2026-07-30T06:12:03Z",
  "last_error": null,
  "days": [ { "d": "2026-07-30", "views": 12, "uniques": 9 } ]
}
```

This is free to do now precisely because nothing reads the file yet — the dashboard side
is unbuilt (see Out of Scope). Doing it later would be a breaking change.

### 3. Credentials

`GOATCOUNTER_TOKEN` repo secret, scoped to **Read statistics** only. Added and confirmed
present 2026-07-29T17:13Z.

`TRAFFIC_PAT` becomes unused by this script. Leave the secret in place for now; removing
it is not part of this change.

### 4. Workflow — `.github/workflows/daily-update.yml`

The "Record page traffic" step stays where it is in the sequence. Changes:

- `env: GH_TOKEN: ${{ secrets.TRAFFIC_PAT }}` → `GOATCOUNTER_TOKEN: ${{ secrets.GOATCOUNTER_TOKEN }}`
- `continue-on-error: true` is **kept** — a secondary metric must never block the day's
  devotional from publishing.
- Add a step summary write so failures are visible in the Actions UI rather than buried
  in a collapsed log.

### 5. History reset — `traffic.json`

Reset to the empty envelope:

```json
{ "fetched_at": null, "last_error": null, "days": [] }
```

The 15 existing rows are all zeros and describe a period that was never measured.
GoatCounter has no backfill; history genuinely begins at install.

## Data flow

```
visitor loads index.html
  → count.js pings furadi.goatcounter.com
    → daily workflow run
      → record_traffic.py GETs /api/v0 stats for trailing 14 days
        → upsert into traffic.json (180-day window)
          → committed and pushed by the existing commit step
```

## Error handling

The failure this design is reacting to is not a crash — it is **silence**. The counter
sat broken for weeks because `continue-on-error: true` swallowed the failure and nothing
downstream signalled that the data was stale.

So: never block, but make noise.

- On success, write `fetched_at` (UTC ISO timestamp) and set `last_error` to `null`.
- On failure, write `last_error` with the reason, leave `days` untouched, print a loud
  message to the GitHub step summary, and exit non-zero. The step's `continue-on-error`
  absorbs the non-zero exit so the run proceeds and the devotional still publishes — the
  step shows as failed in the UI, which is the point.
- A stale `fetched_at` is therefore visible in the committed file itself, not only in a
  log that nobody reads.

## Testing

Unit tests in `tests/`, stdlib `unittest`, matching the existing
`tests/test_generate_daily.py` pattern. No new dependency.

- Upsert merges a new day without disturbing existing rows
- Re-fetching an already-recorded day overwrites rather than duplicates
- The 180-day trim keeps the most recent rows
- A failed fetch writes `last_error` and does not clobber existing data
- Parsing is asserted against a **recorded real API response** used as a fixture, not a
  hand-written guess at the schema

## Sequencing

Order matters, because the parser must be written against reality:

1. Script tag goes live on the site.
2. Generate a visit or two so there is non-zero data.
3. Make one real API call and capture the actual response.
4. **Then** write the parser and the fixture against that captured response.

## Resolved: confirmed API shape

Probed 2026-07-29 via a temporary Actions workflow (the token lives only in repo secrets,
so the probe ran inside CI rather than from a workstation; removed afterwards).

`GET /api/v0/stats/total?start=&end=` returns:

```json
{
  "total": 1, "total_events": 0, "total_utc": 1,
  "stats": [ { "day": "2026-07-29", "hourly": [ 24 ints ], "daily": 1 } ]
}
```

The parser reads `stats[].day` and `stats[].daily`. Recorded verbatim as
`tests/fixtures/goatcounter_stats_total.json`.

Two gotchas found while probing:

- **The API answers in the site's timezone, not UTC.** Requesting `start=2026-07-15&
  end=2026-07-29` returned days `2026-07-14` → `2026-07-28`. The fetch window therefore
  asks for `tomorrow` as its end date to be certain today is included.
- **Bot filtering is real and server-side.** A visit from the in-app browser
  (`Claude/… Electron/…` user agent) did not register even though client-side
  `goatcounter.filter()` returned `false`. Correct behaviour, but worth knowing before
  concluding the tag is broken during future testing.

## Out of scope

- Dashboard wiring. `steadfast_pipeline.py` and the Steadfast Counter rail entry in
  `YT Metrics v2` do not exist yet — confirmed by grep on 2026-07-29. Separate spec.
- Removing the now-unused `TRAFFIC_PAT` secret.
- Per-path breakdowns. The devotional is effectively one page.
- A provider-agnostic adapter layer. One provider, no concrete second — YAGNI.

## Cost

Zero. GoatCounter's hosted tier is free for non-commercial use up to ~100k pageviews per
month, well above this site's volume. No metered API charge on retrieval. Self-hosting
was considered and rejected: it means running a server for one number a day.
