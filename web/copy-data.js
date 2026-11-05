import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const srcPath = path.resolve(__dirname, '../videos.json');
const destDir = path.resolve(__dirname, 'data');
const destPath = path.join(destDir, 'videos.json');

if (fs.existsSync(srcPath)) {
  if (!fs.existsSync(destDir)) {
    fs.mkdirSync(destDir, { recursive: true });
  }
  fs.copyFileSync(srcPath, destPath);
  console.log('Successfully copied data from ../videos.json -> data/videos.json');
} else if (fs.existsSync(destPath)) {
  console.log('Root videos.json not found; using existing data/videos.json');
} else {
  console.error('\n[ERROR] No videos.json available.');
  console.error('  Expected root file: ' + srcPath);
  console.error('  Expected fallback:  ' + destPath);
  console.error('Run classify.py first to generate videos.json, then build again.\n');
  process.exit(1);
}
