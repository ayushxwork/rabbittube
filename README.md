# VideoHub

VideoHub is a static, read-only index of YouTube videos that Hacker News commenters repeatedly recommended: a Python pipeline pulls comment data from the open-index/hacker-news dataset, keeps only videos linked by many distinct users across many distinct months, classifies the survivors with an AI model, and a Next.js site (static export) presents the results with search, topic filters, per-video pages, and a browser-stored Library (liked / watch later / history). It is an independent community project with no backend — everything is precomputed at build time and shipped as plain files.

## How it works

1. **Extract** — `extract_hn.py` streams monthly Parquet files of Hacker News comments from the open-index/hacker-news dataset on Hugging Face, keeps comments that link to YouTube, strips HTML, and writes `comments.jsonl`.
2. **Filter** — `pipeline.py` reads `comments.jsonl`, extracts YouTube video IDs, and keeps only candidates recommended by at least `--min-users` distinct users in at least `--min-months` distinct months (defaults: 2 users, 2 months), writing `candidates.json`.
3. **Classify** — `classify.py` fetches titles/channels via YouTube's public oEmbed endpoint, asks Gemini (via its OpenAI-compatible endpoint, configured in `.env`) to summarize each video and label its comments, drops videos with fewer than 2 "recommend" mentions, and writes `videos.json`. Responses are cached in `cache/`, so re-runs are cheap.
4. **Build** — `web/copy-data.js` copies `videos.json` into `web/data/`, then Next.js (`output: "export"`) builds the static site into `web/out/`.

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
