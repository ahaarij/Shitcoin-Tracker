"use client";

import { memo, useState } from "react";
import { McChart } from "./McChart";
import { CopyButton, safeUrl, shortAddr } from "./TokenCard";
import { chainMeta, sourceLabel } from "@/lib/chains";
import { compactUsd, formatChange, formatDuration, formatGain, formatMultiple, formatPrice } from "@/lib/format";
import { formatAge, useNow } from "@/lib/useNow";
import type { Runner, Snipers } from "@/lib/types";

const MILESTONES = [100, 200, 300, 500, 1000, 2000]; // % gains -> 2x, 3x, 4x, 6x, 11x, 21x

function gainColor(pct: number | null | undefined) {
  if (pct == null) return "text-dim";
  return pct >= 0 ? "text-signal" : "text-bad";
}

/** One labelled number in the stats grid. */
function Stat({ label, children, sub, hint }: { label: string; children: React.ReactNode; sub?: React.ReactNode; hint?: string }) {
  return (
    <div className="min-w-0 rounded-md bg-bg/60 px-2.5 py-2 shadow-[inset_0_0_0_1px_var(--color-line)]" title={hint}>
      <div className="text-[10px] uppercase tracking-[0.12em] text-faint">{label}</div>
      <div className="mt-0.5 truncate font-mono text-sm font-semibold tabular-nums text-ink">{children}</div>
      {sub && <div className="truncate font-mono text-[11px] tabular-nums text-dim">{sub}</div>}
    </div>
  );
}

/** Buys vs sells as a split bar plus counts. */
function TxnBar({ label, buys, sells }: { label: string; buys: number; sells: number }) {
  const total = buys + sells;
  const pct = total ? (buys / total) * 100 : 50;
  return (
    <div className="flex items-center gap-2 font-mono text-[11px] tabular-nums">
      <span className="w-6 text-faint">{label}</span>
      <span className="w-10 text-right text-signal">{buys}</span>
      <div className="flex h-1.5 flex-1 gap-[2px] overflow-hidden rounded-full" aria-label={`${buys} buys, ${sells} sells`}>
        {total > 0 ? (
          <>
            <span className="rounded-l-full bg-signal/70" style={{ width: `${pct}%` }} />
            <span className="flex-1 rounded-r-full bg-bad/70" />
          </>
        ) : (
          <span className="flex-1 rounded-full bg-line" />
        )}
      </div>
      <span className="w-10 text-bad">{sells}</span>
    </div>
  );
}

function ExtLink({ href, children }: { href: string | null | undefined; children: React.ReactNode }) {
  const safe = safeUrl(href ?? undefined);
  if (!safe) return null;
  return (
    <a
      href={safe}
      target="_blank"
      rel="noopener noreferrer nofollow"
      className="inline-flex h-7 items-center rounded border border-line-2 px-2 font-mono text-[11px] text-dim transition-colors hover:border-faint hover:text-ink"
    >
      {children}
      <svg viewBox="0 0 24 24" className="ml-1 size-3 opacity-60" fill="none" stroke="currentColor" strokeWidth="2"><path d="M7 17 17 7M8 7h9v9" /></svg>
    </a>
  );
}

function Avatar({ r }: { r: Runner }) {
  const [broken, setBroken] = useState(false);
  const img = safeUrl(r.meta?.image ?? undefined);
  const color = chainMeta(r.chain).color;
  if (img && !broken) {
    return (
      // eslint-disable-next-line @next/next/no-img-element -- arbitrary remote hosts; next/image would need allow-listing them
      <img
        src={img}
        alt=""
        loading="lazy"
        referrerPolicy="no-referrer"
        onError={() => setBroken(true)}
        className="size-12 shrink-0 rounded-lg bg-bg object-cover shadow-[inset_0_0_0_1px_var(--color-line-2)]"
      />
    );
  }
  return (
    <div
      className="flex size-12 shrink-0 items-center justify-center rounded-lg font-mono text-lg font-bold"
      style={{ color, background: `${color}14`, boxShadow: `inset 0 0 0 1px ${color}40` }}
    >
      {(r.symbol || "?").slice(0, 2).toUpperCase()}
    </div>
  );
}

/** Who bought in the first seconds, and how much of the supply they still hold. */
function SniperPanel({ s, chain }: { s: Snipers | null; chain: Runner["chain"] }) {
  const explorer = chainMeta(chain).explorer;
  if (!s) {
    return <div className="rounded-md bg-bg/60 px-2.5 py-2 font-mono text-[11px] text-faint shadow-[inset_0_0_0_1px_var(--color-line)]">sniper check pending…</div>;
  }
  const limit = s.maxAllowedPct;
  const pctOfLimit = Math.min(100, (s.holdingPct / Math.max(limit, 0.01)) * 100);
  return (
    <div className="flex flex-col gap-2 rounded-md bg-bg/60 px-2.5 py-2 shadow-[inset_0_0_0_1px_var(--color-line)]">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <span className="text-[10px] uppercase tracking-[0.12em] text-faint" title={`Wallets (other than the creator) that bought in the ${s.window} after launch`}>
          Snipers · {s.window}
        </span>
        <span className={`font-mono text-[11px] ${s.passes ? "text-signal" : "text-bad"}`}>
          {s.passes ? "✓" : "✕"} limit {limit}%
        </span>
      </div>

      {/* holdings vs the limit */}
      <div className="flex items-center gap-2">
        <span className={`font-mono text-lg font-semibold tabular-nums ${s.passes ? "text-ink" : "text-bad"}`}>{s.holdingPct.toFixed(1)}%</span>
        <div className="flex-1">
          <div className="h-1.5 overflow-hidden rounded-full bg-line" role="meter" aria-valuemin={0} aria-valuemax={limit} aria-valuenow={s.holdingPct} aria-label="Sniper holdings vs limit">
            <div className={`h-full rounded-full ${s.passes ? "bg-signal/70" : "bg-bad/80"}`} style={{ width: `${pctOfLimit}%` }} />
          </div>
          <div className="mt-0.5 font-mono text-[10px] text-faint">held now by snipers, of the {limit}% limit</div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 font-mono text-[11px] tabular-nums text-dim sm:grid-cols-4">
        <span title="Sniper wallets found">wallets <span className="text-ink">{s.count}</span></span>
        <span title="Sniper wallets that still hold some">still in <span className="text-ink">{s.stillHolding}</span></span>
        <span title="% of supply the snipers bought at launch">bought <span className="text-ink">{s.boughtPct.toFixed(1)}%</span></span>
        <span title="% of supply the snipers have sold since">sold <span className="text-ink">{Math.max(0, s.boughtPct - s.holdingPct).toFixed(1)}%</span></span>
        <span title="% of supply the creator bought at launch">dev bought <span className="text-ink">{s.devBoughtPct.toFixed(1)}%</span></span>
        <span title="% of supply the creator holds now">
          dev holds <span className={s.devHoldingPct > 10 ? "text-bad" : "text-ink"}>{s.devHoldingPct.toFixed(1)}%</span>
        </span>
      </div>

      {s.wallets.length > 0 && (
        <details className="group">
          <summary className="cursor-pointer list-none font-mono text-[11px] text-dim hover:text-ink">
            <span className="inline-block transition-transform group-open:rotate-90">▸</span> sniper wallets ({s.wallets.length}
            {s.count > s.wallets.length ? ` of ${s.count}` : ""})
          </summary>
          <table className="mt-1 w-full font-mono text-[11px] tabular-nums">
            <thead>
              <tr className="text-left text-[10px] uppercase tracking-wider text-faint">
                <th className="font-normal">wallet</th>
                <th className="text-right font-normal">bought</th>
                <th className="text-right font-normal">holds now</th>
              </tr>
            </thead>
            <tbody>
              {s.wallets.map((w) => (
                <tr key={w.address} className="text-dim">
                  <td className="py-px">
                    <span className="inline-flex items-center">
                      <a
                        href={chain === "solana" ? `https://solscan.io/account/${encodeURIComponent(w.address)}` : explorer(w.address).replace("/token/", "/address/")}
                        target="_blank"
                        rel="noopener noreferrer nofollow"
                        className="hover:text-ink"
                      >
                        {shortAddr(w.address)}
                      </a>
                      <CopyButton text={w.address} />
                    </span>
                  </td>
                  <td className="text-right">{w.boughtPct.toFixed(2)}%</td>
                  <td className={`text-right ${w.holdingPct > 0 ? "text-ink" : "text-faint"}`}>{w.holdingPct > 0 ? `${w.holdingPct.toFixed(2)}%` : "sold"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
    </div>
  );
}

/** Plain-language warning signs computed from the numbers. */
function riskFlags(r: Runner): { label: string; level: "warn" | "info" }[] {
  const flags: { label: string; level: "warn" | "info" }[] = [];
  const liq = r.market?.liquidityUsd;
  const onCurve = r.chain === "solana" && (r.pair?.dex ?? r.market?.dex) === "pumpfun";
  if (r.now.fromPeakPct != null && r.now.fromPeakPct <= -40) flags.push({ label: `Down ${Math.abs(Math.round(r.now.fromPeakPct))}% from peak`, level: "warn" });
  const m5 = r.pair?.txns.m5;
  if (m5 && m5.sells > m5.buys && m5.sells >= 5) flags.push({ label: "More sells than buys (5m)", level: "warn" });
  if (liq != null && liq < 5000) flags.push({ label: `Thin liquidity (${compactUsd(liq)})`, level: "warn" });
  if (r.now.gainPct != null && r.now.gainPct < 0) flags.push({ label: "Now below launch value", level: "warn" });
  if (r.snipers && !r.snipers.passes) flags.push({ label: `Snipers now hold ${r.snipers.holdingPct.toFixed(1)}% (over ${r.snipers.maxAllowedPct}%)`, level: "warn" });
  if (r.snipers && r.snipers.devHoldingPct > 10) flags.push({ label: `Dev holds ${r.snipers.devHoldingPct.toFixed(1)}%`, level: "warn" });
  if (!r.meta?.twitter && !r.meta?.telegram && !r.meta?.website) flags.push({ label: "No socials found", level: "info" });
  if (onCurve) flags.push({ label: "Still on Pump.fun bonding curve", level: "info" });
  else if (r.chain === "solana" && r.pair?.dex) flags.push({ label: `Graduated to ${r.pair.dex}`, level: "info" });
  if (r.baseline.kind === "first-seen") flags.push({ label: "Gain measured from first DexScreener price", level: "info" });
  if (!r.tracking) flags.push({ label: "No longer updating", level: "info" });
  return flags;
}

export const RunnerCard = memo(function RunnerCard({ r, thresholdPct, isNew }: { r: Runner; thresholdPct: number; isNew?: boolean }) {
  const now = useNow();
  const chain = chainMeta(r.chain);
  const m = r.market;
  const p = r.pair;
  const flags = riskFlags(r);
  const nativeSym = r.chain === "solana" ? "SOL" : (p?.quoteSymbol ?? "");
  const launchedLocal = new Date(r.detectedAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  return (
    <li className={`relative overflow-hidden rounded-xl border border-line bg-panel ${isNew ? "animate-slide-in" : ""}`}>
      <span className="absolute inset-y-0 left-0 w-[3px]" style={{ background: chain.color }} />

      {/* ---------- title row ---------- */}
      <div className="flex flex-wrap items-start gap-3 border-b border-line px-4 py-3 pl-5">
        <Avatar r={r} />
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 flex-wrap items-baseline gap-x-2">
            <h3 className="truncate text-base font-semibold text-ink" title={r.name}>{r.name}</h3>
            <span className="font-mono text-sm text-signal/90">${r.symbol}</span>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-1.5 font-mono text-[11px] text-dim">
            <span
              className="rounded px-1.5 py-px text-[10px] font-bold tracking-wider"
              style={{ color: chain.color, background: `${chain.color}1a`, boxShadow: `inset 0 0 0 1px ${chain.color}40` }}
            >
              {chain.short}
            </span>
            <span className="rounded bg-line px-1.5 py-px text-[10px] uppercase tracking-wide">{sourceLabel(r.source)}</span>
            {p?.dex && <span className="rounded bg-line px-1.5 py-px text-[10px] uppercase tracking-wide">{p.dex}</span>}
            <span className="flex items-center">
              <span title={r.address}>{shortAddr(r.address)}</span>
              <CopyButton text={r.address} />
            </span>
            <span className="text-faint" suppressHydrationWarning>
              launched {launchedLocal} · {formatAge(r.detectedAt, now)}
            </span>
          </div>
        </div>

        {/* headline: peak gain */}
        <div className="ml-auto text-right">
          <div className="font-mono text-2xl font-bold leading-none tabular-nums text-signal sm:text-3xl">{formatGain(r.peak.gainPct ?? r.hit.gainPct)}</div>
          <div className="mt-1 font-mono text-[11px] text-dim">
            peak · {formatMultiple(r.peak.gainPct ?? r.hit.gainPct)} launch
          </div>
          <div className="mt-0.5 font-mono text-[11px] text-warn">
            hit {formatGain(r.hit.gainPct)} in {formatDuration(r.hit.ageSec)}
          </div>
        </div>
      </div>

      {r.meta?.description && (
        <p className="line-clamp-2 border-b border-line px-5 py-2 text-xs text-dim" title={r.meta.description}>
          {r.meta.description}
        </p>
      )}

      {/* ---------- body: stats + chart ---------- */}
      <div className="grid gap-4 px-4 py-3 pl-5 lg:grid-cols-[1.35fr_1fr]">
        <div className="flex flex-col gap-2">
          <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-4">
            <Stat
              label="Launch MC"
              sub={r.baseline.kind === "launch" ? "at launch" : "first seen"}
              hint="Starting market cap the gain is measured from"
            >
              {compactUsd(r.baseline.mcUsd)}
            </Stat>
            <Stat label="When it hit" sub={<span className="text-warn">{formatGain(r.hit.gainPct)} · {formatDuration(r.hit.ageSec)}</span>}>
              {compactUsd(r.hit.mcUsd)}
            </Stat>
            <Stat
              label="Peak MC"
              sub={<span>{formatGain(r.peak.gainPct)}{r.peak.ageSec != null ? ` · ${formatDuration(r.peak.ageSec)}` : ""}</span>}
            >
              {compactUsd(r.peak.mcUsd)}
            </Stat>
            <Stat
              label="MC now"
              sub={
                <span>
                  <span className={gainColor(r.now.gainPct)}>{formatGain(r.now.gainPct)}</span>
                  {r.now.fromPeakPct != null && r.now.fromPeakPct < 0 && <span className="text-bad"> · {Math.round(r.now.fromPeakPct)}% pk</span>}
                </span>
              }
            >
              {compactUsd(r.now.mcUsd)}
            </Stat>

            <Stat label="Price" sub={p?.priceNative != null && nativeSym ? `${formatPrice(p.priceNative).replace("$", "")} ${nativeSym}` : undefined}>
              {formatPrice(m?.priceUsd)}
            </Stat>
            <Stat label="Liquidity" sub={p?.fdvUsd != null ? `FDV ${compactUsd(p.fdvUsd)}` : undefined} hint="Money in the trading pool. Pump.fun bonding-curve tokens report none.">
              {m?.liquidityUsd != null ? compactUsd(m.liquidityUsd) : r.chain === "solana" ? "curve" : "—"}
            </Stat>
            <Stat label="Volume 5m / 1h" sub={p?.volume.h24 != null ? `24h ${compactUsd(p.volume.h24)}` : undefined}>
              {compactUsd(p?.volume.m5)} / {compactUsd(p?.volume.h1)}
            </Stat>
            <Stat
              label="Price chg 5m / 1h"
              sub={p?.priceChange.h6 != null ? `6h ${formatChange(p.priceChange.h6)}` : undefined}
            >
              <span className={gainColor(p?.priceChange.m5)}>{formatChange(p?.priceChange.m5) ?? "—"}</span>
              <span className="text-faint"> / </span>
              <span className={gainColor(p?.priceChange.h1)}>{formatChange(p?.priceChange.h1) ?? "—"}</span>
            </Stat>
          </div>

          {/* buys vs sells */}
          {p && (
            <div className="flex flex-col gap-1 rounded-md bg-bg/60 px-2.5 py-2 shadow-[inset_0_0_0_1px_var(--color-line)]">
              <div className="flex justify-between text-[10px] uppercase tracking-[0.12em] text-faint">
                <span>Buys</span>
                <span>Transactions</span>
                <span>Sells</span>
              </div>
              <TxnBar label="5m" buys={p.txns.m5.buys} sells={p.txns.m5.sells} />
              <TxnBar label="1h" buys={p.txns.h1.buys} sells={p.txns.h1.sells} />
              <TxnBar label="24h" buys={p.txns.h24.buys} sells={p.txns.h24.sells} />
            </div>
          )}

          <SniperPanel s={r.snipers} chain={r.chain} />

          {/* creator / pair */}
          <div className="flex flex-wrap gap-x-4 gap-y-1 font-mono text-[11px] text-dim">
            {typeof r.extra?.devBuySol === "number" && (
              <span>
                dev buy <span className="text-warn">{r.extra.devBuySol.toFixed(r.extra.devBuySol < 0.01 ? 4 : 2)} SOL</span>
              </span>
            )}
            {r.extra?.creator && (
              <span className="flex items-center">
                creator&nbsp;
                <a className="hover:text-ink" href={chain.explorer(r.extra.creator).replace("/token/", "/account/")} target="_blank" rel="noopener noreferrer nofollow">
                  {shortAddr(r.extra.creator)}
                </a>
                <CopyButton text={r.extra.creator} />
              </span>
            )}
            {p?.address && (
              <span className="flex items-center">
                pair&nbsp;<span title={p.address}>{shortAddr(p.address)}</span>
                <CopyButton text={p.address} />
                {p.quoteSymbol && <span className="text-faint">&nbsp;vs {p.quoteSymbol}</span>}
              </span>
            )}
          </div>
        </div>

        <div className="flex flex-col gap-2">
          <div className="flex items-baseline justify-between">
            <span className="flex items-center gap-2 text-[10px] uppercase tracking-[0.12em] text-faint">
              Market cap since launch
              {r.live && now - Date.parse(r.updatedAt) < 20_000 ? (
                <span className="flex items-center gap-1 rounded bg-signal/10 px-1 py-px text-signal" title="Updating on every trade">
                  <span className="size-1.5 animate-pulse-dot rounded-full bg-signal" />
                  live
                </span>
              ) : r.tracking ? (
                <span className="rounded bg-line px-1 py-px" title="Refreshed every ~10 seconds">~10s</span>
              ) : null}
            </span>
            <span className="font-mono text-[10px] text-faint">dashed: launch · +{thresholdPct}%</span>
          </div>
          <McChart history={r.history} baseline={r.baseline.mcUsd} thresholdPct={thresholdPct} hitAgeSec={r.hit.ageSec} />

          {/* milestones */}
          <div className="flex flex-wrap gap-1">
            {MILESTONES.map((g) => {
              const at = r.milestones[String(g)];
              return (
                <span
                  key={g}
                  className={`rounded px-1.5 py-0.5 font-mono text-[10px] tabular-nums ${
                    at != null ? "bg-signal/10 text-signal shadow-[inset_0_0_0_1px_rgb(57_255_159/0.3)]" : "bg-line/60 text-faint"
                  }`}
                  title={at != null ? `Reached ${formatMultiple(g)} (+${g}%) ${formatDuration(at)} after launch` : `Not reached ${formatMultiple(g)} yet`}
                >
                  {formatMultiple(g)} {at != null ? formatDuration(at) : "—"}
                </span>
              );
            })}
          </div>
        </div>
      </div>

      {/* ---------- flags + links ---------- */}
      <div className="flex flex-col gap-2 border-t border-line px-4 py-2.5 pl-5 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap gap-1">
          {flags.map((f) => (
            <span
              key={f.label}
              className={`flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] ${
                f.level === "warn" ? "bg-bad/10 text-bad" : "bg-line/70 text-dim"
              }`}
            >
              {f.level === "warn" ? "⚠" : "ⓘ"} {f.label}
            </span>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <ExtLink href={r.dexscreenerUrl}>DexScreener</ExtLink>
          {r.extra?.pumpUrl && <ExtLink href={r.extra.pumpUrl}>Pump.fun</ExtLink>}
          <ExtLink href={chain.explorer(r.address)}>Explorer</ExtLink>
          <ExtLink href={r.meta?.website}>Website</ExtLink>
          <ExtLink href={r.meta?.twitter}>X</ExtLink>
          <ExtLink href={r.meta?.telegram}>Telegram</ExtLink>
        </div>
      </div>
      <div className="px-5 pb-2 font-mono text-[10px] text-faint" suppressHydrationWarning>
        {r.tracking
          ? `updated ${formatAge(r.updatedAt, now)} · ${r.live ? "live on every trade" : "refreshes every ~10s"} · snipers re-checked every minute`
          : "no longer updating (tracking window ended or server restarted)"}
      </div>
    </li>
  );
});
