import type {
  AddDropWeekIn, AddDropWeekOut, FixtureTeam, HistoryOut, Meta, MispricedRow, MultiSeasonOut, MultiSuggestIn, MultiSuggestOut, MultiTradeIn, MultiTradeOut, Perceived, Player,
  RankingsOut, Roster, SeasonOut, SeasonPageOut, SitStartOut, Source, StreamOut, StrategyIn, SuggestIn, SuggestOut, SyncStatus, TradeIn,
  TradeOut, WaiverOut, WeeklyIn, WeeklyOut,
} from "./types";

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
const post = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) });

export const api = {
  meta: (injuries: boolean) => request<Meta>(`/api/meta?${q(injuries)}`),
  roster: (league: string, team: string, source: Source, injuries: boolean) =>
    request<Roster>(`/api/leagues/${league}/roster/${team}?source=${source}&${q(injuries)}`),
  freeAgents: (league: string, source: Source, injuries: boolean) =>
    request<{ source: Source; players: Player[] }>(`/api/leagues/${league}/free-agents?source=${source}&${q(injuries)}`),
  analyze: (league: string, body: TradeIn) => request<TradeOut>(`/api/leagues/${league}/trade/analyze`, post(body)),
  season: (league: string, body: TradeIn & { n_sims?: number; strength_sd?: number }) =>
    request<SeasonOut>(`/api/leagues/${league}/trade/season`, post(body)),
  suggest: (league: string, body: SuggestIn) => request<SuggestOut>(`/api/leagues/${league}/trade/suggest`, post(body)),
  multiAnalyze: (league: string, body: MultiTradeIn) =>
    request<MultiTradeOut>(`/api/leagues/${league}/trade/multi/analyze`, post(body)),
  multiSeason: (league: string, body: MultiTradeIn & { n_sims?: number; strength_sd?: number }) =>
    request<MultiSeasonOut>(`/api/leagues/${league}/trade/multi/season`, post(body)),
  tradeFixtures: (league: string, body: TradeIn) =>
    request<{ teams: FixtureTeam[] }>(`/api/leagues/${league}/trade/fixtures`, post(body)),
  multiFixtures: (league: string, body: MultiTradeIn) =>
    request<{ teams: FixtureTeam[] }>(`/api/leagues/${league}/trade/multi/fixtures`, post(body)),
  multiSuggest: (league: string, body: MultiSuggestIn) =>
    request<MultiSuggestOut>(`/api/leagues/${league}/trade/multi/suggest`, post(body)),
  mispricing: (league: string, team: string, perceived: Perceived, injuries: boolean) =>
    request<{ sell_high: MispricedRow[]; buy_low: MispricedRow[] }>(
      `/api/leagues/${league}/trade/mispricing?team=${team}&perceived=${perceived}&${q(injuries)}`),
  weekly: (league: string, body: WeeklyIn) => request<WeeklyOut>(`/api/leagues/${league}/weekly`, post(body)),
  stream: (league: string, body: WeeklyIn & { used: number | null; droppable: string[] }) =>
    request<StreamOut>(`/api/leagues/${league}/weekly/stream`, post(body)),
  waiver: (league: string, team: string, strategy: StrategyIn | null, injuries: boolean) =>
    request<WaiverOut>(`/api/leagues/${league}/waiver`, post({ team, strategy, injuries })),
  seasonPage: (league: string, team: string, n: number, sd: number, injuries: boolean) =>
    request<SeasonPageOut>(`/api/leagues/${league}/season?team=${team}&n=${n}&sd=${sd}&${q(injuries)}`),
  rankings: (league: string, source: Source, injuries: boolean) =>
    request<RankingsOut>(`/api/leagues/${league}/rankings?source=${source}&${q(injuries)}`),
  addDropWeek: (league: string, body: AddDropWeekIn) =>
    request<AddDropWeekOut>(`/api/leagues/${league}/adddrop/week`, post(body)),
  history: (league: string, team: string, injuries: boolean) =>
    request<HistoryOut>(`/api/leagues/${league}/history?team=${team}&${q(injuries)}`),
  sitstart: (league: string, body: WeeklyIn) => request<SitStartOut>(`/api/leagues/${league}/sitstart`, post(body)),
  syncStatus: () => request<SyncStatus>("/api/sync"),
  syncStart: (players: boolean) => request<SyncStatus>("/api/sync", post({ players })),
};
