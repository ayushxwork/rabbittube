import videosData from "../data/videos.json";
import { Video, VideoCardData } from "../types";

/** Videos in the exact order of videos.json — the pipeline already ranks them. */
export function getAllVideos(): Video[] {
  return [...(videosData as Video[])];
}

export function getVideoById(id: string): Video | undefined {
  const videos = videosData as Video[];
  return videos.find((v) => v.video_id === id);
}

/** Slim card fields only — keeps home page HTML small (no comment payloads). */
export function getVideoCards(): VideoCardData[] {
  return getAllVideos().map(
    ({
      video_id,
      title,
      channel,
      summary,
      topic,
      distinct_users,
      distinct_months,
      first_linked_year,
      last_linked_year,
    }) => ({
      video_id,
      title,
      channel,
      summary,
      topic,
      distinct_users,
      distinct_months,
      first_linked_year,
      last_linked_year,
    })
  );
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
