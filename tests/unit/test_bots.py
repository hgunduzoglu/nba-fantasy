import copy

import numpy as np
import pytest

from fdo.bots.league_mix import assign_profiles
from fdo.bots.mock import BotLeague, MockDraft
from fdo.bots.thurstone import BatchDraft, pick_rng, scaled_t
from fdo.draft.state import state_from_log
from fdo.roster.assignment import RosterModel

ONLY_MARKET = {"MarketFollower": 15, "ValueHunter": 0, "PositionAware": 0, "PuntBuilder": 0,
               "RandomHuman": 0, "AutoDrafter": 0}


def test_profile_assignment(config):
    names = assign_profiles(config, np.random.default_rng(0))
    assert len(names) == 16
    assert names[15] == config.model.bots.user_auto_profile
    opp = names[:15]
    assert opp.count("MarketFollower") == 6 and opp.count("AutoDrafter") == 1


def test_scaled_t_has_unit_variance():
    x = scaled_t(np.random.default_rng(1), 5.0, 400_000)
    assert x.var() == pytest.approx(1.0, abs=0.03)


def test_same_seed_same_draft(universe, config):
    a = BatchDraft(universe, config, 3, seed=99)
    b = BatchDraft(universe, config, 3, seed=99)
    a.run_until(209)
    b.run_until(209)
    np.testing.assert_array_equal(a.pick_player, b.pick_player)
    c = BatchDraft(universe, config, 3, seed=100)
    c.run_until(209)
    assert not np.array_equal(a.pick_player, c.pick_player)


def test_sim_streams_do_not_depend_on_batch_size(universe, config):
    a = BatchDraft(universe, config, 4, seed=5)
    b = BatchDraft(universe, config, 1, seed=5, sim_offset=2)
    a.run_until(60)
    b.run_until(60)
    np.testing.assert_array_equal(a.pick_player[2, :59], b.pick_player[0, :59])


def test_zero_sigma_follows_adp_order(universe, config):
    cfg = config.with_overrides({"model": {"bots": {
        "mix": ONLY_MARKET, "beta_need": 0.0, "beta_stack": 0.0,
        "enforce_completion_feasibility": False}}})
    u = copy.copy(universe)
    u.sigma = np.zeros_like(universe.sigma)
    b = BatchDraft(u, cfg, 2, seed=3)
    b.run_until(209)
    expected = np.argsort(u.adp, kind="stable")[:208]
    np.testing.assert_array_equal(b.pick_player[0], expected)
    np.testing.assert_array_equal(b.pick_player[1], expected)


def test_feasibility_completes_all_rosters(universe, config):
    b = BatchDraft(universe, config, 60, seed=11)
    b.run_until(209)
    model = RosterModel(config)
    for s in range(b.S):
        for seat in range(1, 17):
            players = b.roster_matrix(seat)[s]
            pos = [universe.groups[universe.group[p]] for p in players]
            assert model.open_active_count(pos) == 0, (s, seat)


def test_perceived_ranking_is_consistent_within_draft(universe, config):
    b = BatchDraft(universe, config, 1, seed=8)
    seat = 3
    sig = universe.sigma * b.ptab.sigma_mult[b.profile[0, seat - 1]]
    q = b.q_raw[0, seat - 1]
    r1 = q + config.model.bots.jitter_rho * sig * pick_rng(8, 0, 3).standard_normal(universe.n)
    r2 = q + config.model.bots.jitter_rho * sig * pick_rng(8, 0, 120).standard_normal(universe.n)
    rank = lambda v: np.argsort(np.argsort(v))
    rho = np.corrcoef(rank(r1), rank(r2))[0, 1]
    assert rho > 0.99


def test_mock_draft_undo_replays_identically(synthetic_ds, universe, config):
    m = MockDraft(synthetic_ds, config, seed=4, universe=universe)
    m.play_until_user()
    assert m.log.next_seat == 16 and m.log.next_pick == 16
    first = m.log
    m.play_to_end()
    full = m.log
    m.truncate(10)
    assert m.log.picks == first.picks[:9]
    m.play_until_user()
    assert [p.player_id for p in m.log.picks] == [p.player_id for p in first.picks]
    m.set_log(full)
    m.undo()
    m.play_next()
    assert [p.player_id for p in m.log.picks] == [p.player_id for p in full.picks]


def test_bot_league_choose_matches_mock(synthetic_ds, universe, config):
    m = MockDraft(synthetic_ds, config, seed=4, universe=universe)
    m.play_until_user()
    taken = m.log.taken
    user_pick = next(str(universe.ids[i]) for i in np.argsort(universe.adp)[40:]
                     if universe.ids[i] not in taken)
    m.pick(user_pick)
    league = BotLeague(BatchDraft(universe, config, 1, 4))
    state = state_from_log(m.log, config, synthetic_ds.draft_ids)
    pid = league.choose(state.next_seat, state)
    assert pid == m.play_next()
