"""Sakatlıkta rol değişimi (README §13.24): bu sezonun NBA maç kayıtlarından "o yokken" takım arkadaşlarının
maç başı istatistik farkı.

Yahoo'nun kalan sezon projeksiyonu takım arkadaşının sakatlığına neredeyse tepki vermez (§13.20). Haftalık kararlar
için kısa vadeli rol önemlidir:

* **Önemli oyuncu**: bu sezon en az 3 maç, maç başı en az 20 dakika.
* **Yok kümesi A**: takımın şu an oynamayan önemli oyuncuları (Yahoo O/INJ/NA ya da CBS dönüş tarihi bugünden sonra /
  sezon boyu). Bütün sezonu kaçıran oyuncu önemli sayılmaz (yokluğu zaten bütün maçlarda ve projeksiyonda).
* Takımın maçları: A'nın hiçbirinin oynamadığı (W) ve hepsinin oynadığı (H). W boşsa (A'dakiler farklı zamanlarda
  yoktu) en çok dakika alan X tek başına kullanılır.
* **Takım arkadaşı Y**: W'de en az 1, H'de en az 2 maçı varsa fark ``Δ = ort(W) − ort(H)``, küçültme
  ``n_W / (n_W + 4)``. Kalan sezon (ROS) maç başına eklenir (negatif olmaz, isabet ≤ deneme, üçlük ≤ isabet).
* **Geçerlilik**: A'nın en erken bilinen dönüşüne kadar (hariç); bilinmiyorsa bugünden 14 gün.

Eşleştirme: ``fdo.ingest.identity`` (ad + takım, yalnız ad, baş harf + soyad + takım; yalnız tek aday kalınca).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from fdo.ingest.identity import Resolver
from fdo.schedule.calendar import normalize_team
from fdo.trade.data import ROS, TradeData
from fdo.types import STATS

MIN_GAMES = 3
MIN_MINUTES = 20.0
SHRINK_GAMES = 4.0
DEFAULT_DAYS = 14
OUT = ("O", "INJ", "NA")
FIELDS = ("minutes", *STATS)


@dataclass(frozen=True)
class RoleBoost:
    player_id: str
    team: str
    absent: tuple[str, ...]           # yok sayılan önemli oyuncular (Yahoo kimliği)
    until: dt.date                     # bu güne kadar (hariç) geçerli
    n_without: int
    n_with: int
    delta: dict[str, float]            # maç başı fark (küçültülmüş), ``minutes`` dahil
    raw: dict[str, float]              # küçültülmemiş fark
    per_game: dict[str, float]         # uygulanan maç başı (ROS + Δ, STATS)


def load_logs(directory: str | Path, season: str) -> pd.DataFrame | None:
    path = Path(directory) / f"gamelogs_nba_{season}.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path)
    df["game_date"] = pd.to_datetime(df["game_date"]).dt.date
    df["nba_team"] = df["nba_team"].map(normalize_team)
    return df


def resolver(players: pd.DataFrame, overrides: pd.DataFrame | None = None):
    """Ad (+ NBA takımı) → Yahoo oyuncu kimliği ya da ``None`` (``fdo.ingest.identity``: yalnız tek aday kalınca)."""
    return Resolver(players, overrides).player_id


def match_ids(logs: pd.DataFrame, players: pd.DataFrame) -> pd.Series:
    """Log satırı → Yahoo oyuncu kimliği (eşleşmeyen ``None``)."""
    one = resolver(players)
    names = logs[["name", "nba_team"]].drop_duplicates()
    ids = {(r.name, r.nba_team): one(r.name, r.nba_team) for r in names.itertuples()}
    return pd.Series([ids[(n, t)] for n, t in zip(logs["name"], logs["nba_team"])], index=logs.index)


def out_until(data: TradeData) -> dict[str, dt.date | None]:
    """Şu an oynamayan oyuncu → bilinen dönüş günü (``None``: bilinmiyor, ``date.max``: sezon boyu)."""
    out: dict[str, dt.date | None] = {}
    inj = getattr(data, "injuries", None)
    if inj is not None and len(inj):
        for pid, r in inj.iterrows():
            if r["kind"] == "season":
                out[pid] = dt.date.max
            elif r["kind"] == "out_until" and not pd.isna(r["return_date"]):
                ret = pd.Timestamp(r["return_date"]).date()
                if ret > data.as_of:
                    out[pid] = ret
    for pid, status in data.players["injury_status"].items():
        if str(status) in OUT and pid not in out:
            out[pid] = None
    return out


def role_boosts(data: TradeData, logs: pd.DataFrame | None) -> dict[str, RoleBoost]:
    if logs is None or logs.empty:
        return {}
    logs = logs.assign(player_id=match_ids(logs, data.players))
    logs = logs[logs["minutes"] > 0]
    games = logs.groupby("player_id").agg(n=("minutes", "size"), mpg=("minutes", "mean"))
    important = set(games.index[(games["n"] >= MIN_GAMES) & (games["mpg"] >= MIN_MINUTES)])
    absent_all = out_until(data)
    ros = data.stats[ROS]
    out: dict[str, RoleBoost] = {}
    for team, tl in logs.groupby("nba_team"):
        absent = [p for p in absent_all if p in important and set(tl.loc[tl["player_id"] == p, "nba_team"]) == {team}
                  and normalize_team(str(data.players.loc[p, "nba_team"] or "")) == team]
        if not absent:
            continue
        played = tl.groupby("game_date")["player_id"].agg(set)
        without = [d for d, s in played.items() if not s & set(absent)]
        with_ = [d for d, s in played.items() if set(absent) <= s]
        used = absent
        if not without or len(with_) < 2:
            used = [max(absent, key=lambda p: games.loc[p, "mpg"])]
            without = [d for d, s in played.items() if used[0] not in s]
            with_ = [d for d, s in played.items() if used[0] in s]
        if not without or len(with_) < 2:
            continue
        rets = [absent_all[p] for p in used]
        known = [r for r in rets if r is not None]
        until = min(known) if known else data.as_of + dt.timedelta(days=DEFAULT_DAYS)
        for pid, pl in tl[tl["player_id"].notna() & ~tl["player_id"].isin(absent)].groupby("player_id"):
            w, h = pl[pl["game_date"].isin(without)], pl[pl["game_date"].isin(with_)]
            if len(w) < 1 or len(h) < 2 or pid not in ros.index or not (ros.loc[pid, "gp"] > 0):
                continue
            raw = (w[list(FIELDS)].mean() - h[list(FIELDS)].mean()).to_dict()
            k = len(w) / (len(w) + SHRINK_GAMES)
            delta = {s: float(v) * k for s, v in raw.items()}
            base = (ros.loc[pid, list(STATS)] / ros.loc[pid, "gp"]).astype(float)
            pg = {s: max(0.0, float(base[s]) + delta[s]) for s in STATS}
            pg["fgm"], pg["ftm"] = min(pg["fgm"], pg["fga"]), min(pg["ftm"], pg["fta"])
            pg["fg3m"] = min(pg["fg3m"], pg["fgm"])
            if not np.isfinite(list(pg.values())).all():
                continue
            out[pid] = RoleBoost(pid, team, tuple(used), until, len(w), len(h), delta,
                                 {s: float(v) for s, v in raw.items()}, pg)
    return out
