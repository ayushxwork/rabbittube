# VideoHub

VideoHub is a static, read-only index of YouTube videos that Hacker News commenters repeatedly linked to: a Python pipeline pulls comment data from the open-index/hacker-news dataset, keeps only videos linked by many distinct users across many distinct months, enriches them with AI-generated summaries, topics and comment labels, and a Next.js site (static export) presents the results with search, topic filters, per-video pages, and a browser-stored Library (liked / watch later / history). It is an independent community project with no backend — everything is precomputed at build time and shipped as plain files.

## How it works

1. **Extract** — `extract_hn.py` streams monthly Parquet files of Hacker News comments from the open-index/hacker-news dataset on Hugging Face, keeps comments that link to YouTube, strips HTML, and writes `comments.jsonl`.
2. **Filter** — `pipeline.py` reads `comments.jsonl`, extracts YouTube video IDs, and keeps only videos linked by at least 3 distinct users in at least 3 distinct months, writing `candidates.json`.
3. **Rank & classify** — `classify.py` ranks videos by how many distinct people linked them in the last 3 years, then by total distinct users, and takes the top ones; the site keeps that order. For each video it fetches the title and channel from YouTube's public oEmbed endpoint, then asks Gemini (via its OpenAI-compatible endpoint, configured in `.env`) for a one-line summary, a topic, and labels for a sample of comments; the summary, topic and labels are shown on the video page. Responses are cached in `cache/`, so re-runs are cheap. Output: `videos.json`.
4. **Build** — `web/copy-data.js` copies a trimmed `videos.json` (video fields plus labeled comments only) into `web/data/`, then Next.js (`output: "export"`) builds the static site into `web/out/`.

## Run order

Requires Python 3 with `duckdb` (extract) and `openai` (classify) installed, plus Node.js for the site.

```powershell
# 1. Extract comments -> comments.jsonl   (slow: streams ~11 GB of Parquet)
python extract_hn.py

# 2. Filter candidates -> candidates.json
python pipeline.py

# 3. Classify -> videos.json              (needs GEMINI_API_KEY in .env)
python classify.py

# 4. Build the site -> web/out
cd web
npm ci
npm run build
```

Each stage reads the previous stage's output, so they can be re-run independently. Useful flags: `pipeline.py --min-users 3 --min-months 3`, `classify.py --limit 5` (test run), `extract_hn.py --test` (self-test).

## Data and attribution

- Data from the [open-index/hacker-news](https://huggingface.co/datasets/open-index/hacker-news) dataset (derived from Hacker News content hosted by Y Combinator).
- Licensed under the [Open Data Commons Attribution License (ODC-By v1.0)](https://opendatacommons.org/licenses/by/1-0/).
- VideoHub is an independent community project, not affiliated with or endorsed by Y Combinator or YouTube.
- Summaries, topics and labels are AI-generated and may be wrong.
