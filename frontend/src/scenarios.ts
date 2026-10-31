import { useCallback, useState } from "react";
import type { StrategyChoice } from "./components/StrategyPicker";

export interface NamedId {
  id: string;
  name: string;
}

/** Kaydedilmiş takas senaryosu (tarayıcıda saklanır; JSON olarak dışa/içe aktarılabilir). */
export interface Scenario {
  id: string;
  created: string;
  league: string;
  team: string;
  teamName: string;
  opp: string;
  oppName: string;
  giveA: NamedId[];
  giveB: NamedId[];
  dropA: NamedId[];
  dropB: NamedId[];
  addA: NamedId[];
  addB: NamedId[];
  auto: boolean;
  stratA: StrategyChoice;
  stratB: StrategyChoice;
  stratALabel: string;
  stratBLabel: string;
  metrics: {
    a: { ecw_delta: number; win_delta: number; strategy_delta: number };
    b: { ecw_delta: number; win_delta: number; strategy_delta: number };
    fairness: number;
    perceived: number | null;
    mutual: boolean;
  };
  season?: { me_playoff: number; me_champion: number; opp_playoff: number; opp_champion: number };
}

const KEY = "tl.scenarios";

function read(): Scenario[] {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) || "[]");
    return Array.isArray(v) ? v : [];
  } catch {
    return [];
  }
}

function write(list: Scenario[]) {
  try {
    localStorage.setItem(KEY, JSON.stringify(list));
  } catch {
    /* özel pencere vb.: yalnızca oturumda kalır */
  }
}

export function useScenarios() {
  const [list, setList] = useState<Scenario[]>(read);
  const commit = useCallback((next: Scenario[]) => {
    setList(next);
    write(next);
  }, []);
  return {
    list,
    add: (s: Scenario) => commit([s, ...list.filter((x) => x.id !== s.id)]),
    update: (id: string, patch: Partial<Scenario>) => commit(list.map((x) => (x.id === id ? { ...x, ...patch } : x))),
    remove: (id: string) => commit(list.filter((x) => x.id !== id)),
    replaceAll: (items: Scenario[]) => commit(items),
  };
}

export function downloadJson(name: string, data: unknown) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}
