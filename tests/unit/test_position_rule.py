import copy

import numpy as np
import pytest

from fdo.bots.mock import MockDraft
from fdo.bots.thurstone import BatchDraft
from fdo.draft.events import DraftError, DraftLog
from fdo.draft.rules import check_pick, validate_log
from fdo.roster.assignment import RosterModel

C = frozenset({"C"})
PG = frozenset({"PG"})


def center_heavy_log(config, n_centers_for_seat1: int):
    """Seat 1 yalnızca C alır, diğerleri PG."""
    positions = {f"c{i}": C for i in range(20)} | {f"f{i}": PG for i in range(300)}
    log = DraftLog.new(config)
    ci = fi = 0
    while True:
        if log.next_seat == 1:
            if ci == n_centers_for_seat1:
                return log, positions
            log = log.make_pick(f"c{ci}")
            ci += 1
        else:
            log = log.make_pick(f"f{fi}")
            fi += 1


def test_rule_rejects_pick_that_makes_roster_uncompletable(config):
    log, pos = center_heavy_log(config, 7)          # 7 C: eksik 6 aktif slot, kalan 6 pick
    assert log.next_seat == 1
    with pytest.raises(DraftError, match="Pozisyon kuralı"):
        check_pick(log, "c7", pos, config)          # 8. C → kalan 5 pick, 6 eksik slot
    check_pick(log, "f299", pos, config)            # PG kabul


def test_rule_off_allows_everything(config):
    off = config.with_overrides({"unverified": {"position_limits_enforced_in_draft": False}})
    log, pos = center_heavy_log(off, 7)
    check_pick(log, "c7", pos, off)
    bad = log.make_pick("c7")
    validate_log(bad, pos, off)
    with pytest.raises(DraftError):
        validate_log(bad, pos, config)


def test_mock_enforces_rule_for_user_and_import(synthetic_ds, universe, config):
    m = MockDraft(synthetic_ds, config, seed=1, universe=universe)
    pos = synthetic_ds.positions()
    centers = [p for p in universe.ids if pos[p] == C]
    others = [p for p in universe.ids if "C" not in pos[p]]
    model = RosterModel(config)
    rejected = False
    while not m.log.is_complete:
        if m.log.next_seat == m.my_seat:
            cand = next(p for p in centers if p not in m.log.taken)
            if m.is_allowed(cand):
                m.pick(cand)
            else:
                rejected = True
                with pytest.raises(DraftError):
                    m.pick(cand)
                m.pick(next(p for p in others if p not in m.log.taken and m.is_allowed(p)))
        else:
            m.play_next()
    assert rejected
    mine = [pos[p.player_id] for p in m.log.picks if p.seat == m.my_seat]
    assert model.open_active_count(mine) == 0


def test_bots_obey_rule_even_if_feasibility_flag_off(universe, config):
    cfg = config.with_overrides({"model": {"bots": {"enforce_completion_feasibility": False}}})
    b = BatchDraft(copy.copy(universe), cfg, 20, seed=3)
    assert b.enforce_feasibility
    b.run_until(209)
    model = RosterModel(cfg)
    for s in range(b.S):
        for seat in range(1, 17):
            players = b.roster_matrix(seat)[s]
            assert model.open_active_count([universe.groups[universe.group[p]] for p in players]) == 0


def test_advisor_augments_candidates_when_no_pair_is_feasible(synthetic_ds, universe, config):
    """10 C-olmayan oyuncu + iki C slotu açık: yalnızca C-olmayan adaylarla hiçbir çift geçerli değil."""
    import numpy as np

    from fdo.advisor.pairs import feasible_combos, setup_problem
    from fdo.advisor.rollout import delta_ecw
    from fdo.advisor.simulate import prepare_context
    from fdo.bots.mock import MockDraft

    ctx = prepare_context(synthetic_ds, config, seed=1, universe=universe, fill_sims=20)
    m = MockDraft(synthetic_ds, config, seed=3, universe=universe)
    pos = synthetic_ds.positions()
    order = [str(universe.ids[i]) for i in np.argsort(universe.adp)]
    while True:
        m.play_until_user()
        if m.log.next_pick >= 176:
            break
        pid = next(p for p in order if p not in m.log.taken and "C" not in pos[p] and m.is_allowed(p))
        m.pick(pid, "user")
    assert m.log.next_pick == 176
    prob = setup_problem(ctx, m.log, ctx.base_fill)
    base = prob.roster_vec + prob.fill_sum([177, *prob.after_turn])
    delta = delta_ecw(prob, base, 176, prob.available)
    non_c = [universe.index[p] for p in order if p not in m.log.taken and "C" not in pos[p]][:4]
    cands, feasible = feasible_combos(prob, non_c, delta)
    assert feasible and len(cands) > 4
    assert all(any("C" in universe.groups[universe.group[i]] for i in c) for c in feasible)
