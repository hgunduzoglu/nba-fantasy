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
import json
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



def delay_pmf(obs: pd.DataFrame, unit: str = "games_missed", max_k: int = 10) -> dict[int, float]:
    """Dönüş gecikmesi dağılımı (Kaplan–Meier'den): en erken tarihten sonra tam ``k`` takım maçı daha kaçırma
    olasılığı ``P(T = k)``; son değer (``max_k``) kuyruktur, ``P(T ≥ max_k)``. Gözlem yoksa ``{0: 1}`` (CBS tarihi)."""
    if not len(obs):
        return {0: 1.0}
    curve = _survival(obs, unit)

    def survive(k: int) -> float:                                  # P(T > k)
        return min((v for x, v in curve if x <= k), default=1.0)
    out, prev = {}, 1.0
    for k in range(max_k):
        s = survive(k)
        out[k] = max(0.0, prev - s)
        prev = s
    out[max_k] = max(0.0, prev)
    return out


def questionable_outcomes(reports: list[tuple[dt.date, pd.DataFrame]], logs: pd.DataFrame, players: pd.DataFrame,
                          season_start: dt.date, overrides: pd.DataFrame | None = None) -> pd.DataFrame:
    """Belirsiz (game time decision, day-to-day, questionable, probable, doubtful) listelenen oyuncuların takımının
    rapordan sonraki ilk maçında oynayıp oynamadığı: oyuncu ve maç başına bir gözlem (ilk rapordan). Maç kayıtlarının
    son gününden sonraki maçlar bilinmediği için dışarıda kalır."""
    cols = ["player_id", "name", "report_date", "game", "played"]
    if logs is None or logs.empty:
        return pd.DataFrame(columns=cols)
    on, team_days, team_of, last = _log_index(logs, players, overrides)
    resolve = Resolver(players, overrides, source="cbs")
    seen: set[tuple[str, dt.date]] = set()
    rows = []
    for report_date, rep in sorted(reports, key=lambda x: x[0]):
        for r in rep.itertuples():
            if interpret(r.status_text, season_start)[0] != "day_to_day":
                continue
            pid = resolve(r.name, getattr(r, "nba_team", "")).player_id
            team = team_of.get(pid) or normalize_team(str(getattr(r, "nba_team", "") or ""))
            game = next((d for d in team_days.get(team, []) if d >= report_date), None)
            if pid is None or game is None or game > last or (pid, game) in seen:
                continue
            seen.add((pid, game))
            rows.append({"player_id": pid, "name": r.name, "report_date": report_date, "game": game,
                         "played": (pid, game) in on})
    return pd.DataFrame(rows, columns=cols)


def _log_index(logs: pd.DataFrame, players: pd.DataFrame, overrides: pd.DataFrame | None):
    """Maç kayıtlarından: oynanan (oyuncu, gün) kümesi, takım → maç günleri, oyuncu → son takımı, son maç günü."""
    logs = logs.assign(game_date=pd.to_datetime(logs["game_date"]).dt.date,
                       nba_team=logs["nba_team"].map(normalize_team))
    one = Resolver(players, overrides)
    keys = logs[["name", "nba_team"]].drop_duplicates()
    ids = {(r.name, r.nba_team): one(r.name, r.nba_team).player_id for r in keys.itertuples()}
    logs = logs.assign(player_id=[ids[(n, t)] for n, t in zip(logs["name"], logs["nba_team"])])
    played = logs[logs["minutes"].fillna(0) > 0] if "minutes" in logs else logs
    on = set(zip(played["player_id"], played["game_date"]))
    team_days = {t: sorted(set(g)) for t, g in logs.groupby("nba_team")["game_date"]}
    team_of = {p: t for p, t in logs.groupby("player_id")["nba_team"].last().items()}
    return on, team_days, team_of, max(logs["game_date"])


def load_roster_snapshots(directory: str | Path) -> list[tuple[dt.date, dict]]:
    """Yahoo kadro anlık görüntüleri (``rosters.json``), güne göre: arşiv partileri, eski günlük kopyalar
    (``snapshots/<gün>/``) ve güncel dosya. Aynı gün birden çok kez yakalandıysa en erken yakalanan (maçlardan önceki
    durum)."""
    directory = Path(directory)
    found: list[dict] = []
    for m in batches(directory):
        info = m["files"].get("rosters.json")
        if info:
            found.append(json.loads(read_object(directory, info["sha256"])))
    for path in [*sorted(root(directory).glob("*/rosters.json")), directory / "rosters.json"]:
        if path.exists():
            found.append(json.loads(path.read_text(encoding="utf-8")))
    out: dict[dt.date, dict] = {}
    for d in found:
        day = d.get("roster_date")
        if not day:
            continue
        day = dt.date.fromisoformat(day)
        if day not in out or str(d.get("captured_at") or "") < str(out[day].get("captured_at") or ""):
            out[day] = d
    return sorted(out.items(), key=lambda x: x[0])


def yahoo_questionable_outcomes(snapshots: list[tuple[dt.date, dict]], logs: pd.DataFrame, players: pd.DataFrame,
                                overrides: pd.DataFrame | None = None,
                                statuses: tuple[str, ...] = ("Q", "GTD", "DTD")) -> pd.DataFrame:
    """Yahoo'da ``statuses`` etiketli (modelin haftalık kadroda kullandığı etiket) kadrolu oyuncuların takımının o gün
    ya da sonraki ilk maçında oynayıp oynamadığı: oyuncu ve maç başına bir gözlem (ilk anlık görüntüden). Anlık görüntü
    maçlardan önce alınır; maç kayıtlarının son gününden sonraki maçlar dışarıda kalır."""
    cols = ["player_id", "name", "status", "report_date", "game", "played"]
    if logs is None or logs.empty:
        return pd.DataFrame(columns=cols)
    on, team_days, team_of, last = _log_index(logs, players, overrides)
    seen: set[tuple[str, dt.date]] = set()
    rows = []
    for day, snap in sorted(snapshots, key=lambda x: x[0]):
        for league in snap.get("leagues", []):
            for team in league.get("teams", []):
                for slot in team.get("slots", []):
                    status, pid = slot.get("status"), str(slot.get("player_id") or "")
                    if status not in statuses or not pid:
                        continue
                    nba = team_of.get(pid) or normalize_team(str(slot.get("nba_team") or ""))
                    game = next((d for d in team_days.get(nba, []) if d >= day), None)
                    if game is None or game > last or (pid, game) in seen:
                        continue
                    seen.add((pid, game))
                    rows.append({"player_id": pid, "name": slot.get("player_name"), "status": status,
                                 "report_date": day, "game": game, "played": (pid, game) in on})
    return pd.DataFrame(rows, columns=cols)
