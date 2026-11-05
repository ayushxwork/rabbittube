import videosData from "../data/videos.json";
import { Video } from "../types";

export function getAllVideos(): Video[] {
  const videos = [...(videosData as Video[])];
  return videos.sort((a, b) => {
    // 1. distinct_months descending
    if (b.distinct_months !== a.distinct_months) {
      return b.distinct_months - a.distinct_months;
    }
    // 2. distinct_users descending
    if (b.distinct_users !== a.distinct_users) {
      return b.distinct_users - a.distinct_users;
    }
    // 3. title ascending
    return a.title.localeCompare(b.title);
  });
}

export function getVideoById(id: string): Video | undefined {
  const videos = videosData as Video[];
  return videos.find((v) => v.video_id === id);
}

export function getActiveTopics(): string[] {
  const videos = videosData as Video[];
  const set = new Set<string>();
  for (const v of videos) {
    if (v.topic && v.topic.trim()) {
      set.add(v.topic.trim());
    }
  }
  return Array.from(set).sort((a, b) => a.localeCompare(b));
}
