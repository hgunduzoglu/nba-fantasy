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
