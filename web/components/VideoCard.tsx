"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Video, getVideoChannel } from "../types";
import { isWatchLater, toggleWatchLater } from "../lib/storage";

interface VideoCardProps {
  video: Video;
}

export default function VideoCard({ video }: VideoCardProps) {
  const [saved, setSaved] = useState(false);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    setSaved(isWatchLater(video.video_id));
  }, [video.video_id]);

  const handleToggleWatchLater = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    const nextSaved = toggleWatchLater(video.video_id);
    setSaved(nextSaved);
  };

  const channel = getVideoChannel(video);

  return (
    <article className="flex flex-col bg-white dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-800 rounded-lg overflow-hidden hover:border-neutral-400 dark:hover:border-neutral-600 transition-colors">
      {/* Thumbnail area */}
      <Link href={`/v/${video.video_id}`} className="relative aspect-video w-full bg-neutral-100 dark:bg-neutral-800 block group overflow-hidden">
        <img
          src={`https://i.ytimg.com/vi/${video.video_id}/hqdefault.jpg`}
          alt={video.title}
          className="w-full h-full object-cover group-hover:scale-105 transition-transform"
          loading="lazy"
        />
        {/* Topic Tag Badge */}
        {video.topic && (
          <span className="absolute bottom-2 left-2 bg-black/80 text-white text-[11px] font-medium px-2 py-0.5 rounded">
            {video.topic}
          </span>
        )}
        {/* Quick Watch Later button */}
        {mounted && (
          <button
            type="button"
            onClick={handleToggleWatchLater}
            title={saved ? "Remove from Watch later" : "Save to Watch later"}
            aria-label={saved ? "Remove from Watch later" : "Save to Watch later"}
            className="absolute top-2 right-2 p-1.5 rounded-full bg-black/70 hover:bg-black text-white text-xs opacity-0 group-hover:opacity-100 transition-opacity"
          >
            {saved ? "✓" : "⏱"}
          </button>
        )}
      </Link>

      {/* Info area */}
      <div className="p-3.5 flex flex-col flex-1">
        <h3 className="font-semibold text-sm leading-snug line-clamp-2 hover:text-blue-600 dark:hover:text-blue-400">
          <Link href={`/v/${video.video_id}`}>
            {video.title}
          </Link>
        </h3>
        
        <p className="text-xs text-neutral-600 dark:text-neutral-400 mt-1 line-clamp-1">
          {channel}
        </p>

        <p className="text-[11px] text-neutral-500 dark:text-neutral-500 mt-0.5">
          {video.distinct_users} {video.distinct_users === 1 ? "user" : "users"} · {video.distinct_months} {video.distinct_months === 1 ? "month" : "months"}
        </p>

        {video.summary && (
          <p className="text-xs text-neutral-700 dark:text-neutral-300 mt-2 line-clamp-2 bg-neutral-50 dark:bg-neutral-800/50 p-2 rounded border border-neutral-100 dark:border-neutral-800 flex-1">
            {video.summary}
          </p>
        )}
      </div>
    </article>
  );
}
