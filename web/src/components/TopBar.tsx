interface TopBarProps {
  backendOnline: boolean;
}

export function TopBar({ backendOnline }: TopBarProps) {
  return (
    <header className="flex h-[60px] shrink-0 items-center justify-between gap-4 border-b border-border bg-surface px-6">
      <div className="relative w-full max-w-md">
        <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-text-tertiary">
          <IconSearch />
        </span>
        <input
          type="text"
          placeholder="Search templates, icons, or documentation…"
          className="w-full rounded-lg border border-border bg-bg py-2 pl-9 pr-14 text-sm text-text-primary placeholder:text-text-tertiary outline-none transition-[border-color,box-shadow] focus:border-brand focus:shadow-focus-ring focus:bg-surface"
        />
        <kbd className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 rounded-md border border-border bg-surface px-1.5 py-0.5 text-[11px] font-medium text-text-tertiary">
          ⌘K
        </kbd>
      </div>

      <div className="flex shrink-0 items-center gap-5">
        <a href="#" className="flex items-center gap-1.5 text-sm text-text-secondary transition-colors hover:text-text-primary">
          <IconBook />
          Docs
        </a>
        <a href="#" className="flex items-center gap-1.5 text-sm text-text-secondary transition-colors hover:text-text-primary">
          <IconPlug />
          Integrations
        </a>

        <span className="flex items-center gap-1.5 rounded-full bg-success-soft px-2.5 py-1 text-xs font-medium text-success-text">
          <span className="h-1.5 w-1.5 rounded-full bg-success-dot" />
          {backendOnline ? "Backend Online" : "Backend Offline"}
        </span>

        <button
          type="button"
          aria-label="Notifications"
          className="grid h-8 w-8 place-items-center rounded-lg text-text-secondary transition-colors hover:bg-bg-subtle"
        >
          <IconBell />
        </button>

        <button
          type="button"
          aria-label="Account"
          className="grid h-8 w-8 place-items-center rounded-full bg-brand text-xs font-semibold text-white"
        >
          A
        </button>
      </div>
    </header>
  );
}

function IconSearch() {
  return (
    <svg width="15" height="15" viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round">
      <circle cx="6.5" cy="6.5" r="4.5" />
      <path d="M10 10l3.5 3.5" />
    </svg>
  );
}

function IconBook() {
  return (
    <svg width="15" height="15" viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round">
      <path d="M2 3.2A1.2 1.2 0 0 1 3.2 2H7v10.5H3.2A1.2 1.2 0 0 1 2 11.3V3.2Z" />
      <path d="M13 3.2A1.2 1.2 0 0 0 11.8 2H8v10.5h3.8a1.2 1.2 0 0 0 1.2-1.2V3.2Z" />
    </svg>
  );
}

function IconPlug() {
  return (
    <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round">
      <path d="M6 2v3M10 2v3" />
      <path d="M4 5h8v2.5A4 4 0 0 1 8 11.5a4 4 0 0 1-4-4V5Z" />
      <path d="M8 11.5V14" />
    </svg>
  );
}

function IconBell() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round">
      <path d="M8 2.2a3.3 3.3 0 0 0-3.3 3.3v1.9c0 .6-.2 1.2-.6 1.7L3 10.5h10l-1.1-1.4a2.7 2.7 0 0 1-.6-1.7V5.5A3.3 3.3 0 0 0 8 2.2Z" />
      <path d="M6.3 12.8a1.8 1.8 0 0 0 3.4 0" />
    </svg>
  );
}
