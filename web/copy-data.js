import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const srcPath = path.resolve(__dirname, '../videos.json');
const destDir = path.resolve(__dirname, 'data');
const destPath = path.join(destDir, 'videos.json');

const MAX_COMMENT_CHARS = 300;
const UNLABELED = 'unlabeled';

function truncateText(text) {
  return text.length > MAX_COMMENT_CHARS ? text.slice(0, MAX_COMMENT_CHARS) : text;
}

/**
 * Trim the full classified dataset down to what the frontend needs.
 *
 * Per video keeps: video_id, title, channel, summary, topic, distinct_users,
 * distinct_months, mention_count (total mentions before trimming), and a
 * "comments" array containing only comments whose label is NOT "unlabeled",
 * each with id, author, text (truncated to 300 chars) and label.
 * first_linked_year / last_linked_year are kept when they are integers and
 * omitted when absent (or when they hold a non-integer value).
 * Everything else is dropped.
 */
export function trimVideos(data) {
  if (!Array.isArray(data)) {
    throw new Error('Expected an array of videos, got ' + typeof data);
  }
  return data.map((video) => {
    const source = Array.isArray(video.comments)
      ? video.comments
      : Array.isArray(video.mentions)
        ? video.mentions
        : [];
    const comments = [];
    for (const comment of source) {
      const label = comment && comment.label;
      if (typeof label !== 'string' || label === UNLABELED) continue;
      comments.push({
        id: String(comment.id ?? ''),
        author: String(comment.author ?? ''),
        text: truncateText(String(comment.text ?? '')),
        label,
      });
    }
    return {
      video_id: video.video_id,
      title: video.title,
      channel: video.channel,
      summary: video.summary,
      topic: video.topic,
      distinct_users: video.distinct_users,
      distinct_months: video.distinct_months,
      ...(Number.isInteger(video.first_linked_year)
        ? { first_linked_year: video.first_linked_year }
        : {}),
      ...(Number.isInteger(video.last_linked_year)
        ? { last_linked_year: video.last_linked_year }
        : {}),
      mention_count: source.length,
      comments,
    };
  });
}

function main() {
  if (fs.existsSync(srcPath)) {
    if (!fs.existsSync(destDir)) {
      fs.mkdirSync(destDir, { recursive: true });
    }

    let raw;
    try {
      raw = JSON.parse(fs.readFileSync(srcPath, 'utf8'));
    } catch (err) {
      console.error('\n[ERROR] Could not parse ' + srcPath);
      console.error(String(err.message));
      console.error('Fix or regenerate videos.json, then try again.\n');
      process.exit(1);
    }

    const trimmed = trimVideos(raw);
    const mentionTotal = trimmed.reduce((n, v) => n + v.mention_count, 0);
    const commentTotal = trimmed.reduce((n, v) => n + v.comments.length, 0);

    fs.writeFileSync(destPath, JSON.stringify(trimmed, null, 2) + '\n');
    console.log(
      'Successfully copied data from ../videos.json -> data/videos.json' +
        ` (${trimmed.length} videos, ${commentTotal}/${mentionTotal} comments kept after trimming)`
    );
  } else if (fs.existsSync(destPath)) {
    console.log('Root videos.json not found; using existing data/videos.json');
  } else {
    console.error('\n[ERROR] No videos.json available.');
    console.error('  Expected root file: ' + srcPath);
    console.error('  Expected fallback:  ' + destPath);
    console.error('Run classify.py first to generate videos.json, then build again.\n');
    process.exit(1);
  }
}

// Only run when executed directly, so the trim function can be imported
// by tests without triggering a copy.
const isMain =
  process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1]);
if (isMain) {
  main();
}
