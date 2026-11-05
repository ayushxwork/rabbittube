import Link from "next/link";

export default function Navbar() {
  return (
    <header className="border-b border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 sticky top-0 z-30">
      <div className="max-w-7xl mx-auto px-4 h-14 flex items-center justify-between">
        <Link href="/" className="flex items-center gap-2 font-bold text-lg tracking-tight hover:opacity-80">
          <span className="bg-red-600 text-white text-xs px-2 py-0.5 rounded font-black">
            PLAY
          </span>
          <span>VideoHub</span>
        </Link>
        <nav className="flex items-center gap-4 text-sm font-medium">
          <Link
            href="/"
            className="text-neutral-600 dark:text-neutral-300 hover:text-black dark:hover:text-white px-2 py-1 rounded"
          >
            Home
          </Link>
          <Link
            href="/library"
            className="text-neutral-600 dark:text-neutral-300 hover:text-black dark:hover:text-white px-2 py-1 rounded"
          >
            Library
          </Link>
        </nav>
      </div>
    </header>
  );
}
