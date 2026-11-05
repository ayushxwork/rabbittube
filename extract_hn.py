import argparse
from datetime import datetime, timezone
import html
import json
import os
import random
import re
import sys
import tempfile
import urllib.request
import csv
import io
from typing import Any, Dict, List, Optional, Tuple

import duckdb

# Add videohub directory to sys.path so we can import extract_youtube_ids
sys.path.insert(0, os.path.dirname(__file__))
from pipeline import extract_youtube_ids

HREF_REGEX = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)
TAG_REGEX = re.compile(r'<[^>]+>')
YT_PATTERN = re.compile(r'(?:youtube\.com|youtu\.be)', re.IGNORECASE)
STATS_URL = "https://huggingface.co/datasets/open-index/hacker-news/raw/main/stats.csv"
HF_BASE_URL = "https://huggingface.co/datasets/open-index/hacker-news/resolve/main"


def process_comment_html(raw_html: str) -> str:
    """
    Process raw HN HTML comment:
    1. Decode HTML entities (e.g. &#x2F; becomes /).
    2. Extract YouTube URLs from href attribute values and visible text.
    3. Strip HTML tags for final text field.
    4. Append any YouTube hrefs found into text field so pipeline.py's regex sees full URL.
    """
    if not raw_html:
        return ""

    # Step 1: FIRST decode HTML entities
    decoded = html.unescape(raw_html)

    # Step 2: Extract YouTube URLs from href attribute values
    hrefs = HREF_REGEX.findall(decoded)
    yt_hrefs = [h.strip() for h in hrefs if YT_PATTERN.search(h)]

    # Step 3: Strip HTML tags for final text
    text_cleaned = re.sub(r'</?(?:p|br\s*/?)>', '\n', decoded, flags=re.IGNORECASE)
    text_cleaned = TAG_REGEX.sub('', text_cleaned).strip()
    text_cleaned = re.sub(r'\n{3,}', '\n\n', text_cleaned)

    # Step 4: Append any hrefs found into the text field
    if yt_hrefs:
        to_append = [h for h in yt_hrefs if h not in text_cleaned]
        if to_append:
            return f"{text_cleaned}\n" + " ".join(to_append)
    return text_cleaned


def get_monthly_file_list(order: str = "desc") -> List[Tuple[str, int]]:
    """Fetch stats.csv from Hugging Face or use fallback generator."""
    items: List[Tuple[str, int]] = []
    try:
        req = urllib.request.Request(STATS_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read().decode("utf-8")
        reader = csv.DictReader(io.StringIO(content))
        for row in reader:
            count = int(row.get("count", 0))
            if count > 0:
                year = row["year"]
                month = int(row["month"])
                rel_path = f"data/{year}/{year}-{month:02d}.parquet"
                items.append((rel_path, count))
    except Exception as e:
        print(f"Notice: Failed to fetch stats.csv ({e}), using default archive range.")
        for y in range(2006, 2027):
            for m in range(1, 13):
                if y == 2006 and m < 10:
                    continue
                if y == 2026 and m > 8:
                    break
                rel_path = f"data/{y}/{y}-{m:02d}.parquet"
                items.append((rel_path, 100000))

    if order == "desc":
        items.reverse()
    return items


def extract_hn(
    output_file: str = "comments.jsonl",
    limit: Optional[int] = None,
    max_scanned: Optional[int] = None,
    order: str = "desc",
    months_limit: Optional[int] = None,
) -> None:
    file_list = get_monthly_file_list(order=order)
    if months_limit:
        file_list = file_list[:months_limit]

    print(f"Starting HN extraction -> output: {output_file}")
    if limit:
        print(f"Limit: stopping after {limit} matching comments kept.")
    if max_scanned:
        print(f"Max scanned: stopping after {max_scanned} comments scanned.")

    total_scanned = 0
    total_kept = 0
    distinct_video_ids = set()
    kept_samples: List[Dict[str, Any]] = []

    con = duckdb.connect()

    # Open output file
    # If starting fresh, overwrite; create parent dir if needed
    os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
    out_f = open(output_file, "w", encoding="utf-8")

    temp_parquet = os.path.join(tempfile.gettempdir(), "videohub_temp_month.parquet")

    try:
        for idx, (rel_path, expected_count) in enumerate(file_list, 1):
            if limit and total_kept >= limit:
                break
            if max_scanned and total_scanned >= max_scanned:
                break

            url = f"{HF_BASE_URL}/{rel_path}"
            month_label = rel_path.split("/")[-1].replace(".parquet", "")
            print(f"[{idx}/{len(file_list)}] Streaming {month_label} (~{expected_count:,} items)...", end=" ", flush=True)

            try:
                # Download single month file to temporary location
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=60) as resp, open(temp_parquet, "wb") as f_out:
                    while True:
                        chunk = resp.read(1024 * 512)
                        if not chunk:
                            break
                        f_out.write(chunk)
            except Exception as dl_err:
                print(f"Failed to download ({dl_err}), skipping.")
                continue

            # Query total comments scanned in this file
            try:
                count_res = con.sql(f"""
                    SELECT count(*) FROM '{temp_parquet}'
                    WHERE type = 2 AND deleted = 0 AND dead = 0 AND "by" IS NOT NULL
                """).fetchone()
                month_scanned = count_res[0] if count_res else 0
            except Exception:
                month_scanned = expected_count

            # Query candidate comments containing youtube.com or youtu.be
            query = f"""
                SELECT id, "by", epoch(time)::BIGINT as created_utc, text
                FROM '{temp_parquet}'
                WHERE type = 2 AND deleted = 0 AND dead = 0 AND "by" IS NOT NULL
                  AND (lower(text) LIKE '%youtube.com%' OR lower(text) LIKE '%youtu.be%')
            """
            try:
                candidates = con.sql(query).fetchall()
            except Exception as q_err:
                print(f"Query error ({q_err}), skipping.")
                continue

            month_kept = 0
            for row in candidates:
                if limit and total_kept >= limit:
                    break
                if max_scanned and (total_scanned + month_scanned) >= max_scanned:
                    break

                item_id, author, created_utc, raw_text = row
                if not author or not author.strip():
                    continue

                cleaned_text = process_comment_html(raw_text or "")
                # Extract video IDs to ensure comment actually contains YouTube video link(s)
                video_ids = extract_youtube_ids(cleaned_text)
                if not video_ids:
                    continue

                for vid in video_ids:
                    distinct_video_ids.add(vid)

                # Format record as pipeline.py expects:
                # id, author, created_utc [unix seconds, int], text, thread_title, url
                record = {
                    "id": str(item_id),
                    "author": author.strip(),
                    "created_utc": int(created_utc),
                    "text": cleaned_text,
                    "thread_title": "",
                    "url": f"https://news.ycombinator.com/item?id={item_id}",
                }

                out_f.write(json.dumps(record, ensure_ascii=False) + "\n")
                month_kept += 1
                total_kept += 1

                # Keep a sample pool for random verification
                if len(kept_samples) < 50:
                    kept_samples.append(record)
                else:
                    # Reservoir sampling to keep representative random sample
                    r = random.randint(0, total_kept - 1)
                    if r < len(kept_samples):
                        kept_samples[r] = record

            total_scanned += month_scanned
            print(f"scanned {month_scanned:,} comments, kept {month_kept} (total kept: {total_kept:,})")

    finally:
        out_f.close()
        if os.path.exists(temp_parquet):
            try:
                os.remove(temp_parquet)
            except OSError:
                pass

    print("\n" + "=" * 60)
    print("EXTRACTION SUMMARY")
    print("=" * 60)
    print(f"Comments scanned: {total_scanned:,}")
    print(f"Comments kept:    {total_kept:,}")
    print(f"Distinct YouTube video IDs: {len(distinct_video_ids):,}")

    # Verify created_utc
    if kept_samples:
        first = kept_samples[0]
        ts = first["created_utc"]
        is_int = isinstance(ts, int)
        dt_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        print(f"created_utc validation: {'CONFIRMED (int)' if is_int else 'FAILED'}, e.g. {ts} -> {dt_str} (type: {type(ts).__name__})")
    else:
        print("created_utc validation: No comments kept to validate.")

    # Print 3 random kept comments
    print("\n--- 3 Random Kept Comments ---")
    if kept_samples:
        sample_count = min(3, len(kept_samples))
        chosen_samples = random.sample(kept_samples, sample_count)
        for i, s in enumerate(chosen_samples, 1):
            month = datetime.fromtimestamp(s["created_utc"], tz=timezone.utc).strftime("%Y-%m")
            # Truncate text for readability if long
            disp_text = s["text"] if len(s["text"]) <= 240 else s["text"][:237] + "..."
            print(f"\n[{i}] Author: {s['author']} | Month: {month} | ID: {s['id']}")
            print(f"    Text: {disp_text}")
    else:
        print("None kept.")
    print("=" * 60)


def test_fake_comment() -> None:
    """Test HTML cleaning with escaped entities and shortened visible link text."""
    fake_html = (
        '<p>Check this talk: '
        '<a href="https:&#x2F;&#x2F;www.youtube.com&#x2F;watch?v=dQw4w9WgXcQ" rel="nofollow">'
        'youtube.com&#x2F;watch?v=...</a> it is great.</p>'
    )
    cleaned = process_comment_html(fake_html)
    ids = extract_youtube_ids(cleaned)
    print("Test fake comment input:", fake_html)
    print("Cleaned text:", repr(cleaned))
    print("Extracted video IDs:", ids)
    assert "dQw4w9WgXcQ" in ids, f"Failed: {ids}"
    print("TEST PASSED: Video ID dQw4w9WgXcQ extracted correctly from escaped/shortened link.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract YouTube comments from Hacker News archive.")
    parser.add_argument("--output", default="comments.jsonl", help="Output JSONL file (default: comments.jsonl)")
    parser.add_argument("--limit", type=int, default=None, help="Stop after keeping N matching comments")
    parser.add_argument("--max-scanned", type=int, default=None, help="Stop after scanning N comments")
    parser.add_argument("--order", choices=["desc", "asc"], default="desc", help="Processing order (default: desc, recent months first)")
    parser.add_argument("--months-limit", type=int, default=None, help="Process at most N monthly files")
    parser.add_argument("--test", action="store_true", help="Run self-test on fake comment with escaped shortened link")
    args = parser.parse_args()

    if args.test:
        test_fake_comment()
        sys.exit(0)

    extract_hn(
        output_file=args.output,
        limit=args.limit,
        max_scanned=args.max_scanned,
        order=args.order,
        months_limit=args.months_limit,
    )
