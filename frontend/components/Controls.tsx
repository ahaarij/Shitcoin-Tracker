"use client";

import { CHAINS } from "@/lib/chains";
import { MAX_LEN_OPTIONS, type Settings } from "@/lib/useSettings";
import type { ChainKey, Status } from "@/lib/types";

function IconButton({
  active,
  onClick,
  title,
  children,
}: {
  active?: boolean;
  onClick: () => void;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-label={title}
      aria-pressed={active}
      className={`flex h-9 items-center gap-1.5 rounded-md border px-2.5 font-mono text-xs transition-colors ${
        active
          ? "border-signal/50 bg-signal/10 text-signal"
          : "border-line-2 bg-panel text-dim hover:border-faint hover:text-ink"
      }`}
    >
      {children}
    </button>
  );
}

export function Controls({
  settings,
  update,
  toggleChain,
  status,
  paused,
  setPaused,
  onToggleSound,
  onToggleNotify,
}: {
  settings: Settings;
  update: <K extends keyof Settings>(key: K, value: Settings[K]) => void;
  toggleChain: (c: ChainKey, solo?: boolean) => void;
  status: Status | null;
  paused: boolean;
  setPaused: (p: boolean) => void;
  onToggleSound: () => void;
  onToggleNotify: () => void;
}) {
  const tpm = new Map(status?.chains.map((c) => [c.chain, c.tokensPerMinute]));

  return (
    <div className="border-b border-line bg-bg/85 backdrop-blur-md">
      <div className="mx-auto flex max-w-6xl flex-col gap-2.5 px-4 py-2.5">
        {/* Chain filter chips — scrolls horizontally on phones */}
        <div className="-mx-4 flex gap-1.5 overflow-x-auto px-4 pb-0.5 [scrollbar-width:none]">
          {CHAINS.map((c) => {
            const on = settings.chains[c.key];
            return (
              <button
                key={c.key}
                type="button"
                aria-pressed={on}
                title={`${on ? "Hide" : "Show"} ${c.label} (shift-click to show only ${c.label})`}
                onClick={(e) => toggleChain(c.key, e.shiftKey || e.altKey || e.metaKey)}
                className="flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 font-mono text-[11px] transition-all"
                style={{
                  borderColor: on ? `${c.color}66` : "var(--color-line-2)",
                  background: on ? `${c.color}14` : "transparent",
                  color: on ? c.color : "var(--color-faint)",
                }}
              >
                <span
                  className="size-1.5 rounded-full"
                  style={{ background: on ? c.color : "var(--color-faint)" }}
                />
                {c.label}
                <span className="tabular-nums opacity-60">{tpm.get(c.key) ?? 0}/m</span>
              </button>
            );
          })}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <label className="relative min-w-0 flex-1 basis-56">
            <span className="sr-only">Search</span>
            <svg
              className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-faint"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <circle cx="11" cy="11" r="7" />
              <path d="m20 20-3.5-3.5" />
            </svg>
            <input
              value={settings.search}
              onChange={(e) => update("search", e.target.value)}
              placeholder="Search name, $symbol or address…"
              spellCheck={false}
              className="h-9 w-full rounded-md border border-line-2 bg-panel pl-8 pr-8 font-mono text-sm text-ink placeholder:text-faint focus:border-signal/60 focus:outline-none"
            />
            {settings.search && (
              <button
                type="button"
                onClick={() => update("search", "")}
                className="absolute right-2 top-1/2 -translate-y-1/2 px-1 text-faint hover:text-ink"
                aria-label="Clear search"
              >
                ×
              </button>
            )}
          </label>

          <IconButton active={paused} onClick={() => setPaused(!paused)} title={paused ? "Resume feed" : "Pause feed"}>
            {paused ? (
              <svg viewBox="0 0 24 24" className="size-3.5" fill="currentColor"><path d="M7 5v14l12-7z" /></svg>
            ) : (
              <svg viewBox="0 0 24 24" className="size-3.5" fill="currentColor"><path d="M6 5h4v14H6zM14 5h4v14h-4z" /></svg>
            )}
            {paused ? "Resume" : "Pause"}
          </IconButton>

          <IconButton active={settings.sound} onClick={onToggleSound} title="Sound on new tokens">
            <svg viewBox="0 0 24 24" className="size-3.5" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M11 5 6 9H3v6h3l5 4z" fill="currentColor" stroke="none" />
              {settings.sound ? <path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13" /> : <path d="m16 9 5 6m0-6-5 6" />}
            </svg>
            <span className="hidden sm:inline">Sound</span>
          </IconButton>

          <IconButton active={settings.notify} onClick={onToggleNotify} title="Browser notifications">
            <svg viewBox="0 0 24 24" className="size-3.5" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9M10.3 21a1.94 1.94 0 0 0 3.4 0" />
            </svg>
            <span className="hidden sm:inline">Notify</span>
          </IconButton>

          <label className="flex h-9 items-center gap-1.5 rounded-md border border-line-2 bg-panel px-2.5 font-mono text-xs text-dim">
            <span className="hidden sm:inline">Show</span>
            <select
              value={settings.maxLen}
              onChange={(e) => update("maxLen", Number(e.target.value))}
              className="bg-transparent text-ink focus:outline-none"
              aria-label="Maximum feed length"
            >
              {MAX_LEN_OPTIONS.map((n) => (
                <option key={n} value={n} className="bg-panel">
                  {n}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>
    </div>
  );
}
