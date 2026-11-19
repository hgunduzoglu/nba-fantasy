"""Veri kontrolleri: kadrolu oyuncularda kararı sessizce bozabilecek veri sorunları (README §13.52).

Senkronizasyondan sonra (ve uygulamada) kadrolu oyuncular için tek tek bakılır; her bulgu oyuncu, sahibi olan lig
takımları ve kısa bir açıklamayla döner. Kontroller:

* ``unmodeled``: kalan sezon projeksiyonu yok ya da 0 maç (dolgudan sonra da): takasta ve simülasyonda 0 değerli.
* ``filled``: Yahoo'nun 0 maç verdiği ya da satırı olmayan oyuncu sezon + sezon öncesi değerlerle dolduruldu (bilgi).
* ``stale``: Yahoo'nun maç başı projeksiyonu bariz bayattı; bu sezon + sezon öncesiyle düzeltildi (bilgi).
* ``team``: Yahoo'daki NBA takımı son maç kaydındaki takımdan farklı (takas sonrası gecikme; maç takvimi yanlış takımdan).
* ``role``: son ``RECENT`` maçta dakika, öncesine göre belirgin değişti; projeksiyon rol değişimine geç tepki verir.
* ``idle``: sakat görünmüyor ama takımının son maçlarında hiç oynamadı.
* ``il_slot``: IL slotunda ama Yahoo durumu IL'e uygun değil (Q, GTD ya da sağlıklı): Yahoo alım/takası engelleyebilir.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from fdo.inseason.roles import match_ids
from fdo.schedule.calendar import normalize_team
from fdo.trade.data import ROS, TradeData
from fdo.types import STATS

RECENT = 5                   # son kaç maç
ROLE_MIN_DELTA = 6.0         # dakika farkı (en az)
ROLE_MIN_RATIO = .3          # göreli fark (en az)
IDLE_TEAM_GAMES = 3          # takımın son kaç maçında hiç oynamadıysa
IL_OK = {"O", "INJ", "IL", "OFS", "NA", "SUSP", "D"}    # IL slotunda durabilecek Yahoo durumları


@dataclass(frozen=True)
class Finding:
    check: str
    level: str                       # "warn" | "info"
    player_id: str
    name: str
    message: str
    teams: tuple[tuple[str, str, str], ...]   # (lig, takım kimliği, takım adı)


def _owners(data: TradeData) -> dict[str, list[tuple[str, str, str]]]:
    out: dict[str, list[tuple[str, str, str]]] = {}
    for lid, lg in data.leagues.items():
        for tid, roster in lg.rosters.items():
            for p in roster:
                out.setdefault(p, []).append((lid, tid, lg.teams[tid]))
    return out


def _modeled(f: pd.DataFrame, pid: str) -> bool:
    if pid not in f.index:
        return False
    r = f.loc[pid]
    vals = r[list(STATS)].to_numpy(float)
    return bool(np.isfinite(vals).all() and np.isfinite(r["gp"]) and r["gp"] > 0 and (vals >= 0).all()
                and r["fgm"] <= r["fga"] and r["ftm"] <= r["fta"])


def data_checks(data: TradeData, logs: pd.DataFrame | None = None) -> list[Finding]:
    """Kadrolu oyuncuların veri bulguları (önce uyarılar, sonra bilgiler; her grupta ada göre)."""
    owners = _owners(data)
    ros = data.stats[ROS]
    status = data.players["injury_status"].fillna("").astype(str)
    inj = data.injuries
    filled = set(data.durability.index[data.durability["ros_filled"]]) \
        if data.durability is not None and "ros_filled" in data.durability.columns else set()
    stale = set(data.durability.index[data.durability["ros_stale"]]) \
        if data.durability is not None and "ros_stale" in data.durability.columns else set()
    found: list[Finding] = []

    def add(check, level, pid, message, teams=None):
        found.append(Finding(check, level, pid, str(data.players.loc[pid, "name"]), message,
                             tuple(owners[pid] if teams is None else teams)))

    il_at: dict[str, list[tuple[str, str, str]]] = {}          # oyuncu → IL slotunda olduğu takımlar
    for lid, lg in data.leagues.items():
        for tid, members in lg.injury_rosters.items():
            for p in members:
                il_at.setdefault(p, []).append((lid, tid, lg.teams[tid]))
    for pid in owners:
        st = status.get(pid, "")
        kind = inj.loc[pid, "kind"] if inj is not None and pid in inj.index else None
        if not _modeled(ros, pid):
            why = ("Yahoo'da aktif değil (NA)" if st == "NA" else "sezon boyu yok" if kind == "season"
                   else "kalan sezon projeksiyonunda satırı yok" if pid not in ros.index or pd.isna(ros.loc[pid, "gp"])
                   else "Yahoo kalan sezon için 0 maç veriyor")
            add("unmodeled", "warn", pid, f"Modellenmiyor ({why}); takasta ve simülasyonda değeri 0 sayılır.")
        elif pid in filled:
            add("filled", "info", pid, f"Yahoo projeksiyonu yoktu ya da 0 maçtı; sezon + sezon öncesi değerlerle "
                                       f"dolduruldu ({ros.loc[pid, 'gp']:.0f} maç).")
        elif pid in stale:
            add("stale", "info", pid, "Yahoo projeksiyonu bayattı (bu sezonun yarısının altında); maç başı değerler "
                                      "bu sezon + sezon öncesiyle düzeltildi.")
        if pid in il_at and st not in IL_OK:
            add("il_slot", "warn", pid, f"IL slotunda ama Yahoo durumu {st or 'sağlıklı'}; Yahoo bu durumda alım ve "
                                        "takası engelleyebilir, aktife almak gerekebilir.", il_at[pid])
    if logs is not None and not logs.empty:
        found += _log_checks(data, logs, owners, status)
    order = {"warn": 0, "info": 1}
    return sorted(found, key=lambda f: (order.get(f.level, 2), f.check, f.name))


def _log_checks(data, logs, owners, status) -> list[Finding]:
    logs = logs[logs["game_date"] < data.as_of]
    logs = logs.assign(player_id=match_ids(logs, data.players))
    team_dates = logs.groupby("nba_team")["game_date"].agg(lambda s: sorted(set(s)))
    out: list[Finding] = []
    mine = logs[logs["player_id"].isin(set(owners))]

    def add(check, pid, message):
        out.append(Finding(check, "warn", pid, str(data.players.loc[pid, "name"]), message, tuple(owners[pid])))

    for pid, pl in mine.groupby("player_id"):
        pl = pl.sort_values("game_date")
        last = pl.iloc[-1]
        yahoo_team = normalize_team(str(data.players.loc[pid, "nba_team"] or ""))
        if yahoo_team and last["nba_team"] != yahoo_team:
            add("team", pid, f"Yahoo'da {yahoo_team}, son maçı {last['nba_team']} formasıyla ({last['game_date']}); "
                             "maç takvimi yanlış takımdan sayılıyor olabilir.")
        played = pl[pl["minutes"] > 0]
        st = status.get(pid, "")
        dates = team_dates.get(last["nba_team"], [])
        recent_team = dates[-IDLE_TEAM_GAMES:]
        if st not in IL_OK and len(recent_team) == IDLE_TEAM_GAMES and not set(played["game_date"]) & set(recent_team):
            add("idle", pid, f"Sakat görünmüyor (Yahoo: {st or 'sağlıklı'}) ama takımının son {IDLE_TEAM_GAMES} maçında "
                             "oynamadı.")
        if len(played) >= RECENT + 3:
            now, before = played["minutes"].iloc[-RECENT:].mean(), played["minutes"].iloc[:-RECENT].mean()
            d = now - before
            if abs(d) >= ROLE_MIN_DELTA and abs(d) >= ROLE_MIN_RATIO * max(before, 1.0):
                trend = "arttı" if d > 0 else "düştü"
                add("role", pid, f"Son {RECENT} maçta dakika {trend}: {before:.0f} → {now:.0f} dk. Projeksiyon rol "
                                 "değişimine geç tepki verir; değeri olduğundan " + ("düşük" if d > 0 else "yüksek")
                                 + " görünebilir.")
    return out


def as_dicts(found: list[Finding], league_id: str | None = None) -> list[dict]:
    """JSON için; ``league_id`` verilirse yalnız o ligde kadrolu oyuncular (takım listesi de o lige daraltılır)."""
    rows = []
    for f in found:
        teams = [t for t in f.teams if league_id is None or t[0] == str(league_id)]
        if not teams:
            continue
        d = asdict(f)
        d["teams"] = [{"league_id": a, "team_id": b, "team_name": c} for a, b, c in teams]
        rows.append(d)
    return rows
