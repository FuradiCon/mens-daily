"""
Records the devotional site's page views into a rolling history file.

Source is GoatCounter, not GitHub. GitHub's traffic API measures views of the
*repository page* on github.com, not visits to the published GitHub Pages site,
so it reported zeros forever (see
docs/superpowers/specs/2026-07-29-goatcounter-page-views-design.md).

GoatCounter exposes a single per-day number — its docs call it "visitors" and it
is already de-duplicated by session — so each row carries one `views` count.
There is no separate uniques metric to record.

The Furadi Social Analytics dashboard reads this file (via
raw.githubusercontent.com) to power the "Steadfast Counter" entry.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
TRAFFIC_PATH = ROOT / "traffic.json"
KEEP_DAYS = 180

# Refetch a trailing window rather than just yesterday: if a daily run is skipped,
# the next run backfills the gap instead of leaving a permanent hole. Same cost.
WINDOW_DAYS = 14

SITE_CODE = os.environ.get("GOATCOUNTER_SITE", "furadi")
BASE_URL = f"https://{SITE_CODE}.goatcounter.com/api/v0"


def parse_days(payload):
    """Turn a /stats/total response into {"d", "views"} rows.

    Shape confirmed against a real recorded response (see
    tests/fixtures/goatcounter_stats_total.json):
        {"total": N, "stats": [{"day": "YYYY-MM-DD", "hourly": [...], "daily": N}]}
    """
    return [
        {"d": stat["day"], "views": stat.get("daily", 0)}
        for stat in payload.get("stats", [])
    ]


def merge_days(existing, incoming, keep_days=KEEP_DAYS):
    """Upsert incoming rows over existing ones, sorted by date, trimmed to keep_days."""
    history = {row["d"]: row for row in existing}
    for row in incoming:
        history[row["d"]] = row
    return sorted(history.values(), key=lambda r: r["d"])[-keep_days:]


def read_envelope(path):
    """Read traffic.json, tolerating the pre-2026-07-29 bare-array format."""
    if not path.exists():
        return {"fetched_at": None, "last_error": None, "days": []}

    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return {"fetched_at": None, "last_error": None, "days": data}
    return {
        "fetched_at": data.get("fetched_at"),
        "last_error": data.get("last_error"),
        "days": data.get("days", []),
    }


def write_envelope(path, days, fetched_at, last_error=None):
    payload = {"fetched_at": fetched_at, "last_error": last_error, "days": days}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def announce(message):
    """Surface a message where it can't be missed.

    This counter sat broken for weeks because the step failed quietly behind
    continue-on-error. Failures go to the run summary, not just the log.
    """
    print(message, file=sys.stderr)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(message + "\n")


def fetch_days(token):
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=WINDOW_DAYS)
    # end is exclusive-ish and the API answers in the site's timezone, so ask for
    # tomorrow to be sure today is included.
    end = today + timedelta(days=1)

    resp = requests.get(
        f"{BASE_URL}/stats/total",
        params={"start": start.isoformat(), "end": end.isoformat()},
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        timeout=15,
    )
    resp.raise_for_status()
    return parse_days(resp.json())


def main():
    existing = read_envelope(TRAFFIC_PATH)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    token = os.environ.get("GOATCOUNTER_TOKEN")
    if not token:
        reason = "GOATCOUNTER_TOKEN is not set"
        announce(f"Traffic not recorded: {reason}")
        write_envelope(TRAFFIC_PATH, existing["days"], existing["fetched_at"], reason)
        sys.exit(1)

    try:
        incoming = fetch_days(token)
    except Exception as exc:  # network, HTTP, or malformed JSON
        reason = f"{type(exc).__name__}: {exc}"
        announce(f"Traffic not recorded: {reason}")
        # Preserve whatever history we already have; only the stamp changes.
        write_envelope(TRAFFIC_PATH, existing["days"], existing["fetched_at"], reason)
        sys.exit(1)

    merged = merge_days(existing["days"], incoming)
    write_envelope(TRAFFIC_PATH, merged, now)

    latest = merged[-1] if merged else None
    print(
        f"Recorded traffic through {latest['d']} ({latest['views']} views) "
        f"— {len(merged)} days total"
        if latest
        else "Recorded traffic: no days returned"
    )


if __name__ == "__main__":
    main()
