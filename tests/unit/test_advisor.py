import numpy as np
import pytest

from fdo.advisor.pairs import AdvisorError, recommend, setup_problem
from fdo.advisor.rollout import largest_gap_tiers, rollout_pair
from fdo.advisor.simulate import make_engine, prepare_context
from fdo.bots.mock import MockDraft
from fdo.draft.events import DraftLog
from fdo.ingest import build_dataset
from fdo.ingest.synthetic import synthetic_frames, synthetic_manifest

ONLY_MARKET = {"MarketFollower": 15, "ValueHunter": 0, "PositionAware": 0, "PuntBuilder": 0,
               "RandomHuman": 0, "AutoDrafter": 0}


@pytest.fixture(scope="module")
def ctx(synthetic_ds, universe, config):
    return prepare_context(synthetic_ds, config, seed=42, universe=universe, fill_sims=40)


@pytest.fixture(scope="module")
def log16(ctx, synthetic_ds, config):
    m = MockDraft(synthetic_ds, config, seed=5, universe=ctx.universe)
    m.play_until_user()
    return m.log


# --- deterministik (σ → 0) oyuncak dünya ----------------------------------

@pytest.fixture(scope="module")
def det(config):
    cfg = config.with_overrides({"model": {"bots": {
        "mix": ONLY_MARKET, "sigma0": 0.0, "sigma1": 0.0, "sigma_floor": 0.0,
        "beta_need": 0.0, "beta_stack": 0.0}}})
    players, proj, adp = synthetic_frames(300, np.random.default_rng(3), cfg, as_of="2026-10-01")
    adp = adp.assign(adp_std=np.nan, default_rank=np.nan, pct_drafted=np.nan)
    # X: değerli bir oyuncu, ADP 150 (48'e kesin kalır); Y: X'in birebir kopyası, ADP 25 (kesin gider)
    from fdo.valuation import balanced_value_rank
    vr = balanced_value_rank(proj, cfg)
    x_id = vr.sort_values().index[5]
    y_id = vr.sort_values().index[-1]
    stats = [c for c in proj.columns if c not in ("player_id",)]
    proj.loc[proj.player_id == y_id, stats] = proj.loc[proj.player_id == x_id, stats].to_numpy()
    players.loc[players.player_id == y_id, "yahoo_positions"] = \
        players.loc[players.player_id == x_id, "yahoo_positions"].to_numpy()
    adp.loc[adp.player_id == x_id, "adp"] = 140.0
    adp.loc[adp.player_id == y_id, "adp"] = 25.0
    manifests = {k: synthetic_manifest(k, f"<mem>/{k}", "2026-10-01", 3)
                 for k in ("players", "projections", "adp")}
    ds, rep = build_dataset(players, proj, adp, cfg, manifests=manifests)
    assert ds is not None, rep.errors
    context = prepare_context(ds, cfg, seed=1, fill_sims=20)
    m = MockDraft(ds, cfg, seed=1, universe=context.universe)
    m.play_until_user()
    return context, m.log, x_id, y_id


def test_deterministic_survival_is_zero_one_and_matches_adp_order(det):
    context, log, _, _ = det
    u = context.universe
    eng = make_engine(context, log, 20, seed=0)
    order = [i for i in np.argsort(u.adp, kind="stable") if eng.taken_at[0, i] == 0]
    a, b = int(order[0]), int(order[1])
    eng.force(a)
    eng.force(b)
    eng.run_until(48)
    p = np.mean(eng.taken_at == 0, axis=0)
    assert set(np.unique(p)) <= {0.0, 1.0}
    gone = set(order[2:32])          # 18..47 arası 30 rakip pick'i ADP sırasıyla
    for i in order[:60]:
        if i in (a, b):
            continue
        assert p[i] == (0.0 if i in gone else 1.0), i


def test_toy_problem_take_the_one_that_will_not_last(det):
    context, log, x_id, y_id = det
    names = context.dataset.names()
    res = recommend(context, log, n_sims=30, pinned_players=[x_id, y_id], conditional_fill=False)
    cands = res.candidates.set_index("player_id")
    assert cands.loc[x_id, "delta_ecw"] == pytest.approx(cands.loc[y_id, "delta_ecw"])
    assert cands.loc[x_id, "p_surv_next"] == 1.0 and cands.loc[y_id, "p_surv_next"] == 0.0
    with_one = [p for p in res.pairs if (x_id in p.players) != (y_id in p.players)]
    assert with_one and y_id in with_one[0].players
    # aynı partnerle doğrudan karşılaştırma
    partner = next(p for p in res.candidates.player_id if p not in (x_id, y_id))
    res2 = recommend(context, log, n_sims=30, conditional_fill=False,
                     pinned_pairs=[(x_id, partner), (y_id, partner)])
    ex = next(p for p in res2.pairs if set(p.players) == {x_id, partner})
    ey = next(p for p in res2.pairs if set(p.players) == {y_id, partner})
    assert ey.mean > ex.mean, (names[x_id], names[y_id])


# --- genel özellikler -----------------------------------------------------

def test_pairs_are_unordered(ctx, log16):
    prob = setup_problem(ctx, log16, ctx.base_fill)
    eng = make_engine(ctx, log16, 30, seed=9)
    snap = eng.snapshot()
    avail = np.flatnonzero(prob.available & ctx.has_vec)
    a, b = int(avail[0]), int(avail[1])
    w1 = rollout_pair(prob, eng, snap, (a, b)).W
    w2 = rollout_pair(prob, eng, snap, (b, a)).W
    np.testing.assert_array_equal(w1, w2)


def test_crn_same_seed_same_result(ctx, log16):
    r1 = recommend(ctx, log16, n_sims=30, conditional_fill=False)
    r2 = recommend(ctx, log16, n_sims=30, conditional_fill=False)
    assert [p.players for p in r1.pairs] == [p.players for p in r2.pairs]
    assert [p.mean for p in r1.pairs] == [p.mean for p in r2.pairs]
    prob = setup_problem(ctx, log16, ctx.base_fill)
    eng = make_engine(ctx, log16, 30, seed=9)
    snap = eng.snapshot()
    pair = tuple(sorted(np.flatnonzero(prob.available & ctx.has_vec)[:2].tolist()))
    d = rollout_pair(prob, eng, snap, pair).W - rollout_pair(prob, eng, snap, pair).W
    assert np.all(d == 0)


def test_se_shrinks_like_inverse_sqrt(ctx, log16):
    prob = setup_problem(ctx, log16, ctx.base_fill)
    pair = tuple(sorted(np.flatnonzero(prob.available & ctx.has_vec)[:2].tolist()))
    se = {}
    for S in (50, 200):
        eng = make_engine(ctx, log16, S, seed=13)
        W = rollout_pair(prob, eng, eng.snapshot(), pair).W
        se[S] = W.std(ddof=1) / np.sqrt(S)
    assert 1.4 < se[50] / se[200] < 2.8


def test_result_contents(ctx, log16):
    res = recommend(ctx, log16, n_sims=30)
    assert res.turn == (16, 17) and res.next_turn == (48, 49)
    assert len(res.pairs) >= 5
    top = res.pairs[0]
    assert top.tier == 1 and top.regret == 0.0
    assert {"p_surv", "se", "adp_eff", "adp_status", "go_p50"} <= set(top.outcome.pool.columns)
    assert top.outcome.pool["p_surv"].gt(0).all()
    assert top.outcome.next_choices["probability"].sum() == pytest.approx(1.0)
    assert top.outcome.cat_p.shape == (30, 9)
    assert "wait_cost" in res.candidates
    assert res.params["S"] == 30 and res.params["fill"] == "conditional"


def test_single_pick_turn_208(ctx, synthetic_ds, config):
    m = MockDraft(synthetic_ds, config, seed=6, universe=ctx.universe)
    while m.log.next_pick < 208:
        m.play_next()
    res = recommend(ctx, m.log, n_sims=20, conditional_fill=False)
    assert res.turn == (208,) and res.next_turn is None
    assert all(len(p.players) == 1 for p in res.pairs)
    assert res.pairs[0].outcome.pool.empty


def test_not_users_turn_raises(ctx, config):
    with pytest.raises(AdvisorError):
        recommend(ctx, DraftLog.new(config), n_sims=10)


def test_largest_gap_tiers():
    v = np.array([1.0, 0.95, 0.5, 0.48, 0.1])
    assert largest_gap_tiers(v, 3).tolist() == [1, 1, 2, 2, 3]


def test_category_weights_change_objective(ctx, log16):
    base = recommend(ctx, log16, mode="fast", n_sims=30)
    punt = recommend(ctx, log16, mode="fast", n_sims=30, category_weights={"FT_PCT": 0.0, "TOV": 0.0})
    assert base.params["category_weights"] is None and punt.params["category_weights"]["FT_PCT"] == 0.0
    for p in punt.pairs:
        assert p.mean < p.ecw                                    # iki kategori sıfır → ağırlıklı < ECW
    for p in base.pairs:
        assert abs(p.mean - p.ecw) < 1e-9
    with pytest.raises(AdvisorError):
        recommend(ctx, log16, mode="fast", n_sims=10, category_weights={"XYZ": 1.0})
