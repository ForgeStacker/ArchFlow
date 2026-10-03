import { motion } from "framer-motion";
import { useEffect, useRef } from "react";
import gsap from "gsap";
import type { CompilationResponse } from "../lib/api";
import { DiagramPreview } from "./DiagramPreview";

interface ResultCardProps {
  result: CompilationResponse;
}

function downloadFile(filename: string, content: string, mime: string) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function ResultCard({ result }: ResultCardProps) {
  const scoreRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const target = { value: 0 };
    const tween = gsap.to(target, {
      value: result.quality_score,
      duration: 1.1,
      ease: "power2.out",
      onUpdate: () => {
        if (scoreRef.current) {
          scoreRef.current.textContent = Math.round(target.value).toString();
        }
      },
    });
    return () => {
      tween.kill();
    };
  }, [result.quality_score]);

  const errorCount = result.diagnostics.findings.filter((f) => f.severity === "error").length;
  const warningCount = result.diagnostics.findings.filter((f) => f.severity === "warning").length;
  const scoreColor =
    result.quality_score >= 90 ? "text-success" : result.quality_score >= 70 ? "text-warning" : "text-danger";

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.97, y: 16 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      transition={{ type: "spring", stiffness: 260, damping: 24 }}
      className="min-w-0 overflow-hidden rounded-xl border border-border bg-surface p-6 shadow-card"
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wider text-text-tertiary">
            {result.diagram_id}
          </h3>
          <div className="mt-1 flex items-baseline gap-1">
            <span ref={scoreRef} className={`text-4xl font-extrabold ${scoreColor}`}>
              0
            </span>
            <span className="text-lg font-semibold text-text-disabled">/100</span>
          </div>
          <p className="mt-1 text-xs text-text-tertiary">
            {result.diagnostics.hard_pass ? "All hard gates passed" : "Hard gates failing"} ·{" "}
            {result.resolved_icons.length} icons · {errorCount} errors · {warningCount} warnings
          </p>
        </div>
        <motion.div
          animate={{ rotate: [0, 6, -6, 0] }}
          transition={{ duration: 2.4, repeat: Infinity, ease: "easeInOut" }}
          className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-success-soft text-2xl text-success"
        >
          ✓
        </motion.div>
      </div>

      <div className="mt-5 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() =>
            downloadFile(`${result.diagram_id}.drawio`, result.drawio_xml, "application/xml")
          }
          className="rounded-lg bg-brand px-4 py-2.5 text-sm font-semibold text-white shadow-card transition-colors hover:bg-brand-hover"
        >
          Download .drawio
        </button>
        <a
          href={`https://app.diagrams.net/?splash=0#R${encodeURIComponent(btoa(result.drawio_xml))}`}
          target="_blank"
          rel="noreferrer"
          className="rounded-lg border border-border px-4 py-2.5 text-sm font-medium text-text-secondary transition-colors hover:border-brand hover:text-brand"
        >
          Open in draw.io ↗
        </a>
      </div>

      <div className="mt-5 min-w-0">
        <div className="mb-2 flex items-center justify-between gap-3">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-text-tertiary">
            Live draw.io preview
          </h4>
          <span className="text-[11px] text-text-disabled">Generated from this result</span>
        </div>
        <DiagramPreview xml={result.drawio_xml} />
      </div>

      {result.diagnostics.findings.length > 0 && (
        <div className="mt-5 max-h-40 overflow-y-auto rounded-xl border border-border bg-bg-subtle p-3">
          {result.diagnostics.findings.slice(0, 12).map((finding, index) => (
            <div
              key={`${finding.code}-${index}`}
              className="flex items-start gap-2 py-1 text-xs"
            >
              <span
                className={`mt-0.5 h-1.5 w-1.5 shrink-0 rounded-full ${
                  finding.severity === "error"
                    ? "bg-danger"
                    : finding.severity === "warning"
                      ? "bg-warning"
                      : "bg-text-disabled"
                }`}
              />
              <span className="text-text-secondary">{finding.message}</span>
            </div>
          ))}
        </div>
      )}
    </motion.div>
  );
}
