import { useEffect, useState } from "react";

/** Senaryo katmanı (README §13.53): bekleyen ya da varsayımsal takaslar ve rol çarpanları. Tarayıcıda saklanır ve açıkken
 *  her API isteğine ``X-FDO-Scenario`` başlığıyla eklenir; sunucu bütün hesapları bu varsayımla yapar. */
export interface WhatIfTrade {
  league: string;
  team_a: string;
  team_b: string;
  give_a: string[];
  give_b: string[];
  drop_a: string[];
  drop_b: string[];
  add_a: string[];
  add_b: string[];
  auto: boolean;
  /** Ekranda gösterilen özet (sunucuya gitmez). */
  label: string;
}

export interface WhatIf {
  enabled: boolean;
  trades: WhatIfTrade[];
  roles: Record<string, { factor: number; name: string }>;
}

const KEY = "tl.whatif";
const EMPTY: WhatIf = { enabled: true, trades: [], roles: {} };

function read(): WhatIf {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) || "null");
    return v && Array.isArray(v.trades) && typeof v.roles === "object" ? { ...EMPTY, ...v } : EMPTY;
  } catch {
    return EMPTY;
  }
}

let state: WhatIf = read();
const listeners = new Set<(w: WhatIf) => void>();

export function whatIf(): WhatIf {
  return state;
}

export function setWhatIf(next: WhatIf) {
  state = next;
  try {
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    /* özel pencere: yalnız bu oturumda */
  }
  listeners.forEach((f) => f(next));
}

export function hasItems(w: WhatIf = state): boolean {
  return w.trades.length > 0 || Object.keys(w.roles).length > 0;
}

export function isActive(w: WhatIf = state): boolean {
  return w.enabled && hasItems(w);
}

/** Sunucuya giden biçim (etiketler ve adlar hariç). */
export function payload(w: WhatIf = state) {
  return {
    trades: w.trades.map(({ label: _label, ...t }) => t),
    roles: Object.fromEntries(Object.entries(w.roles).map(([id, r]) => [id, r.factor])),
  };
}

/** API isteği için başlık (senaryo kapalıysa boş). */
export function scenarioHeader(): Record<string, string> {
  return isActive() ? { "X-FDO-Scenario": JSON.stringify(payload()) } : {};
}

/** Kısa özet: "2 takas, 1 rol çarpanı". */
export function summary(w: WhatIf = state): string {
  const parts = [];
  if (w.trades.length) parts.push(`${w.trades.length} takas`);
  const n = Object.keys(w.roles).length;
  if (n) parts.push(`${n} rol çarpanı`);
  return parts.join(", ");
}

export function useWhatIf(): WhatIf {
  const [w, setW] = useState(state);
  useEffect(() => {
    listeners.add(setW);
    return () => { listeners.delete(setW); };
  }, []);
  return w;
}

export function addTrade(t: WhatIfTrade) {
  setWhatIf({ ...state, enabled: true, trades: [...state.trades, t] });
}
