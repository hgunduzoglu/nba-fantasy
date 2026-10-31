"""Boştaki oyuncular: kalan sezon için en iyi "al + bırak" (README §13.13).

Kullanıcının kadrosunda ``d`` yerine boştaki ``f`` gelirse takımın kalan sezon (ROS, tipik hafta)
vektörü ``R − v_d + v_f`` olur; ligdeki diğer takımlara karşı kategori olasılıkları yeniden hesaplanır.
Strateji puanı ``9·Σ w_c·ΔP_c`` (normalize ağırlıklar), ağırlıksız ΔECW ayrıca verilir. IL'deki oyuncular
bırakma adayı değildir. Pozisyon kontrolü: bırakma sonrası doldurulamayan aktif slot sayısı artmamalı.
IL'den dönecek oyuncu varsa dönüşte yer açma bedeli (``TradeEngine.crunch_vector``) her iki kadroda da düşülür:
eklenen oyuncu dönüşte bırakılacaksa yalnız dönüşe kadar katkı verir.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from fdo.matchup.ecw import ecw_vs
from fdo.roster.assignment import best_assignment
from fdo.trade.engine import TradeEngine
from fdo.trade.strategy import CATEGORIES, Strategy


def _opponents(engine: TradeEngine, team_id: str) -> np.ndarray:
    keep = [i for i, t in enumerate(engine.team_ids) if t != team_id]
    return engine.baseline_vectors[keep]


def swap_delta(engine: TradeEngine, team_id: str, drop: str, add: str, strategy: Strategy | None = None) -> float:
    """``drop`` yerine ``add`` kalıcı olursa kalan sezon strateji ECW değişimi."""
    s = strategy or Strategy()
    opp = _opponents(engine, team_id)
    roster = engine.league.rosters[team_id]
    il = engine._il(team_id, roster)
    base = engine.team_vector(roster, il, s)
    new = engine.team_vector(tuple(p for p in roster if p != drop) + (add,), il, s)
    p0, p1 = ecw_vs(base, opp, engine.config).mean(axis=0), ecw_vs(new, opp, engine.config).mean(axis=0)
    return float(9 * (p1 - p0) @ s.normalized)


def free_agents(engine: TradeEngine) -> list[str]:
    owned = {p for r in engine.league.rosters.values() for p in r}
    return [p for p in engine.ids if p not in owned and engine.modeled[engine.index[p]]]


def drop_candidates(engine: TradeEngine, team_id: str) -> list[str]:
    lg = engine.league
    return [p for p in lg.rosters[team_id] if p not in lg.injury_rosters[team_id]]


def waiver_table(engine: TradeEngine, team_id: str, strategy: Strategy | None = None, *,
                 top: int = 60) -> pd.DataFrame:
    """Boştaki her oyuncu için en iyi bırakma eşi ve etkisi (strateji puanına göre azalan)."""
    s = strategy or Strategy()
    w = s.normalized
    fa = free_agents(engine)
    drops = drop_candidates(engine, team_id)
    if not fa or not drops:
        return pd.DataFrame()
    opp = _opponents(engine, team_id)
    roster = engine.league.rosters[team_id]
    il = engine._il(team_id, roster)
    raw = engine.roster_vector(roster)
    base = engine.team_vector(roster, il, s)
    p0 = ecw_vs(base, opp, engine.config).mean(axis=0)                               # (C,)
    vf = engine.vecs[[engine.index[p] for p in fa]]                                    # (F, 24)
    vd = engine.vecs[[engine.index[p] for p in drops]]                                 # (D, 24)
    new = raw[None, None, :] - vd[None, :, :] + vf[:, None, :]                        # (F, D, 24)
    if any(engine.return_share(p) > 0 for p in il):
        # IL dönüşü: her (ekle, bırak) çifti için dönüşte kimin bırakılacağı değişebilir
        for i, f in enumerate(fa):
            for j, d in enumerate(drops):
                new[i, j] -= engine.crunch_vector(tuple(p for p in roster if p != d) + (f,), il, s)
    p1 = ecw_vs(new, opp[None, None], engine.config).mean(axis=-2)                     # (F, D, C)
    dp = p1 - p0
    score = 9 * dp @ w                                                                 # (F, D)
    # pozisyon: bırakma sonrası doldurulamayan aktif slot artmamalı
    active = drop_candidates(engine, team_id)
    open0 = best_assignment(engine.positions(active), engine.config).n_open_active
    order = np.argsort(-score.max(axis=1), kind="stable")[: max(top * 2, top)]
    feas_cache: dict[tuple[str, str], bool] = {}

    def feasible(f: str, d: str) -> bool:
        key = (f, d)
        if key not in feas_cache:
            after = [p for p in active if p != d] + [f]
            feas_cache[key] = best_assignment(engine.positions(after), engine.config).n_open_active <= open0
        return feas_cache[key]

    rows = []
    players = engine.data.players
    for i in order:
        f = fa[i]
        for j in np.argsort(-score[i], kind="stable"):
            if feasible(f, drops[j]):
                break
        else:
            continue
        rows.append({"add": f, "drop": drops[j], "score": float(score[i, j]),
                     "delta_ecw": float(dp[i, j].sum()),
                     **{f"d_{c}": float(dp[i, j, k]) for k, c in enumerate(CATEGORIES)},
                     "name": players.loc[f, "name"], "drop_name": players.loc[drops[j], "name"],
                     "positions": players.loc[f, "yahoo_positions"], "nba_team": players.loc[f, "nba_team"],
                     "status": players.loc[f, "injury_status"]})
        if len(rows) >= top:
            break
    return pd.DataFrame(rows).sort_values("score", ascending=False, kind="stable").reset_index(drop=True)


def drop_ranking(engine: TradeEngine, team_id: str, strategy: Strategy | None = None) -> pd.DataFrame:
    """Kadrondaki her oyuncunun yerine en iyi boştaki oyuncu gelirse fark (negatifse o oyuncu değerli)."""
    t = waiver_table(engine, team_id, strategy, top=10_000)
    if t.empty:
        return t
    best = t.sort_values("score", ascending=False).drop_duplicates("drop")
    return best[["drop", "drop_name", "add", "name", "score", "delta_ecw"]].reset_index(drop=True)
