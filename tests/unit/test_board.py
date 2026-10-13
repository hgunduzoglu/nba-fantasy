import numpy as np
import pytest

from fdo.advisor.board import category_board
from fdo.advisor.pairs import setup_problem
from fdo.advisor.rollout import delta_ecw
from fdo.advisor.simulate import prepare_context
from fdo.bots.mock import MockDraft


@pytest.fixture(scope="module")
def ctx(synthetic_ds, universe, config):
    return prepare_context(synthetic_ds, config, seed=42, universe=universe, fill_sims=40)


def test_board_matches_delta_ecw_on_the_clock(ctx, synthetic_ds, config):
    m = MockDraft(synthetic_ds, config, seed=5, universe=ctx.universe)
    m.play_until_user()
    b = category_board(ctx, m.log, n_sims=16)
    assert b.on_clock and b.pick == m.log.next_pick and b.avail_pick > b.pick
    prob = setup_problem(ctx, m.log, ctx.base_fill)
    t1 = prob.turn[0]
    base = prob.roster_vec + prob.fill_sum([n for n in prob.turn + prob.after_turn if n != t1])
    ref = delta_ecw(prob, base, t1, prob.available)
    idx = [ctx.universe.index[p] for p in b.table["player_id"]]
    np.testing.assert_allclose(b.table["delta_ecw"], ref[idx], atol=1e-9)
    d = b.table[[f"d_{c}" for c in config.categories]].sum(axis=1)
    np.testing.assert_allclose(d, b.table["delta_ecw"], atol=1e-9)
    assert b.table["delta_ecw"].is_monotonic_decreasing
    assert not set(b.table["player_id"]) & m.log.taken


def test_board_while_waiting_and_weights(ctx, synthetic_ds, config):
    m = MockDraft(synthetic_ds, config, seed=5, universe=ctx.universe)
    for _ in range(5):
        m.play_next()
    b = category_board(ctx, m.log, n_sims=16)
    assert not b.on_clock and b.avail_pick == b.pick == config.league.my_seat
    assert b.table["p_avail"].between(0, 1).all()
    w = {c: (0.0 if c == "FT_PCT" else 1.0) for c in config.categories}
    bw = category_board(ctx, m.log, n_sims=0, category_weights=w)
    t = bw.table
    np.testing.assert_allclose(t["score"], t["delta_ecw"] - t["d_FT_PCT"], atol=1e-9)
    assert t["p_avail"].isna().all()


def test_perf_levels_and_scarcity():
    import pandas as pd

    from fdo.advisor.board import perf_level, scarcity

    assert [perf_level(z) for z in (2.0, 1.2, 0.6, 0.0, -0.7, -3.0)] == \
        ["Elite", "Great", "Good", "Avg", "Below", "Poor"]
    t = pd.DataFrame({"z_PTS": [2.0, 1.6, 0.7, -2.0], "z_BLK": [0.0, 0.0, 1.1, 0.2]})
    s = scarcity(t, ["PTS", "BLK"])
    assert s["PTS"].tolist() == [2, 0, 1] and s["BLK"].tolist() == [0, 1, 0]
