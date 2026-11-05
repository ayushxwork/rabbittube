import type { Metadata } from "next";
import { getAllVideos, getActiveTopics } from "../lib/data";
import HomeVideoGrid from "../components/HomeVideoGrid";

export const metadata: Metadata = {
  title: "VideoHub - Community-Curated YouTube Index",
  description: "Curated index of YouTube videos that the Hacker News community keeps recommending.",
};

export default function HomePage() {
  const videos = getAllVideos();
  const topics = getActiveTopics();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Community Recommendations</h1>
        <p className="text-xs text-neutral-500 dark:text-neutral-400 mt-1">
          Hand-picked tech talks, tutorials, and discussions persistently endorsed on Hacker News.
        </p>
      </div>

      <HomeVideoGrid initialVideos={videos} topics={topics} />
    </div>
  );
}
