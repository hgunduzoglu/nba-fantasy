"""Algılanan değer ve yanlış fiyatlama: sat-yüksek / al-düşük (README §13.15).

Menajerler oyuncuya genelde bu sezonun rakamlarıyla (ya da sezon öncesi isim değeriyle) bakar; bizim
karar ölçümüz kalan sezon projeksiyonudur (ROS). İkisini aynı ölçeğe koymak için:

1. Algılanan sıra: ``season_total`` bu sezonun maç başı dengeli z değerine göre (en az ``min_gp`` maç; daha azı
   sezon öncesi sırasına düşer). ``preseason`` isim değeridir: menajerlerin sezon öncesi fiyatlaması, yani ligin
   kendi draftı (açık artırmada ödenen fiyat, yılan draftta seçim sırası) ile Yahoo ADP'sinin ortalama sırası
   (README §13.30); draft edilmeyenler arkada, sezon öncesi projeksiyon sırasıyla. Draft verisi yoksa sezon öncesi
   projeksiyonun z sırası. ``blend`` iki sıranın ortalamasıdır.
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

PERCEPTIONS = {"season_total": "Bu sezonun rakamları", "preseason": "Sezon öncesi isim değeri (draft sırası)",
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


def draft_rank(engine: TradeEngine, ids: list[str]) -> pd.Series | None:
    """Sezon öncesi piyasa sırası (küçük = değerli): ligin kendi draftı (fiyat varsa fiyat, yoksa seçim sırası) ve
    Yahoo ADP'si; ikisi de varsa sıraların ortalaması. Draft verisi yoksa ``None``, draft edilmeyen oyuncu NaN."""
    ranks = []
    if engine.data.adp is not None:
        adp = engine.data.adp.reindex(ids).dropna()
        if len(adp):
            ranks.append(adp.rank(method="average"))
    if engine.data.draft is not None:
        d = engine.data.draft
        d = d[d["league_id"] == engine.league.league_id].drop_duplicates("player_id").set_index("player_id")
        d = d.reindex([p for p in ids if p in d.index])
        key = -d["cost"].dropna() if d["cost"].notna().any() else d["pick"].dropna()
        if len(key):
            ranks.append(key.rank(method="average"))
    if not ranks:
        return None
    return pd.concat(ranks, axis=1).mean(axis=1).reindex(ids)


def _preseason_rank(engine: TradeEngine, ids: list[str]) -> pd.Series:
    proj = _per_game_rank(engine, "preseason", ids)
    market = draft_rank(engine, ids)
    if market is None or market.isna().all():
        return proj
    drafted = market.notna()
    rest = proj[~drafted].rank(method="first") + int(drafted.sum())
    rest = rest.fillna(float(len(ids)))
    return market[drafted].rank(method="first").reindex(ids).fillna(rest)


def perceived_ranks(engine: TradeEngine, basis: str = "season_total", *, min_gp: int = 3) -> pd.Series:
    """Modellenebilen oyuncu → algılanan sıra (1 = en iyi, boşluksuz)."""
    if basis not in PERCEPTIONS:
        raise ValueError(f"basis: {', '.join(PERCEPTIONS)} ({basis!r})")
    ids = [p for p in engine.ids if engine.modeled[engine.index[p]]]
    pre = _preseason_rank(engine, ids)
    if basis == "preseason":
        rank = pre
    else:
        cur = _per_game_rank(engine, "season_total", ids, min_gp)
        cur = cur.fillna(pre)
        rank = cur if basis == "season_total" else (cur + pre.fillna(cur)) / 2
    return rank.rank(method="first")


def perceived_prices(engine: TradeEngine, basis: str = "season_total", *, min_gp: int = 3) -> pd.Series:
    """Oyuncu → algılanan fiyat (ROS piyasa ölçeğinde); modellenemeyenler NaN."""
    rank = perceived_ranks(engine, basis, min_gp=min_gp)
    ids = list(rank.index)
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


__all__ = ["PERCEPTIONS", "mispricing", "perceived_prices", "perceived_ranks", "ROS"]
