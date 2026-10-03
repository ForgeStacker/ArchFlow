import { motion } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import gsap from "gsap";
import type { Provider } from "../lib/api";

const STAGES = ["Planning architecture", "Resolving icons", "Routing edges", "Rendering draw.io"];
const MAX_CHARS = 2000;

const PROVIDERS: { id: Provider | "auto"; label: string; dotColor: string }[] = [
  { id: "aws", label: "AWS", dotColor: "bg-provider-aws" },
  { id: "azure", label: "Azure", dotColor: "bg-provider-azure" },
  { id: "gcp", label: "Google Cloud", dotColor: "bg-provider-gcp" },
  { id: "auto", label: "Auto-detect", dotColor: "bg-text-tertiary" },
];

const EXAMPLE_PROMPT =
  "A serverless API with a queue-backed worker writing to a database, plus monitoring and alerts";

interface PromptCardProps {
  prompt: string;
  onPromptChange: (prompt: string) => void;
  provider: Provider;
  onProviderChange: (provider: Provider) => void;
  onSubmit: () => void;
  loading: boolean;
  error: string | null;
}

export function PromptCard({
  prompt,
  onPromptChange,
  provider,
  onProviderChange,
  onSubmit,
  loading,
  error,
}: PromptCardProps) {
  const [stageIndex, setStageIndex] = useState(0);
  const barRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!loading) {
      setStageIndex(0);
      return;
    }
    const timeline = gsap.timeline({ repeat: -1 });
    STAGES.forEach((_, index) => {
      timeline.call(() => setStageIndex(index));
      timeline.to({}, { duration: 1.1 });
    });
    if (barRef.current) {
      gsap.fromTo(
        barRef.current,
        { backgroundPosition: "0% 0%" },
        { backgroundPosition: "200% 0%", duration: 1.6, repeat: -1, ease: "none" },
      );
    }
    return () => {
      timeline.kill();
    };
  }, [loading]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5 }}
      className="rounded-2xl border border-border bg-surface p-6 shadow-card"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="grid h-7 w-7 place-items-center rounded-lg bg-brand-wash text-brand">
            <IconWand />
          </span>
          <h2 className="text-sm font-semibold text-text-primary">Describe your architecture</h2>
        </div>
        <button
          type="button"
          onClick={() => onPromptChange(EXAMPLE_PROMPT)}
          className="flex items-center gap-1 rounded-full border border-border px-3 py-1.5 text-xs font-medium text-text-secondary transition-colors hover:border-brand hover:text-brand"
        >
          <IconSparkle />
          Try an example
        </button>
      </div>

      <div className="relative mt-3">
        <textarea
          value={prompt}
          onChange={(event) => onPromptChange(event.target.value.slice(0, MAX_CHARS))}
          placeholder={`e.g. A serverless API with a queue-backed worker writing to a database,\nplus monitoring and alerts`}
          rows={4}
          className="w-full resize-none rounded-xl border border-border bg-surface px-4 py-3.5 text-[15px] text-text-primary placeholder:text-text-tertiary outline-none transition-[border-color,box-shadow] focus:border-brand focus:shadow-focus-ring"
        />
        <span className="pointer-events-none absolute bottom-3 right-4 text-xs text-text-tertiary">
          {prompt.length}/{MAX_CHARS}
        </span>
      </div>

      <div className="mt-5 flex flex-wrap items-start justify-between gap-6">
        <div>
          <p className="mb-2 text-xs font-medium text-text-secondary">Cloud provider</p>
          <div className="flex gap-2">
            {PROVIDERS.map((item) => {
              const active = item.id === provider;
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => item.id !== "auto" && onProviderChange(item.id)}
                  className={`flex items-center gap-1.5 rounded-lg border px-3 py-2 text-sm transition-colors ${
                    active
                      ? "border-brand bg-brand-wash font-medium text-brand-active"
                      : "border-border bg-surface text-text-secondary hover:border-text-tertiary"
                  }`}
                >
                  {item.id !== "auto" && <span className={`h-2 w-2 rounded-full ${item.dotColor}`} />}
                  {active && item.id !== "auto" && <IconCheck />}
                  {item.label}
                </button>
              );
            })}
          </div>
        </div>

        <div>
          <p className="mb-2 text-xs font-medium text-text-secondary">Architecture style (optional)</p>
          <button
            type="button"
            className="flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text-secondary transition-colors hover:border-text-tertiary"
          >
            <IconSparkle />
            Auto-detect
            <IconChevronDown />
          </button>
        </div>
      </div>

      <motion.button
        type="button"
        onClick={onSubmit}
        disabled={loading || prompt.trim().length === 0}
        whileTap={{ scale: 0.985 }}
        className="mt-5 flex w-full items-center justify-center gap-2 rounded-xl bg-brand px-6 py-3.5 text-sm font-semibold text-white transition-colors hover:bg-brand-hover disabled:cursor-not-allowed disabled:opacity-50"
      >
        {loading ? (
          "Compiling…"
        ) : (
          <>
            <IconSparkle />
            Generate Diagram
            <IconArrowRight />
          </>
        )}
      </motion.button>

      {loading && (
        <div className="mt-3">
          <div
            ref={barRef}
            className="h-1 w-full overflow-hidden rounded-full bg-border-subtle"
            style={{
              backgroundImage:
                "linear-gradient(90deg, rgba(184,87,56,0.12) 0%, rgba(184,87,56,0.9) 50%, rgba(184,87,56,0.12) 100%)",
              backgroundSize: "200% 100%",
            }}
          />
          <motion.p key={stageIndex} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} className="mt-2 text-xs text-text-tertiary">
            {STAGES[stageIndex]}…
          </motion.p>
        </div>
      )}

      {error && (
        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="mt-4 rounded-xl border border-danger/25 bg-danger-soft px-4 py-3 text-sm text-danger-text"
        >
          {error}
        </motion.p>
      )}
    </motion.div>
  );
}

function IconWand() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 14l5-5" />
      <path d="M8.5 2.5l1 1M12 2v2M14 4.5h2M9.5 5.5l5 5-2 2-5-5 2-2Z" />
    </svg>
  );
}

function IconSparkle() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="currentColor">
      <path d="M8 1.5l1.3 3.9 3.9 1.3-3.9 1.3L8 11.9l-1.3-3.9-3.9-1.3 3.9-1.3L8 1.5Z" />
    </svg>
  );
}

function IconCheck() {
  return (
    <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 8.5l3.2 3.2L13 5" />
    </svg>
  );
}

function IconChevronDown() {
  return (
    <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 6l4 4 4-4" />
    </svg>
  );
}

function IconArrowRight() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 8h10M9 4l4 4-4 4" />
    </svg>
  );
}
