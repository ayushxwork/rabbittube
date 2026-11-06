// Known label values plus any other string the pipeline may emit.
export type CommentLabel =
  | "recommend"
  | "cite"
  | "joke"
  | "criticize"
  | "unlabeled"
  | (string & {});

export interface CommentMention {
  id: string;
  author: string;
  text: string;
  created_utc?: number;
  thread_title?: string;
  url?: string;
  label?: CommentLabel;
}

/**
 * Slim card fields only. Passed to client components (home grid, cards)
 * so comment payloads never end up in page HTML.
 */
export interface VideoCardData {
  video_id: string;
  title: string;
  channel?: string;
  summary: string;
  topic: string;
  distinct_users: number;
  distinct_months: number;
  first_linked_year?: number;
  last_linked_year?: number;
}

export interface Video extends VideoCardData {
  first_linked_year?: number;
  last_linked_year?: number;
  mention_count?: number;
  comments?: CommentMention[];
  mentions?: CommentMention[]; // Compatible with existing file
}

export function getVideoComments(video: Video): CommentMention[] {
  return video.comments ?? video.mentions ?? [];
}

export function getVideoChannel(video: VideoCardData): string {
  return video.channel?.trim() || "YouTube";
}
