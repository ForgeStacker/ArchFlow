import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { searchIcons, type IconResult, type Provider } from "../lib/api";

interface IconExplorerCardProps {
  provider: Provider;
}

export function IconExplorerCard({ provider }: IconExplorerCardProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<IconResult[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const handle = window.setTimeout(() => {
      setLoading(true);
      searchIcons({ q: query, provider, limit: 8 })
        .then((response) => setResults(response.results))
        .catch(() => setResults([]))
        .finally(() => setLoading(false));
    }, 250);
    return () => window.clearTimeout(handle);
  }, [query, provider]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.1 }}
      className="rounded-xl border border-border bg-surface p-5 shadow-card"
    >
      <h3 className="text-xs font-semibold uppercase tracking-wider text-text-tertiary">
        Browse the offline icon registry
      </h3>
      <input
        type="text"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="Search Lambda, Cosmos DB, BigQuery…"
        className="mt-3 w-full rounded-lg border border-border bg-bg px-3 py-2.5 text-sm text-text-primary placeholder:text-text-disabled outline-none transition-colors focus:border-brand focus:shadow-focus-ring"
      />
      <div className="mt-3 space-y-1">
        {loading && <p className="text-xs text-text-disabled">Searching…</p>}
        {!loading && query && results.length === 0 && (
          <p className="text-xs text-text-disabled">No exact matches for this provider.</p>
        )}
        {results.map((icon, index) => (
          <motion.div
            key={icon.id}
            initial={{ opacity: 0, x: -6 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: index * 0.03 }}
            className="flex items-center justify-between rounded-lg px-2.5 py-1.5 text-xs hover:bg-bg-subtle"
          >
            <span className="text-text-secondary">{icon.display_name}</span>
            <span className="rounded-full bg-bg-subtle px-2 py-0.5 font-mono text-[10px] text-text-tertiary">
              {icon.kind}
            </span>
          </motion.div>
        ))}
      </div>
    </motion.div>
  );
}
