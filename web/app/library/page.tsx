import type { Metadata } from "next";
import { getAllVideos } from "../../lib/data";
import LibraryView from "../../components/LibraryView";

export const metadata: Metadata = {
  title: "Your Library - VideoHub",
  description: "View your liked videos, watch later queue, and viewing history.",
};

export default function LibraryPage() {
  const videos = getAllVideos();

  return <LibraryView allVideos={videos} />;
}
