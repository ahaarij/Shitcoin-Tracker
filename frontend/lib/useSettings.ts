"use client";

import { useCallback, useEffect, useState } from "react";
import { CHAINS } from "./chains";
import type { ChainKey } from "./types";

export interface Settings {
  chains: Record<ChainKey, boolean>;
  search: string;
  sound: boolean;
  notify: boolean;
  maxLen: number;
  // Runners page
  runnerAlerts: boolean;
  runnerMinGain: number;
  runnerSort: RunnerSort;
  runnerActiveOnly: boolean;
}

export type RunnerSort = "hit" | "peak" | "now" | "fastest";
export const RUNNER_GAIN_OPTIONS = [200, 300, 500, 1000];

export const MAX_LEN_OPTIONS = [50, 100, 250, 500, 1000];

const KEY = "ntr:settings:v1";

const DEFAULTS: Settings = {
  chains: Object.fromEntries(CHAINS.map((c) => [c.key, true])) as Record<ChainKey, boolean>,
  search: "",
  sound: false,
  notify: false,
  maxLen: 250,
  runnerAlerts: false,
  runnerMinGain: 200,
  runnerSort: "hit",
  runnerActiveOnly: false,
};

function load(): Settings {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return DEFAULTS;
    const saved = JSON.parse(raw) as Partial<Settings>;
    return {
      ...DEFAULTS,
      ...saved,
      chains: { ...DEFAULTS.chains, ...(saved.chains ?? {}) },
      runnerMinGain: RUNNER_GAIN_OPTIONS.includes(saved.runnerMinGain as number) ? (saved.runnerMinGain as number) : DEFAULTS.runnerMinGain,
      runnerSort: (["hit", "peak", "now", "fastest"] as const).includes(saved.runnerSort as RunnerSort) ? (saved.runnerSort as RunnerSort) : DEFAULTS.runnerSort,
      maxLen: MAX_LEN_OPTIONS.includes(saved.maxLen as number) ? (saved.maxLen as number) : DEFAULTS.maxLen,
    };
  } catch {
    return DEFAULTS; // private mode / blocked storage: just use defaults
  }
}

/** Settings persisted in localStorage. Defaults on first render (SSR-safe), then hydrated. */
export function useSettings() {
  const [settings, setSettings] = useState<Settings>(DEFAULTS);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    setSettings(load());
    setLoaded(true);
  }, []);

  useEffect(() => {
    if (!loaded) return;
    try {
      localStorage.setItem(KEY, JSON.stringify(settings));
    } catch {
      /* ignore */
    }
  }, [settings, loaded]);

  const update = useCallback(<K extends keyof Settings>(key: K, value: Settings[K]) => {
    setSettings((s) => ({ ...s, [key]: value }));
  }, []);

  const toggleChain = useCallback((chain: ChainKey, solo = false) => {
    setSettings((s) => {
      if (solo) {
        // Shift/alt-click: show only this chain (or everything again if it was already solo).
        const isSolo = Object.entries(s.chains).every(([k, v]) => v === (k === chain));
        const next = Object.fromEntries(CHAINS.map((c) => [c.key, isSolo ? true : c.key === chain]));
        return { ...s, chains: next as Settings["chains"] };
      }
      return { ...s, chains: { ...s.chains, [chain]: !s.chains[chain] } };
    });
  }, []);

  return { settings, update, toggleChain };
}
