export interface CommentMention {
  id: string;
  author: string;
  text: string;
  created_utc?: number;
  thread_title?: string;
  url?: string;
  label?: "recommend" | "cite" | "joke" | "criticize" | string;
}

export interface Video {
  video_id: string;
  title: string;
  channel?: string;
  summary: string;
  topic: string;
  distinct_users: number;
  distinct_months: number;
  comments?: CommentMention[];
  mentions?: CommentMention[]; // Compatible with existing file
}

export function getVideoComments(video: Video): CommentMention[] {
  return video.comments ?? video.mentions ?? [];
}

export function getVideoChannel(video: Video): string {
  return video.channel?.trim() || "YouTube";
}
