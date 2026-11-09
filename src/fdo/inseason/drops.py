"""Yalnız bırakma: IL'den dönen oyuncuya yer açarken kimi bırakmalı (README §13.26).

Dönen oyuncular (``activate``) aktif kadroya katılır; adaylar aktif oyuncular + dönenlerdir (dönenin kendisi de
bırakılabilir). Her aday için iki kayıp hesaplanır, referans herkesin tutulduğu (kapasite aşımı yok sayılan) kadrodur:

* **Kalan sezon**: aday çıkınca kadronun tipik hafta vektörü (kalan IL'liler dönüş bedeliyle,
  ``TradeEngine.team_vector``) ligdeki diğer takımlara karşı; strateji kaybı ``9·Σ w_c·ΔP_c`` ve ağırlıksız ΔECW.
* **Bu hafta**: kalan günlerde eşleşme (dönen, dönüş gününden itibaren oynar; günlük kadro çözücüsü yerleştirir);
  strateji puanı, beklenen kategori ve P(5+) farkı.

Pozisyon: bırakma sonrası doldurulamayan aktif slot sayısı adaylar arasındaki en azdan fazlaysa işaretlenir. Öneri:
pozisyonu bozmayan adaylar arasından kalan sezon kaybı en düşük ``need`` oyuncu (en az bir).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import numpy as np
import pandas as pd

from fdo.inseason.weekly import Stint, WeekModel, accumulated_vector
from fdo.matchup.ecw import ecw_vs
from fdo.roster.assignment import best_assignment
from fdo.trade.strategy import CATEGORIES

#: Dönüş tarihi bu kadar gün içindeyse oyuncu "dönüyor" sayılır (varsayılan aktifleştirme).
SOON_DAYS = 2


def returning(model: WeekModel, team_id: str, as_of: dt.date, soon: int = SOON_DAYS) -> list[str]:
    """IL'de olup dönen (ya da dönmek üzere olan) oyuncular: bilinen dönüş tarihi ``soon`` gün içinde ya da tarih
    bilinmiyor ve durum artık "oynamaz" değil (Yahoo'da IL'de sağlıklı oyuncu kadroyu geçersiz yapar)."""
    lg = model.engine.league
    status = model.engine.data.players["injury_status"]
    out = []
    for p in lg.rosters[team_id]:
        if p not in lg.injury_rosters[team_id]:
            continue
        ret = model.return_date.get(p)
        if ret is not None:
            if ret <= as_of + dt.timedelta(days=soon):
                out.append(p)
        elif str(status.get(p, "") or "") not in model.out_statuses:
            out.append(p)
    return out


@dataclass
class DropPlan:
    activate: list[str]
    active: list[str]                 # aktifleştirme sonrası aktif kadro (adaylar)
    need: int                         # kapasiteye inmek için bırakılması gereken oyuncu
    week_base: tuple[np.ndarray, float, float]   # herkes tutulursa bu hafta (P, beklenen kategori, P(5+))
    rows: pd.DataFrame                # aday başına kayıplar (kalan sezon kaybına göre artan)
    recommended: list[str]


def drop_plan(model: WeekModel, team_id: str, opp_id: str, days: list[dt.date], activate: list[str], *,
              acc_mine=None, acc_opp=None) -> DropPlan:
    eng, s = model.engine, model.strategy
    lg = eng.league
    roster = lg.rosters[team_id]
    il = frozenset(lg.injury_rosters[team_id]) & frozenset(roster)
    act = [p for p in dict.fromkeys(activate) if p in il]
    il_after = il - set(act)
    active = [p for p in roster if p not in il] + act
    need = max(0, len(active) - lg.capacity)
    w = s.normalized

    # kalan sezon: ligdeki diğer takımlara karşı ortalama kategori olasılığı
    opp = eng.baseline_vectors[[i for i, t in enumerate(eng.team_ids) if t != team_id]]
    p_all = ecw_vs(eng.team_vector(roster, il_after, s), opp, eng.config).mean(axis=0)            # (C,)
    vecs = np.stack([eng.team_vector(tuple(x for x in roster if x != d), il_after, s) for d in active]) \
        if active else np.zeros((0, opp.shape[1]))
    p_ros = ecw_vs(vecs, opp[None], eng.config).mean(axis=-2) - p_all[None, :]                   # (D, C)

    # bu hafta: rakibin aktif kadrosuna karşı kalan günler
    a_m = accumulated_vector(acc_mine)
    opp_tw = model.team_week(opp_id, [Stint(p, slot=k) for k, p in enumerate(model.active_roster(opp_id))], days,
                             accumulated_vector(acc_opp))

    def week(ids):
        tw = model.team_week(team_id, [Stint(p, slot=k) for k, p in enumerate(ids)], days, a_m)
        return (tw, *model.evaluate(tw, opp_tw))

    tw0, p0, ew0, sc0, p50 = week(active)

    opens = {d: best_assignment(eng.positions([p for p in active if p != d]), eng.config).n_open_active
             for d in active}
    least_open = min(opens.values(), default=0)
    rows = []
    for j, d in enumerate(active):
        _, p1, ew1, sc1, p51 = week([p for p in active if p != d])
        rows.append({"player": d, "returning": d in act,
                     "ros_loss": float(-9 * p_ros[j] @ w), "ros_d_ecw": float(p_ros[j].sum()),
                     "ros_dp": {c: float(p_ros[j, i]) for i, c in enumerate(CATEGORIES)},
                     "week_loss": float(sc0 - sc1), "week_d_expected": float(ew1 - ew0), "week_d_p5": float(p51 - p50),
                     "week_dp": {c: float(p1[i] - p0[i]) for i, c in enumerate(CATEGORIES)},
                     "games": int(tw0.counted.get(d, 0)), "games_left": model.games_in(d, days),
                     "open_slots": int(opens[d] - least_open)})
    table = pd.DataFrame(rows)
    if len(table):
        table = table.sort_values(["ros_loss", "week_loss"], kind="stable").reset_index(drop=True)
    ok = table[table["open_slots"] == 0] if len(table) else table
    recommended = list(ok["player"].head(max(1, need))) if len(ok) else []
    return DropPlan(act, active, need, (p0, ew0, p50), table, recommended)
