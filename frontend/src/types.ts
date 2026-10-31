export type CategoryKey =
  | "FG_PCT" | "FT_PCT" | "FG3M" | "PTS" | "REB" | "AST" | "STL" | "BLK" | "TOV";

export interface Category {
  key: CategoryKey;
  label: string;
  lower_is_better: boolean;
}

export type Source = "ros" | "season" | "preseason";

export interface Team {
  id: string;
  name: string;
}

export interface League {
  id: string;
  name: string;
  default_team: string;
  teams: Team[];
  capacity: number;
  il_slots: number | null;
  trade_deadline: string | null;
  playoffs: string | null;
}

export interface Preset {
  name: string;
  weights: number[];
}

export interface Meta {
  as_of: string;
  leagues: League[];
  categories: Category[];
  sources: Record<Source, string>;
  presets: Preset[];
  injury_file: string | null;
  issues: string[];
}

export interface Injury {
  kind: "out_until" | "season" | "day_to_day" | "unknown";
  return_date: string | null;
  text: string;
  injury: string;
}

export interface Player {
  id: string;
  name: string;
  nba_team: string;
  positions: string[];
  status: string;
  il: boolean;
  injury: Injury | null;
  modeled: boolean;
  gp: number | null;
  stats: Record<CategoryKey, number | null>;
  attempts: { fgm: number | null; fga: number | null; ftm: number | null; fta: number | null };
  z: Record<CategoryKey, number | null>;
  value: number | null;
  rank: number | null;
}

export interface Roster {
  team_id: string;
  team: string;
  source: Source;
  players: Player[];
}

export interface StrategyIn {
  preset?: string;
  name?: string;
  weights?: number[];
}

export interface TradeIn {
  team_a: string;
  team_b: string;
  give_a: string[];
  give_b: string[];
  drop_a?: string[];
  drop_b?: string[];
  add_a?: string[];
  add_b?: string[];
  auto_balance: boolean;
  strategy_a?: StrategyIn | null;
  strategy_b?: StrategyIn | null;
  injuries: boolean;
}

export interface CategoryProb {
  key: CategoryKey;
  label: string;
  before: number;
  after: number;
}

export interface RankRow {
  key: CategoryKey;
  label: string;
  value_before: number | null;
  value_after: number | null;
  rank_before: number | null;
  rank_after: number | null;
}

export interface TradeSide {
  team_id: string;
  team: string;
  strategy: string;
  ecw_before: number;
  ecw_after: number;
  ecw_delta: number;
  win_before: number;
  win_after: number;
  win_delta: number;
  strategy_before: number;
  strategy_after: number;
  strategy_delta: number;
  fit_score: number;
  categories: CategoryProb[];
  adjustments: Record<"drop" | "add" | "move_to_il", { id: string; name: string }[]>;
  ranks: Record<string, RankRow[]>;
}

export interface TradeOut {
  teams: { a: TradeSide; b: TradeSide };
  fairness: number;
  perceived_balance: number | null;
  assessments: {
    mutual_benefit: boolean;
    both_matchup_improve: boolean;
    fairness_ratio: number;
    commissioner_risk: string;
    review_type: string;
    review_time: string;
    deadline: string | null;
    deadline_passed: boolean;
  };
  notes: string[];
  modes: Record<string, string>;
}

export interface SeasonSide {
  team_id: string;
  playoff_before: number;
  playoff_after: number;
  champion_before: number;
  champion_after: number;
  seed_before: number;
  seed_after: number;
}

export interface SeasonOut {
  n_sims: number;
  strength_sd: number;
  teams: { a: SeasonSide; b: SeasonSide };
  notes: string[];
}
