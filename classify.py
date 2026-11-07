"""
VideoHub - Phase 2: classify.py
Classifies candidate YouTube videos and individual comments using Google Gemini
via its OpenAI-compatible endpoint. Fetches video titles/channels from YouTube's
public oEmbed endpoint, caches all responses to disk, filters for videos with
at least MIN_RECOMMEND_COUNT 'recommend' mentions, and outputs videos.json.
"""

import argparse
from datetime import datetime
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Set, Tuple

from openai import OpenAI

# ---------------------------------------------------------------------------
# Constants & Configuration
# ---------------------------------------------------------------------------
# Threshold: Keep video only if at least N comments are labeled "recommend"
# (0 = no video is dropped for lacking "recommend" labels; labels still computed)
MIN_RECOMMEND_COUNT = 0

# Free-tier rate limits: 15 RPM means >= 4.0s minimum interval per call;
# 5.0s is used for headroom. On a 429 the interval doubles for the rest of the
# run (up to PACING_INTERVAL_CAP) and eases back toward this base after
# PACING_RELAX_AFTER consecutive clean calls.
REQUEST_INTERVAL_SECONDS = 5.0
PACING_INTERVAL_CAP = 60.0
PACING_RELAX_AFTER = 3
# Live pacing state for the current run; reset by run_classification().
PACE = {"interval": REQUEST_INTERVAL_SECONDS, "clean_calls": 0}
OEMBED_INTERVAL_SECONDS = 0.3
MAX_RETRIES = 2  # retry up to 2 times on invalid LLM output (3 attempts total)
MAX_429_RETRIES = 3
MAX_5XX_RETRIES = 3  # transient HTTP 5xx: up to 3 retries (10s/20s/40s backoff)
RETRYABLE_5XX = (500, 502, 503, 504)

CACHE_DIR = "cache"
CLASSIFICATION_CACHE_FILE = os.path.join(CACHE_DIR, "classifications.json")
OEMBED_CACHE_FILE = os.path.join(CACHE_DIR, "oembed.json")

DEFAULT_CANDIDATES_FILE = "candidates.json"
DEFAULT_TOPICS_FILE = "topics.json"
DEFAULT_OUTPUT_FILE = "videos.json"

VALID_LABELS = {"recommend", "cite", "joke", "criticize"}


def load_env(env_path: str = ".env") -> None:
    """Load key-value pairs from .env into os.environ if not already set."""
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    if key not in os.environ:
                        os.environ[key] = val


def load_topics(topics_file: str) -> List[str]:
    """Load valid topics list from topics.json."""
    if not os.path.exists(topics_file):
        default_topics = [
            "coding", "math", "science", "space", "history",
            "tech-gadgets", "money", "culture", "startups", "other"
        ]
        with open(topics_file, "w", encoding="utf-8") as f:
            json.dump(default_topics, f, indent=2)
        return default_topics
    with open(topics_file, "r", encoding="utf-8") as f:
        return json.load(f)


def load_json_cache(filepath: str) -> Dict[str, Any]:
    """Load a persistent JSON cache from disk."""
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: Failed to load {filepath} ({e}), starting fresh.")
    return {}


def save_json_cache(filepath: str, cache_data: Dict[str, Any]) -> None:
    """Save cache data to disk atomically."""
    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
    temp_file = f"{filepath}.tmp"
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(cache_data, f, indent=2, ensure_ascii=False)
    os.replace(temp_file, filepath)


def redact_secrets(text: str) -> str:
    """Strip API keys/credentials from text before printing or caching."""
    if not text:
        return ""
    redacted = text
    for env_name in ("GEMINI_API_KEY", "API_KEY", "OPENAI_API_KEY"):
        value = os.getenv(env_name)
        if value and len(value) >= 8:
            redacted = redacted.replace(value, "***REDACTED***")
    # Key-shaped tokens regardless of where they came from
    redacted = re.sub(r"AIza[0-9A-Za-z_\-]{8,}", "***REDACTED***", redacted)
    redacted = re.sub(r"\bsk-[0-9A-Za-z_\-]{8,}", "***REDACTED***", redacted)
    redacted = re.sub(r"(?i)\bbearer\s+[0-9A-Za-z_\-\.\=]{8,}", "Bearer ***REDACTED***", redacted)
    return redacted


def extract_http_status(exc: BaseException) -> Optional[int]:
    """Best-effort HTTP status code extraction from an API exception."""
    for attr in ("status_code", "http_status"):
        code = getattr(exc, attr, None)
        if isinstance(code, int):
            return code
    response = getattr(exc, "response", None)
    code = getattr(response, "status_code", None) if response is not None else None
    if isinstance(code, int):
        return code
    match = re.search(r"Error code:\s*(\d{3})", str(exc))
    if match:
        return int(match.group(1))
    return None


def build_failure_info(
    exc: Optional[BaseException], fallback_message: str = ""
) -> Dict[str, Any]:
    """Structured, secret-redacted failure record for the classification cache."""
    if exc is not None:
        message = redact_secrets(str(exc)) or redact_secrets(type(exc).__name__)
        http_status = extract_http_status(exc)
    else:
        message = redact_secrets(fallback_message)
        http_status = None
    return {
        "status": "failed",
        "http_status": http_status,
        "error": message[:500],
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def atomic_write_json(filepath: str, data: Any) -> None:
    """Write JSON atomically (temp file + rename) so readers never see a partial file."""
    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
    temp_file = f"{filepath}.tmp"
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(temp_file, filepath)


# ---------------------------------------------------------------------------
# Comment Selection
# ---------------------------------------------------------------------------
def truncate_window_around_video_url(text: str, video_id: str, max_chars: int = 500) -> str:
    """
    Truncate `text` to `max_chars` using a window centered on the first
    youtube.com / youtu.be URL that points at `video_id`, so that link is never
    cut. Cut sides are marked with "...". Falls back to head truncation when no
    such URL is found.
    """
    if len(text) <= max_chars:
        return text

    url_re = re.compile(
        r"https?://(?:www\.|m\.)?(?:"
        r"youtube\.com/(?:watch\?(?:[^#\s]*&)?v=|embed/|shorts/|v/|live/)"
        r"|youtu\.be/)" + re.escape(video_id) + r"[^\s<>\"']*"
    )
    match = url_re.search(text)
    if not match:
        return text[:max_chars]

    url_start, url_end = match.span()
    url_len = url_end - url_start
    total = len(text)
    center = (url_start + url_end) // 2

    # Budget of raw text after reserving "..." markers on both cut sides
    budget = max_chars - 6
    if budget >= url_len:
        win_start = center - budget // 2
        if win_start < 0:
            win_start = 0
        if win_start + budget > total:
            win_start = total - budget
        win_end = win_start + budget
    else:
        # Window cannot hold the link plus markers: keep the whole URL anyway.
        win_start, win_end = url_start, url_end

    prefix = "..." if win_start > 0 else ""
    suffix = "..." if win_end < total else ""
    return prefix + text[win_start:win_end] + suffix


def select_candidate_comments(
    mentions: List[Dict[str, Any]],
    max_comments: int = 12,
    max_chars: int = 500,
    video_id: str = "",
) -> List[Dict[str, Any]]:
    """
    Select up to `max_comments` mentions for classification:
    - 6 SHORT: among comments whose URL-stripped text is >= 15 chars, the 6
      with the shortest stripped length.
    - 6 RICH: the richest of the remaining eligible comments (distinct authors
      preferred). Bare links (< 15 stripped chars) are excluded entirely.
      Fewer short comments are filled by rich ones and vice versa.
    - Truncation keeps a window around this video's URL (see
      truncate_window_around_video_url); original mention order is restored.
    """

    def stripped_len(m: Dict[str, Any]) -> int:
        return len(re.sub(r"https?://\S+", "", m.get("text", "")).strip())

    short_quota = min(6, max_comments // 2)
    rich_quota = max_comments - short_quota

    eligible = []
    for i, m in enumerate(mentions):
        s_len = stripped_len(m)
        if s_len >= 15:
            eligible.append((i, m, s_len))

    # SHORT: the shortest eligible comments (original order breaks ties)
    short_sel = sorted(eligible, key=lambda t: (t[2], t[0]))[:short_quota]
    short_idx = {t[0] for t in short_sel}
    remaining = [t for t in eligible if t[0] not in short_idx]

    # RICH: richest of the remaining, distinct authors preferred
    used_authors = {t[1].get("author", "anonymous") for t in short_sel}
    rich_sorted = sorted(remaining, key=lambda t: (-t[2], t[0]))
    rich_sel: List[Tuple[int, Dict[str, Any], int]] = []
    for t in rich_sorted:
        if len(rich_sel) >= rich_quota:
            break
        author = t[1].get("author", "anonymous")
        if author in used_authors:
            continue
        used_authors.add(author)
        rich_sel.append(t)
    rich_idx = {t[0] for t in rich_sel}
    for t in rich_sorted:
        if len(rich_sel) >= rich_quota:
            break
        if t[0] in rich_idx:
            continue
        rich_sel.append(t)

    # Restore original mention order, then window-truncate to max_chars
    chosen = sorted(short_sel + rich_sel, key=lambda t: t[0])
    result = []
    for _, m, _ in chosen:
        text = truncate_window_around_video_url(m.get("text", ""), video_id, max_chars)
        result.append({
            "id": str(m.get("id", "")),
            "author": m.get("author", "anonymous"),
            "text": text,
        })
    return result


# ---------------------------------------------------------------------------
# YouTube oEmbed Lookup
# ---------------------------------------------------------------------------
def fetch_youtube_oembed(video_id: str, oembed_cache: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """
    Fetch title and channel name from YouTube's public oEmbed endpoint.
    Returns dict with {"title": ..., "channel": ...} or None if unavailable/404.
    """
    if video_id in oembed_cache:
        cached = oembed_cache[video_id]
        if cached.get("status") == "unavailable":
            return None
        return {"title": cached["title"], "channel": cached["channel"]}

    url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) VideoHub/1.0"})

    try:
        time.sleep(OEMBED_INTERVAL_SECONDS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            title = html.unescape(data.get("title", "").strip())
            channel = html.unescape(data.get("author_name", "").strip())
            if not title:
                oembed_cache[video_id] = {"status": "unavailable"}
                save_json_cache(OEMBED_CACHE_FILE, oembed_cache)
                return None

            result = {"title": title, "channel": channel}
            oembed_cache[video_id] = {"status": "ok", "title": title, "channel": channel}
            save_json_cache(OEMBED_CACHE_FILE, oembed_cache)
            return result
    except urllib.error.HTTPError as e:
        # Video deleted, private, or 404/400
        oembed_cache[video_id] = {"status": "unavailable", "code": e.code}
        save_json_cache(OEMBED_CACHE_FILE, oembed_cache)
        return None
    except Exception as e:
        print(f"oEmbed error for {video_id}: {e}")
        return None


# ---------------------------------------------------------------------------
# Gemini OpenAI-Compatible Classification
# ---------------------------------------------------------------------------
def parse_and_validate_response(
    raw_text: str,
    valid_topics: List[str],
    expected_comment_ids: Set[str],
) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """Parse JSON and validate schema and topics."""
    # Strip markdown code blocks if present
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    cleaned = cleaned.strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        return False, None, f"JSONDecodeError: {e}"

    if not isinstance(data, dict):
        return False, None, "Response is not a JSON object"

    summary = data.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        return False, None, "Missing or empty 'summary' string"

    topic = data.get("topic")
    if topic not in valid_topics:
        return False, None, f"Invalid topic '{topic}'. Must be one of: {valid_topics}"

    labels = data.get("comment_labels")
    if not isinstance(labels, list) or len(labels) == 0:
        return False, None, "'comment_labels' must be a non-empty list"

    parsed_labels = []
    seen_ids: Set[str] = set()
    for item in labels:
        if not isinstance(item, dict):
            return False, None, "Item in 'comment_labels' is not an object"
        cid = str(item.get("comment_id", "")).strip()
        label = str(item.get("label", "")).strip().lower()
        if label not in VALID_LABELS:
            return False, None, f"Invalid label '{label}' for comment {cid}. Must be in {VALID_LABELS}"
        if cid in seen_ids:
            # Exactly one label per comment_id: keep the first, drop duplicates.
            continue
        seen_ids.add(cid)
        parsed_labels.append({"comment_id": cid, "label": label})

    return True, {
        "summary": summary.strip(),
        "topic": topic,
        "comment_labels": parsed_labels,
    }, "OK"


def note_rate_limit() -> float:
    """Raise the adaptive pacing interval after a 429: double it, up to the cap."""
    new_interval = min(PACE["interval"] * 2.0, PACING_INTERVAL_CAP)
    if new_interval != PACE["interval"]:
        PACE["interval"] = new_interval
        print(
            f"Pacing raised to {PACE['interval']:.1f}s per call "
            f"(cap {PACING_INTERVAL_CAP:.1f}s)."
        )
    PACE["clean_calls"] = 0
    return PACE["interval"]


def note_clean_call() -> float:
    """After PACING_RELAX_AFTER consecutive clean calls, ease pacing one step."""
    if PACE["interval"] <= REQUEST_INTERVAL_SECONDS:
        PACE["clean_calls"] = 0
        return PACE["interval"]
    PACE["clean_calls"] += 1
    if PACE["clean_calls"] >= PACING_RELAX_AFTER:
        PACE["interval"] = max(REQUEST_INTERVAL_SECONDS, PACE["interval"] / 2.0)
        PACE["clean_calls"] = 0
        print(f"Pacing relaxed to {PACE['interval']:.1f}s per call.")
    return PACE["interval"]


def call_gemini_classification(
    client: OpenAI,
    model: str,
    video_id: str,
    comments: List[Dict[str, Any]],
    topics: List[str],
    title: str = "",
    channel: str = "",
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    Call Gemini API with bounded retries and exponential backoff.
    `title` and `channel` (from oEmbed) are included in the prompt so the
    summary can describe the video itself.
    Returns (classification_dict, None) on success, or
    (None, failure_info) with secret-redacted error details on failure.
    On daily quota exhaustion the process exits cleanly (progress is cached).
    """
    topics_list_str = ", ".join(f'"{t}"' for t in topics)
    comments_payload = "\n".join(
        f"[Comment ID: {c['id']}, Author: {c['author']}]\n{c['text']}\n"
        for c in comments
    )
    expected_ids = {c["id"] for c in comments}

    system_prompt = (
        "You are an expert content analyzer indexing community discussions from Hacker News.\n"
        "Analyze the provided comments referencing a YouTube video and output strict JSON with:\n"
        "1. 'summary': Describe the VIDEO itself in ONE sentence of at most 25 words, using the "
        "video title and channel plus what the comments reveal about its content. "
        "Never mention commenters, comments, discussion, or people. Do not start with 'The video'. "
        "Example: \"A lecture by Dr. Robert Lustig arguing that fructose drives obesity and metabolic disease.\"\n"
        f"2. 'topic': Exactly one topic from this list: [{topics_list_str}].\n"
        "   Definitions (pick the single best fit):\n"
        "     coding = programming, software, systems, databases;\n"
        "     tech-gadgets = consumer hardware and devices;\n"
        "     science = natural sciences;\n"
        "     math = mathematics;\n"
        "     space = astronomy and space exploration;\n"
        "     history = historical events and figures;\n"
        "     money = finance and economics;\n"
        "     startups = founding and building companies;\n"
        "     culture = society, politics, law, media;\n"
        "     other = anything else.\n"
        "3. 'comment_labels': An array with EXACTLY ONE object per input comment_id. Every comment_id you "
        "were given must appear exactly once - no duplicates, none missing.\n"
        "   Allowed label values:\n"
        "   - 'recommend': The commenter explicitly urges others to watch the video, or says it is worth "
        "watching, excellent, or must-see (e.g. 'everyone needs to watch this').\n"
        "   - 'cite': The commenter links the video as evidence, a source, or a quote supporting a point in "
        "a discussion about something else (neutral references and timestamps count as cite).\n"
        "   - 'joke': A meme or humorous reference to the video ('obligatory reference', 'for anyone too "
        "young to get the reference', quoting a line for laughs).\n"
        "   - 'criticize': The commenter says the video is wrong, bad, or misleading.\n"
        "   RULE: when unsure, choose 'cite'. Use 'recommend' only when the commenter is clearly telling "
        "others to watch the video.\n"
        "Output ONLY the JSON object. Do not include markdown formatting or extra text."
    )

    user_prompt = (
        f"Video ID: {video_id}\n"
        f"Title: {title}\n"
        f"Channel: {channel}\n\n"
        f"Comments referencing this video:\n{comments_payload}\n\n"
        "Respond with strict JSON."
    )

    coverage_retry_used = False
    for attempt in range(MAX_RETRIES + 1):
        backoff_sleep = 10.0
        for rate_retry in range(MAX_429_RETRIES + 1):
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.2,
                )
                raw_content = response.choices[0].message.content or ""
                break
            except Exception as e:
                err_msg = redact_secrets(str(e))
                http_status = extract_http_status(e)
                # Check for 429 rate limit or quota exhaustion
                if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                    # Check if daily cap was hit
                    if "daily" in err_msg.lower() or "per_day" in err_msg.lower():
                        print(f"\n[FATAL] Daily quota cap reached on Gemini API: {err_msg}")
                        print("Stopping cleanly. All progress has been cached.")
                        sys.exit(0)

                    # Adaptive pacing: back off subsequent calls in this run.
                    note_rate_limit()

                    if rate_retry < MAX_429_RETRIES:
                        print(f"Rate limited (429). Backing off {backoff_sleep:.1f}s before retry {rate_retry + 1}/{MAX_429_RETRIES}...")
                        time.sleep(backoff_sleep)
                        backoff_sleep *= 2.0
                        continue
                    else:
                        print(f"Exceeded 429 retries for video {video_id}: {err_msg}")
                        return None, build_failure_info(e)
                elif http_status in RETRYABLE_5XX:
                    # Transient server-side errors: bounded retries with 10s/20s/40s backoff
                    if rate_retry < MAX_5XX_RETRIES:
                        print(f"HTTP {http_status} from Gemini for video {video_id}. Backing off {backoff_sleep:.1f}s before retry {rate_retry + 1}/{MAX_5XX_RETRIES}...")
                        time.sleep(backoff_sleep)
                        backoff_sleep *= 2.0
                        continue
                    else:
                        print(f"Exceeded 5xx retries for video {video_id}: {err_msg}")
                        return None, build_failure_info(e)
                else:
                    print(f"API call error for video {video_id}: {err_msg}")
                    return None, build_failure_info(e)

        # Validate JSON output
        is_valid, parsed_data, err_reason = parse_and_validate_response(raw_content, topics, expected_ids)
        if is_valid and parsed_data:
            # Exactly one label per input comment_id: retry once when any are
            # missing, then accept and let the leftovers become "unlabeled".
            labeled_ids = {item["comment_id"] for item in parsed_data.get("comment_labels", [])}
            missing_ids = sorted(expected_ids - labeled_ids)
            if missing_ids and not coverage_retry_used:
                coverage_retry_used = True
                print(
                    f"Missing labels for {len(missing_ids)} comment(s) "
                    f"({', '.join(missing_ids)}) - retrying once..."
                )
                time.sleep(2.0)
                continue
            if missing_ids:
                print(
                    f"Accepted with {len(missing_ids)} comment(s) left as "
                    f"'unlabeled': {', '.join(missing_ids)}."
                )
            return parsed_data, None

        print(f"Validation failed for {video_id} (attempt {attempt + 1}/{MAX_RETRIES + 1}): {err_reason}")
        if attempt < MAX_RETRIES:
            time.sleep(2.0)

    print(f"Marking video {video_id} as 'failed' after {MAX_RETRIES + 1} attempts.")
    return None, build_failure_info(
        None,
        f"Invalid model output after {MAX_RETRIES + 1} attempts: {err_reason}",
    )


# ---------------------------------------------------------------------------
# Main Classification Routine
# ---------------------------------------------------------------------------
def compute_recent_users(mentions: List[Dict[str, Any]], cutoff_ts: int) -> int:
    """Distinct authors whose mention timestamp is at or after cutoff_ts (UTC)."""
    recent: Set[str] = set()
    for m in mentions:
        ts = m.get("created_utc")
        if isinstance(ts, (int, float)) and ts >= cutoff_ts:
            recent.add(str(m.get("author", "anonymous")))
    return len(recent)


def linked_year_range(mentions: List[Dict[str, Any]]) -> Tuple[Optional[int], Optional[int]]:
    """(first, last) UTC years of the mention timestamps; (None, None) if none are valid."""
    years = []
    for m in mentions:
        ts = m.get("created_utc")
        if not isinstance(ts, (int, float)):
            continue
        try:
            years.append(time.gmtime(ts).tm_year)
        except (OverflowError, OSError, ValueError):
            continue
    if not years:
        return None, None
    return min(years), max(years)


def run_classification(
    candidates_file: str = DEFAULT_CANDIDATES_FILE,
    topics_file: str = DEFAULT_TOPICS_FILE,
    output_file: str = DEFAULT_OUTPUT_FILE,
    top: int = 300,
    skip: int = 0,
    limit: Optional[int] = None,
) -> None:
    load_env()

    # Reset adaptive pacing for this run (base interval, no pending backoff).
    PACE["interval"] = REQUEST_INTERVAL_SECONDS
    PACE["clean_calls"] = 0

    base_url = os.getenv("BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("API_KEY")
    # Only fall back to OPENAI_API_KEY if not a generic placeholder
    if not api_key:
        candidate_key = os.getenv("OPENAI_API_KEY", "")
        if candidate_key and not candidate_key.lower().startswith("your_"):
            api_key = candidate_key

    model = os.getenv("MODEL", "gemini-2.0-flash")

    if not api_key or api_key.lower().startswith("your_"):
        print("\n[ERROR] GEMINI_API_KEY is not configured with a valid key.")
        print("Please set your Gemini API key in videohub/.env or pass it as an environment variable:")
        print("  $env:GEMINI_API_KEY = \"AIzaSy...\"")
        print("See .env.example for guidance.")
        sys.exit(1)

    topics = load_topics(topics_file)
    print(f"Loaded {len(topics)} valid topics from {topics_file}: {topics}")

    if not os.path.exists(candidates_file):
        print(f"[ERROR] Candidates file '{candidates_file}' not found.")
        print("Please run pipeline.py first to generate candidates.json.")
        sys.exit(1)

    with open(candidates_file, "r", encoding="utf-8") as f:
        candidates: List[Dict[str, Any]] = json.load(f)

    print(f"Total candidates in {candidates_file}: {len(candidates)}")

    # Rank by recent activity: distinct authors active in the last 3 years
    # (UTC) first, then total distinct users, then distinct months.
    cutoff_ts = int(time.time()) - 3 * 365 * 24 * 3600
    for c in candidates:
        c["recent_users"] = compute_recent_users(c.get("mentions", []), cutoff_ts)

    # Sort candidates by recent_users descending, then distinct_users
    # descending, then distinct_months descending
    candidates.sort(
        key=lambda c: (c.get("recent_users", 0), c.get("distinct_users", 0), c.get("distinct_months", 0)),
        reverse=True,
    )

    # Skip the first N candidates after sorting (used to page through batches)
    if skip:
        candidates = candidates[skip:]
        print(f"Skipped first {skip} candidates (--skip {skip}); {len(candidates)} remain.")

    # Slice top N candidates
    if top and len(candidates) > top:
        candidates = candidates[:top]
        print(f"Filtered to top {top} candidates sorted by recent_users, then distinct_users, then distinct_months.")

    # Slice limit for testing
    if limit is not None:
        candidates = candidates[:limit]
        print(f"Applying --limit {limit}: testing on {len(candidates)} videos.")

    # Load caches
    classification_cache = load_json_cache(CLASSIFICATION_CACHE_FILE)
    oembed_cache = load_json_cache(OEMBED_CACHE_FILE)

    # Fetch oEmbed (title & channel) for every candidate BEFORE any Gemini
    # call, reusing the on-disk cache with the usual 0.3s pacing. Unavailable
    # videos (404/private/removed) are excluded from this batch and never
    # reach Gemini.
    print(f"Fetching oEmbed metadata for {len(candidates)} video(s) before any Gemini call...")
    oembed_results: Dict[str, Optional[Dict[str, str]]] = {}
    for cand in candidates:
        oembed_results[cand["video_id"]] = fetch_youtube_oembed(cand["video_id"], oembed_cache)

    # Plan counts (oEmbed ran first, so unavailable videos are known now):
    #   unavailable -> no Gemini call, excluded from videos.json
    #   cached      -> successful cache entries are reused
    #   retry       -> entries with status "failed" are retried once per run
    #   the rest    -> fresh Gemini calls
    unavailable_count = 0
    cached_count = 0
    retry_count = 0
    for c in candidates:
        c_vid = c["video_id"]
        c_entry = classification_cache.get(c_vid)
        c_status = c_entry.get("status") if isinstance(c_entry, dict) else None
        if oembed_results.get(c_vid) is None:
            unavailable_count += 1
        elif c_status in ("failed", "unavailable"):
            retry_count += 1
        elif c_entry is not None:
            cached_count += 1
    calls_needed = len(candidates) - unavailable_count - cached_count

    print("\n" + "=" * 60)
    print("PLANNING CLASSIFICATION BATCH")
    print("=" * 60)
    print(f"Target videos to classify:  {len(candidates)}")
    print(f"Skipped as unavailable:     {unavailable_count}")
    print(f"Already cached on disk:     {cached_count}")
    print(f"Failed, will retry once:    {retry_count}")
    print(f"API calls planned:          {calls_needed}")
    print(f"Model ID:                   {model}")
    print(f"Base URL:                   {base_url}")
    print(f"Pacing interval:            {REQUEST_INTERVAL_SECONDS}s base per call (<= 15 RPM limit; "
          f"doubles up to {PACING_INTERVAL_CAP:.0f}s after 429s, eases back after {PACING_RELAX_AFTER} clean calls)")
    print(f"Recommend threshold:        >= {MIN_RECOMMEND_COUNT} 'recommend' labels required to keep")
    print("=" * 60 + "\n")

    client = OpenAI(api_key=api_key, base_url=base_url)

    processed_results: List[Dict[str, Any]] = []

    for idx, cand in enumerate(candidates, 1):
        vid = cand["video_id"]
        mentions = cand.get("mentions", [])

        # oEmbed (title & channel) was fetched BEFORE any Gemini call; reuse
        # that result so videos.json keeps the same title/channel without a
        # second oEmbed request.
        oembed_data = oembed_results[vid]
        if oembed_data is None:
            # Unavailable (404/private/removed) or oEmbed lookup failed:
            # do NOT call Gemini and exclude the video from videos.json.
            if oembed_cache.get(vid, {}).get("status") == "unavailable":
                if classification_cache.get(vid, {}).get("status") != "unavailable":
                    classification_cache[vid] = {
                        "status": "unavailable",
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    }
                    save_json_cache(CLASSIFICATION_CACHE_FILE, classification_cache)
                print(f"[{idx}/{len(candidates)}] {vid} -> SKIPPED as unavailable (no Gemini call).")
            else:
                print(f"[{idx}/{len(candidates)}] {vid} -> SKIPPED (oEmbed lookup failed; no Gemini call, retry next run).")
            continue

        sample_comments = select_candidate_comments(mentions, max_comments=12, max_chars=500, video_id=vid)

        # Check classification cache: reuse successes, retry failures once per run
        cached_entry = classification_cache.get(vid)
        cached_status = cached_entry.get("status") if isinstance(cached_entry, dict) else None
        cached_failed = cached_status == "failed"
        if cached_entry is not None and not cached_failed and cached_status != "unavailable":
            classification = cached_entry
            print(f"[{idx}/{len(candidates)}] {vid} -> loaded from classification cache.")
        else:
            action = "retrying previously failed entry" if cached_failed else "calling Gemini API"
            print(f"[{idx}/{len(candidates)}] {vid} -> {action} ({len(sample_comments)} comments)...", end=" ", flush=True)
            classification, failure_info = call_gemini_classification(
                client, model, vid, sample_comments, topics,
                title=oembed_data.get("title", ""),
                channel=oembed_data.get("channel", ""),
            )
            if classification is not None:
                classification_cache[vid] = classification
                save_json_cache(CLASSIFICATION_CACHE_FILE, classification_cache)
                print(f"Done. Topic: '{classification['topic']}'")
                note_clean_call()  # adaptive pacing eases back after clean calls
            else:
                classification_cache[vid] = failure_info or build_failure_info(
                    None, "Unknown classification failure"
                )
                save_json_cache(CLASSIFICATION_CACHE_FILE, classification_cache)
                print("FAILED.")
            time.sleep(PACE["interval"])

        # Skip failed classifications
        if not classification or classification.get("status") == "failed":
            continue

        # Map labels to comments
        label_map = {item["comment_id"]: item["label"] for item in classification.get("comment_labels", [])}
        recommend_count = sum(1 for label in label_map.values() if label == "recommend")

        first_linked_year, last_linked_year = linked_year_range(mentions)

        processed_results.append({
            "video_id": vid,
            "title": oembed_data.get("title", ""),
            "channel": oembed_data.get("channel", ""),
            "summary": classification.get("summary", ""),
            "topic": classification.get("topic", ""),
            "distinct_users": cand.get("distinct_users", 0),
            "distinct_months": cand.get("distinct_months", 0),
            "first_linked_year": first_linked_year,
            "last_linked_year": last_linked_year,
            "sample_comments": sample_comments,
            "label_map": label_map,
            "recommend_count": recommend_count,
            "oembed_valid": True,  # unavailable videos are skipped before this point
            "mentions": mentions,
        })

    # Filter for KEPT videos
    kept_videos: List[Dict[str, Any]] = []
    for item in processed_results:
        # Must have at least MIN_RECOMMEND_COUNT 'recommend' labels and valid oEmbed
        if item["recommend_count"] >= MIN_RECOMMEND_COUNT and item["oembed_valid"]:
            # Attach labels back to original mentions
            annotated_comments = []
            for m in item["mentions"]:
                m_copy = dict(m)
                m_copy["label"] = item["label_map"].get(str(m.get("id")), "unlabeled")
                annotated_comments.append(m_copy)

            kept_videos.append({
                "video_id": item["video_id"],
                "title": item["title"],
                "channel": item["channel"],
                "summary": item["summary"],
                "topic": item["topic"],
                "distinct_users": item["distinct_users"],
                "distinct_months": item["distinct_months"],
                "first_linked_year": item["first_linked_year"],
                "last_linked_year": item["last_linked_year"],
                "comments": annotated_comments,
            })

    # Write output atomically, and never destroy an existing dataset when this
    # run produced no successful classifications (e.g. temporary API outage).
    if kept_videos or not os.path.exists(output_file):
        atomic_write_json(output_file, kept_videos)
        write_action = f"Successfully saved {len(kept_videos)} kept videos to {output_file}."
    else:
        write_action = (
            f"[PRESERVED] No successful classifications in this run; "
            f"existing '{output_file}' was left untouched. "
            f"Delete it first if you intentionally want an empty dataset."
        )

    print("\n" + "=" * 60)
    print("CLASSIFICATION & VERIFICATION REPORT")
    print("=" * 60)
    print(f"Total videos processed:  {len(processed_results)}")
    print(f"Videos kept in {output_file}: {len(kept_videos)}")
    print(f"Videos dropped:          {len(processed_results) - len(kept_videos)}")
    print("=" * 60)

    # Detailed print for verification (especially when running --limit 5)
    for i, item in enumerate(processed_results, 1):
        status_tag = "KEPT" if (item["recommend_count"] >= MIN_RECOMMEND_COUNT and item["oembed_valid"]) else "DROPPED"
        drop_reason = ""
        if not item["oembed_valid"]:
            drop_reason = " (oEmbed 404/Unavailable)"
        elif item["recommend_count"] < MIN_RECOMMEND_COUNT:
            drop_reason = f" ({item['recommend_count']}/{MIN_RECOMMEND_COUNT} 'recommend' labels)"

        print(f"\n--- [{i}/{len(processed_results)}] Video: https://youtu.be/{item['video_id']} [{status_tag}{drop_reason}] ---")
        print(f"Title:    {item['title']}")
        print(f"Channel:  {item['channel']}")
        print(f"Topic:    {item['topic']}")
        print(f"Summary:  {item['summary']}")
        print(f"Metrics:  {item['distinct_months']} months, {item['distinct_users']} users, {item['recommend_count']} recommendations")
        print("Comments & Labels:")
        for sc in item["sample_comments"]:
            cid = sc["id"]
            lbl = item["label_map"].get(cid, "unlabeled")
            author = sc["author"]
            # Short preview of comment text
            txt = sc["text"].replace("\n", " ").strip()
            if len(txt) > 120:
                txt = txt[:117] + "..."
            print(f"  * [{lbl.upper():^10}] ({author}): \"{txt}\"")

    print("\n" + "=" * 60)
    print(write_action)
    print("=" * 60 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Classify YouTube candidate videos with Gemini API.")
    parser.add_argument("--candidates", default=DEFAULT_CANDIDATES_FILE, help="Path to candidates.json")
    parser.add_argument("--topics", default=DEFAULT_TOPICS_FILE, help="Path to topics.json")
    parser.add_argument("--output", default=DEFAULT_OUTPUT_FILE, help="Path to videos.json output")
    parser.add_argument("--top", type=int, default=300, help="Classify top N candidates (default: 300)")
    parser.add_argument("--skip", type=int, default=0, help="Skip the first N candidates after sorting (before --top/--limit)")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of videos to classify (e.g. 5)")
    args = parser.parse_args()

    run_classification(
        candidates_file=args.candidates,
        topics_file=args.topics,
        output_file=args.output,
        top=args.top,
        skip=args.skip,
        limit=args.limit,
    )
