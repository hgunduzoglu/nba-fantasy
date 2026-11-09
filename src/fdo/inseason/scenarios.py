"""Takas değerlendirmesinin istatistik temeli (README §13.28).

Takas hesapları kalan sezon için "maç başı oran × kalan maç" vektörleriyle yapılır. Varsayılan temel Yahoo'nun kalan
sezon projeksiyonudur. Alternatif temeller kalan maç sayısını (dayanıklılık dahil) aynı bırakır, yalnızca maç başı
oranları değiştirir; bütün lig aynı temelde değerlenir (rakip takımlar, boştakiler, yerine koyma düzeyi, IL dönüşünde
kimin bırakılacağı):

* ``season`` — bu sezonun gerçekleşen maç başı ortalamaları (en az ``min_games`` maç; yoksa Yahoo).
* ``recent`` — NBA maç kayıtlarından son ``recent_games`` maçın ortalaması (rol değişimini en hızlı yansıtır; en az
  ``min_games`` maç; yoksa bu sezon, o da yoksa Yahoo).
* ``blend`` — Yahoo ile bu sezon arasında, oynanan maça göre ağırlık ``n / (n + prior_games)`` (10 maçta yarı yarıya):
  az maçta projeksiyona, maç biriktikçe gerçekleşene yaslanır.
"""

from __future__ import annotations

import dataclasses

import pandas as pd

from fdo.inseason.roles import match_ids
from fdo.trade.data import ROS, TradeData
from fdo.types import STATS

BASES = {"ros": "Yahoo projeksiyonu", "season": "Bu sezonki oranlar", "recent": "Son 10 maç", "blend": "Karma"}
MIN_GAMES = 3
RECENT_GAMES = 10
PRIOR_GAMES = 10


def _per_game(frame: pd.DataFrame) -> pd.DataFrame:
    gp = frame["gp"].where(frame["gp"] > 0)
    return frame[list(STATS)].div(gp, axis=0)


def basis_rates(data: TradeData, basis: str, logs: pd.DataFrame | None = None, *, min_games: int = MIN_GAMES,
                recent_games: int = RECENT_GAMES, prior_games: int = PRIOR_GAMES) -> pd.DataFrame:
    """``basis`` temelinde kalan sezon çerçevesi: ``gp`` Yahoo'nunki, istatistikler ``oran × gp``."""
    if basis not in BASES:
        raise ValueError(f"Bilinmeyen değerlendirme temeli: {basis}")
    ros = data.stats[ROS]
    if basis == "ros":
        return ros
    yahoo = _per_game(ros)
    season = data.stats["season_total"].reindex(ros.index)
    played = season["gp"].fillna(0)
    actual = _per_game(season)
    known = (played >= min_games) & actual.notna().all(axis=1)
    if basis == "blend":
        w = (played / (played + prior_games)).where(known, 0.0)
        rate = yahoo.mul(1 - w, axis=0) + actual.fillna(0).mul(w, axis=0)
    else:
        rate = yahoo.mask(known, actual)
    if basis == "recent" and logs is not None and len(logs):
        ids = match_ids(logs, data.players)
        games = logs.assign(player_id=ids.values).dropna(subset=["player_id"]).sort_values("game_date")
        last = games.groupby("player_id").tail(recent_games)
        count = last.groupby("player_id").size()
        mean = last.groupby("player_id")[list(STATS)].mean()
        ok = count[count >= min_games].index.intersection(rate.index)
        rate.loc[ok, list(STATS)] = mean.loc[ok, list(STATS)].to_numpy()
    out = ros.copy()
    out[list(STATS)] = rate[list(STATS)].mul(ros["gp"], axis=0)
    return out


def basis_data(data: TradeData, basis: str, logs: pd.DataFrame | None = None) -> TradeData:
    """Kalan sezon istatistikleri ``basis`` temelinde olan veri (önbellekler için parmak izi ayrı)."""
    if basis == "ros":
        return data
    return dataclasses.replace(data, stats={**data.stats, ROS: basis_rates(data, basis, logs)},
                               fingerprint=f"{data.fingerprint}:{basis}")


def per_game_rates(data: TradeData, pid: str) -> dict[str, float | None]:
    """Kalan sezon çerçevesinden maç başı kategori değerleri (oyuncu kartları için)."""
    f = data.stats[ROS]
    if pid not in f.index or not f.loc[pid, "gp"] or pd.isna(f.loc[pid, "gp"]):
        return {}
    r = f.loc[pid, list(STATS)] / f.loc[pid, "gp"]
    pct = lambda m, a: float(r[m] / r[a]) if r[a] else None
    return {"PTS": float(r["pts"]), "REB": float(r["reb"]), "AST": float(r["ast"]), "FG3M": float(r["fg3m"]),
            "STL": float(r["stl"]), "BLK": float(r["blk"]), "TOV": float(r["tov"]),
            "FG_PCT": pct("fgm", "fga"), "FT_PCT": pct("ftm", "fta"), "FGA": float(r["fga"])}
