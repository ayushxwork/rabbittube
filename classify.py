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
MIN_RECOMMEND_COUNT = 2

# Free-tier rate limits for gemini-2.0-flash (15 RPM -> 4.0s minimum interval)
REQUEST_INTERVAL_SECONDS = 4.0
OEMBED_INTERVAL_SECONDS = 0.3
MAX_RETRIES = 2  # retry up to 2 times on invalid LLM output (3 attempts total)
MAX_429_RETRIES = 3

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


# ---------------------------------------------------------------------------
# Comment Selection
# ---------------------------------------------------------------------------
def select_candidate_comments(mentions: List[Dict[str, Any]], max_comments: int = 8, max_chars: int = 500) -> List[Dict[str, Any]]:
    """
    Select up to `max_comments` mentions for classification:
    - Prefers distinct authors first.
    - Truncates comment text to `max_chars`.
    """
    selected: List[Dict[str, Any]] = []
    seen_authors: Set[str] = set()
    overflow: List[Dict[str, Any]] = []

    for m in mentions:
        author = m.get("author", "anonymous")
        if author not in seen_authors:
            seen_authors.add(author)
            selected.append(m)
            if len(selected) == max_comments:
                break
        else:
            overflow.append(m)

    if len(selected) < max_comments:
        for m in overflow:
            selected.append(m)
            if len(selected) == max_comments:
                break

    # Prepare truncated copies
    result = []
    for m in selected:
        text = m.get("text", "")
        if len(text) > max_chars:
            text = text[:max_chars]
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
    for item in labels:
        if not isinstance(item, dict):
            return False, None, "Item in 'comment_labels' is not an object"
        cid = str(item.get("comment_id", "")).strip()
        label = str(item.get("label", "")).strip().lower()
        if label not in VALID_LABELS:
            return False, None, f"Invalid label '{label}' for comment {cid}. Must be in {VALID_LABELS}"
        parsed_labels.append({"comment_id": cid, "label": label})

    return True, {
        "summary": summary.strip(),
        "topic": topic,
        "comment_labels": parsed_labels,
    }, "OK"


def call_gemini_classification(
    client: OpenAI,
    model: str,
    video_id: str,
    comments: List[Dict[str, Any]],
    topics: List[str],
) -> Optional[Dict[str, Any]]:
    """
    Call Gemini API with retries and exponential backoff.
    Returns validated classification dict or None on fatal failure/daily quota.
    """
    topics_list_str = ", ".join(f'"{t}"' for t in topics)
    comments_payload = "\n".join(
        f"[Comment ID: {c['id']}, Author: {c['author']}]\n{c['text']}\n"
        for c in comments
    )
    expected_ids = {c["id"] for c in comments}

    system_prompt = (
        "You are an expert content analyzer indexing community recommendations from Hacker News.\n"
        "Analyze the provided comments referencing a YouTube video and output strict JSON with:\n"
        "1. 'summary': Exactly one sentence explaining what the video covers and why commenters recommend/discuss it.\n"
        f"2. 'topic': Exactly one topic from this list: [{topics_list_str}].\n"
        "3. 'comment_labels': An array of objects with 'comment_id' and 'label' for each comment.\n"
        "   Allowed label values:\n"
        "   - 'recommend': The commenter endorses, praises, suggests, or shares the video as a good/helpful resource.\n"
        "   - 'cite': The commenter links the video neutrally as background proof, timestamp, or reference without endorsing it.\n"
        "   - 'joke': The commenter links the video for humor, meme, sarcasm, or punchline (e.g. Rickroll).\n"
        "   - 'criticize': The commenter links the video to refute, warn against, or criticize it.\n"
        "Output ONLY the JSON object. Do not include markdown formatting or extra text."
    )

    user_prompt = (
        f"Video ID: {video_id}\n\n"
        f"Comments referencing this video:\n{comments_payload}\n\n"
        "Respond with strict JSON."
    )

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
                err_msg = str(e)
                # Check for 429 rate limit or quota exhaustion
                if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                    # Check if daily cap was hit
                    if "daily" in err_msg.lower() or "per_day" in err_msg.lower():
                        print(f"\n[FATAL] Daily quota cap reached on Gemini API: {err_msg}")
                        print("Stopping cleanly. All progress has been cached.")
                        sys.exit(0)

                    if rate_retry < MAX_429_RETRIES:
                        print(f"Rate limited (429). Backing off {backoff_sleep:.1f}s before retry {rate_retry + 1}/{MAX_429_RETRIES}...")
                        time.sleep(backoff_sleep)
                        backoff_sleep *= 2.0
                        continue
                    else:
                        print(f"Exceeded 429 retries for video {video_id}: {e}")
                        return None
                else:
                    print(f"API call error for video {video_id}: {e}")
                    return None

        # Validate JSON output
        is_valid, parsed_data, err_reason = parse_and_validate_response(raw_content, topics, expected_ids)
        if is_valid and parsed_data:
            return parsed_data

        print(f"Validation failed for {video_id} (attempt {attempt + 1}/{MAX_RETRIES + 1}): {err_reason}")
        if attempt < MAX_RETRIES:
            time.sleep(2.0)

    print(f"Marking video {video_id} as 'failed' after {MAX_RETRIES + 1} attempts.")
    return None


# ---------------------------------------------------------------------------
# Main Classification Routine
# ---------------------------------------------------------------------------
def run_classification(
    candidates_file: str = DEFAULT_CANDIDATES_FILE,
    topics_file: str = DEFAULT_TOPICS_FILE,
    output_file: str = DEFAULT_OUTPUT_FILE,
    top: int = 300,
    limit: Optional[int] = None,
) -> None:
    load_env()

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

    # Sort candidates by distinct_months descending, then distinct_users descending
    candidates.sort(
        key=lambda c: (c.get("distinct_months", 0), c.get("distinct_users", 0)),
        reverse=True,
    )

    # Slice top N candidates
    if top and len(candidates) > top:
        candidates = candidates[:top]
        print(f"Filtered to top {top} candidates sorted by distinct_months then distinct_users.")

    # Slice limit for testing
    if limit is not None:
        candidates = candidates[:limit]
        print(f"Applying --limit {limit}: testing on {len(candidates)} videos.")

    # Load caches
    classification_cache = load_json_cache(CLASSIFICATION_CACHE_FILE)
    oembed_cache = load_json_cache(OEMBED_CACHE_FILE)

    # Count planned API requests
    cached_count = sum(1 for c in candidates if c["video_id"] in classification_cache)
    calls_needed = len(candidates) - cached_count

    print("\n" + "=" * 60)
    print("PLANNING CLASSIFICATION BATCH")
    print("=" * 60)
    print(f"Target videos to classify:  {len(candidates)}")
    print(f"Already cached on disk:     {cached_count}")
    print(f"API calls planned:          {calls_needed}")
    print(f"Model ID:                   {model}")
    print(f"Base URL:                   {base_url}")
    print(f"Pacing interval:            {REQUEST_INTERVAL_SECONDS}s per call (<= 15 RPM limit)")
    print(f"Recommend threshold:        >= {MIN_RECOMMEND_COUNT} 'recommend' labels required to keep")
    print("=" * 60 + "\n")

    client = OpenAI(api_key=api_key, base_url=base_url)

    processed_results: List[Dict[str, Any]] = []

    for idx, cand in enumerate(candidates, 1):
        vid = cand["video_id"]
        mentions = cand.get("mentions", [])
        sample_comments = select_candidate_comments(mentions, max_comments=8, max_chars=500)

        # Check classification cache
        if vid in classification_cache:
            classification = classification_cache[vid]
            print(f"[{idx}/{len(candidates)}] {vid} -> loaded from classification cache.")
        else:
            print(f"[{idx}/{len(candidates)}] {vid} -> calling Gemini API ({len(sample_comments)} comments)...", end=" ", flush=True)
            classification = call_gemini_classification(client, model, vid, sample_comments, topics)
            if classification is not None:
                classification_cache[vid] = classification
                save_json_cache(CLASSIFICATION_CACHE_FILE, classification_cache)
                print(f"Done. Topic: '{classification['topic']}'")
            else:
                classification_cache[vid] = {"status": "failed"}
                save_json_cache(CLASSIFICATION_CACHE_FILE, classification_cache)
                print("FAILED.")
            time.sleep(REQUEST_INTERVAL_SECONDS)

        # Skip failed classifications
        if not classification or classification.get("status") == "failed":
            continue

        # Map labels to comments
        label_map = {item["comment_id"]: item["label"] for item in classification.get("comment_labels", [])}
        recommend_count = sum(1 for label in label_map.values() if label == "recommend")

        # Fetch oEmbed (title & channel)
        oembed_data = fetch_youtube_oembed(vid, oembed_cache)

        processed_results.append({
            "video_id": vid,
            "title": oembed_data.get("title", "") if oembed_data else "Unavailable",
            "channel": oembed_data.get("channel", "") if oembed_data else "Unavailable",
            "summary": classification.get("summary", ""),
            "topic": classification.get("topic", ""),
            "distinct_users": cand.get("distinct_users", 0),
            "distinct_months": cand.get("distinct_months", 0),
            "sample_comments": sample_comments,
            "label_map": label_map,
            "recommend_count": recommend_count,
            "oembed_valid": (oembed_data is not None),
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
                m_copy["label"] = item["label_map"].get(str(m.get("id")), "recommend")
                annotated_comments.append(m_copy)

            kept_videos.append({
                "video_id": item["video_id"],
                "title": item["title"],
                "channel": item["channel"],
                "summary": item["summary"],
                "topic": item["topic"],
                "distinct_users": item["distinct_users"],
                "distinct_months": item["distinct_months"],
                "comments": annotated_comments,
            })

    # Write videos.json
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(kept_videos, f, indent=2, ensure_ascii=False)

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
    print(f"Successfully saved {len(kept_videos)} kept videos to {output_file}.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Classify YouTube candidate videos with Gemini API.")
    parser.add_argument("--candidates", default=DEFAULT_CANDIDATES_FILE, help="Path to candidates.json")
    parser.add_argument("--topics", default=DEFAULT_TOPICS_FILE, help="Path to topics.json")
    parser.add_argument("--output", default=DEFAULT_OUTPUT_FILE, help="Path to videos.json output")
    parser.add_argument("--top", type=int, default=300, help="Classify top N candidates (default: 300)")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of videos to classify (e.g. 5)")
    args = parser.parse_args()

    run_classification(
        candidates_file=args.candidates,
        topics_file=args.topics,
        output_file=args.output,
        top=args.top,
        limit=args.limit,
    )
