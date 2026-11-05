# VideoHub Phase 0: Hacker News Dataset Inspection Notes

## 1. Dataset Overview & License
- **Dataset:** `open-index/hacker-news` on Hugging Face (maintained by open-index).
- **License:** Open Data Commons Attribution License (ODC-By) v1.0.
- **Source:** ClickHouse Playground public endpoint mirroring the official Hacker News Firebase API. Content authored by the Hacker News / Y Combinator community.
- **Attribution Requirements:**
  - Notice acknowledging the database (`open-index/hacker-news` on Hugging Face) and original source (Hacker News / Y Combinator).
  - Hyperlink to the dataset URI (`https://huggingface.co/datasets/open-index/hacker-news`).
  - Copy or hyperlink to the ODC-By v1.0 license (`https://opendatacommons.org/licenses/by/1-0/`).
  - Keep intact author notices and state that VideoHub is independent and not endorsed by Y Combinator.

## 2. File Format & Size
- **File Format:** Monthly Apache Parquet files (`data/YYYY/YYYY-MM.parquet`), sorted by `id`, compressed using Zstandard (zstd level 22).
- **Archive Span:** October 2006 (`2006-10.parquet`) through August 2026 (`2026-08.parquet`).
- **Total Files:** 239 monthly Parquet files (plus 5-minute live increments under `today/`).
- **Total Item Count:** 49,324,111 items (~43.06 million comments, ~6.26 million stories).
- **Total Compressed Size:** 11.57 GB (~12,421,533,873 bytes).

## 3. Schema & Field Mapping
Each Parquet file has the following schema:
| Parquet Field | Type | Description | Mapping to `comments.jsonl` |
|---|---|---|---|
| `id` | `uint32` | Unique item ID | `id` (string / int) |
| `type` | `int8` | 1=story, 2=comment, 3=poll, 4=pollopt, 5=job | Filter for `type == 2` |
| `by` | `string` | Author username (DuckDB reserved word `"by"`) | `author` (skip null/empty) |
| `time` | `timestamp[us, UTC]` | Creation timestamp UTC | `created_utc` (unix seconds int) |
| `text` | `string` | HTML body of comment | `text` (strip HTML, decode entities) |
| `parent` | `uint32` | Parent item ID (story or comment) | Used if story join, else skipped |
| `deleted` | `uint8` | 1 if soft-deleted, 0 otherwise | Filter for `deleted == 0` |
| `dead` | `uint8` | 1 if flagged/killed, 0 otherwise | Filter for `dead == 0` |
| `url` | `string` | Link URL for stories (empty for comments) | Set to `https://news.ycombinator.com/item?id={id}` |
| `title` | `string` | Title for stories (empty for comments) | Set `thread_title` to `""` (no parent join) |
| `score` | `int32` | Upvotes minus downvotes | Unused in `comments.jsonl` |
| `kids` | `list<uint32>` | Direct child IDs | Unused |
| `descendants` | `int32` | Total descendant count | Unused |

## 4. Streaming Mode Capabilities
- **Can it be read in streaming mode?** Yes.
  - Hugging Face `datasets`: `load_dataset("open-index/hacker-news", split="train", streaming=True)` streams rows over HTTP without downloading the full archive.
  - DuckDB / PyArrow: Can read remote Parquet files via HTTP / range requests, streaming month-by-month files without keeping full historical data on disk.

## 5. Cheapest Extraction Strategy (Cheapest, Fastest, Minimal Disk)
- **Problem with Naive Row Streaming:** Pure Python iteration through 49M remote records via `datasets` streaming takes ~1.5 to 2.5 hours and is prone to network disconnects.
- **Recommended Extraction (`extract_hn.py`):**
  - Iterate through monthly Parquet file URLs (`data/YYYY/YYYY-MM.parquet`).
  - Stream or buffer each monthly Parquet file (~10 MB to 55 MB each) into memory or a single reusable temporary file.
  - Apply vectorized column filtering via DuckDB or PyArrow:
    `WHERE type = 2 AND deleted = 0 AND dead = 0 AND "by" IS NOT NULL AND (text LIKE '%youtube.com%' OR text LIKE '%youtu.be%')`
  - Strip HTML and decode entities on the matched rows, then append directly to `comments.jsonl`.
- **Resource Estimates:**
  - **Disk:** ~50 MB peak temporary storage (reused per month), ~20 MB to 40 MB final `comments.jsonl`. No full dataset download required.
  - **Network / Bandwidth:** Streams only the 11.57 GB compressed archive across monthly chunks.
  - **Time:** ~6 to 10 minutes total (network transfer + vectorized Parquet scan).

## 6. Terms & Compliance Flags
- **ODC-By v1.0:** Must display attribution to `open-index/hacker-news` and Y Combinator with links to the dataset and ODC-By license in the frontend footer.
- **YouTube Terms of Service:**
  - Embed videos strictly using official YouTube iframe embeds (using privacy-enhanced `youtube-nocookie.com` with a facade thumbnail).
  - Do not scrape or store raw video audio/video binaries.
  - Maintain a prominent, direct link to the original YouTube video on every card/page.
