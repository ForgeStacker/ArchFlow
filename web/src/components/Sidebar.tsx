import { motion } from "framer-motion";
import type { ReactNode } from "react";

export type NavKey =
  | "create"
  | "diagrams"
  | "templates"
  | "icons"
  | "integrations"
  | "settings";

interface NavItem {
  key: NavKey;
  label: string;
  icon: ReactNode;
}

const NAV_ITEMS: NavItem[] = [
  { key: "create", label: "Create Diagram", icon: <IconGrid /> },
  { key: "diagrams", label: "My Diagrams", icon: <IconLayers /> },
  { key: "templates", label: "Templates", icon: <IconTemplate /> },
  { key: "icons", label: "Icon Library", icon: <IconPuzzle /> },
  { key: "integrations", label: "Integrations", icon: <IconPlug /> },
  { key: "settings", label: "Settings", icon: <IconGear /> },
];

interface SidebarProps {
  active: NavKey;
  onNavigate: (key: NavKey) => void;
  backendOnline: boolean;
  diagramsUsed: number;
  diagramsLimit: number;
}

export function Sidebar({ active, onNavigate, backendOnline, diagramsUsed, diagramsLimit }: SidebarProps) {
  const usagePercent = Math.min(100, Math.round((diagramsUsed / diagramsLimit) * 100));

  return (
    <aside className="flex h-screen w-[260px] shrink-0 flex-col border-r border-border bg-bg-subtle">
      <div className="flex items-center gap-2.5 px-5 py-5">
        <div className="grid h-8 w-8 place-items-center rounded-xl bg-brand text-white">
          <IconCloud />
        </div>
        <span className="text-[15px] font-semibold text-text-primary">Cloud Diagram Compiler</span>
      </div>

      <nav className="flex-1 overflow-y-auto scrollbar-thin px-3 py-2">
        {NAV_ITEMS.map((item) => {
          const isActive = item.key === active;
          return (
            <button
              key={item.key}
              type="button"
              onClick={() => onNavigate(item.key)}
              className={`relative mb-0.5 flex w-full items-center gap-2.5 rounded-lg px-3 py-2.5 text-left text-sm transition-colors ${
                isActive ? "font-medium text-brand-active" : "text-text-secondary hover:bg-[#EAE5DD]"
              }`}
            >
              {isActive && (
                <motion.div
                  layoutId="sidebar-active-pill"
                  className="absolute inset-0 rounded-lg bg-brand-soft"
                  transition={{ type: "spring", stiffness: 420, damping: 34 }}
                />
              )}
              <span className="relative z-10 grid h-4 w-4 place-items-center">{item.icon}</span>
              <span className="relative z-10">{item.label}</span>
            </button>
          );
        })}
      </nav>

      <div className="mx-3 mb-3 rounded-xl border border-border bg-surface p-3.5">
        <div className="flex items-center justify-between text-xs">
          <span className="font-medium text-text-primary">Diagrams created</span>
          <span className="text-text-tertiary">
            {diagramsUsed === 0
              ? "No diagrams yet"
              : `${diagramsUsed} ${diagramsUsed === 1 ? "diagram" : "diagrams"}`}
          </span>
        </div>
        {diagramsUsed > 0 && (
          <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-border-subtle">
            <motion.div
              initial={{ width: 0 }}
              animate={{ width: `${usagePercent}%` }}
              transition={{ duration: 0.8, ease: "easeOut" }}
              className="h-full rounded-full bg-brand"
            />
          </div>
        )}
      </div>

      <div className="mx-3 mb-5 rounded-xl border border-border bg-surface p-3.5">
        <div className="flex items-center gap-2">
          <span
            className={`h-2 w-2 rounded-full ${backendOnline ? "bg-success-dot" : "bg-danger"}`}
          />
          <span className="text-xs font-medium text-text-primary">
            {backendOnline ? "Backend Connected" : "Backend Unavailable"}
          </span>
        </div>
        <p className="mt-1.5 text-[11px] leading-snug text-text-tertiary">
          {backendOnline
            ? "Using secure server-side compilation. No API key needed in your browser."
            : "Could not reach the compiler API. Check the backend is running."}
        </p>
        <button type="button" className="mt-2 text-[11px] font-medium text-brand hover:text-brand-hover">
          View Details →
        </button>
      </div>
    </aside>
  );
}

function IconCloud() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
      <path
        d="M4.5 11.5a2.5 2.5 0 0 1 0-5c.1 0 .2 0 .3.01A3.5 3.5 0 0 1 11.4 6 2.6 2.6 0 0 1 11 11.5h-6.5Z"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function IconGrid() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3">
      <rect x="2" y="2" width="5" height="5" rx="1" />
      <rect x="9" y="2" width="5" height="5" rx="1" />
      <rect x="2" y="9" width="5" height="5" rx="1" />
      <rect x="9" y="9" width="5" height="5" rx="1" />
    </svg>
  );
}

function IconLayers() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round">
      <path d="M8 2 2 5l6 3 6-3-6-3Z" />
      <path d="M2 8l6 3 6-3" />
      <path d="M2 11l6 3 6-3" />
    </svg>
  );
}

function IconTemplate() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3">
      <rect x="2" y="2" width="12" height="12" rx="1.5" />
      <path d="M2 6h12" />
      <path d="M6 6v8" />
    </svg>
  );
}

function IconPuzzle() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round">
      <path d="M6 2.5h2a1 1 0 0 1 1 1v1.2a1 1 0 0 0 1.5.9 1.3 1.3 0 1 1 0 2.4 1 1 0 0 0-1.5.9V10a1 1 0 0 1-1 1H6" />
      <path d="M6 11H4a1 1 0 0 1-1-1V8.8a1 1 0 0 0-1.5-.9 1.3 1.3 0 1 1 0-2.4A1 1 0 0 0 3 4.6V3.5a1 1 0 0 1 1-1h2" />
    </svg>
  );
}

function IconPlug() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round">
      <path d="M6 2v3M10 2v3" />
      <path d="M4 5h8v2.5A4 4 0 0 1 8 11.5a4 4 0 0 1-4-4V5Z" />
      <path d="M8 11.5V14" />
    </svg>
  );
}

function IconGear() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3">
      <circle cx="8" cy="8" r="2.2" />
      <path d="M8 2.5v1.4M8 12.1v1.4M13.5 8h-1.4M3.9 8H2.5M11.7 4.3l-1 1M5.3 10.7l-1 1M11.7 11.7l-1-1M5.3 5.3l-1-1" />
    </svg>
  );
}
