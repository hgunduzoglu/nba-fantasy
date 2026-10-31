"""Algılanan değer ve yanlış fiyatlama: sat-yüksek / al-düşük (README §13.15).

Menajerler oyuncuya genelde bu sezonun rakamlarıyla (ya da sezon öncesi isim değeriyle) bakar; bizim
karar ölçümüz kalan sezon projeksiyonudur (ROS). İkisini aynı ölçeğe koymak için:

1. Algılanan sıra: seçilen kaynağın maç başı dengeli z değerine göre (``season_total``'da en az
   ``min_gp`` maç; daha azı sezon öncesi sırasına düşer). ``blend`` iki sıranın ortalamasıdır.
2. Algılanan fiyat: o sıradaki oyuncunun ROS piyasa değeri (``engine.market`` sıralı dizisi). Böylece
   "bu sezon 25. görünen oyuncu" piyasada ROS'un 25. oyuncusu kadar değer görür.
3. ``edge = algılanan fiyat − ROS değeri`` (piyasa birimi): pozitif = sat-yüksek adayı (olduğundan iyi
   görünüyor), negatif = al-düşük hedefi. Oran kullanılmaz: yedek seviyesindeki oyuncularda (ROS ≈ 0.1)
   anlamsız büyür.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from fdo.trade.data import ROS
from fdo.trade.engine import TradeEngine
from fdo.types import STATS
from fdo.valuation import value_players

PERCEPTIONS = {"season_total": "Bu sezonun rakamları", "preseason": "Sezon öncesi isim değeri",
               "blend": "İkisinin ortalaması"}


def _per_game_rank(engine: TradeEngine, mode: str, ids: list[str], min_gp: float = 0.0) -> pd.Series:
    f = engine.data.stats[mode].reindex(ids)
    ok = f["gp"].fillna(0) > max(min_gp, 0) - 1e-9
    ok &= f[list(STATS)].notna().all(axis=1) & (f["gp"] > 0)
    proj = f.loc[ok, list(STATS)].div(f.loc[ok, "gp"], axis=0)
    if proj.empty:
        return pd.Series(np.nan, index=ids)
    proj = proj.assign(player_id=proj.index, projected_gp=f.loc[ok, "gp"])
    v = value_players(proj, engine.config, basis="per_game", method="z").table["V"]
    return v.rank(ascending=False, method="first").reindex(ids)


def perceived_prices(engine: TradeEngine, basis: str = "season_total", *, min_gp: int = 3) -> pd.Series:
    """Oyuncu → algılanan fiyat (ROS piyasa ölçeğinde); modellenemeyenler NaN."""
    if basis not in PERCEPTIONS:
        raise ValueError(f"basis: {', '.join(PERCEPTIONS)} ({basis!r})")
    ids = [p for p in engine.ids if engine.modeled[engine.index[p]]]
    pre = _per_game_rank(engine, "preseason", ids)
    if basis == "preseason":
        rank = pre
    else:
        cur = _per_game_rank(engine, "season_total", ids, min_gp)
        cur = cur.fillna(pre)
        rank = cur if basis == "season_total" else (cur + pre.fillna(cur)) / 2
    rank = rank.rank(method="first")                                  # boşluksuz 1..n
    ladder = np.sort(engine.market.loc[ids].to_numpy(float))[::-1]
    pos = (rank.fillna(len(ladder)).astype(int).clip(1, len(ladder)) - 1).to_numpy()
    return pd.Series(ladder[pos], index=ids).reindex(engine.ids)


def mispricing(engine: TradeEngine, perceived: pd.Series, team_ids=None) -> pd.DataFrame:
    """Kadrolu oyuncular: ROS değeri ve sırası, algılanan fiyat ve sırası, ``edge`` (azalan)."""
    owner = {p: t for t, r in engine.league.rosters.items() for p in r}
    modeled = [p for p in engine.ids if engine.modeled[engine.index[p]]]
    ros_rank = engine.market.loc[modeled].rank(ascending=False, method="first")
    per_rank = perceived.loc[modeled].rank(ascending=False, method="first")
    rows = []
    teams = set(team_ids) if team_ids is not None else set(engine.league.rosters)
    for p, t in owner.items():
        if t not in teams or not engine.modeled[engine.index[p]]:
            continue
        ros, per = float(engine.market[p]), float(perceived.get(p, np.nan))
        rows.append({"player_id": p, "team_id": t, "name": engine.data.players.loc[p, "name"],
                     "ros_value": ros, "perceived": per, "edge": per - ros,
                     "ros_rank": float(ros_rank[p]), "perceived_rank": float(per_rank[p]),
                     "gp_now": float(engine.data.stats["season_total"].loc[p, "gp"])
                     if p in engine.data.stats["season_total"].index else np.nan})
    df = pd.DataFrame(rows)
    return df.sort_values("edge", ascending=False).reset_index(drop=True) if len(df) else df


__all__ = ["PERCEPTIONS", "mispricing", "perceived_prices", "ROS"]
