"use client";

import { useEffect, useState } from "react";
import { isLiked, isWatchLater, toggleLiked, toggleWatchLater } from "../lib/storage";

interface VideoActionsProps {
  videoId: string;
}

export default function VideoActions({ videoId }: VideoActionsProps) {
  const [liked, setLiked] = useState(false);
  const [watchLater, setWatchLater] = useState(false);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    setLiked(isLiked(videoId));
    setWatchLater(isWatchLater(videoId));
  }, [videoId]);

  const handleLike = () => {
    const next = toggleLiked(videoId);
    setLiked(next);
  };

  const handleWatchLater = () => {
    const next = toggleWatchLater(videoId);
    setWatchLater(next);
  };

  if (!mounted) {
    return (
      <div className="flex items-center gap-2">
        <button
          type="button"
          disabled
          className="px-3 py-1.5 text-xs font-medium rounded-md bg-neutral-100 dark:bg-neutral-800 text-neutral-400 opacity-50"
        >
          ♥ Like
        </button>
        <button
          type="button"
          disabled
          className="px-3 py-1.5 text-xs font-medium rounded-md bg-neutral-100 dark:bg-neutral-800 text-neutral-400 opacity-50"
        >
          ⏱ Watch later
        </button>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        onClick={handleLike}
        className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
          liked
            ? "bg-red-600 text-white"
            : "bg-neutral-100 dark:bg-neutral-800 text-neutral-700 dark:text-neutral-300 hover:bg-neutral-200 dark:hover:bg-neutral-700"
        }`}
      >
        {liked ? "♥ Liked" : "♡ Like"}
      </button>

      <button
        type="button"
        onClick={handleWatchLater}
        className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
          watchLater
            ? "bg-black text-white dark:bg-white dark:text-black"
            : "bg-neutral-100 dark:bg-neutral-800 text-neutral-700 dark:text-neutral-300 hover:bg-neutral-200 dark:hover:bg-neutral-700"
        }`}
      >
        {watchLater ? "✓ Saved" : "+ Watch later"}
      </button>
    </div>
  );
}
