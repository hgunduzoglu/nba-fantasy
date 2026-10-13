import numpy as np
import pandas as pd
import pytest

from fdo.calibration.variance import synthetic_gamelogs
from fdo.evaluation import SeasonEvaluator
from fdo.evaluation.backtest import build_strategies, play, run_backtest
from fdo.evaluation.evaluators import GameLogEvaluator, ProjectionNoiseEvaluator, all_play


def test_all_play_scoring_and_ties(config):
    cats = list(config.categories)
    a = pd.DataFrame([[1.0] * 9], columns=cats)
    b = pd.DataFrame([[0.0] * 9], columns=cats)
    c = pd.DataFrame([[0.0] * 9], columns=cats)
    res = all_play({1: a, 2: b, 3: c}, config, "x")
    # TOV düşük iyi: A 8 kategoride kazanır, TOV'da kaybeder
    assert res.category_wins[1] == pytest.approx(8.0)
    assert res.category_wins[2] == pytest.approx((1 + 0.5 * 9) / 2)      # A'ya karşı 1, C ile 9 beraberlik
    assert res.category_rates[1]["TOV"] == 0.0


def test_projection_noise_evaluator_is_seeded(synthetic_ds, config):
    ev1 = ProjectionNoiseEvaluator(synthetic_ds.projections, config, seed=3)
    ev2 = ProjectionNoiseEvaluator(synthetic_ds.projections, config, seed=3)
    assert isinstance(ev1, SeasonEvaluator)
    ids = list(synthetic_ds.projections["player_id"])
    rosters = {s: ids[(s - 1) * 13: s * 13] for s in range(1, 17)}
    r1, r2 = ev1.evaluate(rosters, "2026-27"), ev2.evaluate(rosters, "2026-27")
    assert r1.category_wins == r2.category_wins and "iyimser" in r1.notes[0]
    assert sum(r1.category_wins.values()) == pytest.approx(16 * 4.5, abs=1e-6)   # all-play toplamı sabit
    assert r1.category_wins[1] > r1.category_wins[16]                             # en iyi 13 > en kötü 13


def test_gamelog_evaluator_counts_daily_lineup(synthetic_ds, config):
    proj = synthetic_ds.projections.head(32)
    logs = synthetic_gamelogs(proj, 20, np.random.default_rng(0))
    ev = GameLogEvaluator(logs, synthetic_ds.positions(), config)
    ids = list(proj["player_id"])
    res = ev.evaluate({1: ids[:13], 2: ids[13:26]}, "2025-26")
    assert set(res.category_wins) == {1, 2}
    assert res.category_wins[1] + res.category_wins[2] == pytest.approx(9.0)


def test_play_and_backtest(synthetic_ds, universe, config):
    strats = build_strategies(["adp", "z"], synthetic_ds, config, universe, seed=1)
    rosters = play(synthetic_ds, config, universe, strats["z"], seed=4)
    assert all(len(r) == 13 for r in rosters.values())
    res = run_backtest(synthetic_ds, config, universe, strats,
                       lambda d: ProjectionNoiseEvaluator(synthetic_ds.projections, config, seed=d), 3)
    s = res.summary()
    assert set(s.index) == {"adp", "z"} and (s["drafts"] == 3).all()
    assert s["rank"].between(1, 16).all()
    assert len(res.paired("adp")) == 1


@pytest.mark.slow
def test_ecw_strategy_plays_full_draft(synthetic_ds, universe, config):
    strats = build_strategies(["ecw"], synthetic_ds, config, universe, seed=1)
    rosters = play(synthetic_ds, config, universe, strats["ecw"], seed=2)
    assert len(rosters[config.league.my_seat]) == 13


def test_backtest_script(tmp_path, config):
    from backtest import main

    from fdo.ingest.synthetic import write_synthetic

    write_synthetic(tmp_path, 260, 2, config, "2026-10-01")
    assert main(["--data", str(tmp_path), "--n", "2", "--strategies", "adp,z", "--out", str(tmp_path / "rep")]) == 0
    text = (tmp_path / "rep" / "backtest.md").read_text(encoding="utf-8")
    assert "iyimser" in text and "| z |" in text
