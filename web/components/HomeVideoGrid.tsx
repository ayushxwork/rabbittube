"use client";

import { useMemo, useState } from "react";
import { Video, getVideoChannel } from "../types";
import VideoCard from "./VideoCard";

interface HomeVideoGridProps {
  initialVideos: Video[];
  topics: string[];
}

export default function HomeVideoGrid({ initialVideos, topics }: HomeVideoGridProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedTopic, setSelectedTopic] = useState("All");

  const filteredVideos = useMemo(() => {
    const q = searchQuery.toLowerCase().trim();
    return initialVideos.filter((v) => {
      // Topic filter
      if (selectedTopic !== "All" && v.topic !== selectedTopic) {
        return false;
      }
      // Text search filter
      if (q) {
        const title = (v.title || "").toLowerCase();
        const channel = getVideoChannel(v).toLowerCase();
        const summary = (v.summary || "").toLowerCase();
        return title.includes(q) || channel.includes(q) || summary.includes(q);
      }
      return true;
    });
  }, [initialVideos, selectedTopic, searchQuery]);

  return (
    <div className="space-y-6">
      {/* Search & Topic Filters */}
      <div className="space-y-4">
        {/* Search Input */}
        <div className="relative max-w-xl">
          <input
            type="search"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search by title, channel, or summary..."
            className="w-full px-4 py-2.5 text-sm rounded-lg border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 text-neutral-900 dark:text-neutral-100 placeholder-neutral-400 focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          {searchQuery && (
            <button
              type="button"
              onClick={() => setSearchQuery("")}
              className="absolute right-3 top-2.5 text-xs text-neutral-400 hover:text-neutral-600 dark:hover:text-neutral-200"
            >
              Clear
            </button>
          )}
        </div>

        {/* Topic Filter Chips */}
        <div className="flex flex-wrap gap-2 items-center">
          <span className="text-xs font-semibold text-neutral-500 dark:text-neutral-400 mr-1">
            Topic:
          </span>
          <button
            type="button"
            onClick={() => setSelectedTopic("All")}
            className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
              selectedTopic === "All"
                ? "bg-black text-white dark:bg-white dark:text-black"
                : "bg-neutral-100 dark:bg-neutral-800 text-neutral-700 dark:text-neutral-300 hover:bg-neutral-200 dark:hover:bg-neutral-700"
            }`}
          >
            All ({initialVideos.length})
          </button>
          {topics.map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setSelectedTopic(t)}
              className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
                selectedTopic === t
                  ? "bg-black text-white dark:bg-white dark:text-black"
                  : "bg-neutral-100 dark:bg-neutral-800 text-neutral-700 dark:text-neutral-300 hover:bg-neutral-200 dark:hover:bg-neutral-700"
              }`}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      {/* Results Header */}
      <div className="flex items-center justify-between text-xs text-neutral-500 dark:text-neutral-400 pt-2 border-t border-neutral-200 dark:border-neutral-800">
        <span>
          Showing {filteredVideos.length} of {initialVideos.length} videos
          {selectedTopic !== "All" && ` in "${selectedTopic}"`}
          {searchQuery && ` matching "${searchQuery}"`}
        </span>
        <span>Sorted by months, users, title</span>
      </div>

      {/* Video Grid */}
      {filteredVideos.length > 0 ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {filteredVideos.map((video) => (
            <VideoCard key={video.video_id} video={video} />
          ))}
        </div>
      ) : (
        <div className="text-center py-16 border border-dashed border-neutral-300 dark:border-neutral-700 rounded-lg p-6">
          <p className="text-sm font-medium text-neutral-600 dark:text-neutral-400">
            No videos found matching your filters.
          </p>
          {(searchQuery || selectedTopic !== "All") && (
            <button
              type="button"
              onClick={() => {
                setSearchQuery("");
                setSelectedTopic("All");
              }}
              className="mt-3 text-xs text-blue-600 dark:text-blue-400 hover:underline font-medium"
            >
              Reset filters
            </button>
          )}
        </div>
      )}
    </div>
  );
}
