import type { Meta, Roster, SeasonOut, Source, TradeIn, TradeOut, Player } from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* gövde JSON değil */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

const q = (injuries: boolean) => `injuries=${injuries ? "true" : "false"}`;

export const api = {
  meta: (injuries: boolean) => request<Meta>(`/api/meta?${q(injuries)}`),
  roster: (league: string, team: string, source: Source, injuries: boolean) =>
    request<Roster>(`/api/leagues/${league}/roster/${team}?source=${source}&${q(injuries)}`),
  freeAgents: (league: string, source: Source, injuries: boolean) =>
    request<{ source: Source; players: Player[] }>(
      `/api/leagues/${league}/free-agents?source=${source}&${q(injuries)}`,
    ),
  analyze: (league: string, body: TradeIn) =>
    request<TradeOut>(`/api/leagues/${league}/trade/analyze`, { method: "POST", body: JSON.stringify(body) }),
  season: (league: string, body: TradeIn & { n_sims?: number; strength_sd?: number }) =>
    request<SeasonOut>(`/api/leagues/${league}/trade/season`, { method: "POST", body: JSON.stringify(body) }),
};
