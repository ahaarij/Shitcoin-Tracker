"use client";

import { createContext, useCallback, useContext, useRef } from "react";
import { blip, fanfare, requestNotifications, showNotification, unlockAudio } from "@/lib/alerts";
import { chainMeta } from "@/lib/chains";
import { formatDuration } from "@/lib/format";
import { useRadar } from "@/lib/useRadar";
import { useSettings, type Settings } from "@/lib/useSettings";
import type { Runner, Token } from "@/lib/types";

/** Does a token pass the live feed's chain filter + search? */
export function matches(t: { chain: Token["chain"]; name: string; symbol: string; address: string }, s: Settings, q: string) {
  if (!s.chains[t.chain]) return false;
  if (!q) return true;
  return t.name.toLowerCase().includes(q) || t.symbol.toLowerCase().includes(q) || t.address.toLowerCase().includes(q);
}

export function searchQuery(s: Settings) {
  return s.search.trim().toLowerCase().replace(/^\$/, "");
}

type Ctx = ReturnType<typeof useRadar> &
  ReturnType<typeof useSettings> & {
    toggleSound: () => void;
    toggleNotify: () => Promise<void>;
    toggleRunnerAlerts: () => Promise<void>;
  };

const RadarContext = createContext<Ctx | null>(null);

export function useRadarContext(): Ctx {
  const ctx = useContext(RadarContext);
  if (!ctx) throw new Error("useRadarContext must be used inside <RadarProvider>");
  return ctx;
}

/**
 * Owns the single live connection to the backend and the user's settings, and shares them
 * with every page. Switching between "Live feed" and "Runners" doesn't reconnect.
 */
export function RadarProvider({ children }: { children: React.ReactNode }) {
  const settingsApi = useSettings();
  const { settings, update } = settingsApi;
  const settingsRef = useRef(settings);
  settingsRef.current = settings;
  const alertState = useRef({ lastSound: 0, lastNotify: 0, queued: [] as Token[] });

  // New-token alerts: only for tokens that pass the current filters, throttled so a
  // burst produces one beep / one notification instead of fifty.
  const onNewTokens = useCallback((batch: Token[]) => {
    const s = settingsRef.current;
    if (!s.sound && !s.notify) return;
    const hits = batch.filter((t) => matches(t, s, searchQuery(s)));
    if (!hits.length) return;
    const st = alertState.current;
    const now = Date.now();
    if (s.sound && now - st.lastSound > 700) {
      st.lastSound = now;
      blip();
    }
    if (s.notify) {
      st.queued.push(...hits);
      if (now - st.lastNotify > 5000) {
        st.lastNotify = now;
        const q = st.queued;
        st.queued = [];
        const first = q[q.length - 1];
        showNotification(
          q.length === 1 ? `New on ${chainMeta(first.chain).label}: $${first.symbol}` : `${q.length} new tokens`,
          q.length === 1 ? first.name : q.slice(-5).map((t) => `$${t.symbol} (${chainMeta(t.chain).short})`).join(", "),
        );
      }
    }
  }, []);

  // Runner alerts: separate switch, never throttled away (runners are rare).
  const onNewRunner = useCallback((r: Runner) => {
    const s = settingsRef.current;
    if (!s.runnerAlerts || !s.chains[r.chain]) return;
    fanfare();
    showNotification(
      `🚀 $${r.symbol} +${Math.round(r.hit.gainPct)}% in ${formatDuration(r.hit.ageSec)}`,
      `${r.name} on ${chainMeta(r.chain).label} · MC $${Math.round(r.hit.mcUsd).toLocaleString()}`,
    );
  }, []);

  const radar = useRadar(onNewTokens, onNewRunner);

  const toggleSound = useCallback(() => {
    if (!settingsRef.current.sound) {
      unlockAudio();
      setTimeout(blip, 50); // audible confirmation
    }
    update("sound", !settingsRef.current.sound);
  }, [update]);

  const toggleNotify = useCallback(async () => {
    if (settingsRef.current.notify) return update("notify", false);
    if (await requestNotifications()) update("notify", true);
  }, [update]);

  const toggleRunnerAlerts = useCallback(async () => {
    if (settingsRef.current.runnerAlerts) return update("runnerAlerts", false);
    unlockAudio();
    setTimeout(fanfare, 50);
    await requestNotifications(); // sound still works if notifications are refused
    update("runnerAlerts", true);
  }, [update]);

  return (
    <RadarContext.Provider value={{ ...radar, ...settingsApi, toggleSound, toggleNotify, toggleRunnerAlerts }}>
      {children}
    </RadarContext.Provider>
  );
}
