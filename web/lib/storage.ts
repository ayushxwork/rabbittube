/**
 * LocalStorage utilities for Liked, Watch later, and History.
 * All reads and writes are safely wrapped in try/catch.
 * Always safe for SSR (checks window existence).
 */

const LIKED_KEY = "videohub_liked";
const WATCH_LATER_KEY = "videohub_watch_later";
const HISTORY_KEY = "videohub_history";
const MAX_HISTORY = 50;

function safeGet(key: string): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch (err) {
    console.error(`Error reading ${key} from localStorage:`, err);
    return [];
  }
}

function safeSet(key: string, values: string[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(key, JSON.stringify(values));
  } catch (err) {
    console.error(`Error writing ${key} to localStorage:`, err);
  }
}

export function getLikedIds(): string[] {
  return safeGet(LIKED_KEY);
}

export function isLiked(videoId: string): boolean {
  return getLikedIds().includes(videoId);
}

export function toggleLiked(videoId: string): boolean {
  const current = getLikedIds();
  const index = current.indexOf(videoId);
  let updated: string[];
  let nowLiked: boolean;
  if (index >= 0) {
    updated = current.filter((id) => id !== videoId);
    nowLiked = false;
  } else {
    updated = [videoId, ...current];
    nowLiked = true;
  }
  safeSet(LIKED_KEY, updated);
  return nowLiked;
}

export function getWatchLaterIds(): string[] {
  return safeGet(WATCH_LATER_KEY);
}

export function isWatchLater(videoId: string): boolean {
  return getWatchLaterIds().includes(videoId);
}

export function toggleWatchLater(videoId: string): boolean {
  const current = getWatchLaterIds();
  const index = current.indexOf(videoId);
  let updated: string[];
  let nowSaved: boolean;
  if (index >= 0) {
    updated = current.filter((id) => id !== videoId);
    nowSaved = false;
  } else {
    updated = [videoId, ...current];
    nowSaved = true;
  }
  safeSet(WATCH_LATER_KEY, updated);
  return nowSaved;
}

export function getHistoryIds(): string[] {
  return safeGet(HISTORY_KEY);
}

export function addToHistory(videoId: string): void {
  const current = getHistoryIds();
  // Move to front, deduplicate, limit to MAX_HISTORY (50)
  const updated = [videoId, ...current.filter((id) => id !== videoId)].slice(0, MAX_HISTORY);
  safeSet(HISTORY_KEY, updated);
}

export function clearHistory(): void {
  safeSet(HISTORY_KEY, []);
}
