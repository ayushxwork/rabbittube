"use client";

import { useEffect, useState } from "react";
import { VideoCardData } from "../types";
import { clearHistory, getHistoryIds, getLikedIds, getWatchLaterIds } from "../lib/storage";
import VideoCard from "./VideoCard";

interface LibraryViewProps {
  allVideos: VideoCardData[];
}

type TabType = "liked" | "watch_later" | "history";

export default function LibraryView({ allVideos }: LibraryViewProps) {
  const [activeTab, setActiveTab] = useState<TabType>("liked");
  const [likedIds, setLikedIds] = useState<string[]>([]);
  const [watchLaterIds, setWatchLaterIds] = useState<string[]>([]);
  const [historyIds, setHistoryIds] = useState<string[]>([]);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    setLikedIds(getLikedIds());
    setWatchLaterIds(getWatchLaterIds());
    setHistoryIds(getHistoryIds());
  }, []);

  const handleClearHistory = () => {
    clearHistory();
    setHistoryIds([]);
  };

  const videoMap = new Map(allVideos.map((v) => [v.video_id, v]));

  // Get ordered videos for current tab
  const getTabVideos = (ids: string[]): VideoCardData[] => {
    const list: VideoCardData[] = [];
    for (const id of ids) {
      const v = videoMap.get(id);
      if (v) list.push(v);
    }
    return list;
  };

  const currentList =
    activeTab === "liked"
      ? getTabVideos(likedIds)
      : activeTab === "watch_later"
      ? getTabVideos(watchLaterIds)
      : getTabVideos(historyIds);

  return (
    <div className="space-y-6">
      {/* Page Title */}
      <div>
        <h1 className="text-xl font-bold tracking-tight">Your Library</h1>
        <p className="text-xs text-neutral-500 dark:text-neutral-400 mt-1">
          Saved and recently watched videos stored locally in your browser.
        </p>
      </div>

      {/* Tabs */}
      <div className="flex items-center justify-between border-b border-neutral-200 dark:border-neutral-800">
        <div className="flex items-center gap-6">
          <button
            type="button"
            onClick={() => setActiveTab("liked")}
            className={`pb-3 text-sm font-semibold transition-colors relative ${
              activeTab === "liked"
                ? "text-black dark:text-white border-b-2 border-black dark:border-white"
                : "text-neutral-500 hover:text-black dark:hover:text-white"
            }`}
          >
            Liked {mounted && `(${likedIds.length})`}
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("watch_later")}
            className={`pb-3 text-sm font-semibold transition-colors relative ${
              activeTab === "watch_later"
                ? "text-black dark:text-white border-b-2 border-black dark:border-white"
                : "text-neutral-500 hover:text-black dark:hover:text-white"
            }`}
          >
            Watch Later {mounted && `(${watchLaterIds.length})`}
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("history")}
            className={`pb-3 text-sm font-semibold transition-colors relative ${
              activeTab === "history"
                ? "text-black dark:text-white border-b-2 border-black dark:border-white"
                : "text-neutral-500 hover:text-black dark:hover:text-white"
            }`}
          >
            History {mounted && `(${historyIds.length})`}
          </button>
        </div>

        {activeTab === "history" && mounted && historyIds.length > 0 && (
          <button
            type="button"
            onClick={handleClearHistory}
            className="text-xs text-red-600 dark:text-red-400 hover:underline mb-3"
          >
            Clear History
          </button>
        )}
      </div>

      {/* Content */}
      {!mounted ? (
        <div className="text-center py-16 text-sm text-neutral-400">
          Loading library...
        </div>
      ) : currentList.length > 0 ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {currentList.map((video) => (
            <VideoCard key={video.video_id} video={video} />
          ))}
        </div>
      ) : (
        <div className="text-center py-16 border border-dashed border-neutral-300 dark:border-neutral-700 rounded-lg p-6">
          <p className="text-sm font-medium text-neutral-600 dark:text-neutral-400">
            {activeTab === "liked" && "No liked videos yet. Click the Like button on any video page."}
            {activeTab === "watch_later" && "No videos in Watch Later. Save videos from the home grid or video pages."}
            {activeTab === "history" && "No watch history. Videos you play will appear here."}
          </p>
        </div>
      )}
    </div>
  );
}
