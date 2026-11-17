import { useEffect, useState } from "react";

/** Korunan oyuncular (README §13.54): menajerin "satılık değil" dediği ya da senin vermek istemediğin oyuncular. Lig
 *  başına tarayıcıda saklanır; öneri, tamamlama ve çok takımlı aramada bu oyuncular takasa konmaz. */
type Store = Record<string, Record<string, string>>;      // lig → oyuncu → ad
const KEY = "tl.protected";
let state: Store = (() => {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) || "{}");
    return v && typeof v === "object" ? v : {};
  } catch {
    return {};
  }
})();
const listeners = new Set<(s: Store) => void>();

function commit(next: Store) {
  state = next;
  try {
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    /* özel pencere */
  }
  listeners.forEach((f) => f(next));
}

export function protectedIds(league: string): string[] {
  return Object.keys(state[league] ?? {});
}

export function setProtected(league: string, id: string, name: string | null) {
  const cur = { ...(state[league] ?? {}) };
  if (name === null) delete cur[id];
  else cur[id] = name;
  commit({ ...state, [league]: cur });
}

export function useProtected(league: string): Record<string, string> {
  const [s, setS] = useState(state);
  useEffect(() => {
    listeners.add(setS);
    return () => { listeners.delete(setS); };
  }, []);
  return s[league] ?? {};
}
