"""Yerel Yahoo anlık görüntülerini ortak kimliklerle, kaynakları karıştırmadan okur."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from fdo.config import Config, REPO_ROOT, load_config
from fdo.types import STATS

MODES = {
    "preseason": "Sezon öncesi projeksiyon",
    "season_total": "Bu sezon gerçekleşen",
    "remaining_games_projection": "Kalan sezon projeksiyon",
}
ROS = "remaining_games_projection"
SLOT_ELIGIBILITY = {"PG": ["PG"], "SG": ["SG"], "G": ["PG", "SG"],
                    "SF": ["SF"], "PF": ["PF"], "F": ["SF", "PF"], "C": ["C"],
                    "FC": ["SF", "PF", "C"], "UTIL": ["PG", "SG", "SF", "PF", "C"],
                    "BN": ["PG", "SG", "SF", "PF", "C"]}


@dataclass(frozen=True)
class TradeLeague:
    league_id: str
    name: str
    teams: dict[str, str]
    rosters: dict[str, tuple[str, ...]]
    injury_rosters: dict[str, frozenset[str]]
    settings: dict[str, str]
    config: Config
    default_team_id: str
    roster_date: dt.date
    lineups: dict[str, dict[str, str]] = field(default_factory=dict)    # takım → oyuncu → slot (roster_date günü)

    @property
    def capacity(self) -> int:
        return self.config.roster.size


@dataclass
class TradeData:
    leagues: dict[str, TradeLeague]
    players: pd.DataFrame                    # index: Yahoo player_id (metin)
    stats: dict[str, pd.DataFrame]            # gp + STATS: ilgili dönemin TOPLAMLARI
    sources: dict[str, dict]
    variance: pd.DataFrame | None
    schedule: pd.DataFrame | None
    as_of: dt.date
    fingerprint: str
    issues: tuple[str, ...]
    injuries: pd.DataFrame | None = None     # fdo.inseason.injuries.apply_injuries ile (dönüş tarihleri)
    durability: pd.DataFrame | None = None   # fdo.inseason.durability.apply_durability ile (oynama oranları)


def number(value) -> float:
    """Kaynakta '-' eksik kalır; gerçek sıfırdan ayrıdır."""
    if value is None or str(value).strip() in ("", "-", "--"):
        return float("nan")
    return float(str(value).replace(",", ""))


def file_signature(directory: str | Path) -> str:
    directory = Path(directory)
    names = ["rosters.json", "league_info.json", "player_stat_pages.json", "matchups.json", "yahoo_live.json"]
    paths = [directory / n for n in names]
    paths += list(directory.glob("standings*.csv"))
    paths += list(directory.glob("players_yahoo_*.csv"))
    paths += list(directory.glob("projections_yahoo_*.csv"))
    paths += list(directory.glob("variance*.csv")) + list(directory.glob("schedule*.csv"))
    paths += list(directory.glob("injuries*.csv")) + list(directory.glob("gamelogs_nba_*.csv"))
    paths += list((REPO_ROOT / "config").glob("*.yaml"))
    return hashlib.sha256("|".join(f"{p}:{p.stat().st_mtime_ns}:{p.stat().st_size}"
                                  for p in sorted(paths) if p.exists()).encode()).hexdigest()[:20]


def _config(settings: dict[str, str], n_teams: int, season: str, name: str) -> Config:
    if settings.get("Scoring Type") != "Head-to-Head - Categories":
        raise ValueError(f"{name}: desteklenmeyen scoring türü")
    expected = ("FG%", "FT%", "3PTM", "PTS", "REB", "AST", "ST", "BLK", "TO")
    if any(f"({c})" not in settings.get("Players Stat Categories", "") for c in expected):
        raise ValueError(f"{name}: H2H 9 kategori ayarları eksik veya farklı")
    slots = Counter(s.strip().upper() for s in settings["Roster Positions"].split(","))
    il, il_plus = slots.pop("IL", 0), slots.pop("IL+", 0)
    unknown = set(slots) - set(SLOT_ELIGIBILITY)
    if unknown:
        raise ValueError(f"{name}: bilinmeyen slotlar {unknown}")
    lock = {"Daily - Today": "daily_today", "Daily - Tomorrow": "daily_tomorrow",
            "Weekly": "weekly"}.get(settings.get("Weekly Deadline"))
    # Takım sayısı Max Teams kapasitesi değil, anlık görüntüdeki gerçek takım sayısıdır.
    base = load_config()
    mix = {key: 0 for key in base.model.bots.mix}
    mix["MarketFollower"] = n_teams - 1
    return base.with_overrides({
        "league": {"name": name, "season": season, "teams": n_teams, "my_seat": 1,
                   "rounds": sum(slots.values()), "draft_type": "snake"},
        "roster": {"slots": dict(slots), "active_slots": [s for s in slots if s != "BN"],
                   "slot_eligibility": SLOT_ELIGIBILITY},
        "unverified": {"lineup_lock": lock, "il_slots": il, "il_plus_slots": il_plus},
        "model": {"bots": {"mix": mix}, "valuation": {"pool_size": n_teams * sum(slots.values())}},
    })


def _stat_pages(pages: list[dict], kind: str) -> tuple[pd.DataFrame, dict]:
    records, dates, urls = [], [], []
    for page in pages:
        if page["kind"] != kind:
            continue
        dates.append(page["captured_at"])
        urls.append(page["source_url"])
        headers = page["table"]["headers"][-1]
        required = {"gp": "GP*", "fgm": "FGM/A*", "ftm": "FTM/A*", "fg3m": "3PTM",
                    "pts": "PTS", "reb": "REB", "ast": "AST", "stl": "ST", "blk": "BLK", "tov": "TO"}
        idx = {k: headers.index(v) for k, v in required.items()}
        for row in page["table"]["rows"]:
            c = row["cells"]
            r = {"player_id": str(row["player_id"]), "gp": number(c[idx["gp"]])}
            for mk, at in (("fgm", "fga"), ("ftm", "fta")):
                pair = c[idx[mk]].split("/")
                r[mk], r[at] = (number(x) for x in pair)
            r.update({s: number(c[idx[s]]) for s in STATS if s not in ("fgm", "fga", "ftm", "fta")})
            r["reported_fg_pct"] = number(c[headers.index("FG%")])
            r["reported_ft_pct"] = number(c[headers.index("FT%")])
            records.append(r)
    if not records:
        raise ValueError(f"İstatistik kaynağı yok: {kind}")
    df = pd.DataFrame(records).set_index("player_id")
    if df.index.has_duplicates:
        raise ValueError(f"{kind}: aynı oyuncu birden fazla istatistik satırında")
    return df, {"captured_at": max(dates), "source_url": urls[0], "pages": len(urls),
                "basis": "period_total", "kind": kind}


def preseason_file(directory: Path, season: str, schedule: pd.DataFrame | None) -> Path:
    """Sonradan eklenen sezon içi CSV, sezon öncesi kaynağının yerine geçemez."""
    year = int(season[:4])
    start = pd.to_datetime(schedule["game_date"]).min().date() if schedule is not None else None
    candidates = []
    for path in directory.glob("projections_yahoo_*.csv"):
        dates = pd.to_datetime(pd.read_csv(path, usecols=["as_of"])["as_of"], errors="coerce").dropna()
        if len(dates):
            latest = dates.max().date()
            if latest.year == year and (start is None or latest < start):
                candidates.append((latest, path))
    if not candidates:
        raise ValueError("Sezon öncesi tarihli projeksiyon CSV'si bulunamadı")
    # Takvim yoksa en erken kayıt açık tarih bilgisiyle korunur; haftalık model ayrıca süre ister.
    return (max(candidates) if start is not None else min(candidates))[1]


def load_trade_data(directory: str | Path | None = None) -> TradeData:
    directory = Path(directory) if directory else REPO_ROOT / "data" / "real"
    read = lambda n: json.loads((directory / n).read_text(encoding="utf-8-sig"))
    root, info = read("rosters.json"), read("league_info.json")
    as_of = dt.date.fromisoformat(root["roster_date"])
    meta = {str(lg["league_id"]): lg for lg in info["leagues"]}
    master_path = sorted(directory.glob("players_yahoo_*.csv"))[-1]
    master = pd.read_csv(master_path, dtype=str, keep_default_na=False)
    master["player_id"] = master["yahoo_player_id"].astype(str)
    if master["player_id"].duplicated().any():
        raise ValueError("Oyuncu kimlikleri benzersiz değil")
    players = master.set_index("player_id")[["name", "nba_team", "yahoo_positions", "injury_status"]].copy()
    leagues = {}
    for lg in root["leagues"]:
        lid = str(lg["league_id"])
        settings = meta[lid]["settings"]["values"]
        team_names, rosters, injury, occupied, lineups = {}, {}, {}, set(), {}
        for team in lg["teams"]:
            tid = str(team["team_id"])
            if tid in team_names:
                raise ValueError(f"{lid}: tekrarlanan team_id {tid}")
            team_names[tid] = team["team_name"]
            ids, il_ids = [], set()
            lineups[tid] = {str(sl["player_id"]): sl["slot"] for sl in team["slots"] if sl.get("player_id")}
            for slot in team["slots"]:
                if not slot.get("player_id"):
                    continue
                pid = str(slot["player_id"])
                if pid in occupied:
                    raise ValueError(f"{lid}: oyuncu iki kadroda: {pid}")
                occupied.add(pid)
                ids.append(pid)
                if slot.get("is_injury_slot", slot["slot"] in ("IL", "IL+")):
                    il_ids.add(pid)
                players.loc[pid] = [slot["player_name"], slot["nba_team"],
                                    ",".join(slot["eligible_positions"]), slot.get("status") or ""]
            rosters[tid], injury[tid] = tuple(ids), frozenset(il_ids)
        collected = meta[lid].get("schedules", {}).get("teams", [])
        # Kullanıcının takımı: is_user_team işareti (tam fikstür); yoksa tek fikstürü toplanan takım.
        flagged = [str(t["team_id"]) for t in collected if str(t.get("is_user_team")).lower() == "true"]
        preferred = (flagged[0] if flagged else str(collected[0]["team_id"]) if len(collected) == 1
                     else next(iter(team_names)))
        leagues[lid] = TradeLeague(lid, lg["league_name"], team_names, rosters, injury, settings,
                                  _config(settings, len(rosters), root["season"], lg["league_name"]),
                                  preferred if preferred in team_names else next(iter(team_names)), as_of, lineups)
    stats, sources = {}, {}
    sp = sorted(directory.glob("schedule*.csv"))
    schedule = pd.read_csv(sp[-1]) if sp else None
    preseason_path = preseason_file(directory, root["season"], schedule)
    pre = pd.read_csv(preseason_path, dtype={"player_id": str})
    id_map = master.assign(internal_id=master["player_id"].map(lambda x: "y_" + x)).set_index("internal_id")["player_id"]
    pre["player_id"] = pre["player_id"].map(id_map)
    if pre["player_id"].isna().any() or pre["player_id"].duplicated().any():
        raise ValueError("Sezon öncesi projeksiyon kimlikleri eşlenemedi")
    pre = pre.set_index("player_id")
    stats["preseason"] = pre[list(STATS)].mul(pre["projected_gp"], axis=0)
    stats["preseason"]["gp"] = pre["projected_gp"]
    sources["preseason"] = {"file": preseason_path.name, "as_of": str(pre["as_of"].max()),
                             "basis": "per_game × projected_gp"}
    pages = read("player_stat_pages.json")
    for kind in ("season_total", ROS):
        stats[kind], sources[kind] = _stat_pages(pages, kind)
    # Yeni istatistik sayfalarında bulunan, eski kimlik dosyasında olmayan oyuncular da korunur. Senkronizasyonun
    # yazdığı satırlar (``status`` alanı) kadroda olmayan oyuncunun takımını ve sakatlık durumunu da günceller.
    on_roster = {p for lg in leagues.values() for r in lg.rosters.values() for p in r}
    for page in pages:
        for row in page["table"]["rows"]:
            pid = str(row["player_id"])
            if "status" in row and pid not in on_roster:
                players.loc[pid] = [row["player_name"], row["nba_team"], ",".join(row["positions"]),
                                    row["status"] or ""]
            elif pid not in players.index:
                text = row["cells"][2]
                match = re.search(r"\n([A-Z]+) - ([A-Z,]+)", text)
                players.loc[pid] = [row["player_name"], match[1] if match else "",
                                    match[2] if match else "", ""]
    for mode in stats:
        stats[mode] = stats[mode].reindex(players.index)
    vp = sorted(directory.glob("variance*.csv"))
    variance = pd.read_csv(vp[-1], dtype={"player_id": str}) if vp else None
    if variance is not None:
        variance["player_id"] = variance["player_id"].str.removeprefix("y_")
    issues = []
    for mode, frame in stats.items():
        missing = ~frame[["gp", *STATS]].notna().all(axis=1)
        bad = (frame[list(STATS)] < 0).any(axis=1) | (frame["fgm"] > frame["fga"]) | (frame["ftm"] > frame["fta"])
        if missing.any():
            issues.append(f"{MODES[mode]}: {int(missing.sum())} oyuncuda eksik sayısal alan; ham veri korunur.")
        if bad.any():
            issues.append(f"{MODES[mode]}: {int(bad.sum())} oyuncuda tutarsız şut/sayım verisi.")
        for cat in ("reported_fg_pct", "reported_ft_pct"):
            if cat in frame and ((frame[cat] < 0) | (frame[cat] > 1)).any():
                issues.append(f"{MODES[mode]}: kaynakta geçersiz {cat}; takım yüzdeleri isabet/denemeden hesaplanır.")
    return TradeData(leagues, players, stats, sources, variance, schedule, as_of,
                     file_signature(directory), tuple(issues))
