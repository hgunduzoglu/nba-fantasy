"""İleriye dönük test: geçmiş bir günün verisiyle modelin tahmini, sonra gerçekleşenle karşılaştırılır.

Arşivdeki günlük kopya (``snapshots/<gün>/``: kadrolar, kalan sezon projeksiyonu) ve o günün CBS raporu o gün bilineni
verir (``snapshot_dir``); NBA maç kayıtları o günden sonra olanı. İki düzey ölçülür:

* **Oyuncu** (``forecast`` ↔ ``realized``): pencerede (gün → son maç günü) beklenen maç ve kategori toplamı ile
  gerçekleşen. Dönüş bekleyen sakatlar ayrıca raporlanır: dönüş varsayımı (CBS tarihi kesin mi, ölçülmüş gecikme
  dağılımı mı) burada sınanır.
* **Takas** (``pair_test``): takımın o gün yapabileceği bütün 1'e 1 takaslar; modelin takas puanı (strateji farkı) ve
  oyuncu tahmininden gelen değer farkı ile pencerede gerçekleşen değer farkının işaret uyumu ve sıra korelasyonu.

Değer, dokuz kategorinin gerçekleşen lig dağılımına göre ölçeklenmiş toplamıdır (yüzdeler isabet katkısıyla, top kaybı
eksi). Pencere kısa olduğu için gürültü büyüktür; sonuç örnek boyutuyla okunmalı. Karar günlüğü
(``fdo.evaluation.decisions``) biriktikçe aynı ölçüm gerçekten verilmiş önerilere uygulanır.
"""

from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

from fdo.inseason.identity import Resolver
from fdo.schedule.calendar import normalize_team
from fdo.trade.data import ROS

COUNTS = ("fg3m", "pts", "reb", "ast", "stl", "blk", "tov")
STATS_USED = ("fgm", "fga", "ftm", "fta", *COUNTS)
#: Kopyadan alınan (o günü temsil eden) dosyalar; geri kalanı veri dizininden.
SNAPSHOT_FILES = ("rosters.json", "player_stat_pages.json", "matchups.json")


def snapshot_dir(data_dir: str | Path, day: dt.date, work: str | Path) -> Path:
    """``day`` günü bilineni içeren veri dizini: güncel dizin, o günün kopyası (kadrolar, projeksiyon) ve en geç o
    günkü CBS raporu. Canlı hafta ve sonraki sakatlık raporları alınmaz."""
    data_dir, work = Path(data_dir), Path(work)
    snap = data_dir / "snapshots" / day.isoformat()
    if not (snap / "rosters.json").exists():
        raise FileNotFoundError(f"Kopya yok: {snap}")
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    for p in data_dir.iterdir():
        if not p.is_file() or p.name in SNAPSHOT_FILES or p.name.startswith("yahoo_live"):
            continue
        if p.name.startswith("injuries_cbs_") and p.stem[len("injuries_cbs_"):] > day.isoformat():
            continue
        shutil.copy2(p, work / p.name)
    for name in SNAPSHOT_FILES:
        if (snap / name).exists():
            shutil.copy2(snap / name, work / name)
    return work


def realized(logs: pd.DataFrame, players: pd.DataFrame, start: dt.date, end: dt.date,
             overrides: pd.DataFrame | None = None) -> tuple[pd.DataFrame, int]:
    """Oyuncu kimliği → pencerede oynadığı maç (dakika > 0) ve kategori toplamları; ikinci çıktı kimliği
    bulunamayan maç kaydı adı (bu oyuncular 0 sayılmaz, dışarıda kalır)."""
    w = logs[(logs["game_date"] >= start) & (logs["game_date"] <= end)].copy()
    one = Resolver(players, overrides)
    keys = w[["name", "nba_team"]].drop_duplicates()
    ids = {(r.name, r.nba_team): one(r.name, r.nba_team).player_id for r in keys.itertuples()}
    w["player_id"] = [ids[(n, t)] for n, t in zip(w["name"], w["nba_team"])]
    missing = int(w.loc[w["player_id"].isna(), "name"].nunique())
    w = w[w["player_id"].notna()]
    w["games"] = (w["minutes"].fillna(0) > 0).astype(float)
    return w.groupby("player_id")[["games", *STATS_USED]].sum(), missing


def forecast(engine, start: dt.date, end: dt.date) -> pd.DataFrame:
    """Modelin ``start`` günü beklediği: pencerede oynanacak maç ve kategori toplamı (kalan sezon projeksiyonu, dönüş
    tarihi ve varsa ölçülmüş gecikme dağılımı ile; takas puanıyla aynı dağıtım)."""
    ros = engine.data.stats[ROS].reindex(list(engine.ids))
    teams = engine.data.players["nba_team"].reindex(list(engine.ids))
    rows = {}
    for i, pid in enumerate(engine.ids):
        if not engine.modeled[i]:
            continue
        gp = float(ros.loc[pid, "gp"])
        team = normalize_team(teams.loc[pid]) if isinstance(teams.loc[pid], str) and teams.loc[pid] else ""
        if not np.isfinite(gp) or gp <= 0 or team not in engine._team_games:
            continue
        ret = max(engine.return_day(pid) or engine.data.as_of, engine.data.as_of)
        games = [d for d in engine._team_games[team] if d >= ret]
        pres = engine._presence(len(games)) if ret > engine.data.as_of else np.ones(len(games))
        if not games or pres.sum() <= 0:
            continue
        inside = float(sum(p for d, p in zip(games, pres) if start <= d <= end))
        g = gp * inside / float(pres.sum())
        rows[pid] = {"games": g, **{s: float(ros.loc[pid, s]) / gp * g for s in STATS_USED},
                     "returning": ret > engine.data.as_of}
    return pd.DataFrame.from_dict(rows, orient="index")


def value_scales(real: pd.DataFrame) -> dict:
    """Değer ölçeği gerçekleşen dağılımdan: yüzdelerde lig ortalaması, her kategoride oynayanlar arasında standart
    sapma."""
    played = real[real["games"] > 0]
    fg, ft = played["fgm"].sum() / max(played["fga"].sum(), 1), played["ftm"].sum() / max(played["fta"].sum(), 1)
    impact = pd.DataFrame({"fg": played["fgm"] - fg * played["fga"], "ft": played["ftm"] - ft * played["fta"],
                           **{c: played[c] for c in COUNTS}})
    return {"fg_avg": fg, "ft_avg": ft, "sd": impact.std().replace(0, 1).to_dict()}


def value(totals: pd.DataFrame, scales: dict) -> pd.Series:
    """Dokuz kategorinin ölçeklenmiş toplamı (top kaybı eksi)."""
    sd = scales["sd"]
    v = (totals["fgm"] - scales["fg_avg"] * totals["fga"]) / sd["fg"] \
        + (totals["ftm"] - scales["ft_avg"] * totals["fta"]) / sd["ft"]
    for c in COUNTS:
        v = v + (-1 if c == "tov" else 1) * totals[c] / sd[c]
    return v


def _spearman(a, b) -> float:
    a, b = pd.Series(a).rank(), pd.Series(b).rank()
    return float(np.corrcoef(a, b)[0, 1]) if len(a) > 2 and a.std() > 0 and b.std() > 0 else float("nan")


def pair_test(engine, team: str, fc: pd.Series, real: pd.Series, strategy=None) -> pd.DataFrame:
    """Takımın bütün 1'e 1 takasları (iki tarafta da tahmin ve gerçekleşen değeri olan oyuncular): modelin takas
    puanı (``strategy_delta``, kadro çözümü ve bedava hamleler dahil), oyuncu tahmininden değer farkı ve pencerede
    gerçekleşen değer farkı (alınan − verilen)."""
    from fdo.trade import TradeError, TradeRequest
    from fdo.trade.strategy import Strategy
    s = strategy or Strategy()
    ok = set(fc.index) & set(real.index)
    mine = [p for p in engine.league.rosters[team] if p in ok]
    rows = []
    for other in engine.team_ids:
        if other == team:
            continue
        for give in mine:
            for get in [p for p in engine.league.rosters[other] if p in ok]:
                req = TradeRequest(team, other, (give,), (get,), auto_drop=True, auto_fill=True)
                try:
                    rosters, _, il = engine.resolve(req, {team: s, other: Strategy()})
                    _, m = engine.score(rosters, team, other, s, Strategy(), il)
                except TradeError:
                    continue
                rows.append({"team_b": other, "give": give, "get": get, "model": m[team]["strategy_delta"],
                             "forecast": float(fc[get] - fc[give]), "realized": float(real[get] - real[give])})
    return pd.DataFrame(rows)


def summary(pairs: pd.DataFrame) -> dict:
    """Takas düzeyi: modelin ve oyuncu tahmininin işaret uyumu ve sıra korelasyonu (gerçekleşen değer farkıyla)."""
    if pairs.empty:
        return {"n": 0}
    sign = lambda col: float((np.sign(pairs[col]) == np.sign(pairs["realized"])).mean())
    return {"n": len(pairs), "model_sign": sign("model"), "forecast_sign": sign("forecast"),
            "model_spearman": _spearman(pairs["model"], pairs["realized"]),
            "forecast_spearman": _spearman(pairs["forecast"], pairs["realized"])}
