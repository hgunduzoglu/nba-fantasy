import datetime as dt

import numpy as np
import pandas as pd
import pytest

from factories import proj_frame, proj_row
from fdo.matchup.player_week import per_game_variance, weekly_vectors
from fdo.roster.eligibility import parse_positions
from fdo.schedule import build_calendar, counted_games, player_games, roster_week_table, synthetic_schedule
from fdo.schedule.calendar import assign_weeks, normalize_team


def games(rows):
    return pd.DataFrame(rows, columns=["game_date", "home_team", "away_team"])


@pytest.fixture
def tiny():
    # Salı 20 Ekim 2026 açılış; 2. hafta 26 Ekim pazartesi
    return games([
        ("2026-10-20", "BOS", "NYK"), ("2026-10-22", "BOS", "LAL"), ("2026-10-25", "NY", "LAL"),
        ("2026-10-26", "BOS", "LAL"), ("2026-10-28", "NYK", "BOS"), ("2026-10-30", "BOS", "GS"),
        ("2026-11-02", "LAL", "GSW"), ("2026-11-04", "BOS", "NYK"),
    ])


def test_weeks_start_monday_and_merge(config):
    d = pd.Series(pd.to_datetime(["2026-10-20", "2026-10-25", "2026-10-26", "2026-11-02", "2026-11-09"]))
    assert list(assign_weeks(d, config)) == [1, 1, 2, 3, 4]
    merged = config.with_overrides({"schedule": {"merge_with_next": [2]}})
    assert list(assign_weeks(d, merged)) == [1, 1, 2, 2, 3]


def test_team_aliases():
    assert normalize_team("GS") == "GSW" and normalize_team("ny") == "NYK" and normalize_team("BOS") == "BOS"


def test_calendar_counts_and_playoff_weighting(tiny, config):
    config = config.with_overrides({"unverified": {"playoff_weeks": None}, "schedule": {"merge_with_next": []}})
    cal = build_calendar(tiny, config)
    assert list(cal.weeks.index) == [1, 2, 3]
    assert cal.team_week.loc["BOS"].tolist() == [2, 3, 1]
    assert cal.team_week.loc["GSW"].tolist() == [0, 1, 1]
    assert cal.weeks.loc[1, "start"] == pd.Timestamp("2026-10-20")
    assert cal.weeks.loc[2, "end"] == pd.Timestamp("2026-11-01")
    assert not cal.weeks["playoff"].any()
    assert cal.games_mean(config)["BOS"] == pytest.approx(2.0)

    po = config.with_overrides({"unverified": {"playoff_weeks": 1},
                                "model": {"matchup": {"playoff_weight": 2.0}}})
    cal = build_calendar(tiny, po)
    assert cal.weeks["playoff"].tolist() == [False, False, True]
    assert cal.games_mean(po)["BOS"] == pytest.approx((2 + 3 + 2 * 1) / 4)


def test_player_games_falls_back_for_unknown_team(tiny, config):
    cal = build_calendar(tiny, config)
    players = pd.DataFrame({"player_id": ["a", "b"], "nba_team": ["BOS", "SYN"]})
    mean, var, unknown = player_games(players, cal, config)
    assert mean["a"] == pytest.approx(2.0) and var["a"] == pytest.approx(2 / 3)
    assert mean["b"] == config.model.matchup.games_per_week and unknown == ["SYN"]


def test_synthetic_schedule_is_valid():
    teams = [f"T{i:02d}" for i in range(30)]
    s = synthetic_schedule(teams, dt.date(2026, 10, 20), np.random.default_rng(1))
    long = pd.concat([s[["game_date", "home_team"]].set_axis(["d", "t"], axis=1),
                      s[["game_date", "away_team"]].set_axis(["d", "t"], axis=1)])
    assert not long.duplicated().any()                       # günde en fazla bir maç
    per_team = long["t"].value_counts()
    assert per_team.min() >= 78 and per_team.max() <= 82


def test_daily_lineup_respects_slots(config):
    P = parse_positions
    pos = [P("C")] * 5 + [P("PG")] * 6
    only_c = np.array([[True] * 5 + [False] * 6])
    assert counted_games(pos, only_c, config).sum() == 4      # C, C, UTIL, UTIL
    everyone = np.ones((1, 11), dtype=bool)
    assert counted_games(pos, everyone, config).sum() == 6    # PG, G, C×2, UTIL×2 (SG/SF/PF/F boş)
    pos13 = [P("PG"), P("SG"), P("PG,SG"), P("SF"), P("PF"), P("SF,PF"), P("C"), P("C"), P("PF,C"),
             P("SG,SF"), P("PG"), P("C"), P("SF")]
    assert counted_games(pos13, np.ones((1, 13), dtype=bool), config).sum() == 10


def test_roster_week_table(tiny, config):
    cal = build_calendar(tiny, config)
    t = roster_week_table(["a", "b"], [parse_positions("PG"), parse_positions("C")], ["BOS", "LAL"], cal, config)
    assert t["scheduled"].tolist() == [4, 4, 2] and t["benched"].sum() == 0


def test_weekly_vectors_use_team_games(config):
    proj = proj_frame([proj_row("a", gp=82), proj_row("b", gp=82)])
    var, _ = per_game_variance(proj, None, {})
    base = weekly_vectors(proj, var, config)
    g = pd.Series({"a": 4.0, "b": config.model.matchup.games_per_week})
    w = weekly_vectors(proj, var, config, g, pd.Series({"a": 0.5, "b": 0.0}))
    assert w.loc["a", 1] == pytest.approx(base.loc["a", 1] * 4.0 / config.model.matchup.games_per_week)
    assert w.loc["b", 1] == pytest.approx(base.loc["b", 1])
    gv = config.with_overrides({"model": {"matchup": {"games_variance": True}}})
    wv = weekly_vectors(proj, var, gv, g, pd.Series({"a": 0.5, "b": 0.0}))
    assert wv.loc["a", 7] > w.loc["a", 7] and wv.loc["b", 7] == pytest.approx(w.loc["b", 7])


def test_dataset_with_schedule_changes_vectors(synthetic_ds, config):
    from fdo.advisor.simulate import player_vectors
    from fdo.bots.universe import build_universe

    teams = [f"T{i:02d}" for i in range(30)]
    sched = synthetic_schedule(teams, dt.date(2026, 10, 20), np.random.default_rng(2))
    ds = synthetic_ds.with_schedule(sched)
    assert ds.content_hash != synthetic_ds.content_hash
    u = build_universe(synthetic_ds, config)
    v0, _ = player_vectors(synthetic_ds, config, u)
    v1, _ = player_vectors(ds, config, u)                     # SYN takımı takvimde yok → aynı
    assert np.allclose(np.nan_to_num(v0), np.nan_to_num(v1))
