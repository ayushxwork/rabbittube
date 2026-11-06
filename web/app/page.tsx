import type { Metadata } from "next";
import { getVideoCards, getActiveTopics } from "../lib/data";
import HomeVideoGrid from "../components/HomeVideoGrid";

export const metadata: Metadata = {
  title: "VideoHub - Community-Curated YouTube Index",
  description: "Curated index of YouTube videos that Hacker News commenters repeatedly link to.",
};

export default function HomePage() {
  const videos = getVideoCards();
  const topics = getActiveTopics();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Frequently Linked Videos</h1>
        <p className="text-xs text-neutral-500 dark:text-neutral-400 mt-1">
          Tech talks, tutorials, and discussions repeatedly linked on Hacker News.
        </p>
      </div>

      <HomeVideoGrid initialVideos={videos} topics={topics} />
    </div>
  );
}
