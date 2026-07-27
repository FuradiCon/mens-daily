"""
Daily pipeline for the "Scattered to Steadfast" page.

Uses the Anthropic API (with the web search tool) to pick a fresh NLT verse
about manhood/fatherhood, find a real 2-10 minute talking-head YouTube video
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
USAGE_PATH = ROOT / "usage.json"
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
HISTORY_LOOKBACK_DAYS = 120  # how far back "do not repeat" applies, both in the prompt and the hard check below
HISTORY_RETENTION_DAYS = 180  # how long entries stay in history.json before being pruned
USAGE_RETENTION_DAYS = 180

# Claude Sonnet 5 introductory pricing (through 2026-08-31) — update these if
# either the model or its pricing changes. See platform.claude.com/docs/en/about-claude/pricing.
INPUT_USD_PER_MTOK = 2.0
OUTPUT_USD_PER_MTOK = 10.0
WEB_SEARCH_USD_PER_1000 = 10.0

MIN_DURATION_SECONDS = 2 * 60
MAX_DURATION_SECONDS = 10 * 60

YOUTUBE_URL_RE = re.compile(
    r"(?:youtube\.com/watch\?v=|youtu\.be/)([A-Za-z0-9_-]{11})"
)

SYSTEM_PROMPT = """You are curating content for a men's daily Bible study page focused on \
manhood and fatherhood.

Be efficient with research: a couple of well-chosen searches per step is enough. You do \
NOT need to open every result, cross-check multiple sources, or exhaustively verify \
before answering — a separate system independently re-verifies the video's exact \
duration afterward and will tell you specifically what to fix if you're wrong, so a \
good, quick, specific guess is more valuable than an exhaustive one.

You must:
1. Select ONE Bible verse (or short passage, max 2 verses) in the New Living \
Translation (NLT) that speaks to manhood, fatherhood, or leading a family well. \
Do not reuse any reference in the "recently used" list below. One quick search to \
confirm the exact NLT wording (e.g. the reference plus "NLT") is enough — don't \
cross-check multiple sites for this.
2. One or two searches to find ONE real, currently-live YouTube video that closely \
relates to that verse's theme. It MUST be:
   - a standard long-form video (a normal /watch?v= URL), NOT a YouTube Short
   - talking-head / vlog style: someone speaking directly to camera (sermon clip, \
devotional, vlog), not pure cinematic B-roll
   - approximately 2 to 10 minutes long — go with the best duration estimate the \
search results give you (search snippets usually show it next to the title); the \
video's exact length gets independently verified after you answer, so don't spend \
extra searches confirming it yourself. Favor short devotional clips, "daily \
encouragement" style videos, or sermon excerpts, which tend to run this short, over \
full-length sermons.
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


def usage_from_response(response):
    u = response.usage
    web_searches = 0
    stu = getattr(u, "server_tool_use", None)
    if stu is not None:
        web_searches = getattr(stu, "web_search_requests", 0) or 0
    return {
        "input_tokens": getattr(u, "input_tokens", 0) or 0,
        "output_tokens": getattr(u, "output_tokens", 0) or 0,
        "web_searches": web_searches,
    }


def ask_claude(client, history_text, feedback=None):
    """Returns (candidate_or_None, usage, error_or_None). Usage is always
    populated when the API call itself succeeds — even a response with no
    parseable JSON still cost real tokens/searches and must be counted."""
    user_prompt = f"Recently used verses/videos (do not repeat):\n{history_text}"
    if feedback:
        user_prompt += f"\n\nYour previous pick was rejected: {feedback}\nPlease try again with a different verse and/or video."

    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}],
        messages=[{"role": "user", "content": user_prompt}],
    )
    usage = usage_from_response(response)

    text_blocks = [b.text for b in response.content if getattr(b, "type", None) == "text"]
    if not text_blocks:
        return None, usage, "Model returned no text content"

    try:
        candidate = extract_json(text_blocks[-1])
    except (ValueError, json.JSONDecodeError) as exc:
        return None, usage, f"Could not parse model output as JSON: {exc}"

    return candidate, usage, None


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
            f"Need a different video between 2:00 and 10:00."
        )

    return {
        "video_id": video_id,
        "title": items[0]["snippet"]["title"],
        "channel": items[0]["snippet"]["channelTitle"],
        "thumbnail": f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg",
        "duration_seconds": duration_seconds,
    }, None


def is_duplicate(candidate, history, lookback_days):
    """Hard check backing up the prompt's "don't repeat" instruction — the
    model can ignore instructions, but this always rejects an exact repeat
    of a reference or video within the lookback window."""
    cutoff = datetime.now(timezone.utc).timestamp() - lookback_days * 86400
    ref = (candidate.get("verse", {}).get("reference") or "").strip().lower()
    url = candidate.get("video", {}).get("url") or ""
    video_match = YOUTUBE_URL_RE.search(url)
    video_id = video_match.group(1) if video_match else None

    for entry in history:
        if _safe_ts(entry.get("date")) < cutoff:
            continue
        if ref and (entry.get("reference") or "").strip().lower() == ref:
            return f'"{candidate["verse"]["reference"]}" was already used on {entry["date"]}. Pick a different verse.'
        entry_match = YOUTUBE_URL_RE.search(entry.get("videoUrl") or "")
        entry_id = entry_match.group(1) if entry_match else None
        if video_id and entry_id and video_id == entry_id:
            return (
                f'That video was already used on {entry["date"]} (for {entry.get("reference", "?")}). '
                f"Pick a different video."
            )
    return None


def parse_iso8601_duration(duration):
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration)
    if not match:
        return 0
    hours, minutes, seconds = (int(g) if g else 0 for g in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def format_duration(total_seconds):
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}:{seconds:02d}"


def estimate_cost_usd(run_usage):
    input_cost = run_usage["input_tokens"] / 1_000_000 * INPUT_USD_PER_MTOK
    output_cost = run_usage["output_tokens"] / 1_000_000 * OUTPUT_USD_PER_MTOK
    search_cost = run_usage["web_searches"] / 1000 * WEB_SEARCH_USD_PER_1000
    return round(input_cost + output_cost + search_cost, 4)


def record_usage(today, run_usage, published):
    cost = estimate_cost_usd(run_usage)
    usage_history = load_json(USAGE_PATH, [])
    usage_history.append({
        "date": today,
        "attempts": run_usage["attempts"],
        "inputTokens": run_usage["input_tokens"],
        "outputTokens": run_usage["output_tokens"],
        "webSearches": run_usage["web_searches"],
        "estimatedCostUsd": cost,
        "published": published,
    })
    cutoff = datetime.now(timezone.utc).timestamp() - USAGE_RETENTION_DAYS * 86400
    usage_history = [u for u in usage_history if _safe_ts(u.get("date")) >= cutoff]
    USAGE_PATH.write_text(json.dumps(usage_history, indent=2) + "\n", encoding="utf-8")
    print(
        f"Usage: {run_usage['attempts']} attempt(s), "
        f"{run_usage['input_tokens']} in / {run_usage['output_tokens']} out tokens, "
        f"{run_usage['web_searches']} web searches, est. ${cost:.4f}"
    )


def main():
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if not anthropic_key:
        print("ANTHROPIC_API_KEY is not set; aborting.", file=sys.stderr)
        sys.exit(1)
    youtube_api_key = os.environ.get("YOUTUBE_API_KEY")

    client = anthropic.Anthropic(api_key=anthropic_key)
    history = load_json(HISTORY_PATH, [])
    history_text = recent_history_text(history)

    run_usage = {"attempts": 0, "input_tokens": 0, "output_tokens": 0, "web_searches": 0}
    feedback = None
    accepted = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            candidate, usage, ask_error = ask_claude(client, history_text, feedback)
        except Exception as exc:  # noqa: BLE001 - a real API/network failure, no usage to record
            print(f"Attempt {attempt}: error — {exc}", file=sys.stderr)
            feedback = str(exc)
            continue

        run_usage["attempts"] += 1
        run_usage["input_tokens"] += usage["input_tokens"]
        run_usage["output_tokens"] += usage["output_tokens"]
        run_usage["web_searches"] += usage["web_searches"]

        if ask_error:
            print(f"Attempt {attempt}: rejected — {ask_error}", file=sys.stderr)
            feedback = ask_error
            continue

        dup_reason = is_duplicate(candidate, history, HISTORY_LOOKBACK_DAYS)
        if dup_reason:
            print(f"Attempt {attempt}: rejected — {dup_reason}", file=sys.stderr)
            feedback = dup_reason
            continue

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

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    record_usage(today, run_usage, published=accepted is not None)

    if accepted is None:
        print("All attempts failed; leaving existing data.json untouched.", file=sys.stderr)
        sys.exit(0)

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
    cutoff = datetime.now(timezone.utc).timestamp() - HISTORY_RETENTION_DAYS * 86400
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
