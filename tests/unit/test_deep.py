import numpy as np
import pytest

from fdo.advisor.deep import deep_recommend, full_rollout, successive_halving
from fdo.advisor.pairs import recommend, setup_problem
from fdo.advisor.simulate import prepare_context
from fdo.bots.mock import MockDraft


@pytest.fixture(scope="module")
def setup(synthetic_ds, universe, config):
    cfg = config.with_overrides({"model": {"advisor": {"m_pairs_to_rollout": 6, "sims_per_pair_fast": 30}}})
    ctx = prepare_context(synthetic_ds, cfg, seed=3, universe=universe, fill_sims=30)
    m = MockDraft(synthetic_ds, cfg, seed=5, universe=universe)
    m.play_until_user()
    return ctx, m.log, recommend(ctx, m.log, mode="fast")


def test_full_rollout_crn_and_offset(setup):
    ctx, log, base = setup
    prob = setup_problem(ctx, log, ctx.base_fill)
    combo = tuple(int(ctx.universe.index[p]) for p in base.pairs[0].players)
    a = full_rollout(prob, log, combo, 6, seed=11, sim_offset=0, shortlist_k=20)
    b = full_rollout(prob, log, combo, 3, seed=11, sim_offset=3, shortlist_k=20)
    assert a.shape == (6,) and np.allclose(a[3:], b)          # aynı sim kimliği → aynı sonuç
    assert ((a > 0) & (a < 9)).all()


def test_successive_halving_keeps_best():
    means = {0: 1.0, 1: 3.0, 2: 2.0, 3: 0.5}
    W, reached = successive_halving(lambda i, n, off: np.full(n, means[i]), [0, 1, 2, 3], (4, 4, 8))
    assert reached == {0: 0, 1: 2, 2: 2, 3: 0}               # 4 → 2 → 2 (en az 2 çift kalır)
    assert len(W[1]) == 16 and len(W[0]) == 4


def test_deep_recommend_ranks_survivors_first(setup):
    ctx, log, base = setup
    res = deep_recommend(ctx, log, base, n_pairs=4, rungs=(6, 6))
    t = res.table()
    assert len(t) == 4 and t["basamak"].iloc[0] == 2 and t["sims"].iloc[0] == 12
    assert set(t["pair"]) == {p.label for p in base.pairs[:4]}


def test_deep_with_uncertainty_runs(setup):
    ctx, log, base = setup
    res = deep_recommend(ctx, log, base, n_pairs=2, rungs=(4,), uncertainty=True)
    assert res.params["uncertainty"] and len(res.pairs) == 2
    assert all(((p.W > 0) & (p.W < 9)).all() for p in res.pairs)
