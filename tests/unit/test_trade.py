"""Takasın veri ayrımı, şut hacmi, sahiplik, iki taraf ve olasılık regresyonları."""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from fdo.config import REPO_ROOT, load_config
from fdo.trade import Strategy, TradeData, TradeEngine, TradeError, TradeLeague, TradeRequest, load_trade_data
from fdo.trade.data import MODES, ROS, number, preseason_file
from fdo.trade.report import category_changes, export_result
from fdo.trade.suggest import SearchOptions, suggest_trades
from fdo.types import STATS


@pytest.fixture
def trade_data():
    cfg = load_config()
    slots = {s: 0 for s in cfg.roster.slots}
    slots.update(PG=1, C=1, BN=1)
    mix = {k: 0 for k in cfg.model.bots.mix}
    mix["MarketFollower"] = 3
    cfg = cfg.with_overrides({"league": {"teams": 4, "my_seat": 1, "rounds": 3},
                              "roster": {"slots": slots, "active_slots": ["PG", "C"]},
                              "model": {"bots": {"mix": mix}}})
    rng = np.random.default_rng(52)
    ids = [str(i) for i in range(20)]
    fga = rng.uniform(60, 220, len(ids))
    fgm = fga * rng.uniform(.35, .65, len(ids))
    fta = rng.uniform(10, 100, len(ids))
    ftm = fta * rng.uniform(.55, .95, len(ids))
    fg3 = np.minimum(fgm, rng.uniform(0, 40, len(ids)))
    frame = pd.DataFrame({"gp": 10., "fgm": fgm, "fga": fga, "ftm": ftm, "fta": fta,
                          "fg3m": fg3, "pts": 2 * fgm + ftm + fg3,
                          "reb": rng.uniform(15, 120, len(ids)), "ast": rng.uniform(10, 100, len(ids)),
                          "stl": rng.uniform(1, 20, len(ids)), "blk": rng.uniform(1, 20, len(ids)),
                          "tov": rng.uniform(5, 40, len(ids))}, index=ids)
    players = pd.DataFrame({"name": [f"P{i}" for i in ids], "nba_team": "SYN", "yahoo_positions": "PG,C",
                            "injury_status": ""}, index=ids)
    rosters = {str(t): tuple(ids[(t - 1) * 3:t * 3]) for t in range(1, 5)}
    league = TradeLeague("L", "Test ligi", {t: f"Takım {t}" for t in rosters}, rosters,
                         {t: frozenset() for t in rosters}, {"Trade End Date": "March 4, 2027",
                         "Trade Review": "Commissioner", "Trade Reject Time": "2 days"}, cfg, "1", dt.date(2026, 10, 31))
    schedule = pd.DataFrame({"game_date": ["2026-10-20", "2026-11-27"], "home_team": "SYN", "away_team": "OTHER"})
    return TradeData({"L": league}, players, {m: frame.copy(deep=True) for m in MODES},
                     {m: {"kind": m} for m in MODES}, None, schedule, league.roster_date, "test", ())


@pytest.fixture
def eng(trade_data):
    return TradeEngine(trade_data, "L", utilization=1, horizon_weeks=4)


def test_three_sources_are_independent_and_current_rosters_used(trade_data):
    trade_data.stats["season_total"].loc["0", "pts"] = 10000
    trade_data.stats["preseason"].loc["0", "pts"] = 1
    e = TradeEngine(trade_data, "L", horizon_weeks=4)
    assert e.before["season_total"].totals.loc["1", "PTS"] > 10000
    assert e.before["preseason"].totals.loc["1", "PTS"] < 10000
    assert e.before[ROS].totals.loc["1", "PTS"] != e.before["season_total"].totals.loc["1", "PTS"]


def test_parser_preserves_missing_zero_and_grouped_decimal():
    assert number("1,311") == 1311
    assert number("58.5") == 58.5
    assert number("0") == 0
    assert np.isnan(number("-"))


def test_in_season_csv_cannot_replace_preseason(tmp_path):
    pre = tmp_path / "projections_yahoo_2026-10-12.csv"
    later = tmp_path / "projections_yahoo_2026-11-01.csv"
    for path, date in ((pre, "2026-10-12"), (later, "2026-11-01")):
        pd.DataFrame({"as_of": [date]}).to_csv(path, index=False)
    schedule = pd.DataFrame({"game_date": ["2026-10-20", "2027-04-11"]})
    assert preseason_file(tmp_path, "2026-27", schedule) == pre


def test_zero_shot_attempts_have_no_ratio_contribution(trade_data):
    for frame in trade_data.stats.values():
        frame.loc["0", ["fgm", "fga", "ftm", "fta"]] = 0
    e = TradeEngine(trade_data, "L", horizon_weeks=4)
    assert np.all(e.vecs[e.index["0"], 14:] == 0)
    assert np.isfinite(e.league_probabilities().to_numpy()).all()


def test_fg_and_ft_are_volume_weighted(eng):
    frame = eng.data.stats[ROS]
    roster = list(eng.league.rosters["1"])
    v = eng.before[ROS].totals.loc["1"]
    assert v.FG_PCT == pytest.approx(frame.loc[roster, "fgm"].sum() / frame.loc[roster, "fga"].sum())
    assert v.FT_PCT == pytest.approx(frame.loc[roster, "ftm"].sum() / frame.loc[roster, "fta"].sum())
    assert v.FG_PCT != pytest.approx((frame.loc[roster, "fgm"] / frame.loc[roster, "fga"]).mean())


def test_missing_ratio_component_does_not_use_an_unmatched_denominator(trade_data):
    frame = trade_data.stats[ROS]
    frame.loc["0", "fgm"] = np.nan
    frame.loc["0", "fta"] = np.nan
    e = TradeEngine(trade_data, "L", horizon_weeks=4)
    values = e.before[ROS].totals.loc["1"]
    assert values.FG_PCT == pytest.approx(frame.loc[["1", "2"], "fgm"].sum() / frame.loc[["1", "2"], "fga"].sum())
    assert values.FT_PCT == pytest.approx(frame.loc[["1", "2"], "ftm"].sum() / frame.loc[["1", "2"], "fta"].sum())


def test_turnover_low_is_good_and_ties_share_rank(trade_data):
    for f in trade_data.stats.values():
        f["tov"] = 10
        f.loc[["0", "1", "2"], "tov"] = 1
    e = TradeEngine(trade_data, "L", horizon_weeks=4)
    assert e.before[ROS].ranks.loc["1", "TOV"] == 1
    assert e.before[ROS].ranks.loc["2", "TOV"] == 3


def test_ros_weekly_model_divides_by_remaining_weeks_not_82(eng):
    j = eng.index["0"]
    assert eng.vecs[j, 1] == pytest.approx(eng.data.stats[ROS].loc["0", "pts"] / 4)


def test_trade_updates_both_parties_all_modes_and_opponent(eng):
    original = copy.deepcopy(eng.league.rosters)
    r = eng.analyze(TradeRequest("1", "2", ("0",), ("3",)))
    for m in MODES:
        expected = eng.before[m].totals.loc["1", "PTS"] - eng.data.stats[m].loc["0", "pts"] + eng.data.stats[m].loc["3", "pts"]
        assert r.after[m].totals.loc["1", "PTS"] == pytest.approx(expected)
        assert r.after[m].totals.loc["3"].equals(eng.before[m].totals.loc["3"])
    assert not np.allclose(r.probabilities_before[0, 1], r.probabilities_after[0, 1])
    assert np.allclose(r.probabilities_after[0, 1] + r.probabilities_after[1, 0], 1)
    assert eng.league.rosters == original
    assert set(r.metrics.index) == {"1", "2"}


def test_rank_deltas_reconcile_and_export_is_valid_json(eng):
    r = eng.analyze(TradeRequest("1", "2", ("0",), ("3",)))
    changes = category_changes(r, ROS, "1")
    assert np.allclose(changes["sıra kazancı"], changes["sıra önce"] - changes["sıra sonra"])
    doc = json.loads(export_result(eng, r))
    assert set(doc["comparisons"]) == set(MODES)
    assert doc["assessments"]["calibrated_acceptance_probability"] is None


@pytest.mark.parametrize("proposal", [
    TradeRequest("1", "1", ("0",), ("1",)),
    TradeRequest("1", "2", ("3",), ("0",)),
    TradeRequest("1", "2", ("0", "0"), ("3",)),
    TradeRequest("1", "2", ("0",), ("3",), add_a=("4",)),
    TradeRequest("1", "2", (), ("3",)),
    TradeRequest("1", "2", ("0",), ("3",), drop_a=("0",)),
])
def test_invalid_ownership_and_duplicates_rejected(eng, proposal):
    with pytest.raises(TradeError):
        eng.analyze(proposal)


def test_unequal_trade_requires_drop_and_automatic_plan_is_unique(eng):
    req = TradeRequest("1", "2", ("0", "1"), ("3",))
    with pytest.raises(TradeError, match="kapasitesi"):
        eng.analyze(req)
    r = eng.analyze(replace(req, auto_drop=True, auto_fill=True))
    assert len(r.rosters_after["1"]) == len(r.rosters_after["2"]) == 3
    assert len(r.adjustments["1"]["add"]) == 1
    assert len(r.adjustments["2"]["drop"]) == 1
    assert not set(r.rosters_after["1"]) & set(r.rosters_after["2"])
    assert r.adjustments["1"]["add"][0] not in {p for rr in eng.league.rosters.values() for p in rr}


def test_preexisting_empty_slot_is_not_counted_as_trade_gain(trade_data):
    lg = trade_data.leagues["L"]
    rosters = {**lg.rosters, "1": ("0", "1")}
    trade_data.leagues["L"] = replace(lg, rosters=rosters)
    e = TradeEngine(trade_data, "L", horizon_weeks=4)
    r = e.analyze(TradeRequest("1", "2", ("0",), ("3",), auto_drop=True, auto_fill=True))
    assert r.adjustments["1"]["add"] == ()
    assert len(r.rosters_after["1"]) == 2


@pytest.mark.parametrize("give_a,give_b", [(("0", "1", "2"), ("3", "4")), (("0", "1"), ("3", "4", "5"))])
def test_three_player_packages_balance_both_rosters(eng, give_a, give_b):
    r = eng.analyze(TradeRequest("1", "2", give_a, give_b, auto_drop=True, auto_fill=True))
    assert len(r.rosters_after["1"]) == len(r.rosters_after["2"]) == 3
    assert not set(r.rosters_after["1"]) & set(r.rosters_after["2"])


def test_auto_drop_does_not_treat_an_unknown_player_as_worthless(trade_data):
    trade_data.stats[ROS].loc["4", "pts"] = np.nan
    e = TradeEngine(trade_data, "L", horizon_weeks=4)
    r = e.analyze(TradeRequest("1", "2", ("0", "1"), ("3",), auto_drop=True, auto_fill=True))
    assert "4" not in r.adjustments["2"]["drop"]
    assert "4" in r.rosters_after["2"]


def test_il_transfer_is_symmetric_and_preserves_both_sides(trade_data):
    lg = trade_data.leagues["L"]
    trade_data.players.loc[["0", "3"], "injury_status"] = "O"
    trade_data.leagues["L"] = replace(lg, injury_rosters={**lg.injury_rosters, "1": frozenset(["0"]), "2": frozenset(["3"])})
    e = TradeEngine(trade_data, "L", horizon_weeks=4)
    _, changes, injury = e.resolve(TradeRequest("1", "2", ("0",), ("3",)))
    assert injury["1"] == frozenset(["3"])
    assert injury["2"] == frozenset(["0"])


def test_punt_changes_preference_not_physical_probabilities(eng):
    req = TradeRequest("1", "2", ("0",), ("3",))
    balanced = eng.analyze(req)
    punt = eng.analyze(req, strategy_b=Strategy.preset("Punt FT_PCT"))
    assert np.allclose(balanced.probabilities_after, punt.probabilities_after, equal_nan=True)
    assert balanced.metrics.loc["2", "strategy_delta"] != punt.metrics.loc["2", "strategy_delta"]
    assert balanced.metrics.loc["2", "win_delta"] == punt.metrics.loc["2", "win_delta"]


def test_missing_stats_are_preserved_and_not_replaced_by_another_source(trade_data):
    trade_data.stats[ROS].loc["0", "pts"] = np.nan
    e = TradeEngine(trade_data, "L", horizon_weeks=4)
    assert not e.modeled[e.index["0"]]
    r = e.analyze(TradeRequest("1", "2", ("0",), ("3",)))
    assert not r.assessments["incoming_modeled"]
    assert r.assessments["commissioner_risk"] == "Veri yetersiz"
    assert np.isnan(trade_data.stats[ROS].loc["0", "pts"])
    assert not np.isnan(trade_data.stats["preseason"].loc["0", "pts"])


def test_deadline_stops_suggestions_and_flags_manual_analysis(eng):
    day = dt.date(2027, 3, 5)
    r = eng.analyze(TradeRequest("1", "2", ("0",), ("3",)), analysis_date=day)
    assert r.assessments["deadline_passed"]
    s = suggest_trades(eng, "1", analysis_date=day)
    assert s.examined == 0 and not s.suggestions


def test_suggestions_are_bilateral_bounded_and_reproducible(eng):
    opts = SearchOptions(max_evaluations=250, min_fairness=.1, min_strategy_gain=.00001)
    one = suggest_trades(eng, "2", options=opts)
    two = suggest_trades(eng, "2", options=opts)
    assert one.examined <= 250
    assert all(n > 0 for n in one.opponent_counts.values())
    assert one.suggestions, "fixture must exercise accepted results, not just an empty filter"
    assert [(r.request, r.score) for r in one.suggestions] == [(r.request, r.score) for r in two.suggestions]
    for s in one.suggestions:
        assert min(s.own_strategy_delta, s.other_strategy_delta) >= opts.min_strategy_gain
        assert min(s.own_win_delta, s.other_win_delta) >= opts.min_win_gain
        r = eng.analyze(s.request, strategy_b=s.other_strategy)
        assert r.metrics.loc["2", "win_delta"] == pytest.approx(s.own_win_delta)
        assert r.metrics.loc[s.request.team_b, "win_delta"] == pytest.approx(s.other_win_delta)


def test_real_snapshot_loads_without_modifying_sources():
    base = REPO_ROOT / "data" / "real"
    protected = [base / n for n in ("rosters.json", "league_info.json", "player_stat_pages.json")]
    if not all(p.exists() for p in protected):
        pytest.skip("Kişisel Yahoo anlık görüntüleri repoda bulunmak zorunda değil")
    hashes = [hashlib.sha256(p.read_bytes()).digest() for p in protected]
    data = load_trade_data(base)
    assert len(data.leagues) == 4
    assert {lg.capacity for lg in data.leagues.values()} == {13, 17}
    for lid, lg in data.leagues.items():
        e = TradeEngine(data, lid)
        assert len(e.before[ROS].ranks) == len(lg.teams)
        assert np.isfinite(e.league_probabilities().to_numpy()).all()
    assert hashes == [hashlib.sha256(p.read_bytes()).digest() for p in protected]


def test_injured_active_player_fills_free_il_before_any_drop(trade_data):
    trade_data.players.loc["1", "injury_status"] = "O"
    e = TradeEngine(trade_data, "L", horizon_weeks=4)
    req = TradeRequest("1", "2", ("0",), ("3", "4"))                 # 1 ver 2 al: kapasite 1 aşılır
    rosters, adj, injuries = e.resolve(req)
    assert adj["1"]["move_to_il"] == ("1",) and not adj["1"]["drop"]
    assert "1" in injuries["1"] and set(rosters["1"]) == {"1", "2", "3", "4"}
    trade_data.players.loc["1", "injury_status"] = ""
    with pytest.raises(TradeError):                                  # sakat yoksa bırakma seçilmeli
        TradeEngine(trade_data, "L", horizon_weeks=4).resolve(req)
