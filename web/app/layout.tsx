import type { Metadata } from "next";
import "./globals.css";
import Navbar from "../components/Navbar";
import Footer from "../components/Footer";

export const metadata: Metadata = {
  title: "VideoHub - Curated YouTube Index",
  description: "A curated YouTube index of videos recommended by the Hacker News community.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="min-h-screen flex flex-col bg-white dark:bg-neutral-950 text-neutral-900 dark:text-neutral-100 font-sans antialiased selection:bg-neutral-200 dark:selection:bg-neutral-800">
        <Navbar />
        <main className="max-w-7xl mx-auto px-4 py-6 flex-1 w-full">
          {children}
        </main>
        <Footer />
      </body>
    </html>
  );
}
