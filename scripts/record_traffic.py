"""
Records this repo's GitHub Pages traffic into a rolling history file.

GitHub's traffic API (repos/{owner}/{repo}/traffic/views) only retains the
last 14 days, so this script upserts each day it sees into traffic.json,
building up a longer history over time. The Furadi Social Analytics
dashboard reads this file (via raw.githubusercontent.com) to power the
"Steadfast Counter" entry in its channel rail.
"""

import json
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
TRAFFIC_PATH = ROOT / "traffic.json"
KEEP_DAYS = 180

REPO = os.environ.get("GITHUB_REPOSITORY", "FuradiCon/mens-daily")


def main():
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        print("GH_TOKEN/GITHUB_TOKEN is not set; aborting.", file=sys.stderr)
        sys.exit(1)

    resp = requests.get(
        f"https://api.github.com/repos/{REPO}/traffic/views",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        timeout=15,
    )
    resp.raise_for_status()
    payload = resp.json()

    history = {}
    if TRAFFIC_PATH.exists():
        for row in json.loads(TRAFFIC_PATH.read_text(encoding="utf-8")):
            history[row["d"]] = row

    for point in payload.get("views", []):
        day = point["timestamp"][:10]
        history[day] = {"d": day, "views": point["count"], "uniques": point["uniques"]}

    merged = sorted(history.values(), key=lambda r: r["d"])[-KEEP_DAYS:]
    TRAFFIC_PATH.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    print(f"Recorded traffic through {merged[-1]['d'] if merged else 'n/a'} ({len(merged)} days total)")


if __name__ == "__main__":
    main()
