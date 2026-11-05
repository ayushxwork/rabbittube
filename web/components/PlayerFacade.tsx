"use client";

import { useState } from "react";
import { addToHistory } from "../lib/storage";

interface PlayerFacadeProps {
  videoId: string;
  title: string;
}

export default function PlayerFacade({ videoId, title }: PlayerFacadeProps) {
  const [isPlaying, setIsPlaying] = useState(false);

  const handlePlay = () => {
    setIsPlaying(true);
    addToHistory(videoId);
  };

  return (
    <div className="w-full">
      <div className="relative aspect-video w-full bg-black rounded-lg overflow-hidden shadow-md">
        {isPlaying ? (
          <iframe
            src={`https://www.youtube-nocookie.com/embed/${videoId}?autoplay=1`}
            title={title}
            className="w-full h-full border-0"
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
            allowFullScreen
          />
        ) : (
          <button
            type="button"
            onClick={handlePlay}
            aria-label={`Play video: ${title}`}
            className="relative w-full h-full block group cursor-pointer focus:outline-none"
          >
            {/* Facade Thumbnail */}
            <img
              src={`https://i.ytimg.com/vi/${videoId}/hqdefault.jpg`}
              alt={title}
              className="w-full h-full object-cover"
              loading="eager"
            />
            {/* Semi-transparent dark overlay */}
            <div className="absolute inset-0 bg-black/20 group-hover:bg-black/10 transition-colors" />
            {/* YouTube-style Play Button */}
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="w-16 h-12 bg-red-600 group-hover:bg-red-700 text-white rounded-xl flex items-center justify-center shadow-lg transition-transform group-hover:scale-105">
                <svg
                  className="w-6 h-6 fill-current translate-x-0.5"
                  viewBox="0 0 24 24"
                >
                  <path d="M8 5v14l11-7z" />
                </svg>
              </div>
            </div>
          </button>
        )}
      </div>

      {/* Visible Link to YouTube */}
      <div className="mt-2 flex items-center justify-between text-xs text-neutral-500 dark:text-neutral-400">
        <span>Embed served via youtube-nocookie.com</span>
        <a
          href={`https://www.youtube.com/watch?v=${videoId}`}
          target="_blank"
          rel="noopener noreferrer"
          className="text-blue-600 dark:text-blue-400 hover:underline flex items-center gap-1 font-medium"
        >
          Watch on YouTube ↗
        </a>
      </div>
    </div>
  );
}
