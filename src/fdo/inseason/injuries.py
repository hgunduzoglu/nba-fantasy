"""Sakatlık dönüş tarihleri: CBS Sports NBA injury report (README §13.16).

CBS sayfasında her takımın tablosu: oyuncu, pozisyon, güncelleme, sakatlık, durum metni. Durum metni:

* ``Expected to be out until at least Nov 20`` → ``out_until``, dönüş = o gün (en erken tahmin);
* ``Out for the season`` → ``season`` (kalan sezonda oynamaz);
* ``Game Time Decision`` / ``Day-To-Day`` / ``Questionable`` / ``Probable`` → ``day_to_day`` (oynar);
* diğerleri → ``unknown`` (yalnızca Yahoo durumu kullanılır).

Model etkisi (``apply_injuries``): dönüşten sonra takımın oynayacağı maç sayısı kalan sezon (ROS)
projeksiyonundaki maçtan azsa ROS toplamları orantılı küçültülür (``season`` → sıfır). Haftalık model ve
sezon simülasyonu oyuncuyu dönüş gününe kadar oynatmaz, sonrasında kalan maçlarını dönüş sonrasına yayar.
Ham dosyalar değişmez; düzeltme bellekte ve açıkça raporlanır.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import html as html_lib
import re
from pathlib import Path

import numpy as np
import pandas as pd

from fdo.ingest.identity import IdentityReport, Resolver, load_overrides
from fdo.schedule.calendar import normalize_team
from fdo.trade.data import ROS, TradeData
from fdo.types import STATS

SOURCE_URL = "https://www.cbssports.com/nba/injuries/"
_TITLE = re.compile(r"TableBase-title")
_TEAM = re.compile(r"/nba/teams/([A-Z]{2,4})/")
_ROW = re.compile(r'<tr class="TableBase-bodyTr">(.*?)</tr>', re.S)
_CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_LONG = re.compile(r'CellPlayerName--long">.*?<a[^>]*>(.*?)</a>', re.S)
_TAG = re.compile(r"<[^>]+>")
_UNTIL = re.compile(r"out until (?:at least )?([A-Z][a-z]{2})[a-z]*\.?\s+(\d{1,2})", re.I)
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/120 Safari/537.36", "Accept-Language": "en-US,en;q=0.9"}
DTD = ("game time decision", "day-to-day", "day to day", "questionable", "probable", "doubtful")


def _text(s: str) -> str:
    return " ".join(html_lib.unescape(_TAG.sub(" ", s)).split())


def parse_cbs(page: str) -> pd.DataFrame:
    """CBS injury sayfası → ``name, nba_team, position, updated, injury, status_text``."""
    starts = [m.start() for m in _TITLE.finditer(page)] + [len(page)]
    rows = []
    for a, b in zip(starts[:-1], starts[1:]):
        block = page[a:b]
        team = _TEAM.search(block)
        for tr in _ROW.findall(block):
            cells = _CELL.findall(tr)
            if len(cells) < 5:
                continue
            name = _LONG.search(cells[0])
            rows.append({"name": _text(name.group(1) if name else cells[0]),
                         "nba_team": team.group(1) if team else "", "position": _text(cells[1]),
                         "updated": _text(cells[2]), "injury": _text(cells[3]), "status_text": _text(cells[4])})
    return pd.DataFrame(rows, columns=["name", "nba_team", "position", "updated", "injury", "status_text"])


def interpret(status: str, season_start: dt.date) -> tuple[str, dt.date | None]:
    """Durum metni → (tür, dönüş tarihi). Yıl, sezonun başladığı aydan önceki aylar için +1."""
    s = str(status or "")
    low = s.lower()
    if "out for the season" in low or "season-ending" in low:
        return "season", None
    if m := _UNTIL.search(s):
        month = dt.datetime.strptime(m.group(1)[:3].title(), "%b").month
        year = season_start.year + (1 if month < season_start.month else 0)
        return "out_until", dt.date(year, month, int(m.group(2)))
    if any(k in low for k in DTD):
        return "day_to_day", None
    return "unknown", None


def fetch_cbs(out_dir: str | Path, season_start: dt.date, page: str | None = None) -> tuple[Path, pd.DataFrame]:
    """CBS sayfasını indirir (``page`` verilirse onu ayrıştırır) ve ``injuries_cbs_<UTC tarih>.csv`` yazar."""
    import requests

    captured = dt.datetime.now(dt.timezone.utc)
    if page is None:
        r = requests.get(SOURCE_URL, headers=HEADERS, timeout=30)
        r.raise_for_status()
        page = r.text
    df = parse_cbs(page)
    if df.empty:
        raise ValueError("Sakatlık tablosu bulunamadı (CBS sayfa yapısı değişmiş olabilir).")
    kinds = [interpret(s, season_start) for s in df["status_text"]]
    df["kind"] = [k for k, _ in kinds]
    df["return_date"] = [d.isoformat() if d else "" for _, d in kinds]
    df["source_url"] = SOURCE_URL
    df["captured_at"] = captured.isoformat(timespec="seconds")
    out = Path(out_dir) / f"injuries_cbs_{captured.date().isoformat()}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False, encoding="utf-8")
    return out, df


def refresh_cbs(directory: str | Path) -> str:
    """CBS raporunu günceller (Yahoo senkronizasyonundan sonra); sezon başlangıcı NBA takviminden. Hata
    senkronizasyonu düşürmez, açıklama olarak döner."""
    directory = Path(directory)
    sched = sorted(directory.glob("schedule*.csv"))
    start = (pd.to_datetime(pd.read_csv(sched[-1], usecols=["game_date"])["game_date"]).min().date()
             if sched else dt.date(dt.date.today().year, 10, 1))
    try:
        out, df = fetch_cbs(directory, start)
    except Exception as e:  # noqa: BLE001 — ayrı kaynak
        return f"CBS sakatlık raporu alınamadı: {e}"
    return f"CBS sakatlık raporu: {len(df)} kayıt → {out.name}"


def latest_file(directory: str | Path) -> Path | None:
    files = sorted(Path(directory).glob("injuries_cbs_*.csv"))
    return files[-1] if files else None


def match_injuries(inj: pd.DataFrame, players: pd.DataFrame, season_start: dt.date,
                   overrides: pd.DataFrame | None = None) -> tuple[pd.DataFrame, IdentityReport]:
    """CBS satırlarını oyunculara eşler (``fdo.ingest.identity``: yalnız tek aday kalınca; aynı adlı birden çok aday
    karantinada kalır). Dönüş: ``player_id`` index'li tablo ve eşleştirme raporu (eşleşmeyen / belirsiz satırlar)."""
    resolve = Resolver(players, overrides, source="cbs")
    report = IdentityReport("CBS sakatlık raporu")
    out = []
    for r in inj.itertuples():
        m = resolve(r.name, r.nba_team)
        report.add(f"{r.name} ({r.nba_team})", m)
        if m.player_id is None:
            continue
        kind, ret = interpret(r.status_text, season_start)
        out.append({"player_id": m.player_id, "cbs_name": r.name, "kind": kind, "return_date": ret,
                    "status_text": r.status_text, "injury": r.injury, "updated": r.updated, "match": m.method})
    cols = ["player_id", "cbs_name", "kind", "return_date", "status_text", "injury", "updated", "match"]
    df = pd.DataFrame(out, columns=cols)
    return df.drop_duplicates("player_id").set_index("player_id"), report


def match_players(inj: pd.DataFrame, players: pd.DataFrame, season_start: dt.date,
                  overrides: pd.DataFrame | None = None) -> pd.DataFrame:
    """``match_injuries`` tablosu (rapor olmadan)."""
    return match_injuries(inj, players, season_start, overrides)[0]


def team_games_from(schedule: pd.DataFrame) -> dict[str, list[dt.date]]:
    s = schedule.assign(game_date=pd.to_datetime(schedule["game_date"]).dt.date)
    out: dict[str, list[dt.date]] = {}
    for col in ("home_team", "away_team"):
        for t, g in s.groupby(s[col].map(normalize_team))["game_date"]:
            out.setdefault(t, []).extend(g.tolist())
    return {t: sorted(v) for t, v in out.items()}


def apply_injuries(data: TradeData, injuries: pd.DataFrame, source: str = SOURCE_URL) -> TradeData:
    """ROS toplamlarını dönüş tarihine göre kısar ve sakatlık tablosunu ekler (yeni ``TradeData``)."""
    games = team_games_from(data.schedule)
    stats = {k: v.copy() for k, v in data.stats.items()}
    ros = stats[ROS]
    rows = []
    for pid, r in injuries.iterrows():
        if pid not in ros.index or pid not in data.players.index:
            continue
        team = normalize_team(data.players.loc[pid, "nba_team"] or "")
        start = data.as_of
        if r["kind"] == "out_until" and r["return_date"] is not None and not pd.isna(r["return_date"]):
            start = max(start, pd.Timestamp(r["return_date"]).date())
        elif r["kind"] != "season":
            continue
        left = 0 if r["kind"] == "season" else sum(d >= start for d in games.get(team, []))
        gp = float(ros.loc[pid, "gp"]) if np.isfinite(ros.loc[pid, "gp"]) else np.nan
        new_gp = min(gp, left) if np.isfinite(gp) else np.nan
        if np.isfinite(gp) and gp > 0 and new_gp < gp:
            ros.loc[pid, [*STATS, "gp"]] = ros.loc[pid, [*STATS, "gp"]] * (new_gp / gp)
        rows.append({"player_id": pid, "kind": r["kind"], "return_date": r["return_date"],
                     "games_after_return": left, "ros_gp_before": gp, "ros_gp_after": new_gp})
    table = injuries.join(pd.DataFrame(rows).set_index("player_id")[["games_after_return", "ros_gp_before",
                                                                      "ros_gp_after"]], how="left") \
        if rows else injuries.assign(games_after_return=np.nan, ros_gp_before=np.nan, ros_gp_after=np.nan)
    cut = int((table["ros_gp_after"] < table["ros_gp_before"]).sum())
    sources = {**data.sources, "injuries": {"source_url": source, "kind": "injuries", "rows": len(table)}}
    note = (f"Sakatlık dönüş tarihleri uygulandı ({len(table)} eşleşen oyuncu, {cut} oyuncunun kalan sezon "
            "maçı dönüş tarihine göre kısıldı).")
    return dataclasses.replace(data, stats=stats, sources=sources, injuries=table,
                               fingerprint=f"{data.fingerprint}:inj{len(table)}:{cut}",
                               issues=(*data.issues, note))


def with_injuries(data: TradeData, directory: str | Path) -> TradeData:
    """En yeni ``injuries_cbs_*.csv`` varsa eşleştirip uygular; yoksa ya da eşleşme yoksa ``data`` aynen döner."""
    path = latest_file(directory)
    if path is None:
        return data
    raw = pd.read_csv(path, dtype=str, keep_default_na=False)
    start = pd.to_datetime(data.schedule["game_date"]).min().date() if data.schedule is not None else data.as_of
    matched, report = match_injuries(raw, data.players, start, load_overrides(directory))
    note = f"{report.note()} ({path.name})"
    if matched.empty:
        return dataclasses.replace(data, issues=(*data.issues, note))
    out = apply_injuries(data, matched, source=f"{SOURCE_URL} ({path.name})")
    return dataclasses.replace(out, issues=(*out.issues, note))
