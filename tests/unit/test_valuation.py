import numpy as np
import pandas as pd
import pytest

from factories import proj_frame, proj_row, varied_projections
from fdo.valuation import value_players
from fdo.valuation.pool import basis_frame, category_values, compute_pool_stats, iterate_pool
from fdo.types import STATS
from fdo.valuation.weights import WeightError, preset, validate_weights, weighted_value


def test_less_turnovers_scores_higher(config):
    df = proj_frame([proj_row("a", tov=1.0), proj_row("b", tov=4.0), proj_row("c", tov=2.5)])
    t = value_players(df, config, pool_size=3).table
    assert t.loc["a", "TOV"] > t.loc["c", "TOV"] > t.loc["b", "TOV"]


def test_fg_volume_example(config):
    """§6.2.3: p̄ = 0.47; A 3 FGA %55, B 20 FGA %52 → B'nin FG katkısı daha büyük."""
    x = pd.DataFrame({s: [0.0, 0.0] for s in STATS}, index=["A", "B"])
    x["fgm"] = [1.65, 10.4]
    x["fga"] = [3.0, 20.0]
    vals = category_values(x, config, {"FG_PCT": 0.47, "FT_PCT": 0.0})
    assert vals.loc["A", "FG_PCT"] == pytest.approx(0.24)
    assert vals.loc["B", "FG_PCT"] == pytest.approx(1.00)
    assert vals.loc["B", "FG_PCT"] > vals.loc["A", "FG_PCT"]


def test_impact_sums_to_zero_over_pool(config):
    x = basis_frame(varied_projections(), "total")
    stats = compute_pool_stats(x, x.index, config)
    vals = category_values(x, config, stats.pbar)
    assert abs(vals["FG_PCT"].sum()) < 1e-6
    assert abs(vals["FT_PCT"].sum()) < 1e-6


def test_zero_sigma_does_not_crash_and_warns(config):
    rows = [proj_row(f"p{i}", fgm=4 + i, fga=9 + 2 * i, stl=1.0) for i in range(5)]
    res = value_players(proj_frame(rows), config, pool_size=5)
    assert (res.table["STL"] == 0).all()
    assert any("STL" in w for w in res.warnings)


def test_pool_iteration_stops_within_ten(config):
    x = basis_frame(varied_projections(200, seed=3), "total")
    stats = iterate_pool(x, config, size=50)
    assert stats.n_iter <= 10
    assert stats.size == 50


def test_g_equals_z_when_tau_zero(config):
    df = varied_projections()
    z = value_players(df, config, method="z", pool_size=40).table
    g = value_players(df, config, method="g", pool_size=40, kappa=0.0).table
    cats = list(config.categories)
    np.testing.assert_allclose(g[cats].to_numpy(), z.loc[g.index, cats].to_numpy())


def test_g_shrinks_with_within_variance(config):
    df = varied_projections()
    z = value_players(df, config, method="z", pool_size=40).table
    g = value_players(df, config, method="g", pool_size=40, kappa=1.0).table
    assert g["STL"].abs().max() < z["STL"].abs().max()


def test_zero_weight_makes_value_independent_of_category(config):
    df = varied_projections()
    w = validate_weights(config, {"FT_PCT": 0.0})
    scores = value_players(df, config, weights=w, pool_size=40).scores
    v1 = weighted_value(scores, w)
    changed = scores.copy()
    changed["FT_PCT"] = changed["FT_PCT"] * -7 + 3   # yalnızca FT skoru değişiyor
    v2 = weighted_value(changed, w)
    pd.testing.assert_series_equal(v1, v2)
    assert not weighted_value(changed, validate_weights(config, {})).equals(v1)


def test_weights_do_not_change_pool_stats(config):
    df = varied_projections()
    a = value_players(df, config, pool_size=40)
    b = value_players(df, config, weights=preset(config, "punt_FT_TO"), pool_size=40)
    assert a.stats == b.stats


def test_weight_bounds(config):
    with pytest.raises(WeightError):
        validate_weights(config, {"PTS": 3.5})
    with pytest.raises(WeightError):
        validate_weights(config, {"XYZ": 1.0})


def test_missing_stat_excluded_not_zero(config):
    df = varied_projections(20)
    df.loc[3, "reb"] = np.nan
    t = value_players(df, config, pool_size=10).table
    assert df.loc[3, "player_id"] not in t.index
