"""
VideoHub - Pipeline
Reads comments.jsonl, extracts YouTube IDs, filters candidates
recommended by >= N distinct users in >= M distinct months, and outputs candidates.json.
"""

import argparse
from datetime import datetime, timezone
import json
import os
import re
from typing import Any, Dict, List, Set

YOUTUBE_REGEX = re.compile(
    r"(?:https?://)?(?:www\.|m\.)?(?:youtube\.com/(?:watch\?.*?v=|embed/|v/|shorts/)|youtu\.be/)([a-zA-Z0-9_-]{11})",
    re.IGNORECASE,
)


def extract_youtube_ids(text: str) -> List[str]:
    """Extract unique YouTube video IDs from a block of text."""
    if not text:
        return []
    matches = YOUTUBE_REGEX.findall(text)
    # Deduplicate while preserving order
    seen: Set[str] = set()
    result = []
    for vid in matches:
        if vid not in seen:
            seen.add(vid)
            result.append(vid)
    return result


def parse_month(created_utc: Any) -> str:
    """Convert Unix timestamp (int/float) or ISO string into YYYY-MM."""
    try:
        if isinstance(created_utc, (int, float)):
            dt = datetime.fromtimestamp(float(created_utc), tz=timezone.utc)
            return dt.strftime("%Y-%m")
        if isinstance(created_utc, str):
            # Attempt parsing ISO format or numeric string
            try:
                num = float(created_utc)
                dt = datetime.fromtimestamp(num, tz=timezone.utc)
                return dt.strftime("%Y-%m")
            except ValueError:
                dt = datetime.fromisoformat(created_utc.replace("Z", "+00:00"))
                return dt.strftime("%Y-%m")
    except Exception:
        pass
    return "unknown"


def run_pipeline(
    input_file: str,
    output_file: str,
    min_users: int = 2,
    min_months: int = 2,
) -> List[Dict[str, Any]]:
    # Fall back to sample_comments.jsonl if default comments.jsonl is missing
    if not os.path.exists(input_file) and os.path.exists("sample_comments.jsonl"):
        print(f"Notice: '{input_file}' not found, falling back to 'sample_comments.jsonl'")
        input_file = "sample_comments.jsonl"

    if not os.path.exists(input_file):
        raise FileNotFoundError(f"Input file '{input_file}' not found.")

    candidates_map: Dict[str, Dict[str, Any]] = {}

    with open(input_file, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                comment = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"Skipping malformed JSON on line {line_num}: {e}")
                continue

            text = comment.get("text", "")
            video_ids = extract_youtube_ids(text)
            if not video_ids:
                continue

            author = comment.get("author", "anonymous")
            created_utc = comment.get("created_utc", 0)
            month = parse_month(created_utc)

            mention_data = {
                "id": comment.get("id", f"c_{line_num}"),
                "author": author,
                "created_utc": created_utc,
                "text": text,
                "thread_title": comment.get("thread_title", ""),
                "url": comment.get("url", ""),
            }

            for vid in video_ids:
                if vid not in candidates_map:
                    candidates_map[vid] = {
                        "video_id": vid,
                        "authors": set(),
                        "months": set(),
                        "mentions": [],
                    }
                candidates_map[vid]["authors"].add(author)
                if month != "unknown":
                    candidates_map[vid]["months"].add(month)
                candidates_map[vid]["mentions"].append(mention_data)

    filtered_candidates: List[Dict[str, Any]] = []
    for vid, data in candidates_map.items():
        distinct_users = len(data["authors"])
        distinct_months = len(data["months"])

        if distinct_users >= min_users and distinct_months >= min_months:
            filtered_candidates.append(
                {
                    "video_id": vid,
                    "distinct_users": distinct_users,
                    "distinct_months": distinct_months,
                    "mentions": data["mentions"],
                }
            )

    # Sort candidates by number of mentions descending
    filtered_candidates.sort(key=lambda x: len(x["mentions"]), reverse=True)

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(filtered_candidates, f, indent=2, ensure_ascii=False)

    print(
        f"Pipeline complete: {len(filtered_candidates)} candidates written to {output_file} "
        f"(from {len(candidates_map)} total detected videos)."
    )
    return filtered_candidates


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract and filter YouTube candidate videos.")
    parser.add_argument("--input", default="comments.jsonl", help="Input JSONL file")
    parser.add_argument("--output", default="candidates.json", help="Output JSON file")
    parser.add_argument("--min-users", type=int, default=2, help="Minimum distinct users")
    parser.add_argument("--min-months", type=int, default=2, help="Minimum distinct months")
    args = parser.parse_args()

    run_pipeline(
        input_file=args.input,
        output_file=args.output,
        min_users=args.min_users,
        min_months=args.min_months,
    )
