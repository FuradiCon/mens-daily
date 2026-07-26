"""
Daily pipeline for the "Scattered to Steadfast" page.

Uses the Anthropic API (with the web search tool) to pick a fresh NLT verse
about manhood/fatherhood, find a real 5-10 minute talking-head YouTube video
that matches it, and write a short reflection. The video is independently
verified against the YouTube oEmbed endpoint and the YouTube Data API before
anything is published, so a hallucinated URL or duration never reaches the
site. Writes docs data to data.json / history.json in the project root.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import anthropic
import requests

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "data.json"
HISTORY_PATH = ROOT / "history.json"
ENV_PATH = ROOT / ".env"


def load_dotenv(path):
    """Minimal .env loader for local runs (GitHub Actions supplies these via secrets instead)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


load_dotenv(ENV_PATH)

MODEL = "claude-sonnet-5"
MAX_ATTEMPTS = 6
HISTORY_LOOKBACK_DAYS = 30

MIN_DURATION_SECONDS = 5 * 60
MAX_DURATION_SECONDS = 10 * 60

YOUTUBE_URL_RE = re.compile(
    r"(?:youtube\.com/watch\?v=|youtu\.be/)([A-Za-z0-9_-]{11})"
)

SYSTEM_PROMPT = """You are curating content for a men's daily Bible study page focused on \
manhood and fatherhood.

You must:
1. Select ONE Bible verse (or short passage, max 2 verses) in the New Living \
Translation (NLT) that speaks to manhood, fatherhood, or leading a family well. \
Do not reuse any reference in the "recently used" list below. Use the web search \
tool to confirm the exact NLT wording (e.g. search Bible Gateway for the reference \
plus "NLT") rather than relying purely on memory — word-for-word accuracy matters.
2. Use the web search tool to find ONE real, currently-live YouTube video that \
closely relates to that verse's theme. It MUST be:
   - a standard long-form video (a normal /watch?v= URL), NOT a YouTube Short
   - talking-head / vlog style: someone speaking directly to camera (sermon clip, \
devotional, vlog), not pure cinematic B-roll
   - BETWEEN 5:00 AND 10:00 IN LENGTH — this is a hard requirement, not approximate. \
Full sermons and long teaching videos (15+ minutes) are too long and will be rejected. \
Search results usually show the duration next to the title/thumbnail — read it \
carefully before picking a candidate, and if you're unsure of the exact length, \
open the video's page or check multiple sources to confirm it before finalizing. \
Favor short devotional clips, "daily encouragement" style videos, or sermon EXCERPTS \
rather than full-length sermons, which tend to run this short.
   Do not reuse any video URL in the "recently used" list below.
3. Write a short, practical, 2-3 sentence reflection connecting the verse to \
everyday fatherhood/manhood — warm and direct, not preachy.

After you finish researching, respond with ONLY a single JSON object, no other \
text, no markdown code fences, matching exactly this shape:

{
  "verse": {"reference": "Book Chapter:Verse", "text": "exact NLT wording", "translation": "NLT"},
  "video": {"title": "...", "channel": "...", "url": "https://www.youtube.com/watch?v=...", "duration": "M:SS"},
  "reflection": "..."
}
"""


def load_json(path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return default
    return default


def recent_history_text(history):
    cutoff = datetime.now(timezone.utc).timestamp() - HISTORY_LOOKBACK_DAYS * 86400
    recent = []
    for entry in history:
        try:
            ts = datetime.fromisoformat(entry["date"]).replace(tzinfo=timezone.utc).timestamp()
        except (KeyError, ValueError):
            continue
        if ts >= cutoff:
            recent.append(f'- {entry.get("reference", "?")} / {entry.get("videoUrl", "?")}')
    return "\n".join(recent) if recent else "(none)"


def extract_json(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("No JSON object found in model output")
    return json.loads(match.group(0))


def ask_claude(client, history_text, feedback=None):
    user_prompt = f"Recently used verses/videos (do not repeat):\n{history_text}"
    if feedback:
        user_prompt += f"\n\nYour previous pick was rejected: {feedback}\nPlease try again with a different verse and/or video."

    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 8}],
        messages=[{"role": "user", "content": user_prompt}],
    )

    text_blocks = [b.text for b in response.content if getattr(b, "type", None) == "text"]
    if not text_blocks:
        raise ValueError("Model returned no text content")
    return extract_json(text_blocks[-1])


def validate_video(url, youtube_api_key):
    match = YOUTUBE_URL_RE.search(url or "")
    if not match:
        return None, "URL is not a standard youtube.com/watch or youtu.be link"
    video_id = match.group(1)

    try:
        oembed = requests.get(
            "https://www.youtube.com/oembed",
            params={"url": f"https://www.youtube.com/watch?v={video_id}", "format": "json"},
            timeout=15,
        )
        if oembed.status_code != 200:
            return None, f"oEmbed lookup failed ({oembed.status_code}); video may not exist"
        oembed_data = oembed.json()
    except requests.RequestException as exc:
        return None, f"oEmbed request error: {exc}"

    if not youtube_api_key:
        return {
            "video_id": video_id,
            "title": oembed_data.get("title"),
            "channel": oembed_data.get("author_name"),
            "thumbnail": oembed_data.get("thumbnail_url"),
            "duration_seconds": None,
        }, None

    try:
        data_api = requests.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={"part": "contentDetails,snippet", "id": video_id, "key": youtube_api_key},
            timeout=15,
        )
        data_api.raise_for_status()
        items = data_api.json().get("items", [])
    except requests.RequestException as exc:
        return None, f"YouTube Data API request error: {exc}"

    if not items:
        return None, "Video not found via YouTube Data API"

    iso_duration = items[0]["contentDetails"]["duration"]
    duration_seconds = parse_iso8601_duration(iso_duration)
    if not (MIN_DURATION_SECONDS <= duration_seconds <= MAX_DURATION_SECONDS):
        actual = format_duration(duration_seconds)
        direction = "too long" if duration_seconds > MAX_DURATION_SECONDS else "too short"
        return None, (
            f'"{items[0]["snippet"]["title"]}" is actually {actual} long ({direction}). '
            f"Need a different video between 5:00 and 10:00."
        )

    return {
        "video_id": video_id,
        "title": items[0]["snippet"]["title"],
        "channel": items[0]["snippet"]["channelTitle"],
        "thumbnail": f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg",
        "duration_seconds": duration_seconds,
    }, None


def parse_iso8601_duration(duration):
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration)
    if not match:
        return 0
    hours, minutes, seconds = (int(g) if g else 0 for g in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def format_duration(total_seconds):
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}:{seconds:02d}"


def main():
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if not anthropic_key:
        print("ANTHROPIC_API_KEY is not set; aborting.", file=sys.stderr)
        sys.exit(1)
    youtube_api_key = os.environ.get("YOUTUBE_API_KEY")

    client = anthropic.Anthropic(api_key=anthropic_key)
    history = load_json(HISTORY_PATH, [])
    history_text = recent_history_text(history)

    feedback = None
    accepted = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            candidate = ask_claude(client, history_text, feedback)
            video_info, error = validate_video(candidate.get("video", {}).get("url"), youtube_api_key)
            if error:
                print(f"Attempt {attempt}: rejected — {error}", file=sys.stderr)
                feedback = error
                continue

            candidate["video"]["thumbnail"] = video_info["thumbnail"]
            if video_info["duration_seconds"] is not None:
                candidate["video"]["duration"] = format_duration(video_info["duration_seconds"])
            accepted = candidate
            break
        except Exception as exc:  # noqa: BLE001 - broad by design, this must never crash the Action
            print(f"Attempt {attempt}: error — {exc}", file=sys.stderr)
            feedback = str(exc)

    if accepted is None:
        print("All attempts failed; leaving existing data.json untouched.", file=sys.stderr)
        sys.exit(0)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    entry = {
        "date": today,
        "verse": accepted["verse"],
        "video": accepted["video"],
        "reflection": accepted["reflection"],
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }

    DATA_PATH.write_text(json.dumps(entry, indent=2) + "\n", encoding="utf-8")

    history.append({
        "date": today,
        "reference": accepted["verse"]["reference"],
        "videoUrl": accepted["video"]["url"],
    })
    cutoff = datetime.now(timezone.utc).timestamp() - HISTORY_LOOKBACK_DAYS * 4 * 86400
    history = [
        h for h in history
        if _safe_ts(h.get("date")) >= cutoff
    ]
    HISTORY_PATH.write_text(json.dumps(history, indent=2) + "\n", encoding="utf-8")

    print(f"Published {entry['verse']['reference']} / {entry['video']['url']}")


def _safe_ts(date_str):
    try:
        return datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc).timestamp()
    except (TypeError, ValueError):
        return 0


if __name__ == "__main__":
    main()
