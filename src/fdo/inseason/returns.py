"""Sakatlık dönüşü: CBS'in "en erken" tarihi ile gerçek dönüşün karşılaştırılması ve dönüş gecikmesi varsayımı.

CBS "Expected to be out until at least <tarih>" en erken tarihtir; oyuncu çoğu zaman daha geç döner. Model bu tarihe
``delay_days`` gün ekler (``config/returns.yaml``, ``fdo.inseason.injuries.return_delay``; varsayılan 0 = CBS'in
tarihi). Varsayım doğrulanmadı:
``observed_returns`` her CBS raporundaki en erken tarihi NBA maç kayıtlarındaki ilk maçla karşılaştırır,
``return_curve`` henüz dönmeyenleri sansürlü sayarak (Kaplan–Meier) "en erken tarihten sonra k gün / k takım maçı içinde
dönme" oranını verir (``scripts/calibrate_returns.py``). Örnek az oldukça eğri belirsizdir; sayılar örnek boyutuyla
birlikte okunmalı.
"""

from __future__ import annotations

import datetime as dt
import io
import re
from pathlib import Path

import numpy as np
import pandas as pd

from fdo.ingest.archive import batches, read_object, root
from fdo.inseason.identity import Resolver
from fdo.inseason.injuries import interpret
from fdo.schedule.calendar import normalize_team

_REPORT = re.compile(r"injuries_cbs_(\d{4}-\d{2}-\d{2})\.csv$")


def load_reports(directory: str | Path) -> list[tuple[dt.date, pd.DataFrame]]:
    """Bütün CBS raporları, güne göre (gün başına bir): veri dizinindeki ``injuries_cbs_<gün>.csv``, eski günlük
    kopyalar (``snapshots/<gün>/``) ve değiştirilemez arşivin partileri. Aynı gün birden çok kaynakta varsa ilk bulunan."""
    directory = Path(directory)
    out: dict[dt.date, pd.DataFrame] = {}

    def add(name: str, read) -> None:
        m = _REPORT.search(name)
        if m and dt.date.fromisoformat(m.group(1)) not in out:
            out[dt.date.fromisoformat(m.group(1))] = read()
    for p in [*sorted(directory.glob("injuries_cbs_*.csv")), *sorted(root(directory).glob("*/injuries_cbs_*.csv"))]:
        add(p.name, lambda p=p: pd.read_csv(p, dtype=str, keep_default_na=False))
    for m in batches(directory):
        for name, info in m["files"].items():
            add(name, lambda info=info: pd.read_csv(io.BytesIO(read_object(directory, info["sha256"])), dtype=str,
                                                    keep_default_na=False))
    return sorted(out.items(), key=lambda x: x[0])


def observed_returns(reports: list[tuple[dt.date, pd.DataFrame]], logs: pd.DataFrame, players: pd.DataFrame,
                     season_start: dt.date, overrides: pd.DataFrame | None = None) -> pd.DataFrame:
    """Her "out until at least" satırı için (oyuncu ve en erken tarih başına bir gözlem, ilk rapordan): raporun ardından
    oynadığı ilk maç, ``delay_days`` (ilk maç − en erken tarih; negatif: erken döndü), ``games_missed`` (en erken
    tarihten ilk maça kadar takımının oynadığı maç). Henüz oynamadıysa ``returned=False``: gecikme en az son maç
    gününe kadarki kadardır (sansür). En erken tarihi son maç gününden sonra olanlar bilgi vermez, dışarıda kalır."""
    cols = ["player_id", "name", "report_date", "stated", "first_game", "returned", "delay_days", "games_missed"]
    if logs is None or logs.empty:
        return pd.DataFrame(columns=cols)
    logs = logs.assign(game_date=pd.to_datetime(logs["game_date"]).dt.date,
                       nba_team=logs["nba_team"].map(normalize_team))
    last = max(logs["game_date"])
    resolve = Resolver(players, overrides, source="cbs")
    one = Resolver(players, overrides)
    keys = logs[["name", "nba_team"]].drop_duplicates()
    ids = {(r.name, r.nba_team): one(r.name, r.nba_team).player_id for r in keys.itertuples()}
    logs = logs.assign(player_id=[ids[(n, t)] for n, t in zip(logs["name"], logs["nba_team"])])
    played = logs[logs["minutes"].fillna(0) > 0] if "minutes" in logs else logs
    by_player = {p: sorted(g) for p, g in played.groupby("player_id")["game_date"]}
    team_days = {t: sorted(set(g)) for t, g in logs.groupby("nba_team")["game_date"]}
    team_of = {p: t for p, t in played.groupby("player_id")["nba_team"].last().items()}
    seen: set[tuple[str, dt.date]] = set()
    rows = []
    for report_date, rep in sorted(reports, key=lambda x: x[0]):
        for r in rep.itertuples():
            kind, stated = interpret(r.status_text, season_start)
            if kind != "out_until" or stated is None or stated > last:
                continue
            pid = resolve(r.name, getattr(r, "nba_team", "")).player_id
            if pid is None or (pid, stated) in seen:
                continue
            seen.add((pid, stated))
            games = [d for d in by_player.get(pid, []) if d >= report_date]
            first = games[0] if games else None
            team = team_of.get(pid) or normalize_team(str(getattr(r, "nba_team", "") or ""))
            end = first or last + dt.timedelta(days=1)
            missed = sum(stated <= d < end for d in team_days.get(team, []))
            rows.append({"player_id": pid, "name": r.name, "report_date": report_date, "stated": stated,
                         "first_game": first, "returned": first is not None,
                         "delay_days": ((first or last + dt.timedelta(days=1)) - stated).days, "games_missed": missed})
    return pd.DataFrame(rows, columns=cols)


def _survival(obs: pd.DataFrame, unit: str) -> list[tuple[float, float]]:
    """Kaplan–Meier: (dönüş anı, o andan sonra hâlâ dönmemiş olma oranı). Erken dönüş (negatif) 0 sayılır."""
    t = obs[unit].clip(lower=0).to_numpy(float)
    e = obs["returned"].to_numpy(bool)
    out, s = [], 1.0
    for x in np.unique(t[e]):
        s *= 1 - float(((t == x) & e).sum()) / float((t >= x).sum())
        out.append((float(x), s))
    return out


def return_curve(obs: pd.DataFrame, unit: str = "games_missed", points=(0, 1, 2, 3, 5, 8)) -> pd.DataFrame:
    """En erken tarihten sonra en çok ``k`` (takım maçı ya da gün) içinde dönmüş olma oranı; dönmeyenler gözlem sonuna
    kadar sansürlü. ``at_risk``: k'de hâlâ izlenen gözlem (azsa oran belirsiz)."""
    curve = _survival(obs, unit)
    t = obs[unit].clip(lower=0).to_numpy(float)
    rows = []
    for k in points:
        s = min((v for x, v in curve if x <= k), default=1.0)
        rows.append({"k": k, "returned_share": 1 - s, "at_risk": int((t >= k).sum())})
    return pd.DataFrame(rows)


def median_delay(obs: pd.DataFrame, unit: str = "delay_days") -> float | None:
    """Dönüşlerin yarısının gerçekleştiği gecikme (Kaplan–Meier medyanı); gözlem yetmiyorsa ``None``."""
    return next((x for x, s in _survival(obs, unit) if s <= 0.5), None) if len(obs) else None

