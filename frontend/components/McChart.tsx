"use client";

import { useId, useMemo, useRef, useState } from "react";
import { compactUsd, formatDuration, formatGain } from "@/lib/format";

/**
 * Market cap since launch, for one runner. Single series, so no legend: the card title names it.
 * Two faint reference lines (launch value and the runner threshold), a dot where it qualified,
 * and a crosshair + tooltip on hover/touch.
 */
export function McChart({
  history,
  baseline,
  thresholdPct,
  hitAgeSec,
  height = 120,
}: {
  history: [number, number][];
  baseline: number | null;
  thresholdPct: number;
  hitAgeSec: number | null;
  height?: number;
}) {
  const W = 600; // viewBox width; the SVG scales to its container
  const H = height;
  const pad = { l: 4, r: 4, t: 10, b: 16 };
  const gradId = useId();
  const svgRef = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<number | null>(null);

  const geo = useMemo(() => {
    if (history.length < 1) return null;
    // Start the line at launch (t=0) from the baseline, so the whole climb is visible.
    const pts: [number, number][] = baseline && history[0][0] > 0 ? [[0, baseline], ...history] : history;
    const maxT = Math.max(pts[pts.length - 1][0], 60);
    const threshold = baseline ? baseline * (1 + thresholdPct / 100) : null;
    const values = pts.map((p) => p[1]).concat(threshold ? [threshold] : []);
    const maxV = Math.max(...values) * 1.08;
    const minV = 0;
    const x = (t: number) => pad.l + (t / maxT) * (W - pad.l - pad.r);
    const y = (v: number) => pad.t + (1 - (v - minV) / (maxV - minV)) * (H - pad.t - pad.b);
    const line = pts.map((p, i) => `${i ? "L" : "M"}${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join("");
    const area = `${line}L${x(pts[pts.length - 1][0]).toFixed(1)},${y(0)}L${x(pts[0][0]).toFixed(1)},${y(0)}Z`;
    return { pts, maxT, x, y, line, area, threshold };
  }, [history, baseline, thresholdPct, H]);

  if (!geo) {
    return <div className="flex h-[120px] items-center justify-center font-mono text-xs text-faint">no price history yet</div>;
  }

  const { pts, maxT, x, y, line, area, threshold } = geo;
  const hit = hitAgeSec != null ? pts.reduce((best, p) => (Math.abs(p[0] - hitAgeSec) < Math.abs(best[0] - hitAgeSec) ? p : best), pts[0]) : null;
  const h = hover != null ? pts[hover] : null;

  const onMove = (clientX: number) => {
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const t = ((clientX - rect.left) / rect.width) * W;
    let best = 0;
    for (let i = 1; i < pts.length; i++) if (Math.abs(x(pts[i][0]) - t) < Math.abs(x(pts[best][0]) - t)) best = i;
    setHover(best);
  };

  return (
    <div className="relative select-none">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        className="block h-[120px] w-full touch-none"
        role="img"
        aria-label={`Market cap since launch, from ${compactUsd(pts[0][1])} to ${compactUsd(pts[pts.length - 1][1])}`}
        onPointerMove={(e) => onMove(e.clientX)}
        onPointerDown={(e) => onMove(e.clientX)}
        onPointerLeave={() => setHover(null)}
      >
        <defs>
          <linearGradient id={gradId} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="var(--color-signal)" stopOpacity="0.18" />
            <stop offset="100%" stopColor="var(--color-signal)" stopOpacity="0" />
          </linearGradient>
        </defs>

        {/* reference lines: launch value + runner threshold (recessive) */}
        {baseline != null && (
          <line x1={pad.l} x2={W - pad.r} y1={y(baseline)} y2={y(baseline)} stroke="var(--color-faint)" strokeWidth="1" strokeDasharray="3 4" vectorEffect="non-scaling-stroke" />
        )}
        {threshold != null && (
          <line x1={pad.l} x2={W - pad.r} y1={y(threshold)} y2={y(threshold)} stroke="var(--color-warn)" strokeOpacity="0.45" strokeWidth="1" strokeDasharray="3 4" vectorEffect="non-scaling-stroke" />
        )}

        <path d={area} fill={`url(#${gradId})`} />
        <path d={line} fill="none" stroke="var(--color-signal)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />

        {h && (
          <line x1={x(h[0])} x2={x(h[0])} y1={pad.t} y2={H - pad.b} stroke="var(--color-dim)" strokeWidth="1" vectorEffect="non-scaling-stroke" />
        )}
      </svg>

      {/* Dots and labels as HTML so they stay round/crisp while the SVG stretches */}
      {hit && (
        <span
          className="pointer-events-none absolute size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-panel bg-warn"
          style={{ left: `${(x(hit[0]) / W) * 100}%`, top: y(hit[1]) }}
          title="Qualified as a runner here"
        />
      )}
      {h && (
        <span
          className="pointer-events-none absolute size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-panel bg-signal"
          style={{ left: `${(x(h[0]) / W) * 100}%`, top: y(h[1]) }}
        />
      )}
      <div className="pointer-events-none absolute inset-x-0 bottom-0 flex justify-between font-mono text-[10px] text-faint">
        <span>launch</span>
        <span>+{formatDuration(maxT)}</span>
      </div>
      {threshold != null && (
        <span
          className="pointer-events-none absolute right-1 -translate-y-full font-mono text-[10px] text-warn/70"
          style={{ top: y(threshold) - 1 }}
        >
          +{thresholdPct}%
        </span>
      )}

      {h && (
        <div
          className="pointer-events-none absolute top-0 z-10 rounded-md border border-line-2 bg-bg/95 px-2 py-1 font-mono text-[11px] shadow-lg"
          style={{ left: `${Math.min(Math.max((x(h[0]) / W) * 100, 12), 80)}%`, transform: "translateX(-50%)" }}
        >
          <div className="text-dim">{formatDuration(h[0])} after launch</div>
          <div className="text-ink">
            MC {compactUsd(h[1])}
            {baseline ? <span className={h[1] >= baseline ? " text-signal" : " text-bad"}> {formatGain((h[1] / baseline - 1) * 100)}</span> : null}
          </div>
        </div>
      )}
    </div>
  );
}
