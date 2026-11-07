"""
VideoHub - offline tests for classify.py reliability fixes.

Runs WITHOUT network access and WITHOUT any Gemini requests:
  1. Missing model labels become "unlabeled" (never fabricated "recommend").
  2. Successful cache entries are reused (zero API calls).
  3. Failed cache entries are retried on the next invocation (once per run).
  4. An API failure cannot erase an existing videos.json (preserve + atomic write).
  5. The default --output path remains videos.json (CLI compatibility).
  6. Failure records store http_status/error/timestamp with secrets redacted.
  7. Window truncation, short/rich sampling, and bounded 5xx retries.
  8. Unavailable videos (oEmbed 404/private) get zero Gemini calls, are
     recorded as "unavailable", excluded from videos.json, and counted in
     the plan output.
  9. The prompt carries the video title/channel and the summary rules.
 10. oEmbed is fetched at most once per video.
 11. Recency ranking: recent authors outrank an old classic with more users.
 12. recent_users counts distinct authors only (repeat author counts once).
 13. first_linked_year / last_linked_year are correct for a fixture.
 14. --limit 2 on 10 candidates makes exactly 2 oEmbed calls.
 15. Adaptive pacing: a 429 doubles the interval up to the cap, and clean
     calls ease it back down to the base interval.
 16. 429 and 5xx retries have independent budgets (an interleaved burst
     succeeds where the old shared counter would have failed).

Usage:  python test_classify_offline.py
Exit code: 0 when all tests pass, 1 otherwise.
"""

import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time as real_time
import types

import classify

REPO = os.path.dirname(os.path.abspath(__file__))
# Fake key used only by these tests to prove redaction works. Not a real credential.
DUMMY_KEY = "AIzaOfflineTestKey1234567890DoNotUse12"
FAKE_MODEL = "gemini-3.5-flash-lite"

RESULTS = []


def record(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    status = "PASS" if ok else "FAIL"
    line = f"[{status}] {name}"
    if detail and not ok:
        line += f"  -- {detail}"
    print(line)


def sandbox(name):
    path = os.path.join(tempfile.gettempdir(), "videohub_offline_tests", name)
    if os.path.isdir(path):
        shutil.rmtree(path)
    os.makedirs(os.path.join(path, "cache"))
    return path


def make_candidate(vid, n_mentions=4, users=5, months=5):
    mentions = []
    for i in range(1, n_mentions + 1):
        mentions.append({
            "id": f"m{i}",
            "author": f"user{i}",
            "created_utc": 1700000000 + i * 3456000,
            "text": f"comment {i} about https://youtu.be/{vid}",
            "thread_title": "a thread",
            "url": "https://example.com/thread/comment",
        })
    return {
        "video_id": vid,
        "distinct_users": users,
        "distinct_months": months,
        "mentions": mentions,
    }


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def file_sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def run_in(box, output_file="videos.json", limit=None, top=300):
    """Run classify.run_classification inside a sandbox dir, capturing stdout."""
    old_cwd = os.getcwd()
    buf = io.StringIO()
    try:
        os.chdir(box)
        with contextlib.redirect_stdout(buf):
            classify.run_classification(
                candidates_file="candidates.json",
                topics_file="topics.json",
                output_file=output_file,
                top=top,
                limit=limit,
            )
    finally:
        os.chdir(old_cwd)
    return buf.getvalue()


# --- Fakes (patched in; no network) -----------------------------------------
API_CALLS = []
OEMBED_CALLS = []
API_TITLES = []


def fake_oembed(video_id, oembed_cache):
    return {"title": f"Title of {video_id}", "channel": "TestChannel"}


def fake_api_success(client, model, vid, comments, topics, title="", channel=""):
    API_CALLS.append(vid)
    API_TITLES.append((vid, title, channel))
    ids = [c["id"] for c in comments]
    labels = [{"comment_id": cid, "label": "recommend"} for cid in ids[:2]]
    return {"summary": f"Summary for {vid}", "topic": "coding", "comment_labels": labels}, None


class Fake503(Exception):
    status_code = 503


def fake_api_failure(client, model, vid, comments, topics, title="", channel=""):
    API_CALLS.append(vid)
    exc = Fake503(f"Error code: 503 - overloaded (attempt used key {DUMMY_KEY})")
    return None, classify.build_failure_info(exc)


class Fake503Error(Exception):
    """Simulated upstream HTTP 503 with a status_code attribute."""

    def __init__(self, status):
        super().__init__(f"Error code: {status} - simulated upstream error")
        self.status_code = status


class FakeTime:
    """Records sleep() calls and delegates everything else to the real time module."""

    def __init__(self):
        self.sleeps = []

    def sleep(self, seconds):
        self.sleeps.append(seconds)

    def __getattr__(self, name):
        return getattr(real_time, name)


def make_fake_client(behavior):
    """OpenAI-shaped client whose create() is fully offline (behavior-driven)."""

    def create(**kwargs):
        return behavior()

    return types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create))
    )


def success_response_for(comments):
    labels = [{"comment_id": c["id"], "label": "cite"} for c in comments]
    content = json.dumps({"summary": "ok summary", "topic": "coding",
                          "comment_labels": labels})
    return types.SimpleNamespace(
        choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=content))])


def main():
    os.environ["GEMINI_API_KEY"] = DUMMY_KEY
    os.environ["MODEL"] = FAKE_MODEL

    original_call = classify.call_gemini_classification
    original_oembed = classify.fetch_youtube_oembed
    original_interval = classify.REQUEST_INTERVAL_SECONDS
    classify.fetch_youtube_oembed = fake_oembed
    classify.REQUEST_INTERVAL_SECONDS = 0.0  # keep tests fast; retry policy untouched

    try:
        # ---- Test 1: missing model labels become "unlabeled" -----------------
        box = sandbox("t1_unlabeled")
        vid = "VIDAAAAAA1"
        write_json(os.path.join(box, "candidates.json"), [make_candidate(vid, n_mentions=4)])
        write_json(os.path.join(box, "topics.json"), ["coding", "other"])
        write_json(os.path.join(box, "cache", "classifications.json"), {
            vid: {
                "summary": "cached summary",
                "topic": "coding",
                # model labeled only m1 and m2; m3/m4 must stay "unlabeled"
                "comment_labels": [
                    {"comment_id": "m1", "label": "recommend"},
                    {"comment_id": "m2", "label": "recommend"},
                ],
            }
        })
        API_CALLS.clear()
        classify.call_gemini_classification = fake_api_success
        run_in(box)
        out = read_json(os.path.join(box, "videos.json"))
        labels = {c["id"]: c["label"] for c in out[0]["comments"]} if out else {}
        ok = (
            len(out) == 1
            and labels.get("m1") == "recommend"
            and labels.get("m2") == "recommend"
            and labels.get("m3") == "unlabeled"
            and labels.get("m4") == "unlabeled"
            and sum(1 for v in labels.values() if v == "recommend") == 2
            and API_CALLS == []
        )
        record("missing model labels become 'unlabeled' (no fabricated recommend)", ok,
               f"labels={labels} apiCalls={API_CALLS}")
        record("atomic write leaves no .tmp behind",
               not os.path.exists(os.path.join(box, "videos.json.tmp")))

        # ---- Test 2: successful cache entries are reused ---------------------
        cache_before = file_sha(os.path.join(box, "cache", "classifications.json"))
        API_CALLS.clear()
        run_in(box)
        cache_after = file_sha(os.path.join(box, "cache", "classifications.json"))
        reused = read_json(os.path.join(box, "videos.json"))
        record("successful cache entries reused with zero API calls",
               API_CALLS == [] and len(reused) == 1 and cache_before == cache_after,
               f"apiCalls={API_CALLS} kept={len(reused)}")

        # ---- Test 3: failed cache entries are retried ------------------------
        box = sandbox("t3_retry_failed")
        vid = "VIDBBBBBB2"
        write_json(os.path.join(box, "candidates.json"), [make_candidate(vid, n_mentions=4)])
        write_json(os.path.join(box, "topics.json"), ["coding", "other"])
        write_json(os.path.join(box, "cache", "classifications.json"), {
            vid: {"status": "failed", "http_status": 503,
                  "error": "previous outage", "timestamp": "2026-11-05T18:40:54Z"}
        })
        API_CALLS.clear()
        classify.call_gemini_classification = fake_api_success
        out_text = run_in(box)
        new_cache = read_json(os.path.join(box, "cache", "classifications.json"))
        out = read_json(os.path.join(box, "videos.json"))
        record("failed cache entry retried once and upgraded to success",
               API_CALLS == [vid]
               and new_cache.get(vid, {}).get("status") != "failed"
               and len(out) == 1
               and "retrying previously failed entry" in out_text,
               f"apiCalls={API_CALLS} cache={new_cache.get(vid)}")

        # ---- Test 4: API failure cannot erase an existing videos.json --------
        box = sandbox("t4_preserve")
        vid = "VICEEEEEEE3"
        sentinel = [make_candidate(vid)]  # any pre-existing dataset content
        write_json(os.path.join(box, "candidates.json"), [make_candidate(vid)])
        write_json(os.path.join(box, "topics.json"), ["coding", "other"])
        write_json(os.path.join(box, "cache", "classifications.json"), {})
        output_path = os.path.join(box, "videos.json")
        write_json(output_path, sentinel)
        sha_before = file_sha(output_path)
        API_CALLS.clear()
        classify.call_gemini_classification = fake_api_failure
        out_text = run_in(box)
        sha_after = file_sha(output_path)
        failed_cache = read_json(os.path.join(box, "cache", "classifications.json"))
        entry = failed_cache.get(vid, {})
        cache_raw = open(os.path.join(box, "cache", "classifications.json"), encoding="utf-8").read()
        record("API failure preserves existing videos.json byte-for-byte",
               sha_before == sha_after and "[PRESERVED]" in out_text,
               f"shaChanged={sha_before != sha_after} out={out_text[-200:]}")
        record("failure details stored (status/http_status/error/timestamp)",
               entry.get("status") == "failed"
               and entry.get("http_status") == 503
               and "503" in str(entry.get("error", ""))
               and bool(entry.get("timestamp")),
               f"entry={entry}")
        record("API key redacted from cache and console output",
               DUMMY_KEY not in cache_raw and DUMMY_KEY not in out_text,
               "dummy key leaked")

        # ---- Test 5: default output path stays videos.json (real CLI) --------
        record("classify.DEFAULT_OUTPUT_FILE still 'videos.json'",
               classify.DEFAULT_OUTPUT_FILE == "videos.json",
               f"value={classify.DEFAULT_OUTPUT_FILE!r}")
        box = sandbox("t5_default_cli")
        sentinel = [{"video_id": "KEEPME0001", "title": "keep", "channel": "c",
                     "summary": "s", "topic": "coding", "distinct_users": 4,
                     "distinct_months": 4, "comments": []}]
        write_json(os.path.join(box, "candidates.json"), [make_candidate("VIDFFFFFFF4")])
        write_json(os.path.join(box, "topics.json"), ["coding", "other"])
        write_json(os.path.join(box, "videos.json"), sentinel)
        env = os.environ.copy()
        env["GEMINI_API_KEY"] = DUMMY_KEY
        env["MODEL"] = FAKE_MODEL
        proc = subprocess.run(
            [sys.executable, os.path.join(REPO, "classify.py"), "--limit", "0"],
            cwd=box, env=env, capture_output=True, text=True, encoding="utf-8", timeout=120,
        )
        after = read_json(os.path.join(box, "videos.json"))
        record("CLI default --output runs offline and preserves existing videos.json",
               proc.returncode == 0
               and "[PRESERVED]" in proc.stdout
               and after == sentinel
               and "Applying --limit 0" in proc.stdout,
               f"rc={proc.returncode} stdout_tail={proc.stdout[-300:]!r} stderr={proc.stderr[-300:]!r}")
        # ---- Test 7: window truncation keeps a link sitting past char 500 -----
        classify.call_gemini_classification = original_call  # use the real implementation
        vid = "VIDTRUNC01"
        url = f"https://youtu.be/{vid}"
        long_text = "A" * 560 + " " + url + " trailing prose after the link " + "B" * 400
        picked = classify.select_candidate_comments(
            [{"id": "t1", "author": "u1", "text": long_text}],
            max_comments=12, max_chars=500, video_id=vid,
        )
        out = picked[0]["text"]
        link_pos = long_text.index(url)
        record("truncation: 500-char window keeps a link sitting past char 500",
               link_pos > 500 and url in out
               and out.startswith("...") and out.endswith("...")
               and len(out) <= 500,
               f"pos={link_pos} len={len(out)} head={out[:30]!r} tail={out[-30:]!r}")

        # ---- Test 8: sampling mixes short + rich, excludes bare links --------
        vid = "VIDSAMPLE01"
        u = f"https://youtu.be/{vid}"
        mentions8 = []
        for i in range(10):
            mentions8.append({"id": f"s{i}", "author": f"sa{i}",
                              "text": f"short prose {i:02d} fine {u}"})
        for i in range(10):
            mentions8.append({"id": f"r{i}", "author": f"ra{i}",
                              "text": (f"rich comment number {i:02d} with plenty of surrounding discussion " * 6) + u})
        for i in range(3):
            mentions8.append({"id": f"b{i}", "author": f"ba{i}", "text": u})
        picked8 = classify.select_candidate_comments(
            mentions8, max_comments=12, max_chars=500, video_id=vid)

        def slen(t):
            return len(re.sub(r"https?://\S+", "", t).strip())

        ids8 = [p["id"] for p in picked8]
        eligible8 = [(m["id"], slen(m["text"])) for m in mentions8 if slen(m["text"]) >= 15]
        shortest6 = {eid for eid, _ in sorted(eligible8, key=lambda t: t[1])[:6]}
        original_order = [m["id"] for m in mentions8 if m["id"] in set(ids8)]
        record("sampling: 6 shortest + 6 richest mix, bare links excluded, original order",
               len(picked8) == 12
               and all(slen(p["text"]) >= 15 for p in picked8)
               and shortest6.issubset(set(ids8))
               and max(slen(p["text"]) for p in picked8) >= 150
               and ids8 == original_order,
               f"n={len(picked8)} ids={ids8}")

        # ---- Tests 9 & 10: 5xx retry behavior (fake client, no network) ------
        comments9 = [
            {"id": "c1", "author": "a1", "text": "first comment about the video"},
            {"id": "c2", "author": "a2", "text": "second comment about the video"},
        ]
        fake_time = FakeTime()
        real_time_module = classify.time
        classify.time = fake_time
        try:
            # Test 9: 503 twice, then success
            n9 = [0]

            def behavior9():
                n9[0] += 1
                if n9[0] <= 2:
                    raise Fake503Error(503)
                return success_response_for(comments9)

            result9, fail9 = classify.call_gemini_classification(
                make_fake_client(behavior9), FAKE_MODEL, "VIDTEST001",
                comments9, ["coding", "other"],
            )
            record("503 twice then success ends in success (backoff 10s, 20s)",
                   isinstance(result9, dict) and fail9 is None
                   and n9[0] == 3 and fake_time.sleeps == [10.0, 20.0],
                   f"calls={n9[0]} sleeps={fake_time.sleeps} fail={fail9}")

            # Test 10: 503 forever -> failed after 3 retries
            fake_time.sleeps.clear()
            n10 = [0]

            def behavior10():
                n10[0] += 1
                raise Fake503Error(503)

            result10, fail10 = classify.call_gemini_classification(
                make_fake_client(behavior10), FAKE_MODEL, "VIDTEST002",
                comments9, ["coding", "other"],
            )
            record("503 forever ends 'failed' after 3 retries (backoff 10s, 20s, 40s)",
                   result10 is None and isinstance(fail10, dict)
                   and fail10.get("status") == "failed"
                   and fail10.get("http_status") == 503
                   and n10[0] == 4 and fake_time.sleeps == [10.0, 20.0, 40.0],
                   f"calls={n10[0]} sleeps={fake_time.sleeps} fail={fail10}")
        finally:
            classify.time = real_time_module

        # ---- Test 11: unavailable video excluded with zero Gemini calls ------
        box = sandbox("t11_unavailable")
        unav = "VIDUNAVAIL1"
        okv = "VIDOKAAAA1"
        write_json(os.path.join(box, "candidates.json"),
                   [make_candidate(unav), make_candidate(okv)])
        write_json(os.path.join(box, "topics.json"), ["coding", "other"])
        write_json(os.path.join(box, "cache", "classifications.json"), {})
        API_CALLS.clear()
        API_TITLES.clear()
        OEMBED_CALLS.clear()

        def fake_oembed_mixed(video_id, oembed_cache):
            OEMBED_CALLS.append(video_id)
            if video_id == unav:
                # Mirrors the real fetch for 404/private/removed videos.
                oembed_cache[video_id] = {"status": "unavailable", "code": 404}
                classify.save_json_cache(classify.OEMBED_CACHE_FILE, oembed_cache)
                return None
            return {"title": f"Title of {video_id}", "channel": "TestChannel"}

        classify.fetch_youtube_oembed = fake_oembed_mixed
        classify.call_gemini_classification = fake_api_success
        out_text = run_in(box)
        cache11 = read_json(os.path.join(box, "cache", "classifications.json"))
        out11 = read_json(os.path.join(box, "videos.json"))
        ids11 = [v["video_id"] for v in out11]
        record("unavailable video: zero Gemini calls, recorded 'unavailable', excluded, shown in plan",
               API_CALLS == [okv]
               and cache11.get(unav, {}).get("status") == "unavailable"
               and unav not in ids11
               and ids11 == [okv]
               and re.search(r"Skipped as unavailable:\s+1", out_text) is not None,
               f"api={API_CALLS} cacheEntry={cache11.get(unav)} ids={ids11}")
        record("oEmbed fetched at most once per video; videos.json keeps that title/channel",
               len(OEMBED_CALLS) == 2
               and OEMBED_CALLS.count(unav) == 1
               and OEMBED_CALLS.count(okv) == 1
               and bool(out11)
               and out11[0]["title"] == f"Title of {okv}"
               and out11[0]["channel"] == "TestChannel",
               f"oembedCalls={OEMBED_CALLS} title={(out11[0].get('title') if out11 else None)!r}")
        record("oEmbed title/channel are passed into the Gemini call",
               API_TITLES == [(okv, f"Title of {okv}", "TestChannel")],
               f"apiTitles={API_TITLES}")

        # ---- Test 12: prompt includes title, channel, and summary rules ------
        captured = []

        def capturing_client(response):
            def create(**kwargs):
                captured.append(kwargs)
                return response
            return types.SimpleNamespace(
                chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))

        comments12 = [{"id": "c1", "author": "a1", "text": "this lecture changed how I eat"}]
        result12, fail12 = original_call(
            capturing_client(success_response_for(comments12)), FAKE_MODEL,
            "VIDPROMPT01", comments12, ["coding", "other"],
            title="Why Sugar Makes You Sick",
            channel="Robert Lustig Lectures",
        )
        prompt12 = "\n".join(m["content"] for m in captured[0]["messages"]) if captured else ""
        record("prompt contains title, channel, and the no-commenters summary rule",
               isinstance(result12, dict) and fail12 is None
               and "Why Sugar Makes You Sick" in prompt12
               and "Robert Lustig Lectures" in prompt12
               and "Never mention commenters, comments, discussion, or people" in prompt12
               and "Do not start with 'The video'" in prompt12
               and "25 words" in prompt12,
               f"fail={fail12} captured={len(captured)}")

        # ---- Test 13: recency ranking beats an old classic -----------------
        box = sandbox("t13_ranking")
        old_vid = "VIDOLDCLASS1"
        recent_vid = "VIDRECENT01"
        old_c = make_candidate(old_vid, n_mentions=6, users=100, months=60)
        for i, m in enumerate(old_c["mentions"]):
            m["created_utc"] = 1200000000 + i  # 2008: far outside the 3-year window
        recent_c = make_candidate(recent_vid, n_mentions=3, users=5, months=5)
        for i, m in enumerate(recent_c["mentions"]):
            m["created_utc"] = int(real_time.time()) - 86400 - i  # yesterday: inside the window
        # The old classic is listed FIRST in the file and has more total users,
        # so only the new recency key can put the recent video ahead of it.
        write_json(os.path.join(box, "candidates.json"), [old_c, recent_c])
        write_json(os.path.join(box, "topics.json"), ["coding", "other"])
        write_json(os.path.join(box, "cache", "classifications.json"), {})
        API_CALLS.clear()
        classify.fetch_youtube_oembed = fake_oembed
        classify.call_gemini_classification = fake_api_success
        run_in(box)  # top=300: both processed, call order proves the ranking
        order13 = list(API_CALLS)
        API_CALLS.clear()
        out13b = run_in(box, top=1)  # the ranking message only prints on a top slice
        record("old classic with more users ranks below a recent video (new sort + message)",
               order13 == [recent_vid, old_vid]
               and "sorted by recent_users, then distinct_users, then distinct_months" in out13b
               and API_CALLS == [],  # phase 2 reused the cache: nothing re-classified
               f"order13={order13} apiPhase2={API_CALLS}")

        # ---- Test 14: recent_users counts distinct authors only -------------
        cutoff14 = 1699228800  # fixed reference cutoff (2023-11-05 UTC)
        mentions14 = (
            [{"author": "alice", "created_utc": 1790000000 + i} for i in range(5)]
            + [{"author": "bob", "created_utc": 1790000099}]
            + [{"author": "carol", "created_utc": 1200000000}]  # old: excluded
        )
        got14 = classify.compute_recent_users(mentions14, cutoff14)
        record("recent_users counts distinct authors only (repeat author counts once)",
               got14 == 2, f"got={got14}")

        # ---- Test 15: first/last_linked_year fixture ------------------------
        box = sandbox("t15_years")
        vid15 = "VIDYEARS001"
        cand15 = make_candidate(vid15, n_mentions=4)
        for m, ts in zip(cand15["mentions"], [1546300800, 1672531200, 1704067200, 1640995200]):
            m["created_utc"] = ts  # 2019, 2023, 2024, 2022 (UTC)
        write_json(os.path.join(box, "candidates.json"), [cand15])
        write_json(os.path.join(box, "topics.json"), ["coding", "other"])
        write_json(os.path.join(box, "cache", "classifications.json"), {})
        API_CALLS.clear()
        classify.fetch_youtube_oembed = fake_oembed
        classify.call_gemini_classification = fake_api_success
        run_in(box)
        out15 = read_json(os.path.join(box, "videos.json"))
        e15 = out15[0] if out15 else {}
        record("first_linked_year and last_linked_year are correct for a fixture",
               e15.get("first_linked_year") == 2019 and e15.get("last_linked_year") == 2024,
               f"first={e15.get('first_linked_year')} last={e15.get('last_linked_year')}")

        # ---- Test 16: --limit 2 makes exactly 2 oEmbed calls ---------------
        box = sandbox("t16_limit_oembed")
        cands16 = [
            make_candidate(f"VIDLIMIT{i:02d}A", n_mentions=3, users=10 - i, months=10)
            for i in range(10)
        ]
        write_json(os.path.join(box, "candidates.json"), cands16)
        write_json(os.path.join(box, "topics.json"), ["coding", "other"])
        write_json(os.path.join(box, "cache", "classifications.json"), {})
        API_CALLS.clear()
        OEMBED_CALLS.clear()

        def counting_oembed(video_id, oembed_cache):
            OEMBED_CALLS.append(video_id)
            return {"title": f"Title of {video_id}", "channel": "TestChannel"}

        classify.fetch_youtube_oembed = counting_oembed
        classify.call_gemini_classification = fake_api_success
        out16 = run_in(box, limit=2)
        record("10 candidates with --limit 2 makes exactly 2 oEmbed calls",
               len(OEMBED_CALLS) == 2 and "Applying --limit 2" in out16,
               f"oembedCalls={OEMBED_CALLS} apiCalls={API_CALLS}")

        # ---- Test 17: adaptive pacing (429 doubles, clean calls relax) ------
        # Base 5.0s; the first API call is throttled, so pacing goes 5 -> 10,
        # stays there while cleaning calls 1-2, and eases back to 5.0 on the
        # 3rd clean call. FakeTime records every sleep; no real waiting.
        saved_interval = classify.REQUEST_INTERVAL_SECONDS
        saved_pace = dict(classify.PACE)
        saved_openai = classify.OpenAI
        real_time_module = classify.time
        classify.REQUEST_INTERVAL_SECONDS = 5.0
        classify.PACE["interval"] = 5.0
        classify.PACE["clean_calls"] = 0
        classify.time = FakeTime()
        try:
            box = sandbox("t17_pacing")
            cands17 = [make_candidate(f"VIDPACE{i:02d}A") for i in range(3)]
            write_json(os.path.join(box, "candidates.json"), cands17)
            write_json(os.path.join(box, "topics.json"), ["coding", "other"])
            write_json(os.path.join(box, "cache", "classifications.json"), {})
            API_CALLS.clear()
            classify.fetch_youtube_oembed = fake_oembed
            classify.call_gemini_classification = original_call  # real call path
            create_calls = [0]

            def make_scripted_client():
                def create(**kwargs):
                    create_calls[0] += 1
                    if create_calls[0] == 1:
                        raise Fake503Error(429)  # first call of the run is throttled
                    # Answer exactly the comment ids present in this request.
                    user_msg = kwargs["messages"][1]["content"]
                    ids = re.findall(r"\[Comment ID: (\w+),", user_msg)
                    labels = [{"comment_id": i, "label": "cite"} for i in ids]
                    content = json.dumps({"summary": "ok summary", "topic": "coding",
                                          "comment_labels": labels})
                    return types.SimpleNamespace(
                        choices=[types.SimpleNamespace(
                            message=types.SimpleNamespace(content=content))])
                return types.SimpleNamespace(
                    chat=types.SimpleNamespace(
                        completions=types.SimpleNamespace(create=create)))

            classify.OpenAI = lambda **kwargs: make_scripted_client()
            out17 = run_in(box)
            sleeps17 = list(classify.time.sleeps)
            pace_end = classify.PACE["interval"]
            videos17 = read_json(os.path.join(box, "videos.json"))
            # Cap check: 50 -> min(100, 60) = 60, then stays at the cap.
            classify.PACE["interval"] = 50.0
            classify.PACE["clean_calls"] = 0
            classify.note_rate_limit()
            classify.note_rate_limit()
            cap_ok = classify.PACE["interval"] == classify.PACING_INTERVAL_CAP == 60.0
            record("adaptive pacing: 429 doubles interval up to cap, clean calls relax it back to base",
                   len(videos17) == 3
                   and create_calls[0] == 4
                   and "Pacing raised to 10.0s per call" in out17
                   and "Pacing relaxed to 5.0s per call" in out17
                   and "doubles up to 60s after 429s, eases back after 3 clean calls" in out17
                   and pace_end == 5.0
                   and sleeps17 == [10.0, 10.0, 10.0, 5.0]
                   and cap_ok,
                   f"createCalls={create_calls[0]} paceEnd={pace_end} "
                   f"sleeps={sleeps17} cap={cap_ok} videos={len(videos17)}")
        finally:
            classify.time = real_time_module
            classify.OpenAI = saved_openai
            classify.REQUEST_INTERVAL_SECONDS = saved_interval
            classify.PACE.clear()
            classify.PACE.update(saved_pace)

        # ---- Test 18: 429 and 5xx have independent retry budgets ------------
        real_time_module = classify.time  # the real module (restored after test 17)
        fake_time18 = FakeTime()
        classify.time = fake_time18
        try:
            # Interleaved 429/503 burst: both budgets allow exactly 3 retries,
            # so the 7th call can succeed. The old shared counter would have
            # exhausted after 4 calls and marked the video failed.
            n18 = [0]
            seq18 = [429, 503, 429, 503, 429, 503, "ok"]

            def behavior18():
                step = seq18[min(n18[0], len(seq18) - 1)]
                n18[0] += 1
                if step == "ok":
                    return success_response_for(comments9)
                raise Fake503Error(step)

            result18, fail18 = classify.call_gemini_classification(
                make_fake_client(behavior18), FAKE_MODEL, "VIDSPLITBUD1",
                comments9, ["coding", "other"],
            )
            interleaved_ok = (
                isinstance(result18, dict) and fail18 is None
                and n18[0] == 7
                and fake_time18.sleeps == [10.0, 20.0, 40.0, 80.0, 160.0, 320.0]
            )
            sleeps18 = list(fake_time18.sleeps)

            # Each budget stays bounded alone: endless 429s fail after 3 retries.
            fake_time18.sleeps.clear()
            n18b = [0]

            def behavior18b():
                n18b[0] += 1
                raise Fake503Error(429)

            result18b, fail18b = classify.call_gemini_classification(
                make_fake_client(behavior18b), FAKE_MODEL, "VIDONLY4291",
                comments9, ["coding", "other"],
            )
            bounded_ok = (
                result18b is None and isinstance(fail18b, dict)
                and fail18b.get("http_status") == 429
                and n18b[0] == 4
                and fake_time18.sleeps == [10.0, 20.0, 40.0]
            )
            record("429 and 5xx retries have independent budgets (interleaved burst succeeds; 429-only still capped)",
                   interleaved_ok and bounded_ok,
                   f"calls18={n18[0]} sleeps18={sleeps18} calls429={n18b[0]} "
                   f"boundedSleeps={fake_time18.sleeps}")
        finally:
            classify.time = real_time_module

    finally:
        classify.call_gemini_classification = original_call
        classify.fetch_youtube_oembed = original_oembed
        classify.REQUEST_INTERVAL_SECONDS = original_interval

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = len(RESULTS) - passed
    print("\n" + "=" * 60)
    print(f"TEST SUMMARY: {passed} passed, {failed} failed, {len(RESULTS)} total")
    print("=" * 60)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
