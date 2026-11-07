"""Sit/start: içinde bulunulan haftanın kalan günleri için eşleşmeye göre günlük kadro önerisi (README §13.21).

* **Maç değeri**: oyuncunun bir maçının haftalık strateji puanına (dengelide beklenen kategori galibiyeti) katkısı,
  mevcut düzende: sayılıyorsa ``S(V) − S(V − a·u)``, sayılmıyorsa ``S(V + a·u) − S(V)`` (``V`` haftalık vektör, ``a``
  uygunluk, ``u`` maç başı vektör; oranlar isabet/deneme ile). Rakip oranda az farkla gerideyken ya da öndeyken düşük
  isabetli hacimli şutçunun değeri negatif olabilir: o gün boş slot olsa da oturur.
* **Gün düzeni**: maçı olan ve değeri pozitif oyuncular değer önceliğiyle pozisyon kuralına göre slotlara yerleşir
  (``slot_assignment``). Değerler yeni düzene göre yeniden hesaplanır; düzen değişmeyene kadar (en çok 6 tur).
  Bir oyuncunun maç değeri hafta içinde her gün aynıdır; günler yalnız slot rekabetiyle ayrışır.
* **Bugün**: Yahoo'daki mevcut düzen (senkronizasyon günündeki ``rosters.json`` slotları) ile karşılaştırılır.
* Rakibin düzeni statik önceliktedir (stratejiye göre maç başı değer).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import numpy as np

from fdo.inseason.weekly import TeamWeek, WeekModel, accumulated_vector
from fdo.matchup.ecw import p_at_least, p_win
from fdo.schedule.lineup import active_slot_names

MAX_ROUNDS = 6
SIT_BELOW = -0.002          # maç başı strateji puanı kaybı bundan büyükse oturt (gürültüyü ayıklar)


@dataclass
class Score:
    p: np.ndarray            # (C,)
    expected_wins: float
    strategy_score: float
    p5: float


@dataclass
class SitStartPlan:
    days: list[dt.date]
    players: list[str]
    slot_names: list[str]
    week: TeamWeek           # önerilen düzen (``slots``, ``playing``)
    sat: np.ndarray          # (gün, oyuncu) maçı var, oynayabilir ama değeri negatif → oturtuldu
    value: np.ndarray        # (oyuncu,) bir maçın strateji puanı katkısı (son düzende)
    dp: np.ndarray           # (oyuncu, C) bir maçın kategori olasılığı etkisi
    before: Score            # statik öncelikli düzen
    after: Score
    rounds: int


def _score(model: WeekModel, mine: np.ndarray, opp: np.ndarray) -> Score:
    p = p_win(mine, opp, model.config)
    return Score(p, float(p.sum()), float(9 * p @ model.strategy.normalized),
                 float(p_at_least(p[None, :], 5, model.corr)[0]))


def _marginal(model: WeekModel, tw: TeamWeek, idx: np.ndarray, opp: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Oyuncu başına bir maçın strateji puanı ve kategori olasılığı katkısı (mevcut düzende)."""
    v = tw.vector
    step = model.availability[idx][:, None] * model.unit[idx]                     # (n, 24)
    counted = (tw.counted.to_numpy() > 0)[:, None]
    lo, hi = np.where(counted, v - step, v), np.where(counted, v, v + step)
    dp = p_win(hi, opp, model.config) - p_win(lo, opp, model.config)              # (n, C)
    return 9 * dp @ model.strategy.normalized, dp


def plan_week(model: WeekModel, team: str, opp: str, days: list[dt.date], *, acc_mine=None,
              acc_opp=None) -> SitStartPlan:
    base = model.outlook(team, opp, days, acc_mine=acc_mine, acc_opp=acc_opp)
    stints, opp_vec = base.mine.stints, base.opp.vector
    ids = [s.player_id for s in stints]
    idx = np.array([model.engine.index[p] for p in ids], dtype=int)
    acc = accumulated_vector(acc_mine)
    tw, rounds = base.mine, 0
    sit = np.zeros((len(days), len(ids)), dtype=bool)
    for rounds in range(1, MAX_ROUNDS + 1):
        value, _ = _marginal(model, tw, idx, opp_vec)
        sit = tw.playing & (value < SIT_BELOW)[None, :]
        nxt = model.team_week(team, stints, days, acc, priority=value, sit=sit)
        same = np.array_equal(nxt.slots >= 0, tw.slots >= 0)
        tw = nxt
        if same:
            break
    value, dp = _marginal(model, tw, idx, opp_vec)
    return SitStartPlan(days, ids, active_slot_names(model.config), tw, sit, value, dp,
                        _score(model, base.mine.vector, opp_vec), _score(model, tw.vector, opp_vec), rounds)


def today_changes(plan: SitStartPlan, lineup: dict[str, str], day: dt.date) -> dict[str, list[dict]]:
    """Önerilen gün düzeni ile Yahoo'daki düzen (oyuncu → slot) farkı: ``start`` (yedekte/IL dışı ama oynamalı) ve
    ``sit`` (aktif ama oturmalı). Yalnız o gün maçı olan oyuncular."""
    if day not in plan.days:
        return {"start": [], "sit": []}
    d = plan.days.index(day)
    start, sit = [], []
    for j, pid in enumerate(plan.players):
        if not plan.week.playing[d, j]:
            continue
        now = lineup.get(pid, "")
        active_now = now not in ("", "BN", "IL", "IL+")
        should = plan.week.slots[d, j] >= 0
        row = {"player_id": pid, "yahoo_slot": now, "slot": plan.slot_names[plan.week.slots[d, j]] if should else None,
               "value": float(plan.value[j]), "negative": bool(plan.sat[d, j])}
        if should and not active_now:
            start.append(row)
        elif active_now and not should:
            sit.append(row)
    return {"start": start, "sit": sit}
