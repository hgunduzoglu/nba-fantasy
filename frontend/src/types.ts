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
  read_only?: boolean;
  /** Detaylı analiz (README §13.29): anahtar var mı, sunucuda erişim kodu gerekir mi. */
  report?: { available: boolean; needs_code: boolean };
}

export interface ReportCounter {
  give: { id: string; name: string }[];
  get: { id: string; name: string }[];
  why: string;
  valid: boolean;
}

export interface TradeReportBody {
  decision: string;
  confidence: string;
  headline: string;
  sections: { title: string; points: string[] }[];
  counter_offers: ReportCounter[];
  watch: string[];
}

export interface ReportRecord {
  key: string;
  status: "running" | "done" | "error";
  error?: string;
  created_at?: string;
  model?: string;
  cost?: number;
  report?: TradeReportBody;
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
  /** Kalan sezon maçı oynama oranıyla kısıldıysa (yalnız kalan sezon kaynağında). */
  durability?: { rate: number; yahoo_gp: number; games_left: number } | null;
  stats: Record<CategoryKey, number | null>;
  attempts: { fgm: number | null; fga: number | null; ftm: number | null; fta: number | null };
  z: Record<CategoryKey, number | null>;
  value: number | null;
  rank: number | null;
  /** Bu sezon / sezon öncesi kaynağında: o kaynağa bakan menajerin gözündeki sıra ve bu sıranın kalan sezon
   *  piyasasındaki karşılığı (Değer ile aynı ölçek). Kalan sezon kaynağında null. */
  perceived_value?: number | null;
  perceived_rank?: number | null;
  /** Bu sezon 3 maçtan az: sezon öncesi sırası kullanıldı. */
  perceived_fallback?: boolean | null;
  /** Boştaki oyuncu: hemen alınabilir (FA) ya da waiver'da (``from`` gününden itibaren). */
  availability?: Availability;
}

export interface Availability {
  kind: "FA" | "W";
  from: string | null;
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
  auto_punt?: 1 | 2;
  auto_revive?: 1 | 2;
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
  /** Kalan sezon oranlarının temeli (README §13.28); varsayılan Yahoo projeksiyonu. */
  basis?: Basis;
}

export type Basis = "ros" | "season" | "recent" | "blend";

/** IL dönüş takvimi: kim döner, kim bırakılır (``self_cut``: dönen kadroya girmez). */
export interface ReturnEvent {
  returning: { id: string; name: string };
  date: string | null;
  dropped: { id: string; name: string } | null;
  self_cut: boolean;
  incoming: boolean;
}

export interface ScenarioSide {
  ecw_delta: number;
  win_delta: number;
  strategy_delta: number;
  drops: string[];
  returns: ReturnEvent[];
}

export interface ScenarioRow {
  basis: Basis;
  label: string;
  fairness: number;
  mutual: boolean;
  a: ScenarioSide;
  b: ScenarioSide;
}

export type Rates = Partial<Record<CategoryKey | "FGA", number | null>>;

export interface ScenariosOut {
  bases: ScenarioRow[];
  players: (BriefPlayer & { side: "a" | "b"; season_gp: number | null; rates: Partial<Record<Basis, Rates>> })[];
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
  returns?: ReturnEvent[];
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

export interface BriefPlayer {
  id: string;
  name: string;
  nba_team: string;
  positions: string[];
  status: string;
}

/** Takas ekranındaki seçimi tamamla/dengele (README §13.27). */
export interface CompletePlayer extends BriefPlayer {
  added: boolean;
}

export type CompleteTier = "mutual" | "own" | "loss";

export interface CompleteRow {
  give_a: CompletePlayer[];
  give_b: CompletePlayer[];
  tier: CompleteTier;
  score: number;
  own_delta: number;
  other_delta: number;
  own_win: number;
  other_win: number;
  fairness: number;
  perceived_view: number;
  my_categories: Record<string, number>;
  adjustments: Record<string, { drop: string[]; add: string[]; move_to_il: string[] }>;
}

export interface CompleteOut {
  kind: "get" | "give" | "balance";
  suggestions: CompleteRow[];
  current: CompleteRow | null;
  examined: number;
  rejected_balance: number;
  rejected_view: number;
  rejected_roster: number;
  limit_reached: boolean;
  min_fairness: number;
  min_view: number;
  message: string;
}

export type SuggestMode = "mutual" | "sell_high" | "buy_low";
export type Perceived = "season_total" | "preseason" | "blend";

export interface SuggestIn {
  team: string;
  mode: SuggestMode;
  opponents?: string[] | null;
  opponent_assumption: "balanced" | "punt1" | "punt2";
  perceived: Perceived;
  min_balance: number;
  min_edge: number;
  packages: string[];
  max_evaluations: number;
  min_fairness: number;
  min_gain: number;
  ecw_weight?: number;
  /** Karşılıklı faydada rakibin gözünde (algılanan değer) en az aldığı / verdiği. */
  min_view?: number;
  auto_balance: boolean;
  strategy?: StrategyIn | null;
  injuries: boolean;
}

export interface Suggestion {
  team_b: string;
  team_b_name: string;
  give_a: BriefPlayer[];
  give_b: BriefPlayer[];
  own_delta: number;
  other_delta: number;
  own_win: number;
  other_win: number;
  fairness: number;
  perceived_balance: number | null;
  score: number;
  mode: SuggestMode;
  key_players: string[];
  other_strategy: string;
  other_weights: number[];
  /** Rakiplere karşı ortalama kategori kazanma olasılığı değişimi (0–1 ölçeğinde fark). */
  my_categories: Record<CategoryKey, number>;
  other_categories: Record<CategoryKey, number>;
  /** Fantezi playoff haftalarında kadronun toplam NBA maçı farkı, otomatik bırak/ekle dahil (bilinmiyorsa null). */
  playoff_games: number | null;
  /** Takastan sonra senin aktif kadronda doldurulamayan pozisyon sayısı. */
  position_gap: number;
  /** Rakibin gözünden (algılanan değer): aldığı / verdiği. */
  perceived_view: number | null;
  adjustments: Record<string, Record<"drop" | "add" | "move_to_il", string[]>>;
}

export interface SuggestOut {
  suggestions: Suggestion[];
  strategy: { name: string; weights: number[] };
  examined: number;
  eligible: number;
  rejected_balance: number;
  rejected_view?: number;
  rejected_roster: number;
  limit_reached: boolean;
  message: string;
}

export interface MispricedRow {
  player_id: string;
  name: string;
  team_id: string;
  team: string;
  gp_now: number | null;
  perceived_rank: number;
  ros_rank: number;
  edge: number;
}

export interface GridRow extends BriefPlayer {
  marks: string[];
  counted: number;
}

export interface Outlook {
  p: number[];
  expected_wins: number;
  p5: number;
  strategy_score: number;
  totals: { mine: Record<CategoryKey, number>; opp: Record<CategoryKey, number> };
  counted: { mine: number; opp: number };
  benched: { mine: number; opp: number };
  day_labels: string[];
  grid: { mine: GridRow[]; opp: GridRow[] };
}

export interface WeekInfo {
  week: number;
  start: string;
  end: string;
  playoff: boolean;
  current: boolean;
}

export interface WeeklyOut {
  weeks: WeekInfo[];
  current_week: number;
  week: number;
  week_start: string;
  days: string[];
  opponent: string;
  opponent_name: string;
  fixture_opponent: string | null;
  started: boolean;
  acquisitions_limit: number;
  live: WeeklyLive | null;
  active_roster: BriefPlayer[];
  default_droppable: string[];
  outlook: Outlook;
  notes: string[];
}

/** Yahoo senkronizasyonundan haftanın şu ana kadarki skoru (``yahoo_live.json``). */
export interface WeeklyLive {
  captured_at: string;
  partial_today: boolean;
  mine: Record<string, number> | null;
  opp: Record<string, number> | null;
  category_wins: [number | null, number | null];
  adds_used: number | null;
  manual: boolean;
}

export interface SyncStatus {
  running: boolean;
  log: string[];
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  result: { as_of: string; pages: number; written: string[]; notes: string[]; live: boolean } | null;
  last_sync: string | null;
  read_only?: boolean;
}

export interface WeeklyIn {
  team: string;
  week?: number | null;
  opponent?: string | null;
  sit_out: boolean;
  strategy?: StrategyIn | null;
  acc_mine?: Record<string, number> | null;
  acc_opp?: Record<string, number> | null;
  injuries: boolean;
}

export interface StreamMove {
  day: string;
  add: BriefPlayer;
  drop: BriefPlayer;
  ros_delta: number;
  games: number;
}

export interface StreamOut {
  moves: StreamMove[];
  left: number;
  before: { p: number[]; expected_wins: number; p5: number };
  after: Outlook;
}

export interface WaiverRow {
  add: Player;
  drop: BriefPlayer;
  score: number;
  delta_ecw: number;
  dp: Record<CategoryKey, number>;
  games_this_week: number;
  games_next_week: number;
}

export interface WaiverOut {
  rows: WaiverRow[];
  drops: { drop: BriefPlayer; best_add: BriefPlayer; score: number }[];
  days_this_week: number;
  week: number | null;
  adds_left: number | null;
  fab: number | null;
  synced: boolean;
  waiver_time: string | null;
  waiver_type: string | null;
}

/** Bu haftanın add/drop menüsü (``/adddrop/week``). */
export interface AddDropPlayer extends BriefPlayer {
  availability: Availability;
}

export interface AddDropSingle {
  add: AddDropPlayer;
  drop: BriefPlayer;
  day: string;
  games: number;
  gain: number;
  d_expected_wins: number;
  d_p5: number;
  dp: Record<CategoryKey, number>;
  ros_delta: number;
}

export interface AddDropCategory {
  key: CategoryKey;
  label: string;
  p: number;
  leverage: number;
  chosen: boolean;
}

export interface AddDropWeekOut {
  week: number;
  current_week: number;
  weeks: WeekInfo[];
  days: string[];
  opponent: string;
  opponent_name: string;
  mode: "win" | "critical";
  objective: string;
  chosen: CategoryKey[];
  categories: AddDropCategory[];
  base: { p: number[]; expected_wins: number; p5: number };
  adds_limit: number;
  adds_used: number;
  adds_left: number;
  fab: number | null;
  waiver_time: string | null;
  waiver_type: string | null;
  synced: boolean;
  singles: AddDropSingle[];
  plan: {
    moves: { day: string; add: AddDropPlayer; drop: BriefPlayer; ros_delta: number; games: number }[];
    after: { p: number[]; expected_wins: number; p5: number };
  } | null;
  droppable: string[];
  active_roster: BriefPlayer[];
}

export interface AddDropWeekIn extends WeeklyIn {
  mode: "win" | "critical";
  categories: CategoryKey[] | null;
  droppable: string[] | null;
  used: number | null;
}

export interface DropIn extends WeeklyIn {
  activate: string[] | null;
}

export interface DropPlayer extends BriefPlayer {
  injury: Injury | null;
  return_date: string | null;
  rank?: number | null;
}

export interface DropIL extends DropPlayer {
  season: boolean;
  ready: boolean;
  activated: boolean;
}

export interface DropRow {
  player: DropPlayer;
  returning: boolean;
  ros_loss: number;
  ros_d_ecw: number;
  ros_dp: Record<string, number>;
  week_loss: number;
  week_d_expected: number;
  week_d_p5: number;
  week_dp: Record<string, number>;
  games: number;
  games_left: number;
  games_next: number;
  open_slots: number;
  replacement: { add: BriefPlayer; score: number } | null;
}

export interface DropOut {
  week: number;
  current_week: number;
  weeks: WeekInfo[];
  days: string[];
  opponent: string;
  opponent_name: string;
  objective: string;
  capacity: number;
  active_count: number;
  il: DropIL[];
  activate: string[];
  need: number;
  recommended: string[];
  base: { p: number[]; expected_wins: number; p5: number };
  rows: DropRow[];
  synced: boolean;
}

export interface SeasonTeamRow {
  team_id: string;
  team: string;
  record_now: string;
  exp_w: number;
  exp_l: number;
  exp_t: number;
  exp_pct: number;
  mean_seed: number;
  p_playoff: number;
  p_bye: number | null;
  p_first: number;
  p_champion: number;
}

export interface SeasonPageOut {
  n_sims: number;
  strength_sd: number;
  start_week: number;
  playoff_size: number;
  byes: number;
  playoff_weeks: number[];
  reseed: boolean;
  standings_known: boolean;
  notes: string[];
  table: SeasonTeamRow[];
  schedule: { week: number; start: string; opponent: string; opponent_name: string; exp_cats: number; p_win: number }[];
  playoff_games: { week: number; start: string; end: string; mine: number; avg: number }[];
}

export interface RankTeam {
  team_id: string;
  team: string;
  totals: Record<CategoryKey, number | null>;
  ranks: Record<CategoryKey, number | null>;
  avg_rank: number;
  coverage: { roster: number; complete: number; modeled_ros: number };
  ecw?: number;
  p5?: number;
  p?: Record<CategoryKey, number>;
}

export interface RankingsOut {
  source: Source;
  mode_label: string;
  teams: RankTeam[];
}

// ------------------------------------------------------------------ çok takımlı takas
export interface MoveIn {
  player: string;
  from_team: string;
  to_team: string;
}

export interface MultiTradeIn {
  moves: MoveIn[];
  drops?: Record<string, string[]>;
  adds?: Record<string, string[]>;
  strategies?: Record<string, StrategyIn | null>;
  auto_balance: boolean;
  injuries: boolean;
}

export interface MultiTeamOut {
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
  value_in: number;
  value_out: number;
  perceived_in: number;
  perceived_out: number;
  playoff_games: number | null;
  sent: (BriefPlayer & { to: string; to_name: string })[];
  received: (BriefPlayer & { from: string; from_name: string })[];
  categories: CategoryProb[];
  adjustments: Record<"drop" | "add" | "move_to_il", { id: string; name: string }[]>;
  ranks: Record<string, RankRow[]>;
}

export interface MultiTradeOut {
  teams: MultiTeamOut[];
  fairness: number;
  mutual: boolean;
  assessments: { commissioner_risk: string; review_type: string; deadline: string | null; deadline_passed: boolean;
                 all_matchup_improve: boolean };
  notes: string[];
  modes: Record<string, string>;
  n_teams: number;
}

export interface MultiSeasonOut {
  n_sims: number;
  strength_sd: number;
  teams: (SeasonSide & { team: string })[];
  notes: string[];
}

export interface MultiSuggestIn {
  team: string;
  shapes: string[];
  opponents?: string[] | null;
  opponent_assumption: "balanced" | "punt1" | "punt2";
  shortlist: number;
  shortlist4: number;
  min_fairness: number;
  min_gain: number;
  min_win?: number;
  ecw_weight?: number;
  min_view?: number;
  strategy?: StrategyIn | null;
  injuries: boolean;
}

export interface MultiSuggestTeam {
  team_id: string;
  team: string;
  strategy: string;
  weights: number[];
  strategy_delta: number;
  win_delta: number;
  ecw_delta: number;
  value_in: number;
  value_out: number;
  playoff_games: number | null;
  categories: Record<CategoryKey, number>;
  adjustments: Record<"drop" | "add" | "move_to_il", string[]>;
}

export interface MultiSuggestion {
  shape: string;
  shape_label: string;
  score: number;
  fairness: number;
  moves: { player: BriefPlayer; from: string; from_name: string; to: string; to_name: string }[];
  teams: MultiSuggestTeam[];
}

export interface MultiSuggestOut {
  suggestions: MultiSuggestion[];
  strategy: { name: string; weights: number[] };
  scanned: number;
  candidates: number;
  evaluated: number;
  eligible: number;
  rejected_view?: number;
  message: string;
  shapes: Record<string, string>;
}

// ------------------------------------------------------------------ fikstür etkisi
export interface FixtureWeek {
  week: number;
  start: string | null;
  opponent: string;
  opponent_name: string;
  p_before: number;
  p_after: number;
  exp_before: number;
  exp_after: number;
  /** Rakip de takasta (onun kadrosu da değişti). */
  partner: boolean;
}

export interface FixtureTeam {
  team_id: string;
  team: string;
  weeks: FixtureWeek[];
  wins_before: number;
  wins_after: number;
}

/** Geçmiş haftalar (``/history``): takımın kategori değerleri ve ligdeki sırası. */
export interface HistoryRow {
  week: number;
  start: string | null;
  end: string | null;
  partial: boolean;
  n_teams: number;
  result: { opponent: string; opponent_name?: string; wins: number | null; losses: number | null; ties: number | null } | null;
  values: Record<CategoryKey, number>;
  ranks: Record<CategoryKey, number>;
  median: Record<CategoryKey, number>;
  best: Record<CategoryKey, number>;
}

export interface HistoryOut {
  team: string;
  synced: boolean;
  weeks: HistoryRow[];
  season: HistoryRow | null;
}

/** Haberler (``/news``): lige göre etiketlenmiş olaylar ve rol değişimleri. */
export interface NewsPerson {
  id: string | null;
  name: string;
  owner: "me" | "opp" | "team" | "FA" | "W" | null;
  owner_name: string | null;
  nba_team: string;
  status: string;
  waiver_until?: string | null;
}

export interface NewsEvent {
  id: string;
  source: "cbs" | "espn";
  url: string;
  published: string;
  headline: string;
  body: string;
  analyzed: boolean;
  type: string | null;
  status: string | null;
  return_estimate: string | null;
  games_out: number | null;
  impact: number | null;
  summary: string | null;
  player: NewsPerson | null;
  beneficiaries: NewsPerson[];
  hurt: NewsPerson[];
  tags: ("mine" | "opp" | "fa")[];
}

export interface RoleRow {
  player: NewsPerson;
  team: string;
  absent: string[];
  until: string | null;
  n_without: number;
  n_with: number;
  delta: Record<"minutes" | "pts" | "reb" | "ast" | "stl" | "blk" | "fg3m" | "tov", number>;
  raw_minutes: number;
}

export interface NewsOut {
  events: NewsEvent[];
  roles: RoleRow[];
  opponent: string | null;
  opponent_name: string | null;
}

export interface NewsStatus {
  running: boolean;
  log: string[];
  error: string | null;
  result: { summary: string } | null;
  fetched_at: string | null;
  items: number;
  analyzed: number;
  model: string;
  has_key: boolean;
  read_only?: boolean;
  cost_7d: number;
  cost_total: number;
}

/** Sit/start önerisi (``/sitstart``). */
export interface SitStartCell {
  state: "start" | "sit" | "bench" | "out" | "";
  slot: string | null;
}

export interface SitStartPlayer extends BriefPlayer {
  value: number;
  dp: Record<string, number>;
  games: number;
  started: number;
  yahoo_slot: string | null;
  cells: SitStartCell[];
}

export interface SitStartChange extends BriefPlayer {
  yahoo_slot: string;
  slot: string | null;
  value: number;
  negative: boolean;
}

export interface SitStartToday {
  day: string;
  start: SitStartChange[];
  sit: SitStartChange[];
}

export interface SitStartScore {
  p: number[];
  expected_wins: number;
  p5: number;
  strategy_score: number;
}

export interface SitStartOut {
  week: number;
  current_week: number;
  weeks: WeekInfo[];
  days: string[];
  opponent: string;
  opponent_name: string;
  fixture_opponent: string | null;
  slot_names: string[];
  before: SitStartScore;
  after: SitStartScore;
  players: SitStartPlayer[];
  today: SitStartToday | null;
  rounds: number;
  live: { captured_at: string; partial_today: boolean } | null;
}
