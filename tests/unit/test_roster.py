import numpy as np
import pytest

from fdo.roster.assignment import GroupOracle, RosterModel, can_complete
from fdo.roster.eligibility import eligible_slots, parse_positions, slot_instances


def P(s):
    return parse_positions(s)


@pytest.fixture(scope="module")
def model(config):
    return RosterModel(config)


def test_slot_instances(config):
    inst = slot_instances(config)
    assert len(inst) == 13
    assert inst.count("C") == 2 and inst.count("UTIL") == 2 and inst.count("BN") == 3


def test_parse_positions():
    assert P("PG,SG") == frozenset({"PG", "SG"})
    assert P("sf / pf") == frozenset({"SF", "PF"})
    with pytest.raises(ValueError):
        P("FC")


def test_g_slot_accepts_pg_not_c(config):
    el = config.roster.slot_eligibility
    assert "G" in eligible_slots(P("PG"), el)
    assert "G" not in eligible_slots(P("C"), el)


def test_three_centers_third_goes_util_or_bench(model):
    a = model.assign([P("C"), P("C"), P("C")])
    assert sorted(a.slots[:3]).count("C") == 2
    third = [s for s in a.slots if s != "C"]
    assert third[0] in ("UTIL", "BN")
    assert third[0] == "UTIL"   # aktif slot bench'ten önce


def test_multi_position_player_assigned_correctly(model):
    a = model.assign([P("PG"), P("PG,SG")])
    assert a.slots[0] == "PG"
    assert a.slots[1] == "SG"
    a = model.assign([P("SF,PF"), P("SF")])
    assert a.slots == ("PF", "SF")


def test_specific_before_flex(model):
    a = model.assign([P("PG")])
    assert a.slots == ("PG",)
    assert a.n_open_active == 9


def test_full_roster_fills_all_active(model):
    roster = [P(x) for x in ["PG", "SG", "PG", "SF", "PF", "SF", "C", "C", "PF", "SG", "C", "C", "PG"]]
    a = model.assign(roster)
    assert a.n_open_active == 0
    assert a.slots.count("BN") == 3


def test_can_complete_catches_infeasible(config, model):
    six_centers = [P("C")] * 6
    # 6 C: 2 C + 2 UTIL dolar; 3 BN'den 2'si kullanılır; PG SG G SF PF F eksik (6) → 7 pick kalır
    assert model.open_active_count(six_centers) == 6
    assert can_complete(six_centers, 7, config)
    eight_centers = [P("C")] * 8
    assert model.open_active_count(eight_centers) == 6
    assert not can_complete(eight_centers, 5, config)


def test_group_oracle(config):
    groups = [P("PG"), P("C"), P("SF,PF")]
    oracle = GroupOracle(groups, config)
    open_, fills, needs = oracle.analyze(np.array([0, 4, 0], dtype=np.int16))
    assert open_ == 6
    assert fills.tolist() == [True, False, True]
    assert needs.tolist() == [True, False, True]
    # 2 C: UTIL açık olduğundan herkes "fills"; ama C pozisyonel ihtiyacı doldu
    _, fills, needs = oracle.analyze(np.array([0, 2, 0], dtype=np.int16))
    assert fills.tolist() == [True, True, True]
    assert needs.tolist() == [True, False, True]
