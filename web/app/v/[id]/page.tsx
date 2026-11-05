import type { Metadata } from "next";
import { notFound } from "next/navigation";
import Link from "next/link";
import { getAllVideos, getVideoById } from "../../../lib/data";
import { getVideoChannel, getVideoComments } from "../../../types";
import PlayerFacade from "../../../components/PlayerFacade";
import VideoActions from "../../../components/VideoActions";

interface PageProps {
  params: Promise<{ id: string }>;
}

export async function generateStaticParams() {
  const videos = getAllVideos();
  return videos.map((v) => ({ id: v.video_id }));
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { id } = await params;
  const video = getVideoById(id);
  if (!video) {
    return {
      title: "Video Not Found - VideoHub",
    };
  }
  return {
    title: `${video.title} - VideoHub`,
    description: video.summary || `Recommended on Hacker News by ${video.distinct_users} users.`,
  };
}

export default async function VideoPage({ params }: PageProps) {
  const { id } = await params;
  const video = getVideoById(id);

  if (!video) {
    notFound();
  }

  const channel = getVideoChannel(video);
  const allComments = getVideoComments(video);

  // Filter for comments labeled "recommend"
  const recommendComments = allComments.filter(
    (c) => c.label === "recommend" || !c.label
  );
  const displayComments =
    recommendComments.length > 0 ? recommendComments : allComments;

  return (
    <div className="max-w-4xl mx-auto space-y-8">
      {/* Back button */}
      <div>
        <Link
          href="/"
          className="text-xs text-neutral-500 hover:text-black dark:hover:text-white inline-flex items-center gap-1 font-medium"
        >
          ← Back to all videos
        </Link>
      </div>

      {/* Player Facade */}
      <PlayerFacade videoId={video.video_id} title={video.title} />

      {/* Video Metadata Header */}
      <div className="space-y-4 border-b border-neutral-200 dark:border-neutral-800 pb-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="space-y-1 flex-1">
            <h1 className="text-xl sm:text-2xl font-bold tracking-tight leading-snug">
              {video.title}
            </h1>
            <div className="flex flex-wrap items-center gap-3 text-xs text-neutral-600 dark:text-neutral-400">
              <span className="font-semibold text-neutral-800 dark:text-neutral-200">
                {channel}
              </span>
              <span>•</span>
              <span className="bg-neutral-100 dark:bg-neutral-800 px-2 py-0.5 rounded text-[11px] font-medium text-neutral-700 dark:text-neutral-300">
                {video.topic}
              </span>
              <span>•</span>
              <span className="text-neutral-500">
                Recommended by {video.distinct_users} {video.distinct_users === 1 ? "person" : "people"} over {video.distinct_months} {video.distinct_months === 1 ? "month" : "months"}
              </span>
            </div>
          </div>

          {/* Action buttons (Like, Watch Later) */}
          <VideoActions videoId={video.video_id} />
        </div>

        {/* AI Summary Section */}
        {video.summary && (
          <div className="bg-neutral-50 dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-800 rounded-lg p-4 space-y-1.5">
            <h2 className="text-xs font-bold uppercase tracking-wider text-neutral-500 dark:text-neutral-400">
              AI Summary & Community Context
            </h2>
            <p className="text-sm text-neutral-800 dark:text-neutral-200 leading-relaxed">
              {video.summary}
            </p>
          </div>
        )}
      </div>

      {/* Community Recommendations / Comments Section */}
      <div className="space-y-4">
        <div>
          <h2 className="text-lg font-bold tracking-tight">
            Community Endorsements ({displayComments.length})
          </h2>
          <p className="text-xs text-neutral-500 dark:text-neutral-400">
            Hacker News comments recommending this video, with direct links to discussion threads.
          </p>
        </div>

        <div className="space-y-3">
          {displayComments.map((comment, idx) => {
            // Build HN thread or item URL
            const itemUrl = comment.url && comment.url.startsWith("http")
              ? comment.url
              : `https://news.ycombinator.com/item?id=${comment.id}`;

            return (
              <div
                key={comment.id || idx}
                className="bg-white dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-800 rounded-lg p-4 space-y-2"
              >
                <div className="flex items-center justify-between text-xs text-neutral-500 dark:text-neutral-400 border-b border-neutral-100 dark:border-neutral-800/60 pb-2">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-neutral-800 dark:text-neutral-200">
                      @{comment.author}
                    </span>
                    {comment.label && (
                      <span className="bg-green-100 dark:bg-green-950/60 text-green-800 dark:text-green-300 text-[10px] font-bold uppercase px-1.5 py-0.5 rounded">
                        {comment.label}
                      </span>
                    )}
                  </div>
                  <a
                    href={itemUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-blue-600 dark:text-blue-400 hover:underline flex items-center gap-1 font-medium"
                  >
                    View HN Thread ↗
                  </a>
                </div>

                <p className="text-xs sm:text-sm text-neutral-800 dark:text-neutral-200 whitespace-pre-line leading-relaxed">
                  {comment.text}
                </p>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
