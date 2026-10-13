import dataclasses

import numpy as np
import pytest

from fdo.advisor.pairs import recommend
from fdo.advisor.simulate import make_engine, prepare_context, team_vectors
from fdo.advisor.uncertainty import multipliers, player_params
from fdo.bots.mock import MockDraft


@pytest.fixture(scope="module")
def ctx(synthetic_ds, universe, config):
    cfg = config.with_overrides({"model": {"advisor": {"m_pairs_to_rollout": 4, "sims_per_pair_fast": 120}}})
    return prepare_context(synthetic_ds, cfg, seed=8, universe=universe, fill_sims=30)


def test_multipliers_mean_one_and_crn(ctx):
    m = multipliers(ctx, np.arange(400), seed=3)
    has = ctx.has_vec
    assert m.shape == (400, ctx.universe.n)
    assert abs(m[:, has].mean() - 1.0) < 0.01
    assert (m[:, ~has] == 1.0).all()
    assert np.allclose(multipliers(ctx, np.arange(390, 400), seed=3), m[390:])   # sim kimliği → aynı senaryo


def test_rookies_have_wider_spread(ctx):
    players = ctx.dataset.players.copy()
    rookie_ids = set(ctx.universe.ids[:50])
    players["is_rookie"] = players["player_id"].isin(rookie_ids)
    rctx = dataclasses.replace(ctx, dataset=dataclasses.replace(ctx.dataset, players=players))
    _, kappa, role = player_params(rctx)
    assert kappa[0] == rctx.config.model.scenarios.rookie_gp_kappa and role[0] > role[-1]
    m = multipliers(rctx, np.arange(300), seed=1)
    assert m[:, :50].std() > m[:, 50:][:, ctx.has_vec[50:]].std()


def test_team_vectors_unit_multiplier_is_identity(ctx, synthetic_ds, config):
    m = MockDraft(synthetic_ds, config, seed=2, universe=ctx.universe)
    m.play_until_user()
    eng = make_engine(ctx, m.log, 3, seed=1)
    a = team_vectors(eng, ctx.vecs, ctx.base_fill, m.log.next_pick)
    b = team_vectors(eng, ctx.vecs, ctx.base_fill, m.log.next_pick, np.ones((3, ctx.universe.n)))
    assert np.allclose(a, b)


def test_uncertainty_widens_outcomes(ctx, synthetic_ds, config):
    m = MockDraft(synthetic_ds, config, seed=4, universe=ctx.universe)
    m.play_until_user()
    for _ in range(2):                           # birkaç gerçek oyuncu: senaryo etkisi görünür
        m.pick(next(str(i) for i in ctx.universe.ids[np.argsort(ctx.universe.adp)]
                    if str(i) not in m.log.taken and m.is_allowed(str(i))))
        m.play_until_user()
    base = recommend(ctx, m.log, mode="fast")
    unc = recommend(ctx, m.log, mode="fast", uncertainty=True)
    assert unc.params["uncertainty"] and "sakatlık/rol senaryoları (κ, σ_r)" in unc.uncalibrated
    b0 = {p.label: p for p in base.pairs}
    common = [p for p in unc.pairs if p.label in b0]
    assert common
    for p in common:
        assert abs(p.mean - b0[p.label].mean) < 0.15
    assert np.mean([p.p90 - p.p10 for p in common]) > np.mean([b0[p.label].p90 - b0[p.label].p10 for p in common])
