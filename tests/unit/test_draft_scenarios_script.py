import numpy as np

from draft_scenarios import BROKEN_AFTER_PAIR, Strategy, make_policy, strategies, weights_label

CATS = ("FG_PCT", "FT_PCT", "FG3M", "PTS", "REB", "AST", "STL", "BLK", "TOV")


def test_strategy_grid_names_unique():
    st = strategies(CATS)
    names = [s.name for s in st]
    assert len(names) == len(set(names)) and names[:2] == ["Dengeli", "Uyarlanabilir (kural)"]
    assert any(s.start == 2 and s.punt == ("FT_PCT",) for s in st)


def test_adaptive_punts_broken_category_and_keeps_it():
    pol = make_policy(Strategy("a", "adaptive"), CATS)
    p = np.full((2, 9), 0.5)
    p[0, 3] = BROKEN_AFTER_PAIR - 0.05                     # sim 0: PTS çöktü
    w = pol(1, p)
    assert w[0, 3] == 0 and (w[1] == 1).all()
    p2 = np.full((2, 9), 0.5)
    p2[1, 5] = 0.35                                        # sonraki turn: sim 1 AST < 0.40
    w = pol(2, p2)
    assert w[0, 3] == 0 and w[1, 5] == 0 and w[0].sum() == 8


def test_mix_and_delayed_fixed():
    p = np.tile(np.linspace(0.3, 0.7, 9), (1, 1))
    mix = next(s for s in strategies(CATS) if s.kind == "mix" and s.start == 2 and "zayıf punt" in s.name
               and s.name.endswith("güçlü2 ×1.5 · zayıf punt"))
    pol = make_policy(mix, CATS)
    assert (pol(1, p) == 1).all()                          # 48/49 dengeli
    w = pol(2, p)
    assert w[0, 0] == 0 and w[0, 8] == 1.5 and w[0, 7] == 1.5
    assert (pol(3, p[:, ::-1]) == w).all()                 # karar sabit kalır
    assert weights_label(w[0], CATS) == "FG%×0 BLK×1.5 TO×1.5"
