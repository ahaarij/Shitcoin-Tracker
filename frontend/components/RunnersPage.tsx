"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { RadarSweep } from "./FeedPage";
import { Header } from "./Header";
import { matches, searchQuery, useRadarContext } from "./RadarProvider";
import { RunnerCard } from "./RunnerCard";
import { CHAINS } from "@/lib/chains";
import { formatDuration, formatGain } from "@/lib/format";
import { RUNNER_GAIN_OPTIONS, type RunnerSort } from "@/lib/useSettings";
import type { Runner } from "@/lib/types";

const SORTS: { key: RunnerSort; label: string }[] = [
  { key: "hit", label: "Newest" },
  { key: "peak", label: "Biggest peak" },
  { key: "now", label: "Highest now" },
  { key: "fastest", label: "Fastest" },
];

function peakGain(r: Runner) {
  return r.peak.gainPct ?? r.hit.gainPct;
}

/** "/runners" — tokens that pumped hard within 30 minutes of launch. */
export function RunnersPage() {
  const r = useRadarContext();
  const { settings, update, toggleChain } = r;
  const rules = r.runnerRules;
  const threshold = rules?.minGainPct ?? 200;
  const query = searchQuery(settings);

  // Remember which runners were already there when the page opened, so only new arrivals animate.
  const seenAtMount = useRef<Set<string> | null>(null);
  const [, force] = useState(0);
  useEffect(() => {
    if (seenAtMount.current === null && Object.keys(r.runners).length) {
      seenAtMount.current = new Set(Object.keys(r.runners));
      force((n) => n + 1);
    }
  }, [r.runners]);

  const all = useMemo(() => Object.values(r.runners), [r.runners]);
  const list = useMemo(() => {
    const minGain = Math.max(settings.runnerMinGain, threshold);
    const out = all.filter(
      (x) =>
        matches(x, settings, query) &&
        peakGain(x) >= minGain &&
        (!settings.runnerActiveOnly || (x.now.gainPct ?? -Infinity) >= minGain),
    );
    const by: Record<RunnerSort, (a: Runner, b: Runner) => number> = {
      hit: (a, b) => b.hit.at.localeCompare(a.hit.at),
      peak: (a, b) => peakGain(b) - peakGain(a),
      now: (a, b) => (b.now.gainPct ?? -1e9) - (a.now.gainPct ?? -1e9),
      fastest: (a, b) => a.hit.ageSec - b.hit.ageSec,
    };
    return out.sort(by[settings.runnerSort]);
  }, [all, settings, query, threshold]);

  // Summary numbers for the strip at the top (over everything, not just the filtered view).
  const summary = useMemo(() => {
    if (!all.length) return null;
    const best = all.reduce((a, b) => (peakGain(b) > peakGain(a) ? b : a));
    const fastest = all.reduce((a, b) => (b.hit.ageSec < a.hit.ageSec ? b : a));
    const stillUp = all.filter((x) => (x.now.gainPct ?? -1) >= threshold).length;
    return { best, fastest, stillUp };
  }, [all, threshold]);

  return (
    <>
      <div className="sticky top-0 z-20">
        <Header socket={r.socket} status={r.status} reconnectIn={r.reconnectIn} active="runners" runnerCount={all.length} />

        {/* controls */}
        <div className="border-b border-line bg-bg/85 backdrop-blur-md">
          <div className="mx-auto flex max-w-6xl flex-col gap-2.5 px-4 py-2.5">
            <div className="-mx-4 flex gap-1.5 overflow-x-auto px-4 pb-0.5 [scrollbar-width:none]">
              {CHAINS.map((c) => {
                const on = settings.chains[c.key];
                return (
                  <button
                    key={c.key}
                    type="button"
                    aria-pressed={on}
                    onClick={(e) => toggleChain(c.key, e.shiftKey || e.altKey || e.metaKey)}
                    title={`${on ? "Hide" : "Show"} ${c.label} (shift-click: only ${c.label})`}
                    className="flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 font-mono text-[11px] transition-all"
                    style={{
                      borderColor: on ? `${c.color}66` : "var(--color-line-2)",
                      background: on ? `${c.color}14` : "transparent",
                      color: on ? c.color : "var(--color-faint)",
                    }}
                  >
                    <span className="size-1.5 rounded-full" style={{ background: on ? c.color : "var(--color-faint)" }} />
                    {c.label}
                    <span className="tabular-nums opacity-60">{all.filter((x) => x.chain === c.key).length}</span>
                  </button>
                );
              })}
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <input
                value={settings.search}
                onChange={(e) => update("search", e.target.value)}
                placeholder="Search name, $symbol or address…"
                spellCheck={false}
                aria-label="Search runners"
                className="h-9 min-w-0 flex-1 basis-48 rounded-md border border-line-2 bg-panel px-3 font-mono text-sm text-ink placeholder:text-faint focus:border-signal/60 focus:outline-none"
              />

              <div className="flex h-9 items-center rounded-md border border-line-2 bg-panel p-0.5 font-mono text-xs" role="group" aria-label="Minimum peak gain">
                {RUNNER_GAIN_OPTIONS.filter((g) => g >= threshold).map((g) => (
                  <button
                    key={g}
                    type="button"
                    aria-pressed={settings.runnerMinGain === g}
                    onClick={() => update("runnerMinGain", g)}
                    className={`h-full rounded px-2 transition-colors ${settings.runnerMinGain === g ? "bg-signal/15 text-signal" : "text-dim hover:text-ink"}`}
                  >
                    +{g}%
                  </button>
                ))}
              </div>

              <label className="flex h-9 items-center gap-1.5 rounded-md border border-line-2 bg-panel px-2.5 font-mono text-xs text-dim">
                Sort
                <select
                  value={settings.runnerSort}
                  onChange={(e) => update("runnerSort", e.target.value as RunnerSort)}
                  className="bg-transparent text-ink focus:outline-none"
                >
                  {SORTS.map((s) => (
                    <option key={s.key} value={s.key} className="bg-panel">
                      {s.label}
                    </option>
                  ))}
                </select>
              </label>

              <button
                type="button"
                aria-pressed={settings.runnerActiveOnly}
                onClick={() => update("runnerActiveOnly", !settings.runnerActiveOnly)}
                title="Only runners that are still above the threshold right now"
                className={`flex h-9 items-center rounded-md border px-2.5 font-mono text-xs transition-colors ${
                  settings.runnerActiveOnly ? "border-signal/50 bg-signal/10 text-signal" : "border-line-2 bg-panel text-dim hover:text-ink"
                }`}
              >
                Still up only
              </button>

              <button
                type="button"
                aria-pressed={settings.runnerAlerts}
                onClick={r.toggleRunnerAlerts}
                title="Chime + browser notification when a new runner appears (works on either page)"
                className={`flex h-9 items-center gap-1.5 rounded-md border px-2.5 font-mono text-xs transition-colors ${
                  settings.runnerAlerts ? "border-warn/50 bg-warn/10 text-warn" : "border-line-2 bg-panel text-dim hover:text-ink"
                }`}
              >
                <svg viewBox="0 0 24 24" className="size-3.5" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9M10.3 21a1.94 1.94 0 0 0 3.4 0" />
                </svg>
                {settings.runnerAlerts ? "Alerts on" : "Alert me"}
              </button>
            </div>
          </div>
        </div>
      </div>

      <main className="relative z-10 mx-auto w-full max-w-6xl flex-1 px-4 py-4">
        {/* What counts as a runner */}
        <p className="mb-3 text-sm text-dim">
          Tokens whose market cap rose <span className="font-semibold text-ink">{formatGain(threshold)}</span> or more within{" "}
          <span className="font-semibold text-ink">{rules?.windowMinutes ?? 30} minutes</span> of launch,{" "}
          <span className="font-semibold text-ink">and</span> whose snipers (wallets that bought in the first seconds) hold{" "}
          <span className="font-semibold text-ink">{rules?.maxSniperPct ?? 10}% or less</span> of the supply. Each one keeps
          updating for {rules?.trackHours ?? 6} h after launch; Solana charts move on every trade.{" "}
          <span className="text-faint">
            Solana gains are measured from the real launch market cap; other chains from the first price DexScreener reports.
          </span>
        </p>

        {summary && (
          <div className="mb-4 grid grid-cols-2 gap-1.5 sm:grid-cols-4">
            <SummaryTile label="Runners found" value={String(all.length)} />
            <SummaryTile label="Still above threshold" value={String(summary.stillUp)} />
            <SummaryTile
              label="Biggest peak"
              value={formatGain(peakGain(summary.best))}
              sub={`$${summary.best.symbol}`}
            />
            <SummaryTile
              label="Fastest"
              value={formatDuration(summary.fastest.hit.ageSec)}
              sub={`$${summary.fastest.symbol}`}
            />
          </div>
        )}

        {list.length > 0 ? (
          <ul className="flex flex-col gap-3">
            {list.map((x) => (
              <RunnerCard
                key={x.id}
                r={x}
                thresholdPct={threshold}
                isNew={seenAtMount.current !== null && !seenAtMount.current.has(x.id)}
              />
            ))}
          </ul>
        ) : (
          <div className="flex flex-col items-center justify-center gap-4 py-20 text-center">
            <RadarSweep />
            <div>
              <p className="font-semibold text-ink">{all.length ? "No runners match your filters" : "Watching for runners…"}</p>
              <p className="mt-1 max-w-md text-sm text-dim">
                {all.length
                  ? "Try a lower minimum gain, turn chains back on, or clear the search."
                  : `A token shows up here the moment its market cap is up ${formatGain(threshold)} within ${rules?.windowMinutes ?? 30} minutes of launch. Usually a few per hour; quiet stretches happen. Turn on "Alert me" to get pinged.`}
              </p>
            </div>
          </div>
        )}
      </main>
    </>
  );
}

function SummaryTile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-lg border border-line bg-panel px-3 py-2">
      <div className="text-[10px] uppercase tracking-[0.12em] text-faint">{label}</div>
      <div className="mt-0.5 font-mono text-xl font-semibold tabular-nums text-ink">{value}</div>
      {sub && <div className="truncate font-mono text-[11px] text-dim">{sub}</div>}
    </div>
  );
}
