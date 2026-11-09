# Fantasy Trade Lab / Fantasy Draft Optimizer (FDO)

Turkish version: [README_TR.md](README_TR.md).

Trade Lab's scope, data audit, model formulas, tests and open limitations:
[Claude / developer handoff report](docs/TRADE_LAB_HANDOFF.md).

## In-season Trade Lab

Launch it with `streamlit run src/fdo/ui/app.py`. The default start page is now Trade Lab;
the earlier draft tools are still available from the archive menus.

- **Three separate league rankings:** preseason projection, realized season totals and the current
  rest-of-season projection. Each uses the current rosters. The realized view is the players'
  season totals applied to the current rosters; it is not the team stats earned in Yahoo from
  past active slots, nor a historical standings table.
- **"Takas Analizi" (Trade Analysis):** category values and league-rank changes for both sides, the change in
  rest-of-season ECW and in typical-week P(5+), and a comparison against every opponent.
  Both teams' new rosters are evaluated at the same time. Strategies are chosen separately.
- **"Takas Önerileri" (Trade Suggestions):** 1x1, 2x1, 1x2, 2x2 and optional 3x2/2x3 packages. Packages that clear
  both sides' strategy-dependent ECW and P(5+) thresholds are ranked by mutual benefit and
  package balance. The multi-player search is limited by a shortlist/budget; it does not claim
  to scan every possible package. The acceptance score and commissioner risk are heuristic; they
  are not calibrated probabilities of human acceptance or commissioner approval.
- **Punt:** balanced, single/double punt, custom 0–3 weights, or a hypothetical opponent
  strategy based on the weakest category. Physical win probabilities and the league's nine
  categories are not changed.
- **Roster plan:** normal capacity and IL are kept separate. For uneven packages, the players to
  drop and to add are shown explicitly. Adds from the free-agent pool depend on waiver/acquisition
  rules. Empty slots that already existed are not filled in as a trade benefit.
- Analyses can be downloaded as JSON and rankings as CSV; scenarios are compared within the same session.

Data is read from `data/real/rosters.json`, `league_info.json`, `player_stat_pages.json`, and the older
`players_yahoo_*.csv` and `projections_yahoo_*.csv` files. The new layer lives in
`fdo.trade`; it has no Streamlit dependency. The draft seat and the Yahoo team ID are
separate. The default team is picked from the single team's schedule on hand and can be
changed in the sidebar. The number of teams that actually have a roster is used instead of `Max Teams`.

New personal Yahoo league exports are kept locally, outside Git. In a fresh clone,
these three JSON files must be supplied separately for Trade Lab; the file contract is
described in the [handoff report](docs/TRADE_LAB_HANDOFF.md#6-yerel-çalıştırma-ve-veri-sözleşmesi).

FG% = total FGM / total FGA, FT% = total FTM / total FTA. The source's percentage
columns are never averaged. Preseason per-game data is multiplied by GP; the other
two sources are already period totals. No source fills in another source's missing fields.
Raw faulty/missing data is not modified; the rankings sum the numeric contributions on hand and
show the coverage. The ROS model only includes complete, usable contributions; players with missing data
are not removed from rosters and are not included in automatic suggestion packages.

ROS probabilities spread the totals **over the weeks remaining from the snapshot date to the end of
the NBA season**; they do not divide the remaining GP by 82. The date selection only affects the
trade-deadline check; it does not extrapolate old projections to the new date. The model uses a Normal
approximation, independent variance across players and an adjustable average lineup utilization
rate. P(5+) additionally assumes independence between categories. These are uncalibrated
typical-week indicators; they are not a real weekly lineup, playoff or season simulation.
Missing opponent H2H schedules are not used; all opponents are compared with equal weight.
When the source files change, the cache is refreshed via the file signature.

Verification: `python -m pytest tests/unit/test_trade.py tests/integration/test_trade_ui.py`.
CLI: `python scripts/analyze_trade.py --help` (player IDs are Yahoo IDs).

---

## Reference documentation for the draft tools

A **16-team, H2H 9-Cat Each Category** draft simulator and decision support system for Yahoo Fantasy Basketball 2026–27.

> **Status:** The V1 (M0–M6) implementation is complete; it runs end to end on synthetic data and passes its tests.
> Choosing the real data source and the manifests are user actions (§5.1, §10 M0).
> This file is the project's reference document. Where it conflicts with the code, either the code is fixed or the README is deliberately updated.
>
> **Normative language:** **REQUIRED** = acceptance criterion, **RECOMMENDED** = do not deviate without a justification, **OPTIONAL** = if time allows.

---

## Table of contents

1. [Purpose and scope](#1-purpose-and-scope)
2. [Invariant principles](#2-invariant-principles)
3. [League configuration](#3-league-configuration)
4. [Architecture and repo layout](#4-architecture-and-repo-layout)
5. [Data: sources, legal status, schema, validation](#5-data-sources-legal-status-schema-validation)
6. [Component specifications](#6-component-specifications)
7. [Measuring simulation realism](#7-measuring-simulation-realism)
8. [Streamlit interface](#8-streamlit-interface)
9. [Testing strategy](#9-testing-strategy)
10. [Milestones and acceptance criteria](#10-milestones-and-acceptance-criteria)
11. [Performance budgets](#11-performance-budgets)
12. [Known limitations and open questions](#12-known-limitations-and-open-questions)
13. [V2](#13-v2)
14. [Installation and running](#14-installation-and-running)
15. [Glossary](#15-glossary)

---

## 1. Purpose and scope

### 1.1 V1's one-sentence goal

> While drafting from the 16th seat, to see **which pool of players I am likely to reach at picks 48–49 depending on which pair I take at picks 16–17**, and how that affects my **expected category wins (ECW)** against opponents over the season.

### 1.2 V1 scope

| Included (V1) | Excluded (V2+) |
|---|---|
| CSV ingestion, validation, data manifest | Yahoo API / OAuth / live sync |
| Z-score (default) and G-score (alternative) ranking | Past-season backtest (only its interface in V1) |
| Volume-weighted FG%/FT%, custom weights, punt presets | Daily lineup solver, NBA schedule, B2B |
| Snake draft engine (configurable 3RR), undo/replay, export | Injury scenarios, rookie role models |
| Thurstone ADP bots, bot profiles, ADP fallback | Deep rollout / beam search / MCTS across 13 rounds |
| Position eligibility and slot assignment | H-score-style future-pick weight optimization |
| Variance-aware weekly matchup model (Normal approximation) | Full Monte Carlo season simulation |
| Survival probability, pair-pick suggestion, rollout to the next pair | Variance calibration with nba_api |
| Realism report, reach warnings, alternative roster scenarios (light) | Database, separate backend, deployment |

### 1.3 Technology

Python 3.11+, NumPy, Pandas, SciPy, Streamlit, pytest, PyYAML. No other required dependency. No database; state is kept in JSON/CSV files. No internet connection is required.

---

## 2. Invariant principles

These rules are checked in code review and protected by tests where possible.

1. **ADP ≠ value.** ADP is used only for *opponent behavior and survival probability*. Projections are used only for *player contribution*. The `valuation/` and `matchup/` packages **cannot import** the ADP table. This is enforced by a test (§9.3). The single exception is ADP imputation (§5.6): for a player without ADP, an ADP *estimate* is produced from the value order, and that estimate is flagged as `adp_status=imputed`.
2. **Ranking ≠ objective.** Z and G are used only in the Projection Explorer and in bot profiles. Pair-pick suggestions made to the user are ranked **only by ECW** (expected category wins).
3. **Punt affects only the ranking.** When a category's weight is `0`, that category is dropped from player value. The matchup model, however, **always counts all 9 categories**.
4. **Ratios are always computed from totals.** `FG% = ΣFGM / ΣFGA`, `FT% = ΣFTM / ΣFTA`. Percentages are never averaged anywhere.
5. **Lower TO is better.** This rule is defined in exactly one place (`config.lower_is_better`) and every module reads it from there.
6. **Symmetric ADP distance is forbidden.** No score of the form `−|ADP − pick|` is used in bot decisions. The pick probability of a player who has fallen (past his ADP) **must increase** as picks advance (§9 test).
7. **No hard bans, only tails.** Bot reaches are not blocked by hard bans. Extreme events come from the tail of the model's distribution and are measured in the realism report.
8. **No fabricated real data.** No fabricated statistics are written under a real player's name. Synthetic data is flagged with `is_synthetic=true` and names prefixed with `SYN_`. Synthetic and real data cannot be mixed in the same session (§5.7).
9. **Reproducibility.** Every random operation runs with an externally supplied `numpy.random.Generator`. The same data, config and seed produce the same output.
10. **Honest display of probabilities.** Every probability that relies on uncalibrated parameters is shown in the UI with an `uncalibrated` badge. Monte Carlo estimates are shown together with their standard error (SE).
11. **Pure core.** No module outside `ui/` imports Streamlit. Algorithms are pure functions or classes with explicit dependencies.

---

## 3. League configuration

### 3.1 Finalized settings — `config/league.yaml`

```yaml
league:
  platform: yahoo
  season: "2026-27"
  teams: 16
  my_seat: 16
  rounds: 13               # 208 picks in total
  draft_type: snake
  third_round_reversal: false   # off by default; can be set to true

scoring:
  format: h2h_each_category
  categories: [FG_PCT, FT_PCT, FG3M, PTS, REB, AST, STL, BLK, TOV]
  lower_is_better: [TOV]
  ratio_categories:
    FG_PCT: {makes: FGM, attempts: FGA}
    FT_PCT: {makes: FTM, attempts: FTA}

roster:
  slots: {PG: 1, SG: 1, G: 1, SF: 1, PF: 1, F: 1, C: 2, UTIL: 2, BN: 3}   # 10 active + 3 bench = 13
  active_slots: [PG, SG, G, SF, PF, F, C, UTIL]
  slot_eligibility:
    PG:   [PG]
    SG:   [SG]
    G:    [PG, SG]
    SF:   [SF]
    PF:   [PF]
    F:    [SF, PF]
    C:    [C]
    UTIL: [PG, SG, SF, PF, C]
    BN:   [PG, SG, SF, PF, C]
```

This league has **no** `FC` slot and has two `C` slots. When the config is loaded, `sum(slots) == rounds` is checked (13 = 13).

### 3.2 League rules — verified and unverified settings

The settings were verified by the user (12–13 October 2026). If a field is set to `null`, it is treated as unverified.

```yaml
unverified:
  tie_value: 0.5              # verified: a category tie is recorded as T (like 5-3-1); 0.5 for win%
  pick_timer_seconds: 45      # verified: advisor budget in the real draft (no timer in mocks)
  lineup_lock: daily_today    # verified: daily changes until the game starts → utilization (§6.6.1)
  il_slots: 3                 # verified: not part of the draft roster (13 picks)
  il_plus_slots: 0            # verified: no IL+; a Q (questionable) player gets no effect at all (§5.8)
  playoff_weeks: 3            # verified: fantasy playoffs are the last 3 matchup weeks (V2 schedule)
  keepers: false
  position_limits_enforced_in_draft: true   # verified: Yahoo enforces the position rule during the draft
```

There is no auto-drafting manager in the league (per the user); `AutoDrafter` is 0 in the bot mix (§6.4.3).

`null` values are never silently converted to a default in any calculation. If a value that affects a calculation is `null`, a warning is shown on the relevant screen.

### 3.3 Pick order

For overall pick number `k` (1-based) and team count `T`:

```
r = ceil(k / T)                 # round
p = k − (r − 1)·T               # position within the round (1..T)

forward(r):
  3RR off: forward if r is odd, backward if even
  3RR on : r = 1 forward, r = 2 backward, for r ≥ 3 forward if r is even, backward if odd

seat(k) = p            (if forward)
        = T + 1 − p    (if backward)
```

**Expected values (REQUIRED test):**

| Mode | Seat 16's picks | Adjacent pairs |
|---|---|---|
| 3RR off | 16, 17, 48, 49, 80, 81, 112, 113, 144, 145, 176, 177, 208 | (16,17) (48,49) (80,81) (112,113) (144,145) (176,177), single: 208 |
| 3RR on | 16, 17, 33, 64, 65, 96, 97, 128, 129, 160, 161, 192, 193 | (16,17) (64,65) (96,97) (128,129) (160,161) (192,193), single: 33 |

The concept of a "turn" (a block of picks) is **derived** in code, not hard-coded. A turn is the maximal set of the user's consecutive picks with no opponent pick between them. The advisor works in turns. A 1-element turn is a single pick; a 2-element turn is a pair pick.

---

## 4. Architecture and repo layout

### 4.1 Components and dependency direction

```
                ┌──────────────┐
                │ 1. ingest    │  CSV → validated tables, manifest, ADP fallback
                └──────┬───────┘
          ┌────────────┼──────────────────────┐
          ▼            ▼                      ▼
 ┌──────────────┐ ┌──────────────┐   ┌──────────────┐
 │ 2. valuation │ │ 5. roster    │   │ 3. draft     │  snake order, event log
 │  Z / G / W   │ │ eligibility  │   │   engine     │
 └──────┬───────┘ └──────┬───────┘   └──────┬───────┘
        │                │                  │
        │         ┌──────▼───────┐          │
        │         │ 6. matchup   │◄─────────┤  (rosters from draft state)
        │         │  ECW model   │          │
        │         └──────┬───────┘          │
        ▼                │                  ▼
 ┌──────────────┐        │          ┌──────────────┐
 │ 4. bots      │◄───────┼──────────│ draft state  │
 │ Thurstone    │        │          └──────────────┘
 └──────┬───────┘        │
        └───────┬────────┘
                ▼
        ┌──────────────┐
        │ 7. advisor   │  survival, pair suggestion, rollout, scenarios
        └──────┬───────┘
               ▼
        ┌──────────────┐
        │ 8. ui        │  Streamlit (the only Streamlit dependent)
        └──────────────┘
   + realism/  (measures bot output; used by advisor and ui)
```

Rules:
- Arrows point one way and there are no circular imports.
- `valuation` and `matchup` cannot read ADP (Principle 1).
- `bots` may read ADP and, optionally, `valuation` output for the bot profile.
- ECW is the single optimization objective for `advisor`.

### 4.2 Repo layout

```text
fantasy-draft-optimizer/
  README.md
  pyproject.toml
  config/
    league.yaml               # §3
    model.yaml                # bot, variance, advisor parameters (§6)
  data/
    synthetic/                # generated synthetic data (may be in the repo)
    real/                     # the user's real CSVs (+ raw/ raw exports)
    manifests/                # a manifest for each data set (§5.2)
  src/fdo/
    __init__.py
    config.py                 # YAML loading + validation (dataclass)
    types.py                  # shared types: PlayerId, Category, Slot etc.
    ingest/
      schema.py               # column definitions, types
      load.py                 # CSV reading, column mapping
      validate.py             # rules → ValidationReport
      adp_fallback.py         # ADP confidence classes + imputation
      synthetic.py            # synthetic data generator
    valuation/
      pool.py                 # reference pool iteration
      zscore.py
      gscore.py
      weights.py              # weights, punt presets
    draft/
      order.py                # pick → seat, turns
      events.py               # DraftPick event, log, undo/replay
      state.py                # DraftState derived from the event log
      io.py                   # draft log CSV/JSON import/export
    bots/
      thurstone.py            # perceived order, picking
      profiles.py             # MarketFollower, ValueHunter, ...
      league_mix.py           # profile assignment for the 15 opponents
    roster/
      eligibility.py          # position parsing, slot eligibility
      assignment.py           # optimal slot assignment, completability
    matchup/
      player_week.py          # player weekly mean/variance
      team_totals.py          # team totals
      fill.py                 # profiles for filling incomplete rosters
      ecw.py                  # P(win), ECW, category matrix
    advisor/
      simulate.py             # opponent pick simulation (CRN)
      survival.py             # survival probability
      pairs.py                # candidate generation + pair scoring
      rollout.py              # rollout to the next turn
      scenarios.py            # alternative roster archetypes (light)
      deep.py                 # V2: full-horizon rollout + successive halving (§13.3)
      uncertainty.py          # V2: injury/role scenarios (§13.5)
    realism/
      metrics.py              # pick−ADP distribution, reach, diversity
      report.py
    evaluation/
      interface.py            # SeasonEvaluator protocol
      evaluators.py           # V2: projection+noise and game log evaluators (all-play)
      backtest.py             # V2: strategy comparison (§13.1)
    schedule/                 # V2: schedule, fantasy weeks, daily lineup (§13.4)
    calibration/              # V2: variance (§13.2) and bot (§13.6) calibration
    ui/
      app.py
      pages/
        1_League_and_Data.py
        2_Projection_Explorer.py
        3_Mock_Draft.py
        4_Draft_Assistant.py
        5_Team_Dashboard.py
        6_Realism_Report.py
  scripts/
    make_synthetic.py
    run_mock_batch.py         # N mocks → realism report
    profile_advisor.py        # timing measurement
    estimate_utilization.py   # utilization estimate based on lineup lock (§6.6.1)
    import_yahoo_json.py      # Yahoo JSON → schema CSV + manifest
    fetch_nba_schedule.py     # V2: NBA schedule → schedule CSV
    fetch_gamelogs_nba_api.py # V2: game logs (nba_api, optional)
    calibrate_variance.py     # V2: φ, player variance, category correlation
    calibrate_bots.py         # V2: σ₀/σ₁ fit, survival reliability
    backtest.py               # V2: strategy comparison
  tests/
    unit/ ...                 # per module
    statistical/ ...          # seeded distribution tests
    integration/ ...          # end-to-end mock
    test_architecture.py      # import rules
```

---

## 5. Data: sources, legal status, schema, validation

### 5.1 Legal status and source policy

**This repo does not pull data from any website** (no scrapers, hidden APIs or paywall bypassing). All data comes from CSV files the user provides. Whether a source's data may be used this way is **decided by the user**, after reading that source's terms of use, and the decision is recorded in the manifest (§5.2). The code cannot verify this decision. It only records it and shows it in the UI.

The statuses in the table below are **unverified** as of 12 October 2026. The "User action" column shows what needs to be done.

| Source | Provides | Access | License / terms status | User action | V1 role |
|---|---|---|---|---|---|
| The user's own projection | Everything | Full | Belongs to the user | — | Projection |
| Hashtag Basketball | Projection, ADP | Page / premium | **Unverified**: export and personal-use terms | Read the ToS and subscription terms, record in the manifest | Projection (if permitted) |
| Yahoo Draft Analysis | Yahoo ADP, possible % drafted | Public page | **Unverified**: a public page does not imply permission for automated retrieval | Check the terms for manual copying | ADP |
| Fantasy Alarm ADP / Mock | ADP download, mock CSV | Free page | **Unverified** | Check the download terms | ADP / bot comparison |
| Yahoo Fantasy API | League settings, positions, draft results | Application and approval, read-only by default, attribution required | Yahoo API agreement | Apply in V2 | V2 |
| nba_api (MIT client) | Historical game logs | Free | Client is MIT; NBA.com data is subject to its own terms | Read the terms in V2 | V2: variance calibration |
| Synthetic generator | Test data | Local | Belongs to the repo | — | Development and testing |

**Yahoo position eligibility** is read in V1 from the `yahoo_positions` column of the user's CSV. Yahoo's actual position eligibility can differ from the NBA position. If the column is empty, the player does not enter the draft pool and a validation error is produced.

### 5.2 Data manifest (REQUIRED)

Every real data file has a manifest next to it: `data/manifests/<dosya_adı>.yaml`.

```yaml
file: data/real/projections_hashtag_2026-10-11.csv
kind: projections            # projections | adp | players | variance | draft_log
source_name: "Hashtag Basketball"
source_url: "https://..."
retrieved_at: "2026-10-11"
retrieved_by: "manual export"
license_status: personal_use_confirmed   # personal_use_confirmed | assumed | unknown
license_notes: "Subscription terms section X read; personal use."
season: "2026-27"
basis: per_game
is_synthetic: false
```

- `license_status: unknown` → the file is loaded, but a persistent yellow warning is shown in the UI.
- No manifest → the file is **not loaded**.
- Every suggestion and export carries the `source_name` and `retrieved_at` fields of the manifests it used.

### 5.3 File schemas

Projections and ADP are **separate files** and are joined on `player_id`. This way Principle 1 is also preserved in the data layer.

#### `players.csv` — identity and eligibility

| Column | Type | Required | Description |
|---|---|---|---|
| `player_id` | str | ✔ | Provider-independent internal ID (e.g. `p_0001`) |
| `name` | str | ✔ | Display name |
| `nba_team` | str | | 3-letter code |
| `yahoo_positions` | str | ✔ | Comma-separated: `PG,SG` / `SF,PF` / `C` (allowed: PG, SG, SF, PF, C) |
| `yahoo_player_id` | str | | For V2 matching |
| `nba_person_id` | str | | For V2 nba_api matching |
| `aliases` | str | | Alternative spellings separated by `;` |
| `is_synthetic` | bool | ✔ | |
| `injury_status` | str | | The source's status label (`O`, `Q`, `NA`…); `NA` is not drafted (§5.8) |
| `is_rookie` | bool | | Wider uncertainty in V2 scenarios (§13.5) |

#### `projections_<kaynak>_<tarih>.csv` — per-game projection

| Column | Type | Required | Unit |
|---|---|---|---|
| `player_id` | str | ✔ | |
| `projected_gp` | float | ✔ | Expected number of NBA games (0–82) |
| `minutes` | float | | Minutes / game |
| `fgm`, `fga` | float | ✔ | / game |
| `ftm`, `fta` | float | ✔ | / game |
| `fg3m`, `pts`, `reb`, `ast`, `stl`, `blk`, `tov` | float | ✔ | / game |
| `projection_source` | str | ✔ | |
| `as_of` | date | ✔ | |
| `is_synthetic` | bool | ✔ | |
| `notes` | str | | Role / injury note (not used in calculations in V1) |

There is no raw percentage column. Percentages are derived from `fgm/fga` and `ftm/fta`. If the source file only has the percentage and the number of attempts, the column mapper in `load.py` performs the `fgm = fg_pct × fga` conversion and records it as a validation note.

#### `adp_<kaynak>_<tarih>.csv` — draft market

| Column | Type | Required | Description |
|---|---|---|---|
| `player_id` | str | ✔ | |
| `adp` | float | | May be empty → fallback (§5.6) |
| `adp_std` | float | | Used for the Thurstone σ if the source provides it |
| `adp_min`, `adp_max` | float | | If the source provides them |
| `pct_drafted` | float | | 0–100; used in the confidence class if the source provides it |
| `default_rank` | float | | The platform's default pre-ranking (for the AutoDrafter bot) |
| `adp_source` | str | ✔ | E.g. `yahoo_draft_analysis` |
| `adp_window` | str | | E.g. `preseason_all` / `last_7_days` (whatever the source says) |
| `as_of` | date | ✔ | |
| `is_synthetic` | bool | ✔ | |

#### `variance_<kaynak>.csv` — OPTIONAL (usually absent in V1)

| Column | Type | Description |
|---|---|---|
| `player_id` | str | |
| `stat` | str | `fgm, fga, ftm, fta, fg3m, pts, reb, ast, stl, blk, tov` |
| `per_game_var` | float | Per-game variance |
| `n_games` | int | Estimation sample |
| `seasons` | str | |

If this file is absent, the model defaults in §6.6.2 are used and the results are labeled `uncalibrated`. In V2, `scripts/calibrate_variance.py` produces this file from game logs (§13.2).

#### `schedule_<kaynak>.csv` — V2, OPTIONAL (§13.4)

| Column | Type | Required | Description |
|---|---|---|---|
| `game_date` | date | ✔ | Local (ET) game date |
| `home_team`, `away_team` | str | ✔ | Same codes as `players.nba_team` (alternatives such as GS, NY, SA… are converted) |
| `game_id` | str | | |

#### `gamelogs_<kaynak>.csv` — V2, OPTIONAL (§13.1, §13.2)

| Column | Type | Required | Description |
|---|---|---|---|
| `player_id` | str | ✔ | If missing, matched by `name`; unmatched rows are dropped with a warning |
| `game_date` | date | ✔ | |
| `season` | str | ✔ | E.g. `2025-26` |
| `nba_team`, `minutes` | str, float | | |
| `fgm` … `tov` | float | ✔ | Values in the game |

#### `draft_log.csv` / `.json` — draft events

| Column | Type | Description |
|---|---|---|
| `overall_pick` | int | 1–208 |
| `round` | int | |
| `seat` | int | 1–16 |
| `player_id` | str | |
| `source` | str | `user` / `bot:<profil>` / `import` / `manual` |
| `observed_at` | datetime | |

### 5.4 Name matching

Names in the CSVs are matched to `player_id` in this order:
1. Direct `player_id` match.
2. Match on the normalized name. Normalization: lowercase, accent removal (`unicodedata`), and stripping punctuation and `Jr./Sr./II/III`.
3. Match via the `aliases` column.

A row that matches nothing or matches more than one candidate counts as an **error**, and a correction table is shown in the UI. Fuzzy matching is not applied automatically; it is only offered as a suggestion.

### 5.5 Validation rules

`validate.py` returns a `ValidationReport(errors, warnings, notes)`. If `errors` is not empty, the data set cannot be used.

| Rule | Level |
|---|---|
| Required column missing / type cannot be converted | error |
| Duplicate `player_id` | error |
| `fgm > fga` or `ftm > fta` | error |
| Negative statistic | error |
| `projected_gp ∉ [0, 82]` | error |
| `yahoo_positions` empty or a disallowed value | error |
| `fga = 0` or `fta = 0` | note (valid: ratio contribution is 0) |
| Player without a projection (in players, not in projections) | warning → removed from the pool |
| Player with ADP but no projection | warning → stays in the bot pool, value = unknown; not suggested to the user |
| `abs(pts − (2·fgm + fg3m + ftm)) > 0.5` (rounding tolerance in projections) | warning |
| `fg3m > fgm` | error |
| `as_of` before the season or older than 60 days | warning |
| Mixing synthetic and real files | error (§5.7) |
| No manifest | error |

Missing values are **never filled with 0**. Missing required stat → the player stays out of the pool and is reported.

### 5.6 ADP confidence classes and fallback

Each player is assigned an `adp_status` and an effective ADP `A_i`. The Thurstone σ is also scaled up according to this class.

| `adp_status` | Condition | `A_i` | σ multiplier |
|---|---|---|---|
| `ok` | ADP present; `pct_drafted ≥ τ_pct` or `pct_drafted` not given; `adp ≤ coverage_limit` | `adp` | 1.0 |
| `low_confidence` | ADP present but `pct_drafted < τ_pct` or `adp > coverage_limit` | `w·adp + (1−w)·Â_i`, `w = clip(pct_drafted/τ_pct, 0, 1)` (`w = 0.5` if pct is missing) | 1.5 |
| `imputed` | No ADP, value rank ≤ N | `Â_i` | 2.0 |
| `tail` | No ADP, value rank > N | `Â_i` (`after_coverage`) / `max(A) + (value rank − N)` (`isotonic`) | 2.0 |

`Â_i` (imputation): a monotone **balanced Z-value rank → ADP** mapping (isotonic regression, `scipy`/hand-written PAV) is built over the players in the `ok` class. The mapping is extended linearly beyond the coverage using the slope of the last 20% slice.

**`missing_adp_policy` (default `after_coverage`, changed after seeing real Yahoo data).** Yahoo Draft Analysis ADP only covers ~187 players and at most up to about pick 123 (mostly from 10–12-team leagues); a 16-team league needs 208 picks. With the isotonic method below, players without ADP were squeezed *inside* the coverage (92–121), and the 208th smallest effective ADP came out as 121; bots saw ~100 players as "overdue" in rounds 9–13 (median `pick − A` up to +81). With `after_coverage`:

```
Â_i = max(observed adp) + (value rank among non-ok players)
imputed / tail : A_i = Â_i
low_confidence : A_i = w·adp + (1−w)·Â_i      (w = pct/τ: near the ADP in pct of leagues, after the coverage in the rest)
```

A player who is not listed by the source, or is rarely drafted, is in practice not being picked within the picks the source covers; so they are placed after the coverage by value rank, and the `k`th smallest effective ADP ≈ `k` is preserved (on real data 100/130/160/190/208 → 102/122/148/180/200). The original specification method below can be selected with `missing_adp_policy: isotonic`.

*Implementation note (after the first realism report, for the `isotonic` policy):* Because the `ok` class is selected by `adp ≤ coverage_limit`, the truncation is on the ADP axis. The mapping is therefore fitted in the **ADP → value rank** direction and then inverted (no bias, since the selection is on the regressor). The extension slope is fitted by least squares to the raw points in the last 20% slice instead of the end points of the PAV steps. A direct fit in the value → ADP direction was noticeably compressing the imputation toward earlier picks in late rounds. This is the **only** place where value leaks into ADP. `adp_status` is visible on every screen.

Defaults (`config/model.yaml`, uncalibrated):

```yaml
adp_fallback:
  pct_drafted_threshold: 50     # τ_pct
  coverage_limit: 150           # reliable coverage of mostly 12-team league ADP (assumption)
  missing_adp_policy: after_coverage   # | isotonic
```

**Note:** Picks 145–208 of a 16-team league fall into the region where the mostly 12-team ADP data is sparse. Probabilities coming from ADP are therefore more uncertain in late rounds, and the UI shows this.

### 5.7 Synthetic data policy

`scripts/make_synthetic.py --n 400 --seed 7` produces:
- Players named `SYN_001 … SYN_400`. No real name, team or ID is used. `nba_team = "SYN"`.
- Statistics drawn from a parametric model: minutes → volume, a category profile by position archetype, correlated noise. No values are copied from real players.
- ADP imitates 12-team league sources such as Yahoo Draft Analysis: a player's pick position is `balanced value rank + N(0, σ(rank))`; `% drafted = P(position ≤ 156)`, `ADP = E[position | position ≤ 156]` (truncated mean), and those below 2% are not listed. This lets the bot and fallback paths be tested under conditions similar to real data.
- Position distribution is roughly PG 20%, SG 20%, SF 18%, PF 20%, C 22%, with about 35% of players multi-positional.
- Every file has `is_synthetic=true` and an automatic manifest (`license_status: personal_use_confirmed`, `source_name: synthetic`).

While synthetic data is loaded in the UI, a red **"SENTETİK VERİ — gerçek oyuncu değeri değildir"** (SYNTHETIC DATA — not real player value) banner is shown on every page. Synthetic and real files cannot be combined in the same session.

### 5.8 Player status

The status label from Yahoo Draft Analysis is stored in `players.csv` as `injury_status` (21 `O`, 109 `Q`, 127 `NA` in the real data). User decision (13 October 2026):

- **`NA` (not on the active roster):** not taken into the draft pool. Not suggested to the user, not picked by bots, and not accepted in the log either.
- **`O`, `Q`, `GTD`:** do not change any calculation. The effect of an injury is in the projection's expected number of games (`projected_gp`, e.g. Jimmy Butler III: 35). Since IL slots are not filled in the draft (13 picks = 13 slots), they are not modeled separately.

```yaml
availability:
  undraftable_statuses: [NA]
```

When the CSV is read, the text `NA` in the `injury_status` column is not treated as a missing value (pandas defaults apply in the other columns).

---

## 6. Component specifications

For each component: purpose, input/output, algorithm, parameters. Function signatures are guidance and names may change. The input/output contracts, however, do not change.

### 6.1 Ingestion (`fdo.ingest`)

```python
load_dataset(players_csv, projections_csv, adp_csv, variance_csv=None,
             column_map: dict | None = None) -> tuple[Dataset, ValidationReport]
make_synthetic(n_players: int, rng: np.random.Generator) -> Dataset
```

`Dataset` fields: `players`, `projections`, `adp` (separate DataFrames), `manifests`, `is_synthetic`, `content_hash`. `content_hash` is used for caching and for recording the sources of suggestions. The ADP fallback (§5.6) is applied once when the `Dataset` is built. The `adp_eff`, `adp_status` and `sigma_mult` columns are added to the `adp` table.

### 6.2 Category valuation (`fdo.valuation`)

Valuation reads only the projections.

#### 6.2.1 Basic quantities

Player `i`, category `c`. The calculation basis (`basis`) is selectable:
- `per_game`: `x_ic` = per-game value.
- `total` (**default**): `x_ic` = per game × `projected_gp`. Since a missed game lowers the weekly contribution in H2H, the total is more meaningful for draft ranking. The Explorer shows both bases.

#### 6.2.2 Reference pool (iteration to break the circularity)

```
P₀ ← all players with a projection
repeat (at most 10 times):
    compute statistics over P_k (μ, σ, p̄)
    V ← total Z with balanced weights
    P_{k+1} ← top N players by V
    stop if P_{k+1} == P_k
```

`N = teams × rounds = 208` (default). For sensitivity, the Explorer offers 180/208/240 options. The pool statistics are set once **with balanced weights**. User weights do not change the pool, so the scale does not shift when a slider is moved.

#### 6.2.3 Z-score

Counting categories `c ∈ {FG3M, PTS, REB, AST, STL, BLK}`:

```
z_ic = (x_ic − μ_c) / σ_c          μ, σ: over the pool, ddof = 0
```

TOV (reverse direction):

```
z_i,TOV = (μ_TOV − x_i,TOV) / σ_TOV
```

Ratio categories (shown for FG, FT is the same):

```
p̄_FG   = Σ_{j∈P} FGM_j / Σ_{j∈P} FGA_j
I_i    = FGM_i − p̄_FG · FGA_i            # volume-weighted contribution (impact)
z_i,FG = (I_i − mean_P(I)) / std_P(I)     # mean_P(I) ≈ 0 by construction
```

Check example (REQUIRED test): with `p̄ = 0.47`, player A shoots 55% on 3 FGA (1.65 FGM) and player B shoots 52% on 20 FGA (10.4 FGM). `I_A = 1.65 − 1.41 = 0.24`, `I_B = 10.4 − 9.4 = 1.00`. As a result, B's FG contribution must be larger than A's.

Edge cases:
- `σ_c < 1e-9` → `z = 0` is assigned for this category and a "category does not discriminate" warning is issued.
- `FGA = 0` → `I = 0` (valid).
- Missing stat value → the player stays out of the pool (it is not taken as 0).

#### 6.2.4 G-score (alternative)

Z-score ignores week-to-week uncertainty. G-score adds within-player variance to the denominator (Rosenof, *Improving Algorithms for Fantasy Basketball*, arXiv:2307.02188):

```
G_ic = (x_ic − μ_c) / sqrt(σ_c² + κ · τ_c²)
τ_c² = mean_{j∈P} Var_within(j, c)          # pool mean of within-player variance, on the same basis as x
```

- `Var_within` comes from the player variance model in §6.6.2: from the variance file if there is one, otherwise from the model default.
- For ratio categories, `I` and the variance of `I` are used instead of `x`.
- `κ` is configurable, default `1.0`. **The exact coefficient in the paper must be verified against the paper before implementation.** Until it is verified, the UI shows the `κ` value.
- REQUIRED test: `G == Z` when `τ = 0`.

#### 6.2.5 Weights and punt

```
V_i(w, method) = Σ_c w_c · s_ic          s ∈ {z, g}
```

- `w_c ∈ [0, 3]`, step 0.05. `w_c = 0` means that category is **punted**.
- Presets (`config/model.yaml`): `balanced`, `punt_FT`, `punt_FG`, `punt_TO`, `punt_AST`, `punt_PTS`, `punt_3PM`, `punt_FT_TO`, `punt_FG_FT`. The user can save their own preset as JSON.
- Output table: player, `V`, rank, 9 category scores, `adp_eff` (**display** only), the `value_rank − adp_eff` difference ("cheap/expensive relative to ADP"), `adp_status`.
- Principle 3: weights only change `V`. They are never passed to the matchup model (protected by a test).

### 6.3 Snake draft engine (`fdo.draft`)

#### 6.3.1 Order

```python
seat_for_pick(k, teams, third_round_reversal) -> int
picks_for_seat(seat, teams, rounds, trr) -> list[int]
turns_for_seat(seat, teams, rounds, trr) -> list[tuple[int, ...]]   # [(16,17), (48,49), ..., (208,)]
```

#### 6.3.2 Event sourcing

```python
@dataclass(frozen=True)
class DraftPick:
    overall_pick: int
    round: int
    seat: int
    player_id: str
    source: str              # user | bot:<profil> | import | manual
    observed_at: datetime

class DraftLog:              # immutable list + helpers
    append(pick) -> DraftLog
    undo() -> DraftLog
    truncate(overall_pick) -> DraftLog   # "go back to this pick"
```

`DraftState` is always **derived** from `DraftLog` (`state_from_log(log, config, dataset)`). The state contains: the current pick, the seat on the clock, the available players, every team's roster, and every team's remaining pick numbers.

Rules:
- A player can be picked only once.
- The `seat` value must be consistent with `seat_for_pick(overall_pick)`. An inconsistency during import counts as an error.
- **Position rule** (`position_limits_enforced_in_draft: true`, §3.2): a pick is invalid if it makes it impossible for the team to fill all active slots with its remaining picks (`fdo/draft/rules.py`). Since `DraftLog` does not know positions, the rule is applied in the layers that add picks to the log: user/manual picks and import (`MockDraft`), bots (mandatory in this case even if `enforce_completion_feasibility` is off), the advisor's pair filter, the π policy and scenarios. If the rule is set to `false`, it remains only as a soft/hard rule in the bots and the advisor.

Undo + replay must produce the same state (REQUIRED test). Export formats are CSV and JSON, and manifest references and seed information are included as well.

### 6.4 ADP-based opponent bots (`fdo.bots`)

#### 6.4.1 Thurstone noisy ranking

At the start of each draft (simulation), a **persistent** perceived rank is drawn for each bot `b` and each player `i`:

```
q_bi = A_i + σ_i · ε_bi,     ε_bi ~ t_ν (Student-t, scaled, variance 1)
σ_i  = min(σ_cap, sigma_mult_i · max(σ_floor, adp_std_i))     if adp_std exists
     = min(σ_cap, sigma_mult_i · (σ₀ + σ₁ · A_i))               otherwise
```

`σ_cap` was added after the first realism report: without an upper bound, σ grew without limit with ADP, and players whose ADP is far beyond the pool (`tail`, A ≈ 400–600) could be picked in the first rounds because of the t-tail. The cap is applied **after** the class multiplier: when it was applied before, on real Yahoo data hundreds of out-of-coverage players with σ = 2 × 25 = 50 reached into rounds 9–13 about ~10 times per draft, shifted players with ADP 97–160 by ~+18 picks on average, and only 44–75% of those with ADP 161–208 could get picked.

A small momentary jitter is added at each pick: `q_bi(t) = q_bi + ρ · σ_i · η_bit`, `η ~ N(0,1)`, with `ρ` small. Because most of the noise is persistent, a bot shows **consistent** preferences throughout the draft. A bot that "likes" a player keeps liking him.

The bot picks the available player with the **smallest score**:

```
score_bi(t) = q̃_bi(t) − need_bonus_b(i, t) + penalty_b(i, t)
pick       = argmin_{i ∈ Available, feasible_b(i)} score_bi(t)
```

`q̃` is the modified form of `q` according to the profile (§6.4.2).

Properties of this model:
- **Monotone:** A player who is past his ADP already has a low score, so he is picked quickly. There is no symmetric penalty (Principle 6).
- **No hard bans:** The Student-t tail (small `ν`) allows rare reaches. Their frequency is measured in §7.
- **Wide spread in late rounds:** Thanks to the `σ₁ · A_i` term, uncertainty grows with ADP.

#### 6.4.2 Profiles

| Profile | `q̃` | Additional behavior | σ multiplier |
|---|---|---|---|
| `MarketFollower` | `q` | — | 0.8 |
| `ValueHunter` | `(1−λ)·q + λ·R_b,i` | `R_b,i`: the bot's own balanced Z-value rank | 1.0 |
| `PositionAware` | `q` | Strong `need_bonus` | 1.0 |
| `PuntBuilder` | `(1−λ)·q + λ·R^punt_b,i` | After round `r_punt`, ranks by setting the weight of its roster's weakest category to 0 | 1.0 |
| `AutoDrafter` | `default_rank` if present, otherwise `A` | Represents an absent manager | 0.3 |
| `RandomHuman` | `q` | Heavier tail (smaller `ν`) | 1.5 |

`need_bonus_b(i,t)`: If the player fills one of the bot's not-yet-filled **positional active** slots (PG/SG/G/SF/PF/F/C; excluding UTIL, which accepts every position) (checked with the §6.5 assignment), the bonus is `β_need · f(round)`, where `f(round) = round / rounds`. `f` increases with the round because position needs matter less in early rounds. When UTIL was included, everyone satisfied a "need" as long as UTIL was open, so the bonus did not discriminate.

Threshold used for `penalty_b(i,t)`: the "capacity" of pure position P = the number of active slots specific to P + 1 (PG/SG/SF/PF: 2, C: 3); `β_stack` for every pure-P player beyond this number.

`penalty_b(i,t)`: If there is excessive stacking of the same pure position (e.g. C only), a soft penalty is applied (`β_stack`).

`feasible_b(i)` is a **hard** rule: after the player is added, the number of remaining picks must still be enough to complete the unfilled active slots. This rule can be turned off via `config`.

The `ValueHunter` and `PuntBuilder` profiles use projections. This does not violate Principle 1: bot *behavior* is being modeled, not value being suggested to the user.

#### 6.4.3 League composition and parameters

`config/model.yaml` (all **uncalibrated** defaults; tuned with the §7 report):

```yaml
bots:
  mix: {MarketFollower: 5, ValueHunter: 4, PositionAware: 2, PuntBuilder: 3, RandomHuman: 1, AutoDrafter: 0}   # 15 in total
  # original spec: {MarketFollower: 6, ValueHunter: 3, PositionAware: 2, PuntBuilder: 2, RandomHuman: 1, AutoDrafter: 1};
  # AutoDrafter is 0 because nobody auto-drafts in the league; the share of value- and punt-oriented profiles was increased
  seat_assignment: random_per_draft      # or fixed
  user_auto_profile: MarketFollower       # the user's seat in "play" operations
  sigma0: 1.5
  sigma1: 0.12
  sigma_floor: 1.0
  sigma_cap: 25.0         # added after the first report
  t_df: 8                 # 5 → 8 after the first report
  t_df_random_human: 5    # 3 → 5 after the first report
  jitter_rho: 0.15
  value_lambda: 0.3
  punt_lambda: 0.4
  punt_after_round: 3
  beta_need: 4.0          # in pick units
  position_aware_need_mult: 3.0
  beta_stack: 3.0
  enforce_completion_feasibility: true
  profile_sigma_mult: {MarketFollower: 0.8, ValueHunter: 1.0, PositionAware: 1.0,
                       PuntBuilder: 1.0, AutoDrafter: 0.3, RandomHuman: 1.25}   # RandomHuman 1.5 → 1.25
```

The first realism report (synthetic data, 200 mocks) with the defaults showed 8–18% implausible reaches (z > 2.5) in early rounds and cases of tail players being picked in round 1. After the three changes above (500 mocks, seed 1): early-round implausible reach ≈ 2.2–2.9%, ≤ 1% in middle–late rounds; an ADP≈90 player going in the first 16 occurred 4 times / 4500 player-mocks; Kendall τ ≈ 0.77; incomplete rosters 0.

With real Yahoo data (σ cap after the multiplier, new mix, 500 mocks, seed 1): implausible reach 2.3–3.0% in rounds 1–4, ≤ 1.7% after round 5; median `pick − A` −1.3…+1.9 in rounds 1–7, +6.5…+16.3 in rounds 8–13; an ADP≈90 player going in the first 16 occurred 2 times / 4500 player-mocks; Kendall τ ≈ 0.76; incomplete rosters 0. In the interface, the mix and seat assignment can be changed from the mock page.

*Method tried and abandoned:* a per-player location correction (`q = A + δ_i + σ·ε`; `δ_i` iterated by simulation against `median pick − A`) and a smooth `δ(A)` with one knot per round. Neither converged: since the picks are a permutation, the corrections pushed against each other and censoring (players not picked) made the differences look systematically positive. The actual cause, the large tail σ, was fixed with the cap above.

#### 6.4.4 Interface

```python
class BotLeague:
    @classmethod
    def sample(cls, dataset, config, rng) -> "BotLeague"   # persistent q_bi and profiles are drawn here
    def choose(self, seat, state, rng) -> str              # player_id
```

Vectorization: the `q` matrix is a NumPy array of shape `(15, n_players)`. With the available-player mask, `argmin` is computed in a single line.

#### 6.4.5 Opponent strategy inference (`fdo.bots.inference`)

In a real (or manually entered) draft, for each opponent pick `(k, seat b, player i)`, `M = 200` independent Thurstone
draws are made with each profile `p` in the actual state at that moment (rosters, position rule, punt status), and the
frequency `f_p` with which the bot picks `i` is measured. The likelihood is `ε + (1−ε)·f_p`
(`ε = 0.02`: tolerance for picks the model cannot explain); the posterior is `∝ prior · Π likelihood`, and the prior is the league's
bot mix. The computation is incremental (~40 ms per new pick; rebuilt from scratch on undo). Possible punt:
if the weakest category in the balanced z total of the seat's roster is ≥ 1.5 behind the second-weakest.

When it is enabled in the advisor (on by default in "Canlı Draft" (Live Draft)), the profiles of the opponent seats in the simulations are drawn from this
posterior instead of the mix: the conditional fill table, the rollout and the full horizon.

Measurement (real Yahoo data, 6 drafts played by bots = 90 opponent seats, profiles known):

| Round | Most likely profile correct | Probability of the true profile (prior 0.24) |
|---|---|---|
| 4 | 58% | 0.51 |
| 7 | 70% | 0.61 |
| 13 | 68% | 0.64 |

Survival effect (12 drafts, Brier for the top 60 available players by ADP over the 48→80, 80→112, 112→144 horizons):
mix 0.094 / 0.124 / 0.155, inference 0.093 / 0.125 / 0.156 — **no difference** (within noise). Among bots,
survival probability is determined more by each seat's persistent personal noise than by profile identity, and that
cannot be inferred from observation. If real managers behave more extremely across profiles (hard punts, position
hoarding), the effect could grow; this cannot be verified without a real draft log. Since inference does no harm and
simulates the future development of opponent rosters (and therefore ECW) according to strategy, it is left on.
No LLM is used: the likelihood can be computed directly from the bot model; an LLM would add latency and
non-reproducibility within the 45 s pick timer.

### 6.5 Team composition and position eligibility (`fdo.roster`)

```python
parse_positions("PG,SG") -> frozenset({"PG", "SG"})
eligible_slots(positions, slot_eligibility) -> set[Slot]
best_assignment(roster: list[PlayerId]) -> Assignment       # fill the active slots as much as possible
open_active_slots(roster) -> Counter[Slot]
can_complete(roster, n_remaining_picks, available_pool) -> bool
```

- The assignment is a bipartite matching problem. Rows are players, columns are slot instances (PG, SG, G, SF, PF, F, C₁, C₂, UTIL₁, UTIL₂, BN₁₋₃). Ineligible cells get a large cost. An active slot's cost is lower than a bench slot's cost. It is solved with `scipy.optimize.linear_sum_assignment`.
- So that specific slots fill first, the cost order is: specific (PG/SG/SF/PF/C) < flexible (G/F) < UTIL < BN.
- `can_complete`: checks that the remaining picks can fill the missing active slots with at least one eligible player type. In V1 it does not check whether the pool has enough players of that position; only numeric sufficiency is checked.

### 6.6 Matchup evaluation (`fdo.matchup`)

The matchup model reads only the projections and the optional variance file. **It does not read the category weights.**

#### 6.6.1 Unit: a one-week matchup

```yaml
matchup:
  games_per_week: 3.5          # average; schedule is V2. Assumption.
  utilization: 0.98            # share of played games counted in an active slot (lineup_lock = daily_today)
  games_cap: 82
```

For player `i`:

```
a_i = min(projected_gp_i, 82) / 82               # availability
k_i = utilization · games_per_week · a_i          # expected counted games per week
```

`utilization` was estimated with `scripts/estimate_utilization.py`: 480 mock rosters (13 players, 10 active slots with position eligibility); each day, the players who play that day are placed optimally into the active slots.

| lineup_lock | 2026-27 NBA schedule (24 matchup weeks) | Hypothetical schedule (Mon–Sun 8/6/9/5/8/6/7 games, σ = 3) |
|---|---|---|
| daily_today | **0.987** (used) | 0.982 |
| daily_tomorrow | 0.971 | 0.961 |
| weekly | 0.821 | 0.864 |

The loss comes almost entirely from crowded nights. Streaming/replacement pickups using IL slots are not modeled.

#### 6.6.2 Player weekly mean and variance

For counting stat `s` (fg3m, pts, reb, ast, stl, blk, tov, plus fgm, fga, ftm, fta):

```
m_is  = k_i · x_is                                  # weekly mean
v_is  = per_game_var_is                             # if there is a variance file
      = φ_s · x_is                                  # otherwise: overdispersed Poisson default
s²_is = k_i · v_is                                  # weekly variance
```

The default `φ_s` is `1.0` and is **uncalibrated**. It will be calibrated with nba_api game logs in V2. Randomness in the number of games is ignored in V1 (§12).

Ratio categories (FG shown). For per-game `p_i = FGM_i/FGA_i`, `Y = FGM − r·FGA` is defined relative to a reference rate `r`:

```
Var_game(Y_i) = FGA_i · p_i (1 − p_i)  +  (p_i − r)² · v_i,FGA       # binomial shooting + volume variance
E_week(Y_i)   = k_i · (FGM_i − r · FGA_i)
Var_week(Y_i) = k_i · Var_game(Y_i)
```

#### 6.6.3 Team totals and win probability

Team `A` is compared with `B`. All players on the roster (including fill profiles, §6.6.4) are summed.

Counting categories (excluding TO):

```
D = M_A − M_B,   Var(D) = S²_A + S²_B
P(A wins) = Φ( E[D] / sqrt(Var(D)) )
```

For TO the sign is reversed: `P = Φ((M_B − M_A) / sqrt(S²_A + S²_B))`.

Ratio categories: `r = (ΣFGM_A + ΣFGM_B) / (ΣFGA_A + ΣFGA_B)` (expected pooled rate). `Y_A − Y_B > 0` if and only if A's FG% is greater than B's. Therefore:

```
P(A wins FG) ≈ Φ( (E[Y_A] − E[Y_B]) / sqrt(Var(Y_A) + Var(Y_B)) )
```

Ties: under the Normal approximation `P(tie) = 0`. `tie_value` is used in V2's discrete Monte Carlo evaluator.

If `Var(D) = 0` (only in degenerate tests): `E[D] > 0 → 1`, `< 0 → 0`, `= 0 → 0.5`.

#### 6.6.4 Effect of incomplete rosters (fill profiles)

In the middle of a draft, every team's roster is incomplete. For each remaining pick `n` of team `t`, a **fill profile** `F(n)` is added. `F(n)` is the weekly mean and variance vector of the player expected to be picked at pick number `n`.

- **Base table:** `M_fill` (default 200) full bot drafts are simulated from the starting state. For each pick number, the weekly stat means and the variance means of the players picked are taken. The result is smoothed with a `±w` (default 5) window. The table is cached by `(dataset_hash, config_hash)`.
- **Conditional update (RECOMMENDED):** When it is the user's turn, the table is recomputed from the current state with `M_fill_cond` (default 100) fast simulations. This takes into account players who fell or went early.
- The fill profile is **neutral**. It does not model the future punt tendencies of the opponents or the user (§12).
- Every ECW output shows the "real players / fill" ratio. For example, if it is `2/13 gerçek` (2/13 real), the UI shows an uncertainty warning.

#### 6.6.5 ECW

```
ECW(A vs j) = Σ_c P_c(A, j)                      # expected category wins, between 0 and 9
ECW(A)      = (1/15) · Σ_{j≠A} ECW(A vs j)       # season-long random-opponent assumption
```

Because expectation is linear, ECW **does not require** independence between categories. `P(≥5 categories)` is given only as an extra indicator. That indicator relies on an independence assumption and is shown with an `assumes_independence` badge. It is not used in any optimization.

Outputs:
- `ecw_matrix`: P values of shape 16 × 15 × 9.
- A team × category table of mean P.
- For the user's team, a per-category "winnable / borderline / lost" classification. Thresholds: `P ≥ 0.6`, `0.4–0.6`, `≤ 0.4`.

Marginal value:

```
ΔECW(i | R) = ECW(R ∪ {i}) − ECW(R ∪ {F(n_i)})
```

Here the player is compared with the **fill profile** at the same pick, not with an empty slot. This avoids the "everyone is positive" illusion in early rounds.

Performance: all P calculations are vectorized over shape `(candidates × opponents × categories)`. `scipy.special.ndtr` is used.

### 6.7 Pair recommendation and Monte Carlo lookahead (`fdo.advisor`)

The advisor optimizes only ECW. Z and G are not used here except for candidate pre-screening.

#### 6.7.1 Simulation core and Common Random Numbers

```python
simulate_until(state, until_pick, bot_league_samples, rng_streams) -> list[DraftState]
```

- `S` simulations are run. For each simulation `s`, a `BotLeague` sample (persistent `q_bi` noise) and an RNG stream are drawn once.
- **CRN:** Different candidate pairs are evaluated with the **same** `S` bot samples. The only difference between pairs is the two players removed from the pool. This sharply reduces the variance in pair comparisons.
- Seed hierarchy: `master_seed → (simulation s) → (pick)`. The same seed gives the same result.

#### 6.7.2 Survival probability

```
P_surv(i, n | state, picks_to_take) = (1/S) · Σ_s 1[i is still available at pick n in simulation s]
SE = sqrt(P(1−P) / S)
```

Extra output: the distribution of the pick at which the player goes (median, P10, P90). Survival is always **conditional**. The information "if {a, b} are taken at 16/17" goes into the simulation, because removing a and b from the pool changes the bots' picks.

#### 6.7.3 Pair suggestion algorithm (V1)

This algorithm runs for the user's current turn `(t₁, t₂)` (e.g. 16/17) and next turn `(u₁, u₂)` (e.g. 48/49). Single-pick turns (208, or 33 with 3RR) are the 1-element form of the same algorithm.

```
1. Candidate set C:
     top K₁ (20) by ΔECW
   ∪ ADP urgency: those with P_surv(next turn) < 0.5 and ΔECW within the top K₂ (35)
   ∪ players pinned by the user
   (duplicates removed, |C| ≤ 25)

2. Pairs: unordered 2-combinations from C (≤ 300).
   Pairs that make the roster uncompletable are eliminated (§6.5).

3. Quick score (static):
     Q(a,b) = ECW(R ∪ {a, b} ∪ fill) − ECW(R ∪ fill)
   The top M pairs (30) and pinned pairs move on to the next stage.

4. Rollout (S simulations per pair with CRN, default 500):
     a, b are removed from the pool
     opponent picks are simulated up to u₁ (30 picks between 16/17 → 48/49)
     the user's "next pair" policy π is applied to the available pool at u₁:
        π = the pair that maximizes ECW among the top L (12) players by ΔECW in the pool (myopic)
     Value:
        W_s(a,b) = ECW( R ∪ {a, b} ∪ π_s ∪ fill_{after u₂},
                        opponents: their rosters in the simulation ∪ fill )

5. Result per pair:
     E[W], P10, P50, P90, SE
     regret: E[W] difference from the best pair ± CRN-paired SE
```

Ranking is by `E[W]`. Pairs that are statistically indistinguishable (difference < 2·SE_diff) are shown in the same "tier". This is to avoid showing false certainty.

If `R` is empty (the 16/17 situation), the steps are the same. At 48/49 `R` is populated and the next turn is 80/81. The method is the same at every turn.

#### 6.7.4 The "48/49 pool" output (V1's main screen)

For each selected candidate pair, the following are shown:

1. **Availability table:** the top 30 players by ΔECW at the moment of `u₁`. For each: `P_surv(u₁ | a,b)`, SE, `adp_eff`, `adp_status` and the distribution of the "expected pick at which he goes".
2. **Tier view:** players are split into ΔECW tiers. For each tier, the **expected number of available players** at 48 and the probability that "at least 1 / at least 2 players from the tier remain" are given.
3. **Next-pair distribution:** a frequency table of the pairs chosen by π (top 10) and the probability of each.
4. **Category profile:** after 4 picks (including fill), the mean P(win) and P10–P90 band for each category.
5. **Comparison mode:** two candidate pairs are shown side by side. Availability differences and category profile differences are presented.
6. **Cost of waiting** (a simple per-player indicator):
   ```
   wait_cost_i = ΔECW_i · (1 − P_surv(i, u₁))
   ```
   A high value means "take now", a low value means "can wait". It is for explanation only; the decision is made by `E[W]`.

Every suggestion card includes: the projection and ADP sources used with their `as_of` dates, the seed, `S`, the computation time, and `uncalibrated` badges.

#### 6.7.5 Alternative roster scenarios (light, M6)

A full-draft rollout (`S_full`, default 200) works like this: the user applies the π policy at every turn and the bots play. Final rosters are grouped by their "lost-category signature" (the set of categories with P < 0.4). Output: the 3–5 most frequent archetypes (such as "punt FT+TO-like"). For each archetype, the frequency, mean ECW and a typical roster list are shown. This is a *reachability* indicator. It makes no claim to be an optimal plan.

#### 6.7.6 Parameters (`config/model.yaml`)

```yaml
advisor:
  k1_top_ecw: 20
  k2_urgency_pool: 35
  max_candidates: 25
  m_pairs_to_rollout: 30
  sims_per_pair: 500        # fast mode: 200
  next_policy_top_l: 12
  fill_sims_base: 200
  fill_sims_conditional: 100
  fill_smoothing_window: 5
  scenario_full_sims: 200
```

---

## 7. Measuring simulation realism

The `scripts/run_mock_batch.py --n 500 --seed 1` command produces full mocks and `realism/report.py` generates a report (Markdown and tables). Bot parameters are tuned **only** through this report.

| Metric | Definition | Target / interpretation |
|---|---|---|
| `pick − A` distribution by round | Median, P10, P90 | Median ≈ around 0; the spread grows as rounds advance |
| Reach score | `z_reach = (A_i − pick) / σ_i` | Picks with `z_reach > 2.5` count as an "implausible reach" |
| Implausible reach rate | Percentage of picks with `z_reach > 2.5` per round | Very low in early rounds (< 2%, assumed target), not zero |
| Extreme reach example | How often an ADP≈90 player goes in the first 16 | ≈ 0 in practice but > 0 (no hard ban) |
| Slide rate | `pick − A > 2.5·σ` | Reported |
| Mock diversity | Jaccard similarity of the first-32-pick set across mocks, Kendall τ | Mocks must not be copies of each other (τ < 0.98, assumed target) |
| Position distribution | Position shares per round; number of incomplete rosters at round 13 | Incomplete rosters = 0 (with feasibility on) |
| Bot consistency | Stability of the same bot's preference ranking within a mock | Reported |
| External comparison (optional) | KS test against the `pick − A` distribution if a real draft log exists (e.g. a mock CSV downloaded by the user) | Calibration input in V2 |

The target values are **not verified** against real data. They are revisited together with the first report. Without a real draft log, no claim is made that "the bots pick like Yahoo humans".

**Visibility during a mock:**
- On the draft board, each cell is colored by `z_reach`: neutral, yellow (1.5–2.5), red (> 2.5). Slides are shown in a blue tone.
- The pick log has reach and slide badges.
- The user's own picks are judged by the same measure ("this pick is 2.1σ early relative to ADP").

---

## 8. Streamlit interface

A single app with multiple pages (`st.navigation` or `pages/`). State is kept in `st.session_state`: `dataset`, `config`, `draft_log`, `seed`, `weights`. Heavy computations are cached by the key `(dataset_hash, config_hash, state_hash, seed, params)` (advisor results live in the session state: since the progress bar is updated during computation, `st.cache_*` raises a replay error).

| Page | Content |
|---|---|
| **"Draft Analizi" (Draft Analysis)** | Kept open in a side tab (§13.10): the suggestion computed in the background, suggested pairs, color-coded player board, punt suggestion, opponent strategies |
| **1. League & Data** | View/edit the league config (finalized fields locked, unverified fields with warnings); CSV upload, column mapping, validation report, manifest status; generate-synthetic-data button; `adp_status` distribution; V2: schedule upload and week summary |
| **2. Projection Explorer** | Player table: Z/G choice, `per_game`/`total`, 9 category scores, `V`, rank, `adp_eff` and `value_rank − ADP`, `adp_status`, positions; weight sliders and presets; pool size (180/208/240) sensitivity; filter and search |
| **3. Mock Draft** | 16×13 board; seed; bot mix; "sıradaki pick'i oynat" (play the next pick), "kullanıcıya kadar oynat" (play until the user), "sona kadar oynat" (play to the end); manual pick (search); undo, "pick k'ye dön" (go back to pick k), replay; CSV/JSON export and import; reach colors |
| **4. Draft Assistant** | When it is the user's turn: candidate pair table (E[W], P10–P90, SE, tier); the **48/49 pool** for the selected pair (§6.7.4); comparison of two pairs; cost of waiting; computation parameters and time; "hızlı / tam" (fast / full) mode; V2: full-horizon deep analysis, injury/role uncertainty box, opponent strategy inference, strategy weights (your own punt), punt plan comparison |
| **5. Team Dashboard** | 16 teams × 9 categories mean P(win); user vs each opponent matrix; winnable/borderline/lost categories; real/fill ratio; team FG%/FT% computed from totals; V2: if a schedule is loaded, the roster's weekly games / counted games table |
| **6. Realism Report** | §7 metrics: latest mock and batch report; histograms; implausible reach list |
| **"7. Canlı Draft" (Live Draft)** | Manually tracking the real draft (§8.1): pick entry from a single box, automatic suggestion, opponent strategy table, automatic saving |

UI rules:
- The synthetic data banner (§5.7) and `uncalibrated` badges (Principle 10) are always shown.
- Probabilities are shown with SE, for example `%62 ± 2`. For values coming from an uncalibrated model, the "≈" sign is used.
- While the advisor computation runs, progress is shown with `st.status`. Long computations can be cancelled.
- In a mock, the advisor can be computed **in advance** while opponent picks are being played (optional). The RECOMMENDED approach in V1 is to compute when it is the user's turn; fast mode is the default.

### 8.1 Live draft (Page 7)

Since the Yahoo API cannot be used (§13.7), the real draft is tracked manually in the simulator:

- "Yeni canlı draft başlat" (Start new live draft) → bot playing is turned off (the play buttons in Mock Draft and Draft Assistant
  are disabled). The team on the clock, the round and the next 5 picks are shown; team names are entered from the sidebar.
- Pick entry is a single box: type the player's name and press Enter → the pick is recorded (sorted by ADP; players who violate
  Yahoo's position rule are not in the list). Undo is available.
- The analysis is on the **"Draft Analizi" (Draft Analysis)** page in a side tab (§13.10): each pick is published to the background worker;
  when it is the user's turn, a fast-mode and then a full-mode suggestion is computed with opponent strategy inference.
  The draft page shows only a one-line suggestion summary. The details (pool, comparison, full horizon)
  are in "Detaylı Advisor" (Detailed Advisor).
- The log is written to `data/live/live_draft.json` on every pick (outside git); if the page is refreshed or the app
  is closed, it continues via "Kayıtlı canlı draft'a devam et" (Continue saved live draft).

---

## 9. Testing strategy

`pytest`, seeded and deterministic. Statistical tests run with a fixed seed and tolerance. Crude (flaky) thresholds are avoided and the tolerance is documented in each test.

### 9.1 Unit tests (REQUIRED)

**ingest**
- A missing required column produces an error.
- `fgm > fga` produces an error. `fga = 0` is accepted.
- A duplicate `player_id` produces an error.
- A synthetic + real mix produces an error.
- Without a manifest, the file is not loaded.
- When ADP is empty, `imputed` is assigned. When `pct_drafted` is low, `low_confidence` is assigned and the blending formula works correctly.
- The isotonic mapping is monotone.
- Name normalization: accented and unaccented spellings match. An ambiguous match produces an error.

**valuation**
- TOV: fewer TO gets a higher score.
- The FG volume example in §6.2.3.
- `Σ I_i ≈ 0` over the pool.
- With `σ = 0` there is no crash and a warning is issued.
- The pool iteration stops in ≤ 10 steps.
- `G == Z` when `τ = 0`.
- `w_c = 0` → `V` becomes independent of that category (`V` does not change when the category value is changed).
- Changing weights does not change the pool statistics.

**draft**
- 208 unique picks.
- An exact match of the two tables in §3.3 (3RR off/on).
- `turns_for_seat` returns the correct pairs and single picks.
- State equality after undo + replay.
- Import with an inconsistent seat produces an error.
- Picking the same player twice produces an error.

**roster**
- 2 C slots: in a roster with 3 Cs, one goes to UTIL or BN.
- The G slot accepts PG and does not accept C.
- A multi-position player is assigned to the correct slot.
- `can_complete` catches an uncompletable roster.

**matchup**
- Two identical teams → `P = 0.5` in every category, `ECW = 4.5`.
- Adding a player with a positive contribution to a team increases `P` in that category (monotonicity).
- TO direction: the team with more TO has `P < 0.5` in the TO category.
- Ratio: at equal volume, a higher percentage gives `P > 0.5`.
- Volume: adding a high-volume 42% shooter to a 50% team lowers FG `P`.
- **Punt independence:** ECW does not change when the category weights change.
- The degenerate `Var(D) = 0` case is handled correctly.
- ECW is averaged over 15 opponents.

**bots**
- **Monotonicity (Principle 6):** If a player with ADP 20 is available at pick 50, the rate at which he is picked within the next 3 picks (1000 simulations) must be ≥ 90% (with default parameters).
- **Tail:** The rate at which an ADP≈90 player goes in the first 16 picks must be > 0 and < 1% (10,000 simulations).
- **Consistency:** Within the same draft, a bot's perceived ranking must be highly correlated across picks (small `jitter_rho`).
- In the `σ → 0` limit, bots follow the ADP order exactly.
- With feasibility on, all rosters must be completable at the end of round 13.
- The same seed produces the same draft.

**advisor**
- With deterministic ADP (`σ → 0`), survival values are 0/1 and match the expected result.
- **Toy problem:** Of players X and Y with equal ΔECW, X is certain to last until 48 and Y certainly will not → the suggestion is to take Y now.
- Pairs are unordered: (a,b) ≡ (b,a).
- CRN: the same seed gives the same E[W]. When the same pair is evaluated twice, the difference is 0.
- SE shrinks roughly as `1/√S` as `S` grows.
- A single-pick turn (208) works correctly through the 1-element path.

### 9.2 Integration tests
- End to end with synthetic data: load → value → full mock → advisor (fast mode) → export → import → same state.
- End to end with the 3RR-on configuration.

### 9.3 Architecture test (`test_architecture.py`)
- The `fdo.valuation` and `fdo.matchup` modules do not access the `adp` table or `fdo.bots` (import scan via AST).
- There is no `streamlit` import outside `ui/`.

### 9.4 Measurement, not testing
The §7 realism report and the §11 timing measurements are **reported** in CI, but are not used as test thresholds. Exception: the bot monotonicity and tail tests in §9.1.

---

## 10. Milestones and acceptance criteria

Each milestone works independently and passes its tests. The next milestone does not break the previous one.

### M0 — Data foundation
- [x] Repo skeleton, `pyproject.toml`, `config/league.yaml`, `config/model.yaml`
- [x] Schemas, loader, column mapping, validation report, mandatory manifests
- [x] Synthetic data generator and the synthetic banner policy
- [x] ADP confidence classes and imputation
- [x] §9.1 ingest tests
- [ ] **User action:** decide on the real projection and ADP source, fill in the manifests (§5.1 table)

### M1 — Projection Explorer
- [x] Pool iteration, Z, volume-weighted FG/FT, G (κ labeled), weights and presets
- [x] Pages 1 and 2
- [x] §9.1 valuation tests

### M2 — Snake engine and manual draft board
- [x] Order, turns, event log, undo/replay, import/export
- [x] Roster eligibility and assignment
- [x] Page 3 (manual picks only)
- [x] §9.1 draft and roster tests

### M3 — Thurstone bots and mock simulator
- [x] `BotLeague`, profiles, feasibility
- [x] Bot playing and reach colors on page 3
- [x] `run_mock_batch.py` and page 6 (realism report)
- [x] §9.1 bot tests, the first realism report and a parameter review based on it

### M4 — Matchup model
- [x] Player weekly mean/variance, team totals, P(win), ECW
- [x] Fill profiles (base and conditional)
- [x] Page 5
- [x] §9.1 matchup tests

### M5 — Pair advisor and the 48/49 pool (V1's main goal)
- [x] CRN simulation core, survival, candidate generation, pair scoring, rollout
- [x] Page 4: pair table, 48/49 pool, comparison, cost of waiting
- [x] §9.1 advisor tests, §11 timing measurement
- [x] **Acceptance:** With synthetic data, for at least 5 candidate pairs at 16/17, the availability probabilities at 48/49 are displayed together with their SE. Two pairs can be compared side by side. The result is reproducible with the same seed.

### M6 — Alternative roster scenarios (light)
- [x] Full rollout, archetype grouping, added to page 4 as a tab

---

## 11. Performance budgets

The targets are for an ordinary laptop and **will be verified by measurement**. `scripts/profile_advisor.py` is run at every milestone and reports the results.

| Operation | Target | Measured (Windows laptop, real Yahoo data, 508 players) |
|---|---|---|
| Valuation (600 players, weight change) | < 0.5 s | 0.03 s |
| Single full mock (208 picks, 15 bots) | < 0.2 s | 0.08 s |
| 500-mock batch | < 90 s | 16 s |
| Fill table (200 mocks) | < 40 s (cached) | 6 s |
| Advisor fast mode (`S = 200`, 30 pairs) | < 15 s | 8–12 s (16/17 and 48/49) |
| Advisor full mode (`S = 500`, 30 pairs) | < 45 s | 21–36 s |
| V2 full horizon (8 pairs, successive halving 40/40/80) | < 45 s | ~15 s (pick 16) |

On real data the first measurements exceeded the budget (single mock 0.52 s, fast mode 16–26 s). Cause: players with 3 positions create 12 position groups, and the bot roster analysis was solving `linear_sum_assignment` in every state. The bot analysis was converted to a capacitated matching at the group × slot type level (`GroupFlow`); the question "does this player reduce the empty slots" is now answered from a single matching via residual-graph reachability (equivalence with the old solver is protected by a test). CI reports this measurement on every push.

If a target is exceeded, the following are applied in order: (1) the ECW evaluation is vectorized, (2) the number of candidates and pairs is reduced, (3) successive halving is used: bad pairs are first eliminated with `S = 100`, and `S` is increased for the rest. Once the Yahoo pick timer (§3.2) is known, the full-mode budget is adjusted accordingly.

---

## 12. Known limitations and open questions

### 12.1 Model limitations (deliberately accepted in V1)
- **Normal approximation:** In low-count categories such as STL/BLK, the weekly distribution is skewed and discrete. Ties are ignored.
- **Number of games** is fixed if there is no schedule (`games_per_week`); if a schedule is loaded, it is the team average (§13.4). Variance is optional and there is no covariance between players.
- **Variance parameters (`φ`) are uncalibrated.** For ratio categories, the binomial term is structurally correct. The volume variance, however, is an assumption.
- **Utilization is a single coefficient** (in the advisor). The daily lineup solver is used in the Team Dashboard, the utilization estimate and the backtest (§13.4).
- **Fill profiles are neutral.** They do not model the punt tendencies of opponents or the user.
- **The next-pair policy is myopic** (π). In V1, everything after 49 is represented by fill profiles; the V2 full-horizon mode plays the draft to the end with a greedy ECW π (§13.3).
- **Bot σ₁ was calibrated with 11 real Yahoo draft logs** (§13.6, 14-team mocks/league); the profile mix and the late-round location shift were not calibrated, and the probabilities keep the `uncalibrated` label.
- **Positive shift in the median of `pick − A` in late rounds.** Reaches add a left tail to the `pick − A` distribution; the median is therefore larger than the mean. On real Yahoo data the remaining shift is +6.5…+16.3 in rounds 8–13 (+17…+26 before the σ cap was moved after the multiplier). Players with ADP in the 97–160 band go a few picks after their ADP on average; survival probabilities in this region may be slightly optimistic. Per-player location calibration was tried and did not converge (§6.4.3); calibration with real draft logs is in V2.
- **ADP comes mostly from 10/12-team leagues.** Uncertainty is high in the late rounds of a 16-team league.
- **Season-long random-opponent assumption:** The real H2H schedule and playoff weeks are ignored.

### 12.2 Open questions for the user to verify
1. ~~Category tie rule~~ — answered: a category tie is recorded as T (W-L-T), `tie_value: 0.5`.
2. ~~Draft pick timer~~ — answered: 45 s (advisor budget for the real draft only; no timer in mocks).
3. ~~Whether Yahoo enforces position limits during the draft~~ — answered: it does (§6.3.2).
4. Lineup lock rule, IL/IL+ slots. **Answered (13 October 2026):** daily_today → `utilization` 0.987 (§6.6.1); 3 IL (not filled in the draft), no IL+; NA is not drafted, O/Q have no effect (§5.8).
5. ~~Terms of use of the projection source~~ — user decision: the Yahoo pages are public, personal use (`personal_use_confirmed`).
6. ~~Columns of the ADP source~~ — Yahoo Draft Analysis: has `% drafted` and preseason / all / last 7 days ADP; no std or min/max. ADP covers at most up to about pick 123 (§5.6 `after_coverage`).
7. ~~Auto-drafting manager~~ — answered: none, `AutoDrafter: 0`.
8. ~~Fantasy playoffs and combined weeks~~ — answered: playoffs are the last 3 weeks; only the All-Star week is combined (§13.4).
9. ~~NBA schedule and game logs~~ — user decision: personal use (`personal_use_confirmed`).
10. ~~Yahoo API~~ — user decision: API approval cannot be obtained for individual use; no live sync, picks are entered manually in the real draft.
11. ~~Real draft logs~~ — 10 mocks + 1 real league draft (14 teams) were added; σ₁ 0.12 → 0.18 (§13.6).

### 12.3 Unverified technical claims
- The exact coefficient (`κ`) in the G-score denominator. To be verified against the paper.
- That Yahoo autodraft uses the default ranking. Unverified; the AutoDrafter profile relies on this assumption (not used in this league).
- The exact definition of Yahoo's position rule. The interpretation "a pick is rejected if the active slots cannot be filled with the remaining picks" is applied.
- The realism target values in §7 are assumptions.

---

## 13. V2

Six items of the V2 roadmap have been implemented; the seventh (Yahoo API live sync) was not done, by the user's
decision (§13.7). The parts that need external data (schedule, game logs, draft logs) are **file
based**: the data is downloaded with scripts and loaded with a manifest (§5.1–5.2). `load_data_dir` loads the
`variance*.csv` and `schedule*.csv` files in a data directory together with the data set (in the UI, the
"Diskten yükle" (Load from disk) tab also suggests them).

### 13.1 Backtest (`fdo.evaluation`)

The `SeasonEvaluator` protocol has two implementations; both score **all-play** (each week
every team is compared with the other 15 teams category by category, ties are `tie_value`).
`category_wins[seat]` is the average number of category wins per matchup (0–9, the same scale as ECW).

- `ProjectionNoiseEvaluator`: the realized season is simulated. A player's actual per-game production is
  `projection × exp(σ·z − σ²/2)` (`--projection-sd`, default 0.12), the games ratio is Beta(κ = 8),
  and weekly totals are drawn with a normal approximation. **It is optimistic** (the projection error comes from the model)
  and this note is written into the report.
- `GameLogEvaluator`: realized game records; fantasy weeks via `assign_weeks`, and each day the players who play
  are placed into active slots by the daily lineup solver (§13.4); only counted games are summed.

Strategies (`fdo.evaluation.backtest`): `adp` (lowest ADP), `z` / `g` (balanced Z / G), `ecw`
(the V1 advisor's best pick, with fast settings). For each draft `d`, all strategies see the same bot
noise and the same realized season (CRN); the report gives the average category wins, league rank,
top-3 rate and the paired difference relative to `adp`.

```bash
python scripts/backtest.py --data data/real/ --n 30 --strategies adp,z,g,ecw
```

Measurement (real Yahoo data + 2026-27 schedule + calibrated variance, `noise`, 12 drafts, seat 16, 58 s; small sample):

| Strategy | Category wins per matchup | SE | Average rank (16) | Top 3 |
|---|---|---|---|---|
| ecw | 5.29 | 0.10 | 3.4 | 75% |
| g | 5.13 | 0.12 | 4.3 | 42% |
| z | 5.03 | 0.17 | 5.7 | 42% |
| adp | 4.60 | 0.15 | 8.1 | 8% |

Paired difference relative to `adp`: ecw +0.69 ± 0.18, g +0.53 ± 0.20, z +0.43 ± 0.23. Since the realized season
is projection + noise, these differences are optimistic (a strategy that uses the projection well is rewarded).
The first backtest exposed a bug where the advisor found no valid pair at all in late rounds (the candidate
set ignored the position rule); the candidate set is now built from players who satisfy the rule, and if there is no valid
pair it is expanded with the best players from each position group.

**The data problem persists:** there are no preseason projection/ADP snapshots for past seasons. So
the `gamelogs` evaluator is only meaningful with this data set at the end of the current season
(with that season's logs).

### 13.2 Variance calibration (`fdo.calibration.variance`)

The input is the `gamelogs` schema (§5.3). `scripts/fetch_gamelogs_nba_api.py` downloads a season with `nba_api`
(optional dependency `.[nba]`; the license decision is written to the manifest with `--license-status`).
`scripts/calibrate_variance.py` (one or more seasons):

- `φ_s` = the median of the per-player `s²/μ` ratios (≥ `min_games` games),
- player variance: the ratio is shrunk toward `φ_s`, `d̂ = ((n−1)·d + n₀·φ_s)/(n−1+n₀)`, and scaled by the projection
  mean (`Var = d̂ · μ_proj`; adapts to the player's new role) → `variance` CSV + manifest,
- category correlation: the pooled correlation of within-player standardized game residuals
  (ratio categories `makes − p̄·att`, TOV reversed) → a YAML fragment for `model.variance.category_corr`.

The correlation is used only in the **P(≥5 categories)** indicator (Gaussian copula: `z ~ N(0, R)`,
a category is won ⇔ `z_c < Φ⁻¹(p_c)`; the marginals are preserved). Since ECW is an expectation, it is not affected
by the correlation. Without a correlation, the indicator carries the `assumes_independence` badge.

```bash
python scripts/fetch_gamelogs_nba_api.py --season 2024-25 --license-status personal_use_confirmed
python scripts/fetch_gamelogs_nba_api.py --season 2025-26 --license-status personal_use_confirmed
python scripts/calibrate_variance.py --gamelogs data/real/gamelogs_nba_2024-25.csv data/real/gamelogs_nba_2025-26.csv
python scripts/mark_rookies.py --gamelogs data/real/gamelogs_nba_2024-25.csv data/real/gamelogs_nba_2025-26.csv
```

**Real data (13 October 2026):** 2024-25 + 2025-26, 596 players, 46,858 games (90 players who do not match
the player file — retired/overseas — were dropped). `data/real/variance_nba_2024-25_nba_2025-26.csv`
is loaded together with the data set; `φ` and the correlation are in `config/model.yaml`:

| stat | fgm | fga | ftm | fta | fg3m | pts | reb | ast | stl | blk | tov |
|---|---|---|---|---|---|---|---|---|---|---|---|
| φ | 1.37 | 1.65 | 1.95 | 2.19 | 1.18 | 3.46 | 1.40 | 1.27 | 1.08 | 1.07 | 1.07 |

The V1 default was φ = 1 (Poisson); PTS and free-throw volume are clearly overdispersed. The strongest
category correlations: PTS–3PM 0.67, PTS–FG% 0.60, 3PM–FG% 0.40, REB–PTS 0.31; TOV (in the winning
direction) is negative with the other counting categories (−0.08…−0.16). Players without a variance file entry (rookies)
get `φ · μ`.

**Rookie flag:** `scripts/mark_rookies.py` flags players with no NBA games in the last two seasons
via `players.is_rookie` (139 players, 34 in the draft pool; 2026 draft class: Boozer,
Dybantsa, Wilson, Peterson…). They get wider uncertainty in the scenarios (§13.5).

### 13.3 Deep lookahead (`fdo.advisor.deep`)

**Full-horizon rollout.** V1 represents everything after the next turn with fill profiles. In full-horizon
mode, each candidate pair is simulated to the end of the draft: at each of the user's subsequent picks, π
chooses, among the players who are available in that simulation and leave the roster completable, the one that maximizes
`ECW(current roster + i + fill for the remaining picks)` (the shortlist is rebuilt at every pick
by ΔECW, `deep_shortlist_k`). `W` is computed with the 13 real players of each of the 16 teams.
Since π optimizes ECW against the roster at every pick, punt/balance decisions emerge on their own
(the simulation counterpart of H-score's idea that "future picks adapt to the roster").

**Successive halving.** The top `deep_pairs` (8) pairs of the V1 ranking are evaluated step by step with `deep_rungs` (40, 40, 80) new
simulations; at each rung the best half (at least 2) continues. New
simulations are added with `sim_offset`: earlier simulations are not recomputed and CRN is preserved.

On real Yahoo data (Windows laptop): ~15 s at pick 16; it gets shorter as the draft progresses (a few seconds at pick 144).
The ranking can differ from V1 (pick 16 example: V1's top pair dropped to 5th place in the full horizon).
It is run from the "Derin analiz" (Deep analysis) section in Draft Assistant.

**Not implemented:** beam search (π already does a full search over a shortlist at every turn) and
H-score's closed-form weight optimization.

### 13.4 Schedule and daily lineup (`fdo.schedule`)

- `schedule` schema (§5.3); `scripts/fetch_nba_schedule.py` converts the NBA schedule JSON into regular-season
  games (`--download` or `--input`). Since cdn.nba.com returns 403 from this network, it falls back to the
  stats.nba.com `scheduleleaguev2` endpoint (nba_api), which has the same structure. Games whose teams are not yet known
  (NBA Cup knockout round) are skipped.
- A fantasy week starts on `schedule.week_start` (Monday); `schedule.merge_with_next` lists
  the merged weeks. The last `unverified.playoff_weeks` weeks are the playoffs.
- **2026-27 (retrieved 13 October 2026):** 1,200 games, 24 matchup weeks (20 October – 11 April). The All-Star
  break is 19–24 February 2027 → week 18 is merged with week 19 (15–28 February, an average of 4.1
  games per team). Playoffs: weeks 22–24 (22 March – 11 April). The NBA Cup knockout round and the ~30 games tied to it (2 per
  team) are not in the schedule yet: weeks 7–8 (30 November – 13 December) are counted as incomplete; the schedule should be
  fetched again in mid-December.
- If a schedule is loaded, a player's expected games per week is his team's average per matchup
  instead of the fixed `games_per_week`; playoff weeks are weighted with `matchup.playoff_weight`.
  `matchup.games_variance: true` adds week-to-week variance in the number of games
  (`Var(X) = E[N]σ² + Var(N)μ²`, also to the ratio components; no covariance between players).
- Daily lineup solver: each day, a maximum assignment of the players who play into the active slots, respecting position eligibility.
  Team Dashboard shows your roster's scheduled games / counted games / games left on the bench per week.
  `scripts/estimate_utilization.py` estimates utilization with the real schedule if there is a schedule in the data directory.

### 13.5 Injury and role scenarios (`fdo.advisor.uncertainty`)

Per-simulation player multiplier `m = (a/ā)·r`: games ratio `a ~ Beta(ā·κ, (1−ā)·κ)`
(`ā = projected_gp/82`), role `r = exp(σ_r·z − σ_r²/2)`. For rookies (`players.is_rookie`),
κ is small (5 vs 8) and σ_r is large (0.20 vs 0.08). The multiplier's expectation is 1: E[W] changes little, while P10–P90
reflects the risk. It is turned on with the "Sakatlık/rol belirsizliği" (Injury/role uncertainty) box in Draft Assistant; in the V1 rollout it is applied
to the user's and the opponents' rosters, and in the full horizon to the final rosters (π does not know about
future injuries). The multipliers are seeded with the simulation ID (CRN). Uncalibrated.

### 13.6 Bot calibration (`fdo.calibration.bots`)

With draft logs (`draft_log` schema: Mock Draft export, manually entered Yahoo mock/league drafts), σ₀ and σ₁ are fitted with the **method of simulated moments**: per ADP band (16 picks),
the target is the P10/P50/P90 of the `pick − A` distribution; every point of the grid is simulated with the same seed (CRN).
σ₀/σ₁ only determine the σ of players without `adp_std` (all of them in the Yahoo data).
Survival reliability: observed frequency by bins of the predicted `P(available)` at the user's picks,
and the Brier score (with the current and the fitted parameters). In a synthetic test, the true values (σ₀ = 3, σ₁ = 0.1)
are recovered on a 3 × 3 grid. The profile mix is not fitted.

**Different league size.** Yahoo has no 16-team mocks; 14-team logs are used with `--teams 14`:
the simulation is 14 teams × 13 rounds, and the bot mix is scaled proportionally to 13 opponents
(`league_config`). Since `pick − A` is measured by pick order (the nth player picked), σ₀/σ₁ carry over
largely to 16 teams; picks 183–208 are not observed.

**Name-based logs and automatic picks.** A log can be without `player_id`: a CSV/TSV with `pick`, `player` (Yahoo spelling) and an
optional `auto` column is matched by name/alias. Picks made by Yahoo on behalf of managers who left the mock
(`auto` filled) stay in the draft but do not enter the moments — otherwise the deviation would come out smaller than it is
(there is no autodraft in this league).

```bash
python scripts/convert_draft_results.py --user Hüsamettin --json-user "New York Hav Havs"
python scripts/calibrate_bots.py --logs "data/real/draft_logs/*.csv" --teams 14
```

**Criterion.** The default criterion is the survival Brier on a fixed set (`survival_brier`: every 6 picks, `P(available @ n)` for all players
with ADP `n ± 40`); this is the quantity the advisor uses. Moments
(`--objective moments`) narrowed σ too much on real logs and worsened survival (Brier 0.130 → 0.166):
they try to compensate for the late-round center shift by shrinking σ. The Brier of `survival_reliability`
only counts 0.01–0.99 predictions; since the set changes with σ, it is not used to compare across σ values.

**Result with real logs (13 October 2026).** `data/real/draft_logs/`: 10 Yahoo mocks + 1 real league draft
(14 teams × 13 rounds; raw text/JSON under `raw/`). Teams named "Team N" are Yahoo bots, and the user's
picks were excluded because they were strategy experiments → 1,313 picks (1,007 once hidden automatic picks are removed). Grid σ₀ ∈ {0.5, 1.5, 3, 5},
σ₁ ∈ {0.08, 0.12, 0.18, 0.25, 0.35}, σ_cap ∈ {25, 40, 60}:

| | σ₀ | σ₁ | σ_cap | Survival Brier |
|---|---|---|---|---|
| Previous default | 1.5 | 0.12 | 25 | 0.113 |
| **Selected** | 1.5 | **0.18** | 25 | **0.106** |
| Best by Brier | 3.0 | 0.18 | 25 | 0.106 |
| σ_cap 40 / 60 | — | — | 40 / 60 | 0.12–0.18 (worse) |

**Hidden automatic picks in the mocks.** The name of a manager who leaves a mock remains, but Yahoo makes their picks.
Yahoo's rule was inferred from the "Team N" picks: the best xrank among the players that leave the roster completable
(`autopick_rule_matches`; 91.5% of bot picks match exactly). The humans in the real league draft
match this rule 17% of the time; the "human" teams in the mocks 22–72%, and many of them picked the whole draft or their last 3–13
picks exactly by the rule. For a named team, ≥ 3 consecutive rule matches are treated as automatic
(`infer_autopicks`; chance probability ~0.17³ ≈ 0.5%) → 475 more picks excluded, leaving 1,007 human picks.
The remaining picks match the rule 16.9% of the time — the same as the real league draft. The choice did not change after the cleanup either
(σ₁ = 0.18). In the cleaned data, at picks 33–96 humans pick 2–4 picks **ahead** of ADP
(median −1…−4); the simulation is +1…+4 in the same region — a location shift, which σ cannot fix.

The improvement holds in both halves of the logs (0.116 → 0.109, 0.107 → 0.102); in the single real league draft it is
even. σ₀ ∈ {0.5, 1.5, 3} are within noise in Brier; 1.5 is closest to the observed spread
of players with ADP in the top 48 (observed 1–16 band P10/P90 −2.7/+3.0; with σ₀ = 3, −4.0/+5.0). At picks 33–96,
humans deviate from ADP by ±10–13 picks; the previous σ₁ was too narrow in this region (players said to have "a 5% chance of lasting"
were lasting 18% of the time). Remaining deviation: in late rounds (113–160), the simulation's `pick − A` median is
+4…+8 picks higher than observed (a location shift, which σ cannot fix).

### 13.7 Yahoo API sync — not done

User decision (13 October 2026): Yahoo Fantasy API app approval cannot be obtained for individual use.
The OAuth/draftresults client written in an intermediate version was removed; in the real draft, picks are entered manually from the Mock Draft
page (or a log CSV is imported). For in-season data, the sync that reads pages using the user's own session:
§13.20.

### 13.9 Strategy tools and bot behavior (13 October 2026)

**Strategy weights.** In Draft Assistant and "Canlı Draft" (Live Draft), a 0–2 weight for each of the 9 categories (0 = punt; presets
from `valuation.presets`). If given, the advisor ranks candidates, pairs, the rollout and the full horizon by
`Σ_c w_c·P_c` — a deliberate exception, at the user's request, to Principle 2 (ECW only). The unweighted ECW of each choice
is also shown; this makes the strategy's cost in real category wins visible.

**Punt plan comparison** (`compare_punt_plans`, "Senaryolar" (Scenarios) tab). Balanced, the 9 single-category punts,
common double punts and (if any) the user's weights are played to the end in the same draft scenarios (CRN);
the user's subsequent picks are made with the plan's weights, and the final roster is evaluated on
all 9 categories. Balanced = the advisor's own policy; since ECW already stops investing in lost categories
on its own, a punt only pulls ahead if the roster has drifted in a particular direction. On real data,
16 plans × 60 simulations take ~28 s.

**Bots fitting their roster.** All bots already look at their roster via the empty positional slot bonus, the position stacking penalty and
the position rule; PuntBuilder (3/15) punts its weakest category. In addition,
a "strengthen strong categories" shift was added (`bots.team_fit_lambda`, a pure shift
`q + λ·(R_fit − R_düz)`). On 12 real logs it did not improve accuracy (λ 0.1: Brier 0.1049 → 0.1047, noise;
0.3: 0.1089); a version pulling toward projection value made it clearly worse (humans follow ADP).
Off by default.

**ADP fallback experiments.** The σ multiplier for low-confidence players 1.5 → 1.0 (Brier 0.1059 → 0.1048, in both
halves). Increasing the weight of the real ADP for low-confidence players and an offset on the out-of-coverage Â did not help.
The large "improvement" (0.090) seen in the first sweep was a measurement error: the evaluation set was shifting
together with A; measurements are made on a fixed reference set (by player identity).

### 13.10 Draft Analysis: background advisor and category board (13 October 2026)

The draft screen is kept simple; the analysis is in a separate tab. When the app opens, `data/real` is loaded automatically from disk with `config/league.yaml`
(16 teams, seat 16); the menu is grouped (`st.navigation`: Draft / "İnceleme" (Review) / "Ayarlar" (Settings)).

- **Draft pages** (Mock, "Canlı" (Live)): a pick is searched by name and entered with Enter; in a mock the bots play automatically until it is
  the user's turn (Undo goes back to before the user's last own pick). Every state is
  published to `AnalysisWorker` (`common.publish_draft`); only a one-line suggestion summary remains on the page.
- **Background worker** (`fdo.advisor.background`, a single one per server, `st.cache_resource`): when a new pick
  arrives, it cancels the running job (`Cancelled` in the progress callback) and starts from the latest state. Order:
  opponent strategy model (live draft) and category board (<1 s) → if it is the user's turn, fast mode (~9 s)
  followed by full mode (~25 s), both with the opponent model → when idle, punt plans (~30 s; refreshed when the user's roster
  or the weights change, and also runs while waiting for the turn). Settings: `advisor.background_*`.
- **"Draft Analizi" (Draft Analysis) page** (`/analiz`, kept open in a side tab): reads results from the worker and checks once per second
  whether there is a new result, refreshing if so. The team's category P(win) strip; on the left the player board, on the right
  the suggested pairs (e.g. 16/17, E[W] and tier), the punt suggestion ("ağırlıklara uygula" (apply to weights) button) and opponent
  strategies. Strategy weights are in the sidebar; when they change, the worker recomputes.
- **Player board** (`fdo.advisor.board`, hashtagbasketball style): per-game stats are colored by the player's
  z-score tier (Elite ≥1.5 · Great ≥1.0 · Good ≥0.5 · Avg · Below ≤−0.5 · Poor ≤−1.0);
  in the "Takımına katkı" (Contribution to your team) view, the same cells show `ΔP_c = P_c(R ∪ {i} ∪ fill) − P_c(R ∪ F(t₁) ∪ fill)` (points;
  they sum to ΔECW). Columns: "Katkı" (Contribution, weighted ΔECW), "Etkisi" (Impact, the categories it raises/lowers the most),
  "Kalır" (Survives, the probability of lasting until the user's pick — the next turn if it is the user's turn now — from 64 bot simulations).
  Sort "Öneri" (Suggestion): the players suggested by the advisor first, then by contribution; while waiting, those with a survival probability < 10%
  go to the end. Players the user cannot take because of the position rule are hidden. Category scarcity:
  the number of Elite/Great/Good per category among the remaining players.
- **Players without projections** are not picked by bots (only allowed if no candidate with a projection remains). Example:
  Bronny James's ADP (106.9) came from only 3% of Yahoo drafts and he has no projection.

### 13.11 First pair × strategy scenarios (`scripts/draft_scenarios.py`)

Pre-draft preparation: the 16/17 pair is forced and the draft is simulated to the end (`play_draft`: forced
picks, conditioning on "if the pair lasts until 16" via `BatchDraft.reserve`, a policy per turn). Candidate pairs
are built from players with a ≥ 8% chance of lasting until 16 and high ΔECW + pairs supplied by the user;
they are screened with the balanced and adaptive strategies, the best are measured on a 44-strategy grid (single/double punts,
"48/49 dengeli → X" (balanced until 48/49 → X) and "baştan X" (X from the start), roster-dependent mixes with 1.25/1.5/0.5 weights), and the best
~100 scenarios are re-measured with new simulations. Output `reports/draft_senaryolari.xlsx`: scenarios,
13-player rosters (filterable in Excel via pick-number columns), pair summary, grid, screening and availability
at 16. Requires `pip install -e ".[excel]"` (openpyxl).

### 13.12 Auction draft (`fdo.auction`, Auction Draft page)

`config/league_14_auction.yaml`: 14 teams, seat 9, 2 C (no FC), 13 players, `draft_type: auction`,
`auction: {budget: 200, min_bid: 1, nomination: round_robin}` (the budget and minimum bid are unverified;
they can be changed for the session from the page). If the selected league is snake, the Auction page shows a button to load the auction league.

- **Values** (`values.py`): model value = the surplus of the balanced z total over the replacement level (the (N+1)th, N = T·rounds)
  is distributed over the league's money (`T·budget − N·min_bid`). Market price = Yahoo average auction value (AAV;
  `fdo.ingest.auction.parse_costs` reads JSON/CSV/pasted lines, stored as `data/real/auction_aav_yahoo.csv`),
  scaled to the same total money. Base price: the AAV if there is one, otherwise the model value.
- **Live state** (`state.py`): sales (player, team, price), remaining budget, empty slots, max bid
  `remaining − min_bid·(empty − 1)`, the estimated nominator (seat rotation, full teams are skipped);
  saved to `data/live/auction.json`.
- **Advice** (`advice.py`): inflation = (remaining money − min_bid·remaining slots) / Σ(base − min_bid) (over the best
  `remaining slots` remaining players); expected price = min_bid + (base − min_bid)·inflation. Value to you: the player's
  ECW contribution to your roster (relative to replacement level, with empty slots filled by the pool's average player, with the strategy
  weights) converted to dollars relative to the pool's total expected price; for an average team ≈ the expected
  price. Bid ceiling = min(value, max bid). Nominations: players who are expensive but not worth their price to you
  (let the opponents spend) and targets whose value exceeds their price.
- **Missing**: an opponent bidding behavior model and an auction mock (there is no real auction draft data).

### 13.13 In-season: This Week and Free Agents (`fdo.inseason`)

Uses the Trade Lab data (rosters, rest-of-season projection, NBA schedule); found in the "Trade Merkezi" (Trade Center) menu.

- **Week dates** (`weeks.py`): weeks start on Monday, week 1 starts on the season's first game day, and
  `merge_with_next` (All-Star) weeks are merged. The playoff weeks and the end day are read from the `Playoffs` text in the league settings;
  if the computed last playoff week ends earlier, it is extended to that day (in all four leagues the final round comes out as two
  calendar weeks). In the 93992 standings, everyone having played 9 categories on 31 October confirms that week 1 was
  20–25 October. The schedule has no dates; the dates are derived by this rule.
- **Fixtures** (`fixtures.py`): `fixtures*.csv` (league_id, team_id, week, opponent_team_id) and
  `league_info.json` `schedules.teams`; an A–B matchup is completed as B–A. If there is no record, the opponent is chosen manually.
- **"Bu Hafta" (This Week)** (`weekly.py`): for each remaining day, the players who play that day are placed into the active slots
  (the `daily_today` solver, priority = per-game z according to the strategy). Contribution = counted games × availability
  (`min(1, ROS GP / team's remaining games)`) × per-game ROS vector; the week's score so far is entered manually
  and added as a constant. Players with NA and (optionally) O status do not play, Q players play, and players on IL are off the roster.
  Output: P(win) per category, expected categories, P(5+) (copula), day-by-day roster (▶/B/✕).
- **Streaming plan**: greedy steps, as many as the remaining weekly acquisitions; at each step it picks, from all (drop d, add f, day t),
  the one that increases the weekly strategy score the most. f takes over d's remaining days (the roster is fixed each
  day), and t is only one of f's game days; an added player can later be dropped again. The final plan is converted into a list of actions ordered by
  day; for each action, the rest-of-season effect "if it were permanent" is shown.
- **"Boştaki Oyuncular" (Free Agents)** (`waiver.py`): for each free agent, the best drop partner from the roster; with the rest-of-season
  vector, `R − v_d + v_f` against the other teams in the league (strategy ΔECW, unweighted ΔECW, category ΔP).
  Unfillable active slots do not increase after the drop; a player on IL is not a drop candidate.
- **Limits**: players on waivers, the Can't Cut list and game times are not verified; independence between players
  and the Normal approximation (uncalibrated). The plan is greedy, not a global optimum.

### 13.14 Season simulation (`fdo.inseason.season`, the "Sezon Simülasyonu" page)

Uses the full H2H schedule (`fixtures*.csv`, four leagues, 56 teams, 519 matchups) and the current standings (`standings.py`:
`yahoo_fantasy_snapshot.json`, `league_<id>_standings_raw.json` or `standings*.csv`).

- In a league with full standings, a completed week is taken as `(W+L+T)/9` and the simulation starts from the real W-L-T;
  in a league without standings (currently 229303, 104375) everything is simulated from week 1 (a warning is shown).
- Each team's strength in each week uses that week's NBA schedule and daily lineup (`WeekModel.team_week`);
  the current week uses current injuries and IL, later weeks use the full roster (missed games are in ROS GP).
  Rosters are fixed for the season.
- **The current week**: the real score for the days before the data date is not in the data (the matchup record only has finished
  weeks). These days are the expected contribution of the real pre-trade roster and are the same in every scenario; the post-trade
  roster plays only on the remaining days from the data date on. Previously, the post-trade roster was applied to the whole week (26 October – 1 November
  in the 31 October data): the past-day games of the player traded away were also deleted and credited to the incoming
  player.
- Matchup: category probabilities + Gaussian copula; standings by (W + T/2)/played, ties broken randomly.
  Playoffs: top n teams (`Playoffs` setting), a `2^round` bracket, empty seats are byes; if `Playoff Reseeding` is on, each
  round is highest–lowest, otherwise a fixed bracket. Playoff weeks use their own schedule (final round 14 days).
- Output: per team P(playoff), P(bye) or P(1st), P(champion), average rank, expected W-L-T; the selected
  team's remaining schedule (expected categories and P(win) per week); counted games in the playoff weeks.
- **Trade impact**: in "Takas Analizi" (Trade Analysis) and "Sezon Simülasyonu" (Season Simulation), the rosters without/with the trade use the same draws
  (CRN, seed 1) — both teams' ΔP(playoff), ΔP(champion), and average rank difference.
- The user's team is selected from the `is_user_team` flag in the schedule (the single-team rule had broken with the full schedule).
- **Strength uncertainty**: in each simulation, each team's vector is scaled for the whole season by `λ ~ lognormal(0, sd)`
  (default sd 0.06, 0–0.15 from the page). Without it, strengths are treated as exactly known: in 93992 there were
  overly certain results such as 100% playoffs or +50 points for a single trade. Uncalibrated; trade and suggestion effects
  are computed with the same setting.
- Standings come from three sources, including `standings*.csv` (league_id, team_id, wins, losses, ties); the standings of all four leagues
  were completed on 31 October, and all start from the real result of week 1.
- Limits: category ties, roster changes, injury return timing and game covariance between players
  are not modeled; the probabilities are uncalibrated.

### 13.15 Suggestion types: mutual benefit, sell high, buy low (`fdo.trade.perception`, `suggest.py`)

Three separate types in "Takas Önerileri" (Trade Suggestions) (`SearchOptions.mode`), each with its own thresholds:

- **Mutual benefit** (`mutual`, the previous behavior): both teams' rest-of-season strategy gain and the package's
  market (ROS) balance.
- **Perceived value**: the value the opponent looks at — this season's numbers (per-game z; fewer than 3 games falls back
  to preseason), preseason name value (the league's draft and Yahoo ADP, §13.30), or the average rank of the two (default). The perceived rank is
  converted to the price of the same rank on the ROS market value ladder; `edge = perceived − ROS`. Ratios are
  not used (they blow up meaninglessly at replacement level).
- **Sell high** (`sell_high`): a player with `edge ≥ min_edge` in the package you give; balance in the opponent's eyes
  (perceived value received / given) ≥ threshold; your gain clears its threshold. The opponent's ROS gain is not required.
- **Buy low** (`buy_low`): a player with `−edge ≥ min_edge` in the package you receive; the same balance and gain conditions.
- Score: the previous formula for mutual; for the others, `your combined gain × min(1, perceived balance)`.
- **Realism (1 November 2026)**: mutual benefit also requires balance in the opponent's eyes (perceived received / given,
  `SearchOptions.min_opponent_view`, UI default 0.8); in multi-team trades, for every other team in the trade.
  Since Yahoo ROS gives some players almost all remaining games (e.g. Caruso 72 games, 58 preseason), ROS value
  and the value the opponent looks at can diverge a lot; trades the model sees as a gain but that the opponent would reject by looking at names are filtered out.
- **Free waiver moves** (`TradeEngine.waiver_best`): every team in the trade is assumed to have made the free moves it can make
  with free agents both before and after (an empty active spot is filled with the best free agent; an active player weaker than a free agent is swapped).
  Previously, in a 2-for-1 trade, the free agent filling the opened spot was counted as a gain of the trade: e.g. in Caruso ↔ Jalen Johnson +
  Shannon, 4-2-3-1 Gegen's "gain" (+0.36) actually came from two free agents it could have picked up without the trade (really −0.36).
  Packages inflated with a worthless extra player (copies of the same trade + extra players) are removed from the list.
  The pre-trade table (`before_matrix`) applies these moves to **all** teams in the trade; in the first version they were only
  applied to the team being evaluated, while after the trade they were applied to both sides. The other side's free
  improvement looked like a cost of the trade: a trade of two players with identical stats was recorded as −0.23 / −0.27 ECW for the two sides
  (now 0, test). In METU IE this bias was between −0.002 and −0.073 ECW for Kekstra depending on the opponent; suggestions
  were being filtered out unnecessarily (e.g. the losadanas trade +0.037 → +0.060). The local search for multi-team suggestions still behaves as if only one team
  changes (`before_row`); candidates are re-scored with this shared baseline in the full model.
- On the page, a table of sell-high candidates on your roster / buy-low targets on opponents' rosters; for suggestions,
  "playoff etkisini hesapla" (compute playoff impact) (season simulation, CRN) and sorting by ΔP(playoff) / ΔP(champion).
- Warning: because the value ladder is steep at the very top (e.g. SGA is 17th this season), a large negative edge
  can come out; a real manager looks at name value — which is why the default perceived value is the average.

### 13.16 Injury return dates (`fdo.inseason.injuries`, `scripts/fetch_injuries.py`)

`python scripts/fetch_injuries.py` downloads the CBS Sports NBA injury report (ESPN rejects automated requests)
and writes `data/real/injuries_cbs_<tarih>.csv` (stays local). Interpretation of the status text: "Expected to be out
until at least Nov 22" → return 22 November; "Out for the season" → out for the rest of the season; Game Time Decision /
Day-To-Day / Questionable / Probable → plays. Matching is by (normalized) name + team if needed; otherwise same team +
last name + first initial (CBS "Nicolas Claxton" = Yahoo "Nic Claxton"). 31 October report: 88/88 matched.

- `apply_injuries`: if the games the team will play after the return < ROS GP, the ROS totals are scaled down proportionally
  (on 31 October Yahoo's ROS was already consistent with the returns; nothing was scaled down). The raw files are not modified; on the trade
  screens it is toggled with "Sakatlık dönüş tarihlerini uygula" (Apply injury return dates) in the sidebar.
- Weekly model and season simulation: the player does not play until the return day (✕ in the day-by-day table), and afterwards
  availability is `ROS GP / team games after the return`. Previously, missed games were spread evenly over the season; now the
  timing is correct, especially for playoff weeks (e.g. Banchero returns on 22 November and plays fully in the playoffs).
- Trade engine: if capacity is exceeded, an O/INJ player on the roster is first moved to an empty IL spot, and only then is someone dropped.
- **Cost of IL returns** (`TradeEngine.crunch_vector`, `SeasonSim.drop_schedule`): when a player on IL returns, room must be made
  for him on the active roster. If there is no empty active spot, in return order (earliest return first) the one with the lowest value among the active players and the returning
  player is dropped: if an active player is dropped, his post-return share (`share × contribution`, share = team games after the return
  / remaining team games; ROS games / remaining games if the date is unknown) is subtracted; if the returning player himself is dropped, his entire
  contribution is subtracted. A player ignored for the whole season does not return (no cost). In trade and waiver calculations, the team being changed decides
  with its own strategy, while the other teams and the season simulation decide by balanced value. Previously, the model counted returning players
  as extra without dropping anyone: on 31 October in METU IE, Kekstra's 4 IL players return to a 13/13 active roster;
  playoff probability went from 92% → 70% and championship from 17% → 6% (in 220594, NY Hav Havs 18% → 30%). Trading away a player on IL
  is now valued correctly because it removes this cost; acquiring a player from IL adds the cost.

### 13.17 Suggestion directions and suggestion details (31 October 2026)

In "Takas Önerileri" (Trade Suggestions), your team is searched with several **directions** (strategies); each direction is a separate scan, and the results
appear in tabs, and also side by side in the combined "Tümü" (All) view:

| Direction | Strategy | What it looks for |
|---|---|---|
| "D Dengeli" (Balanced) | all 9 categories with weight 1 | overall strength |
| "P / P2 Otomatik punt" (Auto punt) | weakest 1 / 2 categories set to 0 (`auto_punt`) | trades that give away a weak category and strengthen the rest |
| "C / C2 Zayıfı canlandır" (Revive the weak) | weakest 1 / 2 categories ×3 (`auto_revive`, `Strategy.revive`) | trades that win back a category that looks punted |
| "G Haftalık galibiyet" (Weekly win) | balanced, `ecw_weight = 0` | P(5+) directly instead of ECW; weight on close categories |
| "Ö Seçtiğin strateji" (Your chosen strategy) | preset punt or custom weights | your own preference |

- **Robustness**: your category change from the trade is re-scored with the weights of every direction (ΔP(5+) for the win
  direction); "4/4" means the trade is a gain even if your strategy changes. In the combined view, the directions in which the trade was found are labeled.
- In each suggestion: your and the opponent's **category impact** (the 3 categories that change the most, win probability points), **PO games**
  (the difference in the roster's total NBA games during the fantasy playoff weeks; including automatic drop/add and injury returns),
  **position warning** (an active position that cannot be filled after the trade), balance **in the opponent's eyes** (perceived value, for every
  type) and unweighted ΔECW. Sorting: suggestion score, robustness, ΔECW, or playoff + championship impact.
- Search speed: the engine's hot path (automatic drop/add order, package value, injury status) is read from numpy arrays;
  4000 packages per direction take ~5 seconds (~15 before).

### 13.18 Multi-team trade (`fdo.trade.multi`, the "Çok Takımlı Takas" tab)

Yahoo does not perform a 3–4-team trade as a single transaction; it is done manually, with two-team trades accepted at the same time. This module evaluates it
as a single scenario.

- **Request**: `MultiTradeRequest(moves=((oyuncu, veren, alan), ...), drops, adds, auto_balance)`; 2–4 teams, each team
  gives and receives at least one player. Roster balance follows the same rule as a two-team trade: `TradeEngine.resolve` now works
  through `resolve_moves`, which is independent of the number of teams (an incoming injured player goes to IL; when capacity is exceeded, O/INJ players on the roster go to IL, then
  the lowest-value player is dropped, and an emptied spot is filled with a free agent). `score_many` recomputes the league probabilities
  with all the changed teams. A two-team request gives exactly the same result as the two-team engine (test).
- **Analysis** (`analyze_multi`): for each team ECW, P(5+), strategy score (each team with its own strategy), category
  impact, ROS value and perceived value received/given, PO games, automatic transactions, rank change by the three sources;
  "does everyone win", **value balance** = the received/given ratio of the most unbalanced team, commissioner risk, season impact
  (playoffs/championship for each team, same draws).
- **Suggestions** (`suggest_multi`): cycles you → T1 → T2 (→ T3) → you. Shapes: 1-1-1, you give 2 (2-1-1),
  the middle team gives 2 (1-2-1), you receive 2 (1-1-2), 4 teams 1-1-1-1. Two stages: (1) local search — each team's gain
  is computed in vectorized form from its own roster change only, assuming the rest of the league is fixed (in a 13-team league ~640
  thousand cycles take ~2–3 seconds; for a one-for-one swap the result is the same as the exact model, test); (2) the best 200 candidates are re-scored with the full model
  (automatic drop/add + all changed teams), and the conditions that each team's strategy gain ≥ threshold and value balance
  ≥ threshold are applied here. Score `(smallest gain + geometric mean) × (0.5 + 0.5 × balance)` (the same form as
  two-team mutual benefit). Diversity: an equal share for each shape, at most 3 from the same group of teams, and at most 3 suggestions with the same
  package given by you.
- API: `POST /api/leagues/{lig}/trade/multi/analyze`, `.../multi/season`, `.../multi/suggest`.
- Tab: **"Analiz" (Analysis)** — select 3–4 teams, click a player on the rosters (the default target is the next team in the cycle), change each
  move's target, choose each team's strategy, optionally drop/pick up a free agent. **"Öneriler" (Suggestions)** — shapes,
  your strategy (direction), the assumption for the other teams, thresholds; "Analizde aç" (Open in analysis) moves a suggestion to "Analiz". The two-team "Takas
  Analizi" (Trade Analysis) is unchanged.

### 13.19 Durability: rest-of-season games (`fdo.inseason.durability`, 1 November 2026)

Yahoo's rest-of-season (ROS) projection ignores injury risk: on 31 October it gave 90% of rostered players ≥ 95% of their team's
remaining games (Caruso 72 games; his preseason projection was 58 out of 82). Injury-prone players
looked more valuable than durable ones. `apply_durability` is applied after the injury return dates, always in the
API:

- **Play rate**: prior = preseason projected games / 82 (Yahoo's estimate, which includes injury history). This season's
  games played / team games played is combined with a 20-game prior and pulls the rate **upward only** (a player who has entered the rotation and plays every
  game, e.g. Quenton Jackson .41 → .55). Missed games do not lower the rate: they are already modeled through the current injury return date
  and are not counted twice.
- **Cap** = rate × team games after the return (from today if the return date is unknown). If the ROS games exceed the cap, the ROS
  totals shrink proportionally and per-game values are preserved. A player Yahoo has already scaled down (e.g. Anthony Davis 59) is unchanged;
  a player without a preseason projection is not touched.
- The effect is everywhere: trade engine (weekly vector, market value), weekly model and season simulation (availability
  `ROS GP / remaining team games`), IL return share. In the "Kalan sezon" (Rest of season) source, players who were scaled down are marked with `*` in the GP column; hovering
  shows Yahoo's games and the rate. In the "Bu Hafta" (This Week) view, a healthy player also plays at expected value (at the rate).
- 31 October: 416 players were scaled down (total 30,140 → 24,328 games). METU IE value rank: Kawhi 11 → 48, Kyrie 23 → 60,
  Caruso 37 → 78; Mikal Bridges 90 → 54, Alexander-Walker 45 → 19. Playoff probability: Kekstra 70% → 62%, NY Hav Havs
  30% → 20%, Galatasaray Cafe Crown 25% → 37%, Karaali SK 19% → 27%.

### 13.20 Yahoo sync (`fdo.ingest.yahoo_sync`, `scripts/yahoo_sync.py`, 8 November 2026)

Since the official API path remains closed (§13.7), the league pages are read using the user's own session:

- **Login**: `python scripts/yahoo_login.py` opens a Chrome window without automation; you log in once with a separate profile
  (`%LOCALAPPDATA%\fdo\yahoo-chrome`, outside the repo). The sync takes this profile's cookies once
  with Playwright (hidden window); it fetches the pages over plain HTTP, waiting 0.8 s between them.
- **What is read** (`fdo.ingest.yahoo_html`, the standard library HTML parser): the league home page (standings, FAB,
  waiver order, the week's matchups, the user's team), starting rosters, matchup `date=totals` (the week's team totals
  so far and the category score), the team page (acquisitions used this week, IL, FAB), the waiver list
  (`W (Nov 9)` → the day the player clears), and the season totals and rest-of-season projection pages (30 + 30 pages, optional).
  Results of finished weeks are fetched only if missing (into `matchups.json` with team totals). Then the CBS injury report.
- **What is written** is in the existing format (`rosters.json`, `player_stat_pages.json`), which `load_trade_data` reads unchanged; in
  addition, `standings_live.csv` and `yahoo_live.json`. If a page cannot be read, no file is written. The inputs before and
  after writing go into the immutable archive (§13.31). All outside git.
- **Date**: `roster_date` is today in US Eastern time. The week total is as of the moment it was fetched; since no games are played between
  02:00–12:00 US Eastern (~10:00–20:00 Turkey time), within this window the total is exactly "through yesterday". Outside it, it is flagged `live`
  (today's partial score included; a warning is shown). The matchup page's team table gives the week total even if a date is selected;
  the day-by-day breakdown is only in the player rows, and there are no makes/attempts there; so it is not parsed.
- **Usage**: on the "Bu Hafta" (This Week) page, if the score is not entered manually, the Yahoo total is used; the streaming plan's remaining acquisitions
  come from the acquisitions used in Yahoo. In the season simulation, the past days of the current week are the real totals
  (only if totals exist for all teams; otherwise the expected value from §13.14). Live data is used only if it comes from the same fetch as the rosters and
  from the same week. The team and injury status of players not on a roster now also come from the player pages.
- **App**: "Yahoo'dan güncelle" (Update from Yahoo) in the top bar (a background job, `GET/POST /api/sync`); with "projeksiyonlar" (projections) off
  ~50 pages (~1 min), with it on ~110 pages (~3 min). The first run, including finished weeks, took 160 pages, 4 min 44 s.
  `python scripts/yahoo_sync.py` can be added to Task Scheduler for every morning.
- **Do Yahoo projections react to role changes** (31 October → 7 November snapshots): rest-of-season
  projections are updated weekly (per-game points changed for 271 of 744 players; Paul George 15.2 → 17.3), but
  there is almost no reaction to teammate injuries: Jalen Johnson "O" → at most +0.4 points/game at ATL; Josh Hart "O" →
  Brunson and Anunoby unchanged. Only the injured player's game count drops (73 → 69). Short-term role changes
  must be modeled separately for weekly decisions.

### 13.21 Sit/Start (`fdo.inseason.sitstart`, Sit/Start tab)

When more players have games than there are active slots, who should play; the decision is based on that week's matchup, not on the player's overall value:

- **Game value**: the contribution of one of the player's games to the weekly strategy score (expected category wins under balanced),
  `S(V) − S(V − a·u)` if it counts in the current lineup, `S(V + a·u) − S(V)` if not (`V` is the two teams' weekly vector,
  including the real week score; `a` availability; `u` the per-game vector, role-adjusted for the duration of a role change). Ratios use makes/attempts.
- **Lineup**: each day, players who have a game and a value greater than −0.002 are placed into slots by value priority according to the position rule
  (`slot_assignment`); values are recomputed for the new lineup, until the lineup stops changing (at most 6 rounds). A player whose value is
  below −0.002 sits even if a slot is empty (**ratio protection**: once the counting categories are decided, a low-percentage
  high-volume shooter puts FG%/FT% at risk). The opponent's lineup uses static priority.
- **Today**: the suggested lineup is compared with the lineup in Yahoo (the `rosters.json` slots from the sync day):
  a list of "Başlat" (Start: on the bench but should play) and "Oturt" (Sit: active but should sit). A player whose game has started cannot be changed.
- 7 November (WNBA 26-27, Galatasaray Cafe Crown): with the counting categories settled, 8 player-games were sat by ratio protection,
  expected categories 2.71 → 2.84; in METU IE, Kekstra's lineup was already the same as the suggested one.

### 13.22 Add/Drop: rest of season and this week (`fdo.inseason.adddrop`, Add/Drop tab)

Two separate menus:

- **"Kalan sezon" (Rest of season)**: the free-agent table from §13.13 (ROS ECW, position rule, IL return cost) + availability:
  FAs immediately; a player on waivers from the day Yahoo shows (`W (Nov 9)`, from the sync; for a record without a date, today
  + the waiver period from the league settings). Remaining acquisitions this week, FAB budget and the waiver rule are in the header.
- **"Bu hafta" (This week)**: for each free agent on the shortlist (30), the best single move (the player to drop and the day) and its effect:
  expected categories, P(5+), category probabilities and the rest-of-season effect if the move were permanent; below it, a greedy
  day-by-day plan with the remaining acquisitions (§13.13 streaming). A player on waivers is not planned before the day he clears. Two goals:
  - *"Haftayı kazan" (Win the week)*: expected category wins according to your strategy.
  - *"Kritik kategori" (Critical category)*: play for the selected categories (weight 1, the others 0.05). Automatic selection: for each category, the average
    increase in win probability from adding a single free agent to the remaining days without restriction, over the best 5 candidates
    ("movable"); the two largest categories (≥ 0.02). In a category that is already decided, this increase is ~0.
- 7 November: for Kekstra the critical category is BLK (44%, +9 points movable); a 4-acquisition plan raises expected categories
  from 1.50 → 1.87.

### 13.23 Performance: weekly category ranking (`fdo.inseason.history`, "Performans" (Performance) tab)

Using the team totals of finished weeks (`matchups.json`, §13.20) and the running week's total so far: the team's league rank in each
category (1 = best, fewest for TO; ties share the best rank), the week's category score and the rank of the season
total. The heat table is two-directional (top/bottom third), with values in the cells; hovering shows the league median and the week's
best.

### 13.24 Role changes from injuries (`fdo.inseason.roles`)

Since Yahoo projections barely react to teammate injuries (§13.20), this is measured from this season's NBA game logs
(`gamelogs_nba_2026-27.csv`, refreshed on every sync, outside git):

- **Important player**: ≥ 3 games this season, ≥ 20 min per game. **Absent set**: the team's important players who are currently not playing
  (Yahoo O/INJ/NA, or a CBS return date in the future / out for the season). A player who has missed the entire season is not counted.
- The team's games: those in which none of the absent set played (W) and those in which all of them played (H); if W is empty, the single player
  with the most minutes. A teammate's difference is `ort(W) − ort(H)` (W ≥ 1, H ≥ 2 games), shrinkage `n_W / (n_W + 4)`, added to the
  rest-of-season per-game values. Validity: until the earliest known return (14 days if unknown).
- The weekly model (and therefore "Bu Hafta" (This Week), Sit/Start, Add/Drop and the current/next weeks of the season simulation)
  uses the role-adjusted per-game vector on these days. Name matching: name + team, name, initial + last name + team
  ("N. Alexander-Walker"); on 7 November 100% of the rows matched, with role changes for 106 players (e.g. at OKC, with Holmgren and
  Jalen Williams out, Bennett Stirtz +11 min, +5.9 points).

### 13.25 News analysis (`fdo.inseason.news`, "Haberler" (News) tab, `scripts/news_refresh.py`)

- **Sources**: CBS fantasy player news (RotoWire notes; the first page of the general feed, the last 30 notes ≈ 4–8 hours — since 8
  November the second page and the injury and position feeds return 406 to an automated client) and the ESPN NBA news feed (50
  headlines + summaries, ≈ 1 day).
  A news item's ID is its link; it is stored once, analyzed once, and items older than 21 days are deleted (`news.json`, outside git).
  To avoid gaps, it should be refreshed every 2 hours (Task Scheduler: `scripts/news_refresh.py`); refreshing is free,
  and only new and relevant items go to the model.
- **Filtering** (free, before the model): a CBS item must match the Yahoo player pool and have a role/injury/trade
  signal in its headline (game recaps stay in the list but are not analyzed); an ESPN item must mention the full name of a player in the pool.
- **Model**: `claude-opus-5-5`, effort `low`, structured output with a JSON schema, batches of 30 items, the fixed system prompt
  cached, a server-side fallback model (`fallbacks: "default"`). Changed via `FDO_NEWS_MODEL` (e.g. `claude-sonnet-5-5`
  at roughly half the price). The key comes from `ANTHROPIC_API_KEY` or `.env` in the repo root (outside git). A batch whose response is refused or
  cut off is retried on the next refresh.
- **Output**: event type (injury, return, role ↑/↓, trade, trade rumor, rest…), status, estimated return, games to be
  missed, teammates gaining/losing minutes, fantasy impact (−2…+2) and a one-sentence summary in Turkish. The app tags players by
  league: yours, this week's opponent's, FA / waiver (opportunity).
- **Cost**: the token usage of every call is recorded. First refresh (8 November): 70 items, 42 analyzed, ~$0.15
  (~$0.0036 per item); with 40–80 relevant items per day, ~$6–10 per month.

### 13.26 Drop only: who to drop when a player returns from IL (`fdo.inseason.drops`, Add/Drop → "Sadece bırak", 9 November 2026)

For making room when a player returning from injury is moved to the active roster ("Sadece bırak" (Drop only)). The returning players among those on IL are marked (default:
return date within 2 days, or no date and the status is no longer "out"; can be changed manually). The candidates are the active
players and the returning players themselves; the number that must be dropped is `active + returning − roster capacity`. For each candidate:

- **"Kalan sezon" (Rest of season)**: the roster's typical-week vector with the candidate removed (remaining IL players with their return cost) against the other teams
  in the league; with the strategy, `9·Σ w_c·ΔP_c`. The screen shows the extra weekly loss relative to the suggested option and the categories lost the most.
- **"Bu hafta" (This week)**: the effect on the matchup over the remaining days (expected categories, P(5+)); a returning player plays from his return day on.
- Number of games (this week / next week), value rank in the league (if high, someone else may pick him up after the drop), the name of a better
  free agent if there is one (§13.13 `drop_ranking`), and a warning about an active position that cannot be filled after the drop.

Suggestion: among the candidates that do not break positions, the player(s) with the lowest rest-of-season loss; since the change is permanent, the default
sort is rest of season, while the "Bu hafta" (This week) sort looks only at the matchup. 9 November: at Kekstra, Jaylon Tyson is returning
(14/13); the suggestion is Robert Williams III, with Collin Sexton almost equal (0.006 categories per week).

### 13.27 Completing and balancing a trade from a selection (`fdo.trade.suggest.complete_trade`, "Takas Analizi", 9 November 2026)

After selecting players in "Takas Analizi" (Trade Analysis), one button builds suggestions around the selection; the
selected players stay fixed:

- **Only your players selected** → "Karşılığında ne isteyebilirim?" (What can I ask for in return?): packages of 1–3
  players from the other team.
- **Only their players selected** → "Karşılığında ne verebilirim?" (What can I give in return?): packages of 1–3 players
  from your roster.
- **Both sides selected** → "Takası dengele / tamamla" (Balance / complete the trade): up to 3 players in total are added
  to either side, up to a 3-for-3 package (e.g. 2-for-1 → 2-for-2, 3-for-2, 3-for-3). The current selection's
  evaluation (why it is unbalanced) is shown on top.

Single-player additions scan the whole roster; larger ones scan 10 candidates per side (strategy fit + market value);
at most 4000 packages (0.2–2.5 s on real data). Every package is scored exactly like the trade analysis (selected
strategies, automatic roster balancing). The thresholds model acceptability: value balance (smaller/larger package, on
the model's rest-of-season value or the market's perceived value, whichever is higher, §13.30) of at least 55% and an opponent's view (perceived value: received/given) of at least
0.80. Order: **both win** (both teams' scores rise; the mutual-benefit score of `suggest_trades`), **you win** (the
opponent loses in the model but the names look balanced), **you lose**. A package is dropped when a smaller package of
the same or better tier with the same result is already listed (the added player adds no value, e.g. it is
auto-dropped). "Uygula" (Apply) moves the package into the selection and opens the full analysis; the list stays open.
API: `POST /api/leagues/{lid}/trade/complete`.

### 13.28 Evaluation bases and the IL return timeline (`fdo.inseason.scenarios`, "Takas Analizi", 9 November 2026)

Trade math works on "rest-of-season per-game rate × remaining games". Until now the rates were only Yahoo's
rest-of-season projection, which updates slowly and reflects role changes late (a rookie with a bigger role than
expected, a veteran moved to the bench). There are now four bases. The remaining game count (durability included) is
always Yahoo's, and the whole league (opponents, free agents, replacement level, who is cut at an IL return) is valued on
the same basis:

- **Yahoo projection** (default).
- **This season's rates**: actual per-game averages (at least 3 games; otherwise Yahoo).
- **Last 10 games**: from the NBA game logs (at least 3 games; otherwise this season, then Yahoo).
- **Blend**: between Yahoo and this season, weighted by games played, `n / (n + 10)`.

In "Takas Analizi" (Trade Analysis), the "Değerlendirme" (Evaluation) selector runs the whole analysis (category impact,
season simulation, fixtures) on that basis. The "Değerlendirme temelleri" (Evaluation bases) table shows the same trade on
all four bases side by side (if they agree the conclusion is robust; if they diverge it depends on which rates you
believe) and expands the players' per-game rates on each basis.

**IL return timeline** (`TradeEngine.crunch_plan`, the same rule the evaluation uses): after the trade, in order of return,
who comes back from IL and who is cut. A returning player worth less than the weakest active player displaces nobody
("does not make the roster"); a player received in the trade who is cut at a return is flagged (he only contributes until
then). Return dates come from the CBS injury report.

9 November, tsg fentezi, Acuff → Garland + McCollum: Yahoo +0.36 categories/week, this season's rates −0.26, last 10
games −0.25, blend +0.03. Neither incoming player is cut at the December returns on any basis.

### 13.29 Detailed analysis (Claude; `fdo.inseason.trade_report`, "Takas Analizi", 9 November 2026)

"Detaylı analiz yaz" (Write a detailed analysis) in "Takas Analizi": the app builds a data packet and Claude
(`claude-opus-5-5`, effort `medium`, JSON schema) writes a structured evaluation in Turkish: a decision (accept / counter /
reject / wait) with confidence, sections, counter offers ("Takas ekranında aç" (Open in the trade screen) moves one into the
selection) and things to watch. The packet (~8k tokens):

- Per player: this season, Yahoo rest of season and preseason per-game values, value and perceived rank, durability,
  last-5 average and the last 10 games one by one (minutes, points, shooting), playoff-week games.
- Role on the NBA team: the rotation over the last 5 games (minutes, shots, points) and injured teammates (return date,
  games played this season: e.g. all of Garland's games came without Ingram and Beal).
- Model results on the four bases and the IL return timeline (§13.28), both rosters and category ranks, the last 14 days
  of news, and counter-offer candidates (from the §13.27 completion tool, thresholds relative to the offer's own balance;
  with Yahoo and this season's rates).

The model uses only the packet; general basketball knowledge (age, career norms) only when it doesn't contradict the data,
and it says so. Generation runs in the background (~1 min; Cloudflare's 100 s limit) and the UI polls
(`POST /api/leagues/{lid}/trade/report`, `GET /api/trade/report/{key}`). Reports are saved in
`data/real/trade_reports.json` (git-ignored; not sent to the server) keyed by data signature + trade + strategies, so the
same trade on the same data reopens at no cost. Cost is ~$0.13 per report (9 November run: 13k input, 3.7k output tokens,
70 s). The key is `ANTHROPIC_API_KEY` in `.env` (§13.25). On a read-only server it works only when `FDO_REPORT_CODE` is
set, and the UI asks once for the access code (the address is public; the paid call is protected).

### 13.30 Perceived value: the draft market (`fdo.trade.perception`, 9 November 2026)

The "preseason name value" component of the opponent's view used to be the 9-category z rank of Yahoo's preseason
projection, i.e. it assumed the opponent does the same math as the model. Managers instead know a player by what he cost
in the draft. Example (METU IE, 9 November): Banchero is #107 per game in 9 categories (turnovers, free throws, steals)
and #136 on his preseason projection, but his Yahoo ADP is 35.7 and he went for $22 in the league's auction (Clingan $28,
Jaren Jackson Jr. $21). The old view ranked Banchero #142 and read "Banchero + Jackson → Clingan" as 0.87 in the
opponent's eyes (short for the opponent); in managers' eyes it is 1.53, a clear overpay.

The name-value rank is now:

- The league's own draft (`draft_results.csv`): the auction price (higher = more valuable), or the pick in a snake
  draft.
- Yahoo ADP (`adp_yahoo_*.csv`).
- The average of the two ranks when both exist; undrafted players behind the drafted ones, in preseason projection
  order. Without draft data it is the projection rank, as before.

"This season's numbers" (at least 3 games) and the default average are unchanged. The change reaches everything that
uses perceived value: the opponent's view, mispricing (sell high / buy low), suggestions, completion, the detailed
analysis.

**Value balance in completion** (§13.27): it used to be measured only on the model's rest-of-season value (smaller /
larger package), so trades the model finds lopsided but managers see as balanced (selling high on name value) were cut
at the threshold. Balance is now in the eyes of the model or the market (perceived value), whichever is higher; the
opponent's-view threshold (0.80) is unchanged. In the same example completion used to find only Gobert and Jalen Smith
for Banchero (both losses for you); it now finds Banchero → Clingan (you +0.33 / +0.16 / +0.28 categories/week, Yahoo /
this season / blend; 0.97 in the opponent's eyes) and → Mobley (+0.25 / +0.20 / +0.24; 0.94).

### 13.31 Data archive, identity matching, freshness and decision log (`fdo.ingest`, `fdo.evaluation`, 10 November 2026)

Without Yahoo API access, with data pulled by hand (your own session, "Yahoo'dan güncelle"), these make the same analysis
reproducible and show which data a decision rests on:

- **Immutable archive** (`fdo.ingest.archive`, `scripts/archive_data.py`): at the end of every sync and news refresh the
  analysis inputs (`rosters.json`, player pages, league settings, injury report, NBA game logs, schedule, projections, ADP,
  draft, fixtures; also news and transaction history) are stored by content hash (sha256): `snapshots/objects/` (gzip,
  each content once) and `snapshots/batches/<batch>.json` (file → hash, times, missing files, previous batch). A second
  sync on the same day used to overwrite that day's copy; now every capture is its own batch and unchanged inputs open no
  new batch. Objects are written first and the manifest last, so an interrupted archive leaves no batch. `--legacy`
  imports the old `snapshots/<day>/` folders as (incomplete) batches; `--verify` checks hashes, `--restore` extracts a batch
  into an empty directory. The archive stays outside git and is not sent to the server. The first full batch is 33 files,
  2.1 MB compressed.
- **Time fields** (`fdo.ingest.timestamps`): per file, the moment the source describes (`source_as_of`: roster date, last
  game day, projection date), the capture moment (`captured_at`, from the file's own record) and the moment it changed on
  disk are kept apart. If the file has no time record, the capture time stays empty; disk time does not stand in for it.
- **Player identity** (`fdo.ingest.identity`): the CBS injury report, NBA game logs and news are tied to Yahoo ids by one
  rule set: name + team, name alone (single player in the pool; a team mismatch is reported), initial + surname + team. A
  rule matches only if it leaves **one** candidate. The injury report used to bind a row to the first of two same-name
  players when the team did not match; now the row stays ambiguous. Unmatched and ambiguous rows are listed by name in the
  data notes. Manual fixes: `data/real/id_overrides.csv` (`source, name, nba_team, player_id, note`; outside git). On the
  9 November data nothing changed: CBS 96/96 and NBA logs 3,294/3,294 rows match.
- **Quality checks** (`fdo.trade.data.quality_issues`): besides missing fields, negative counts and makes > attempts, now
  3PM > FGM, points not matching shot components (2·FGM + 3PM + FTM; tolerance for the source's one-decimal rounding: at
  least 1 point or 3%) and stats without games. Raw data is not changed, only reported.
- **Freshness** (`fdo.ingest.freshness`, `GET /api/freshness`): instead of one "last updated", an age per component
  (rosters, player stats, this week, injuries, news, NBA logs, league settings...). A state per decision type: **normal**,
  **conditional** (the result is shown, saying which data is old) or **hold** (refresh this component first). It opens
  from "Veri: …" in the top bar; the Add/Drop page warns when the state is not normal ("valid if the player is still
  free"). The thresholds (e.g. for add/drop, rosters normal up to 12 hours, conditional up to 36) are **starting
  assumptions**, not validated by measurement; change them with `config/freshness.yaml`.
- **Decision log** (`fdo.evaluation.decisions`): trade suggestions and completion (`recommendation`) and trades inspected
  on the trade page (`scenario`) are appended as separate kinds to `data/real/decisions/<month>.jsonl`: request, result
  summary, data signature (content hash; independent of file paths and times), the latest archive batch, code version.
  `FDO_DECISION_LOG=0` turns it off. A scenario does not change the real roster.
- **Data providers** (`fdo.ingest.provider`): the analysis does not know where data comes from; current hand-pulled files
  (`ManualSnapshotProvider`), an archive batch (`ArchivedSnapshotProvider`) and the disabled `YahooApiProvider` deliver the
  same file contract. Yahoo API approval is a prerequisite for nothing; if it comes, read-only access is assumed.
- **Reference cases** (`fdo.evaluation.cases`, `scripts/run_cases.py`): suggestions found wrong are kept in
  `data/real/cases.json` (outside git) as fixed API requests with expectations such as "this package must not be listed";
  results go to `data/real/evaluation/` with code version and data signature. `--batch <batch>` runs the same cases on the
  archived inputs (replay), `--compare` diffs two records. Replay with the 9 November batch produced exactly the same
  suggestions as the current files.
- **Known issues** (`tests/unit/test_known_issues.py`): verified bugs as synthetic cases; unfixed ones are
  `xfail(strict=True)`. Open: completion lists, as a normal suggestion, a trade the other side loses both in the model and in
  its own perception (real case: Banchero → Giannis, 0.82 in the opponent's eyes).

**Credentials and disabled features**: there is no Yahoo API key; sync uses a Chrome profile logged in once with
`scripts/yahoo_login.py` (without it, updating does not work and analysis continues on the existing files).
`ANTHROPIC_API_KEY` (`.env`) is only for news analysis and the detailed analysis; without it those two are off, and trade,
add/drop and season calculations run without an LLM.

### 13.8 V3 candidates

Beam search and H-score weight optimization; fitting the profile mix; covariance of game counts between
players; the real H2H schedule and playoff matchups; a real backtest with past-season snapshots.

---

## 14. Installation and running

The commands below have been verified with V1.

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# synthetic data
python scripts/make_synthetic.py --n 400 --seed 7 --out data/synthetic/

# tests
pytest -q

# realism report
python scripts/run_mock_batch.py --n 500 --seed 1 --data data/synthetic/

# performance measurement (§11); --batch includes 500 mocks
python scripts/profile_advisor.py

# interface
streamlit run src/fdo/ui/app.py
```

Reports are written under `reports/` (not committed to git). GitHub Actions (`.github/workflows/ci.yml`) runs the tests on Python 3.11 and 3.13 on every push; it reports the realism report and the performance measurement, without test thresholds, in the job summary and as an artifact (§9.4). The synthetic data manifests are under `data/synthetic/manifests/`; the loader looks for a manifest first in `manifests/` next to the CSV, then in `manifests/` one directory up (e.g. `data/manifests/`).

Real data: CSVs go under `data/real/` and manifests under `data/manifests/`, and they are loaded from page 1. The repo contains the data set produced from the Yahoo export (12 October 2026) and its raw JSON files; to regenerate it:

```bash
python scripts/import_yahoo_json.py --players data/real/raw/yahoo_players_2026-10-12.json \
    --adp data/real/raw/yahoo_adp_2026-10-12.json --license-status personal_use_confirmed \
    --license-notes "Kullanıcı kararı (2026-10-12): Yahoo sayfaları public; kişisel kullanım."

# utilization estimate (§6.6.1); --schedule for the real schedule
python scripts/estimate_utilization.py --data data/real/ --mocks 30

# V2 (§13)
python scripts/fetch_nba_schedule.py --download --season 2026-27 --license-status personal_use_confirmed
python scripts/fetch_gamelogs_nba_api.py --season 2025-26 --license-status personal_use_confirmed   # pip install -e ".[nba]"
python scripts/calibrate_variance.py --gamelogs data/real/gamelogs_nba_2024-25.csv data/real/gamelogs_nba_2025-26.csv
python scripts/mark_rookies.py --gamelogs data/real/gamelogs_nba_2024-25.csv data/real/gamelogs_nba_2025-26.csv
python scripts/calibrate_bots.py --logs "data/real/draft_logs/*.csv" --data data/real/
python scripts/backtest.py --data data/real/ --n 30 --strategies adp,z,g,ecw
```

---

### 14.1 Trade Lab web app (React + FastAPI)

The new interface for the in-season tools (31 October 2026). The draft and auction pages stay in Streamlit.
Suggestion directions: §13.17; multi-team trade: §13.18.

```powershell
.venv\Scripts\python.exe -m pip install -e ".[dev,web,yahoo,nba,news]"   # once
.venv\Scripts\python.exe scripts\yahoo_login.py                  # once: Yahoo login (§13.20)
.venv\Scripts\python.exe run_app.py                              # http://127.0.0.1:8000
```

Data is refreshed with "Yahoo'dan güncelle" (Update from Yahoo) in the top bar (or `scripts\yahoo_sync.py`): Yahoo, the CBS injury report,
NBA game logs and news. News analysis needs `pip install -e ".[news]"` and `ANTHROPIC_API_KEY=...` in `.env`.
Suggested schedule (Task Scheduler): every morning at ~10:30 `scripts\yahoo_sync.py` (between 10:00–20:00 Turkey time the week score
is exactly "through yesterday"), and `scripts\news_refresh.py` every 2 hours during the day.

If the interface has not been built or `frontend/src` has changed, `run_app.py` first runs `npm install` / `npm run build`
(requires Node.js), then starts FastAPI and opens the browser. Tabs: "Takas Analizi" (Trade Analysis), "Takas Önerileri" (Trade Suggestions), "Çok Takımlı
Takas" (Multi-team Trade), "Bu Hafta" (This Week), Sit/Start (§13.21), Add/Drop (rest of season + this week, §13.22; "Sadece bırak" (Drop only), §13.26; completing/balancing a trade from a selection, §13.27), "Haberler" (News) (§13.24–13.25), "Performans" (Performance)
(§13.23), "Sezon Simülasyonu" (Season Simulation), "Lig Sıralamaları" (League Rankings). League, team, injury return dates, color scale
(green↔red or colorblind-friendly blue↔red) and theme are in the top bar.

**From a phone** (8 November 2026): if the screen is narrower than 760 px, the top shows the page name with league/team (tap for the settings panel) and
the Yahoo update button, and the bottom has a tab bar ("Bu Hafta" (This Week), Sit/Start, Add/Drop, "Haberler" (News), "Daha" (More)). Wide tables turn into cards and
lists: category probabilities as rows/tiles, single moves and the acquisition plan as cards (plan on top), and in Sit/Start "bugün
yapılacaklar" (today's to-dos) at the very top; the remaining tables scroll horizontally with a fixed name column. The app can be added to the home screen (manifest, icons,
a service worker that caches only the interface shell; data is never cached). When returning from the background, if a
sync happened in the meantime, the page refreshes itself.

For access from outside the computer, [Tailscale](https://tailscale.com) (free for personal use, no need for the same Wi-Fi,
the app is not exposed to the internet):

```powershell
# install Tailscale on the computer and the phone, sign in with the same account on both; enable DNS → HTTPS Certificates in the admin console
.venv\Scripts\python.exe run_app.py --no-browser          # the app stays on 127.0.0.1:8000
tailscale serve --bg 8000                                 # once: https://<bilgisayar>.<tailnet>.ts.net → 8000
```

On the phone, open `https://<bilgisayar>.<tailnet>.ts.net` → Safari: Share → Add to Home Screen; Chrome: ⋮ → Add to Home
screen / Install app. An HTTPS address is required (the service worker and the full-screen app only work in a secure context).

- **"Takas Analizi" (Trade Analysis)**: two Yahoo-style roster tables (selectable source: rest of season / this season / preseason;
  per-game stats colored by z level, injury and return-date badges). Clicking a row adds the player
  to the package; the analysis runs automatically as the selection changes: both teams' expected categories, P(5+), strategy
  score, a category impact chart on a shared scale, roster transactions (IL / drop / add), value and perceived balance,
  season impact (playoffs and championship), league rank change by the three sources.
  When the source "Bu sezon" (This season) or "Sezon öncesi" (Preseason) is selected, a **perception column** next to "Değer" (Value): the rank in the eyes of a manager
  looking at that source and that rank's equivalent in the rest-of-season market (same scale as Value, `perceived_prices`; this season
  per game, fewer than 3 games falls back to preseason, marked with *). ▲/▼ rank difference; a difference of ≥ 1 value is in bold (orange: looks
  better than he is → sell, purple: looks worse than he is → buy). Clicking the header sorts by the difference. Value and trade calculations are always
  rest of season: only the remaining games change hands in a trade.
  The `*` at the end of GP in the "Kalan sezon" (Rest of season) source: scaled down from Yahoo's games by the play rate (§13.19; hover for details).
- **Trade screen extras**: manual "bırak" (drop) and searchable free-agent "al" (add) for both sides (automatic balancing is applied after
  these); a strategy selector in every tab: balanced, preset punts, **auto punt** (the weakest 1 or 2 categories from the team's category
  profile, `StrategyIn.auto_punt`), **revive the weak** (the weakest 1–2 categories ×3,
  `StrategyIn.auto_revive`) and custom weights (0–3); **saved scenarios** (in the browser,
  JSON export/import): ΔECW, strategy Δ, ΔP(5+), value and perceived balance, playoff/championship impact side by side;
  "Aç" (Open) restores a scenario with all its selections.
- **Schedule impact** (automatic in two-team and multi-team analysis): for each remaining regular-season week in the schedule,
  the probability of winning the week without → with the trade (the same point estimate as the schedule table in "Sezon Simülasyonu" (Season Simulation):
  that week's NBA games, injury returns, IL return cost), the expected total wins and movement between teams;
  if the opponent is also in the trade, a "takasta" (in trade) marker. `POST /trade/fixtures`, `/trade/multi/fixtures`.
- **"Takas Önerileri" (Trade Suggestions)**: mutual benefit, sell high and buy low as separate types; each is searched in several directions (§13.17);
  mispricing tables; playoff impact for suggestions; "Takas ekranında aç" (Open in trade screen) moves a suggestion, selected, to "Takas
  Analizi" (Trade Analysis).
- **"Çok Takımlı Takas" (Multi-team Trade)**: manual analysis and cycle suggestions for 3–4 teams (§13.18).
- **"Bu Hafta" (This Week) / "Boştaki Oyuncular" (Free Agents) / "Sezon Simülasyonu" (Season Simulation) / "Lig Sıralamaları" (League Rankings)**: the interface for the models in §13.13–§13.16.

Structure: `src/fdo/api/` (FastAPI: `state.py` cached data/engines, `serialize.py` JSON conversion, `app.py` rosters,
trade analysis and season impact, `inseason.py` suggestions, mispricing, weekly + streaming, free agents, season,
rankings, `multi.py` multi-team trade), `frontend/` (Vite + React + TypeScript, no extra UI library; `src/pages/*`, `src/components/*`,
`styles.css` design tokens, light/dark theme). Development: run the API with `uvicorn` (8000) and the
interface with `npm run dev` (5173, `/api` is proxied to 8000) separately. `frontend/node_modules` and `frontend/dist` are not committed to git.
CI builds the interface with type checking; API tests are in `tests/integration/test_api*.py`.

### 14.2 Running read-only on a server (9 November 2026)

The app can run read-only on a server: data is fetched on the computer and sent over, and the server only displays it.
The server configuration (service, reverse proxy, certificate, domain name) is not kept in the repo; it lives only on the server.

- **Read-only mode**: with `FDO_READ_ONLY=1`, `POST /api/sync` and `POST /api/news/refresh` return 403; in the interface,
  "Yahoo'dan güncelle" (Update from Yahoo) and "Haberleri yenile" (Refresh news) are replaced by a "Yenile" (Refresh) button that reloads the latest data on the server.
  Run: `PYTHONPATH=src FDO_READ_ONLY=1 python -m uvicorn fdo.api.app:create_app --factory --port 8610`
  (run `npm run build` first).
- **Sending data** (on the computer, after updating):

  ```powershell
  .venv\Scripts\python.exe scripts\yahoo_sync.py                    # rosters, scores, CBS, NBA game logs, news
  .venv\Scripts\python.exe scripts\news_refresh.py                  # every 2 hours during the day
  .venv\Scripts\python.exe scripts\push_data.py --host <ssh-host>   # or $env:FDO_PUSH_HOST
  ```

  `push_data.py` sends the git-ignored files under `data/real` as a single tar.gz over `ssh` (`--app`, default
  `/srv/fantasy/app`); on the server, `scripts/receive_data.py` puts each file in place from a temporary directory with `os.replace`.
  `snapshots/`, manager contact details and raw captures are not sent. **No restart is needed**: the app reloads the data itself
  when the file signature changes (the first request takes a few seconds). When the code changes, the server needs a `git pull`, an interface
  build and a service restart.
- **Detailed analysis on the server** (optional, paid): a `.env` in the repo root on the server
  (`ANTHROPIC_API_KEY=...`, readable by the service user) and an `FDO_REPORT_CODE=<code>` environment variable on the
  service; the UI asks for the code once. Without a code it is off on the server.

## 15. Glossary

| Term | Meaning |
|---|---|
| **ADP / `A_i`** | Average Draft Position. Used only to model when a player gets picked. `A_i` is the effective ADP after the fallback |
| **ECW** | Expected Category Wins: expected category wins per opponent (0–9), averaged over 15 opponents |
| **ΔECW** | The effect on ECW of adding a player, relative to the fill profile of the same pick |
| **Turn** | The user's consecutive picks with no opponent pick between them (e.g. 16/17) |
| **Fill profile `F(n)`** | The weekly stat mean and variance of the player expected to be picked at pick n |
| **Survival `P_surv`** | The probability that a player is still available at a given pick (from simulation) |
| **CRN** | Common Random Numbers: comparing candidates under the same random scenarios |
| **Thurstone model** | The model in which each bot assigns players a persistent noisy ranking and picks the best perceived one |
| **π (policy)** | The user's pick rule for the next turn inside a rollout (V1: myopic best pair) |
| **Punt** | Setting a category's ranking weight to 0. The league score remains 9 categories |
| **`uncalibrated`** | An output badge for results that rely on parameters not tuned with real data |
