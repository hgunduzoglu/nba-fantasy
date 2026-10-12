import numpy as np
import pytest

from factories import proj_frame, proj_row, varied_projections
from fdo.matchup.ecw import ecw_from_p, ecw_matrix, ecw_vs, p_at_least, p_win, team_ecw
from fdo.matchup.fill import fill_table_from_picks
from fdo.matchup.player_week import (
    WEEK_DIM,
    per_game_variance,
    ratio_game_variance,
    weekly_vectors,
)
from fdo.matchup.team_totals import category_means, team_vector
from fdo.valuation import value_players
from fdo.valuation.weights import preset

CATS = ["FG_PCT", "FT_PCT", "FG3M", "PTS", "REB", "AST", "STL", "BLK", "TOV"]


def vecs(rows, config, variance=None):
    df = proj_frame(rows)
    var, _ = per_game_variance(df, variance, config.model.variance.phi)
    return weekly_vectors(df, var, config)


def team(rows, config):
    return vecs(rows, config).to_numpy().sum(axis=0)


def cat(name):
    return CATS.index(name)


def base_roster(prefix="a"):
    return [proj_row(f"{prefix}{i}", fgm=4 + 0.3 * i, fga=9 + 0.5 * i, reb=4 + i * 0.4,
                     ast=2 + 0.3 * i, tov=1.5 + 0.1 * i) for i in range(10)]


def test_identical_teams_half_and_ecw_45(config):
    t = team(base_roster(), config)
    p = p_win(t, t, config)
    np.testing.assert_allclose(p, 0.5)
    assert ecw_from_p(ecw_vs(t, np.stack([t, t]), config)) == pytest.approx(4.5)


def test_adding_positive_player_increases_p(config):
    a = team(base_roster(), config)
    b = team(base_roster("b"), config)
    boost = team([proj_row("x", reb=12.0, fgm=0.0, fga=0.0, ftm=0.0, fta=0.0, fg3m=0.0)], config)
    assert p_win(a + boost, b, config)[cat("REB")] > p_win(a, b, config)[cat("REB")]


def test_turnover_direction(config):
    a = team(base_roster(), config)
    more_to = team([proj_row("x", tov=5.0)], config)
    b = team(base_roster("b"), config)
    p = p_win(a + more_to, b + team([proj_row("y", tov=0.5)], config), config)
    assert p[cat("TOV")] < 0.5


def test_ratio_higher_pct_wins_at_equal_volume(config):
    a = team([proj_row("a", fgm=5.5, fga=10.0)], config)
    b = team([proj_row("b", fgm=4.5, fga=10.0)], config)
    assert p_win(a, b, config)[cat("FG_PCT")] > 0.5


def test_high_volume_low_pct_shooter_hurts_fg(config):
    fifty = [proj_row(f"a{i}", fgm=5.0, fga=10.0) for i in range(8)]
    opp = [proj_row(f"b{i}", fgm=4.8, fga=10.0) for i in range(9)]
    a = team(fifty, config)
    b = team(opp, config)
    shooter = team([proj_row("s", fgm=8.4, fga=20.0)], config)
    assert p_win(a + shooter, b, config)[cat("FG_PCT")] < p_win(a, b, config)[cat("FG_PCT")]


def test_ratio_from_totals_not_mean_of_pcts(config):
    t = team([proj_row("a", fgm=1.0, fga=2.0), proj_row("b", fgm=9.0, fga=20.0)], config)
    assert category_means(t, config)["FG_PCT"] == pytest.approx(10.0 / 22.0)


def test_ecw_independent_of_punt_weights(config):
    df = varied_projections(26)
    var, _ = per_game_variance(df, None, config.model.variance.phi)
    v = weekly_vectors(df, var, config).to_numpy()
    teams = np.stack([v[:13].sum(axis=0), v[13:].sum(axis=0)])
    before = ecw_matrix(teams, config)
    value_players(df, config, weights=preset(config, "punt_FT_TO"))
    after = ecw_matrix(teams, config)
    np.testing.assert_array_equal(before, after)


def test_degenerate_zero_variance(config):
    a = np.zeros(WEEK_DIM)
    b = np.zeros(WEEK_DIM)
    a[1] = 10.0     # PTS ortalaması, varyans 0
    p = p_win(a, b, config)
    assert p[cat("PTS")] == 1.0
    assert p_win(b, a, config)[cat("PTS")] == 0.0
    assert p[cat("REB")] == 0.5


def test_ecw_averages_over_all_opponents(config):
    rng = np.random.default_rng(0)
    df = varied_projections(16 * 13, seed=2)
    var, _ = per_game_variance(df, None, config.model.variance.phi)
    v = weekly_vectors(df, var, config).to_numpy()
    teams = np.stack([v[i * 13:(i + 1) * 13].sum(axis=0) for i in range(16)])
    m = ecw_matrix(teams, config)
    manual = np.mean([np.sum(p_win(teams[0], teams[j], config)) for j in range(1, 16)])
    assert team_ecw(m)[0] == pytest.approx(manual)
    assert ecw_from_p(ecw_vs(teams[0], teams[1:], config)) == pytest.approx(manual)
    # simetri: P(A>B) + P(B>A) = 1
    np.testing.assert_allclose(m[0, 1] + m[1, 0], 1.0)


def test_ratio_game_variance_binomial_term():
    assert ratio_game_variance(5.0, 10.0, 0.0, 0.5) == pytest.approx(10 * 0.5 * 0.5)
    assert ratio_game_variance(0.0, 0.0, 3.0, 0.5) == pytest.approx(0.25 * 3.0)


def test_variance_file_overrides_default(config):
    import pandas as pd

    df = proj_frame([proj_row("a", reb=5.0)])
    var_file = pd.DataFrame({"player_id": ["a"], "stat": ["reb"], "per_game_var": [9.0]})
    var, calibrated = per_game_variance(df, var_file, config.model.variance.phi)
    assert var.loc["a", "reb"] == 9.0
    assert var.loc["a", "pts"] == pytest.approx(df.loc[0, "pts"])
    assert not calibrated["a"]


def test_p_at_least_independence():
    p = np.full(9, 0.5)
    assert p_at_least(p, 5) == pytest.approx(0.5)
    assert p_at_least(np.ones(9), 9) == pytest.approx(1.0)


def test_fill_table_mean_and_smoothing():
    vecs_ = np.arange(5 * WEEK_DIM, dtype=float).reshape(5, WEEK_DIM)
    vecs_[4] = np.nan                       # projeksiyonsuz oyuncu
    picks = np.array([[0, 1, 2, 4], [1, 0, 3, 4]])
    ft = fill_table_from_picks(picks, vecs_, window=0)
    np.testing.assert_allclose(ft.means[1], (vecs_[0] + vecs_[1]) / 2)
    np.testing.assert_allclose(ft.means[4], ft.means[3])   # örneksiz → en yakın
    smooth = fill_table_from_picks(picks, vecs_, window=1)
    np.testing.assert_allclose(smooth.means[2], (vecs_[[0, 1, 1, 0, 2, 3]]).mean(axis=0))
    assert team_vector(vecs_, [0, 1], ft.rows([1])).shape == (WEEK_DIM,)
