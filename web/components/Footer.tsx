export default function Footer() {
  return (
    <footer className="border-t border-neutral-200 dark:border-neutral-800 bg-neutral-50 dark:bg-neutral-950 mt-16 py-8 text-xs text-neutral-600 dark:text-neutral-400">
      <div className="max-w-7xl mx-auto px-4 space-y-3">
        <p>
          Data from the{" "}
          <a
            href="https://huggingface.co/datasets/open-index/hacker-news"
            target="_blank"
            rel="noopener noreferrer"
            className="underline hover:text-black dark:hover:text-white"
          >
            open-index/hacker-news
          </a>{" "}
          dataset, derived from Hacker News content hosted by Y Combinator.
        </p>
        <p>
          Licensed under the{" "}
          <a
            href="https://opendatacommons.org/licenses/by/1-0/"
            target="_blank"
            rel="noopener noreferrer"
            className="underline hover:text-black dark:hover:text-white"
          >
            Open Data Commons Attribution License (ODC-By v1.0)
          </a>
          .
        </p>
        <p>
          VideoHub is an independent community project, not affiliated with or endorsed by Y Combinator or YouTube.
        </p>
        <p className="text-neutral-500 dark:text-neutral-500">
          Summaries, topics and labels are AI-generated and may be wrong.
        </p>
      </div>
    </footer>
  );
}
