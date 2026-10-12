"""Seed'li dağılım testleri (README §9.1 bots, §9.4 istisnası).

Toleranslar:
* Monotonluk: ≥ %90 (README eşiği), 1000 simülasyon.
* Kuyruk: 0 < oran < %1 (README eşiği), 10.000 simülasyon (1000'lik parçalar).
"""

import numpy as np

from fdo.bots.thurstone import BatchDraft


def _closest_ok(universe, target):
    ok = np.flatnonzero(universe.status == "ok")
    return int(ok[np.argmin(np.abs(universe.adp[ok] - target))])


def test_fallen_player_gets_picked_quickly(universe, config):
    """Pick 50'de ADP≈20 oyuncu uygunsa sonraki 3 pick içinde seçilme oranı ≥ %90."""
    target = _closest_ok(universe, 20)
    by_adp = [i for i in np.argsort(universe.adp, kind="stable") if i != target][:49]
    b = BatchDraft(universe, config, 1000, seed=2024)
    for p in by_adp:
        b.force(int(p))
    assert b.k == 50 and np.all(b.taken_at[:, target] == 0)
    b.run_until(53)
    rate = float(np.mean(b.taken_at[:, target] > 0))
    assert rate >= 0.90, rate


def test_monotone_more_likely_picked_as_draft_advances(universe, config):
    """Düşmüş oyuncunun seçilme olasılığı pick ilerledikçe artar (İlke 6)."""
    target = _closest_ok(universe, 20)
    rates = []
    for start in (25, 40, 60):
        by_adp = [i for i in np.argsort(universe.adp, kind="stable") if i != target][: start - 1]
        b = BatchDraft(universe, config, 400, seed=7)
        for p in by_adp:
            b.force(int(p))
        b.run_until(start + 1)
        rates.append(float(np.mean(b.taken_at[:, target] > 0)))
    assert rates[0] <= rates[1] <= rates[2], rates


def test_reach_tail_is_rare_but_possible(universe, config):
    """ADP≈90 oyuncunun ilk 16 pick'te gitme oranı > 0 ve < %1."""
    target = _closest_ok(universe, 90)
    hits = 0
    total = 0
    for chunk in range(10):
        b = BatchDraft(universe, config, 1000, seed=31, sim_offset=chunk * 1000)
        b.run_until(17)
        hits += int(np.sum(b.taken_at[:, target] > 0))
        total += b.S
    rate = hits / total
    assert 0 < rate < 0.01, rate
