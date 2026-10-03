import { AnimatePresence, motion } from "framer-motion";
import { useState } from "react";
import type { LlmOverride } from "../lib/api";

interface GenerationSettingsCardProps {
  llm: LlmOverride;
  onLlmChange: (value: LlmOverride) => void;
}

export function GenerationSettingsCard({ llm, onLlmChange }: GenerationSettingsCardProps) {
  const [expanded, setExpanded] = useState(false);
  const [revealed, setRevealed] = useState(false);
  const hasOwnKey = Boolean(llm.api_key);

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay: 0.08 }}
      className="rounded-2xl border border-border bg-surface p-5 shadow-card"
    >
      <div className="flex items-center gap-2">
        <span className="grid h-6 w-6 place-items-center rounded-md bg-bg-subtle text-text-secondary">
          <IconGear />
        </span>
        <h3 className="text-sm font-semibold text-text-primary">Generation Settings</h3>
      </div>

      <div className="mt-4 space-y-3">
        <SettingsRow label="Diagram layout" value="Left to Right" />
        <SettingsRow label="Detail level" value="Standard" />
        <div className="flex items-center justify-between">
          <span className="text-sm text-text-secondary">Show resource names</span>
          <ToggleStub />
        </div>
      </div>

      <div className="my-4 h-px bg-border-subtle" />

      <div className="flex items-center justify-between text-sm">
        <div className="flex items-center gap-1.5 text-text-secondary">
          <span className="h-1.5 w-1.5 rounded-full bg-success-dot" />
          AI Engine
        </div>
        <span className="text-xs text-text-tertiary">Connected (server-side)</span>
      </div>
      <div className="mt-2 flex items-center justify-between text-xs text-text-tertiary">
        <span>Provider</span>
        <span className="text-text-secondary">{llm.endpoint ? "Custom endpoint" : "Server default"}</span>
      </div>
      <div className="mt-1 flex items-center justify-between text-xs text-text-tertiary">
        <span>Model</span>
        <span className="truncate text-text-secondary">{llm.model || "Server default"}</span>
      </div>

      <button
        type="button"
        onClick={() => setExpanded((prev) => !prev)}
        className="mt-3 text-xs font-medium text-brand hover:text-brand-hover"
      >
        Manage in Settings →
      </button>

      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.22, ease: "easeOut" }}
            className="overflow-hidden"
          >
            <div className="mt-3 space-y-2 rounded-xl border border-border-subtle bg-bg-subtle p-3">
              <p className="text-[11px] font-medium text-text-tertiary">
                Bring your own key (session-only, never stored)
              </p>
              <div className="flex items-center gap-2">
                <input
                  type={revealed ? "text" : "password"}
                  value={llm.api_key ?? ""}
                  onChange={(event) => onLlmChange({ ...llm, api_key: event.target.value || undefined })}
                  placeholder="sk-... or nvapi-..."
                  autoComplete="off"
                  spellCheck={false}
                  className="flex-1 rounded-lg border border-border bg-surface px-2.5 py-2 font-mono text-xs text-text-primary placeholder:text-text-tertiary outline-none focus:border-brand focus:shadow-focus-ring"
                />
                <button
                  type="button"
                  onClick={() => setRevealed((prev) => !prev)}
                  className="rounded-lg border border-border px-2 py-2 text-[11px] text-text-secondary hover:border-text-tertiary"
                >
                  {revealed ? "Hide" : "Show"}
                </button>
              </div>
              <input
                type="text"
                value={llm.endpoint ?? ""}
                onChange={(event) => onLlmChange({ ...llm, endpoint: event.target.value || undefined })}
                placeholder="Custom endpoint (optional)"
                className="w-full rounded-lg border border-border bg-surface px-2.5 py-2 text-xs text-text-primary placeholder:text-text-tertiary outline-none focus:border-brand focus:shadow-focus-ring"
              />
              <input
                type="text"
                value={llm.model ?? ""}
                onChange={(event) => onLlmChange({ ...llm, model: event.target.value || undefined })}
                placeholder="Custom model (optional)"
                className="w-full rounded-lg border border-border bg-surface px-2.5 py-2 text-xs text-text-primary placeholder:text-text-tertiary outline-none focus:border-brand focus:shadow-focus-ring"
              />
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="mt-4 flex gap-2.5 rounded-xl bg-success-soft p-3">
        <span className="mt-0.5 shrink-0 text-success-dot">
          <IconShieldCheck />
        </span>
        <div>
          <p className="text-xs font-medium text-success-text">
            {hasOwnKey ? "Using your own API key" : "No API key required"}
          </p>
          <p className="mt-0.5 text-[11px] leading-snug text-success-text/80">
            {hasOwnKey
              ? "Sent only with this request, never stored server-side."
              : "Your diagrams compile using the server's securely stored key. Nothing is exposed in your browser."}
          </p>
        </div>
      </div>
    </motion.div>
  );
}

function SettingsRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-sm text-text-secondary">{label}</span>
      <button
        type="button"
        className="flex items-center gap-1.5 rounded-lg border border-border bg-surface px-2.5 py-1.5 text-xs text-text-primary hover:border-text-tertiary"
      >
        {value}
        <IconChevronDown />
      </button>
    </div>
  );
}

function ToggleStub() {
  return (
    <span className="relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full bg-brand transition-colors">
      <span className="absolute left-[2px] h-4 w-4 translate-x-4 rounded-full bg-white shadow-sm transition-transform" />
    </span>
  );
}

function IconGear() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3">
      <circle cx="8" cy="8" r="2.2" />
      <path d="M8 2.5v1.4M8 12.1v1.4M13.5 8h-1.4M3.9 8H2.5M11.7 4.3l-1 1M5.3 10.7l-1 1M11.7 11.7l-1-1M5.3 5.3l-1-1" />
    </svg>
  );
}

function IconChevronDown() {
  return (
    <svg width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 6l4 4 4-4" />
    </svg>
  );
}

function IconShieldCheck() {
  return (
    <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round">
      <path d="M8 2l5 1.8v4.1c0 3-2.1 5.3-5 6.1-2.9-.8-5-3.1-5-6.1V3.8L8 2Z" />
      <path d="M5.8 8l1.6 1.6L10.4 6" strokeLinecap="round" />
    </svg>
  );
}
