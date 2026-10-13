import pytest

from fdo.advisor.scenarios import archetype_label, run_scenarios
from fdo.advisor.simulate import prepare_context
from fdo.bots.mock import MockDraft


@pytest.fixture(scope="module")
def setup(synthetic_ds, universe, config):
    ctx = prepare_context(synthetic_ds, config, seed=4, universe=universe, fill_sims=20)
    m = MockDraft(synthetic_ds, config, seed=2, universe=universe)
    m.play_until_user()
    return ctx, m.log


def test_scenarios_group_final_rosters(setup, config):
    ctx, log = setup
    r = run_scenarios(ctx, log, n_sims=16, seed=1)
    assert 1 <= len(r.archetypes) <= 5
    assert sum(a.frequency for a in r.archetypes) <= 1.0 + 1e-9
    for a in r.archetypes:
        assert len(a.typical_roster) == config.league.rounds
        # imzadaki kategoriler her üyede kaybedilmiş → ortalaması da eşiğin altında
        assert all(p < config.model.matchup.lost_threshold
                   for c, p in zip(config.categories, a.cat_p) if c in a.signature)
    again = run_scenarios(ctx, log, n_sims=16, seed=1)
    assert [a.signature for a in again.archetypes] == [a.signature for a in r.archetypes]


def test_archetype_label():
    assert archetype_label(()).startswith("dengeli")
    assert archetype_label(("FT_PCT", "TOV")) == "punt FT%+TO benzeri"


def test_compare_punt_plans(synthetic_ds, universe, config):
    from fdo.advisor.scenarios import compare_punt_plans
    from fdo.advisor.simulate import prepare_context
    from fdo.bots.mock import MockDraft

    ctx = prepare_context(synthetic_ds, config, seed=2, universe=universe, fill_sims=20)
    m = MockDraft(synthetic_ds, config, seed=6, universe=universe)
    m.play_until_user()
    r = compare_punt_plans(ctx, m.log, n_sims=8, plans=[(), ("FT_PCT",), ("FT_PCT", "TOV")])
    t = r.table.set_index("plan")
    assert set(t.index) == {"dengeli", "punt FT%", "punt FT%+TO"}
    assert t.loc["dengeli", "fark"] == 0.0
    assert t.loc["punt FT%", "FT%"] < t.loc["dengeli", "FT%"]          # punt edilen kategori düşer
    assert r.best["E[W]"] == t["E[W]"].max()


def test_punt_plans_while_waiting(synthetic_ds, universe, config):
    from fdo.advisor.scenarios import compare_punt_plans

    ctx = prepare_context(synthetic_ds, config, seed=2, universe=universe, fill_sims=20)
    m = MockDraft(synthetic_ds, config, seed=2, universe=universe)
    for _ in range(4):
        m.play_next()
    r = compare_punt_plans(ctx, m.log, n_sims=4, plans=[(), ("FT_PCT",)])
    assert len(r.table) == 2 and r.table["E[W]"].between(0, 9).all()


def test_play_draft_forced_pair_and_adaptive_policy(synthetic_ds, universe, config):
    import numpy as np

    from fdo.advisor.scenarios import play_draft
    from fdo.draft.events import DraftLog

    ctx = prepare_context(synthetic_ds, config, seed=2, universe=universe, fill_sims=20)
    lg = config.league
    log = DraftLog(lg.teams, lg.rounds, lg.third_round_reversal)
    pair = [int(i) for i in np.argsort(universe.adp, kind="stable")[:2]]     # normalde 16'ya kalmazlar
    C = len(config.categories)
    seen = []

    def policy(ti, team_p):
        seen.append(ti)
        return np.where(team_p < team_p.min(axis=1, keepdims=True) + 1e-12, 0.0, 1.0)  # en zayıfı punt

    r = play_draft(ctx, log, 3, seed=1, policy=policy, forced={lg.my_seat: pair[0], lg.my_seat + 1: pair[1]},
                   reserve=pair)
    assert (r.rosters[:, 0] == pair[0]).all() and (r.rosters[:, 1] == pair[1]).all()
    assert not np.isin(r.engine.pick_player[:, : lg.my_seat - 1], pair).any()
    assert seen[0] == 1 and np.isnan(r.weights[0]).all()
    assert ((r.weights[1:] == 0).sum(axis=-1) >= 1).all() and r.weights.shape[-1] == C
    assert (r.rosters >= 0).all() and r.P.shape == (3, lg.teams - 1, C)
