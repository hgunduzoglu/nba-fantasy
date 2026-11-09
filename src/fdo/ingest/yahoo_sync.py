"""Yahoo senkronizasyonu: kurulu Chrome profilinin çerezleriyle lig sayfalarını okur ve yerel anlık
görüntüleri günceller (README §13.20).

Çerezler Chrome profilinden bir kez alınır (Playwright, görünmez pencere); sayfalar düz HTTP ile, aralarında
bekleyerek çekilir. Yazılanlar (hepsi ``data/real`` altında, git dışı):

* ``rosters.json`` — başlangıç kadroları (``roster_date`` = ABD Doğu saatine göre bugün).
* ``player_stat_pages.json`` — sezon toplamı ve kalan sezon projeksiyonu sayfaları (``players=True`` ise).
* ``standings_live.csv`` — kategori W-L-T (``fdo.inseason.standings`` okur).
* ``matchups.json`` — biten haftaların kategori sonuçları ve takım toplamları (eksik olanlar çekilir).
* ``yahoo_live.json`` — içinde bulunulan haftanın takım toplamları, kullanıcının alım hakkı, FAB, waiver listesi.

Üzerine yazmadan önce analiz girdilerinin o anki hâli, yazdıktan sonra da yeni hâli değiştirilemez arşive alınır
(``fdo.ingest.archive``, ``snapshots/`` altında): aynı gün ikinci çekim ilkini silmez, aynı içerik ikinci kez saklanmaz.

Haftanın toplamı çekildiği ana kadardır. ABD Doğu saatiyle 02:00–12:00 arası maç oynanmaz (Türkiye ~10:00–20:00):
bu aralıkta toplam tam olarak "dünküne kadar"dır. Dışında ``live=True`` işaretlenir (bugünün kısmi skoru dahil).
"""

from __future__ import annotations

import datetime as dt
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pandas as pd

from fdo.ingest import yahoo_html as Y
from fdo.ingest.archive import ArchiveResult, archive

BASE = "https://basketball.fantasysports.yahoo.com"
PAGE_SIZE = 25
MAX_PLAYERS = 750
#: Senkronizasyonun yazdığı / anlık görüntüye aldığı dosyalar.
#: ``fdo.trade.data.ROS`` ile aynı (ingest, trade'e bağımlı olmasın diye tekrarlandı).
ROS = "remaining_games_projection"
OUTPUTS = ("rosters.json", "player_stat_pages.json", "standings_live.csv", "matchups.json", "yahoo_live.json")


class NotLoggedIn(RuntimeError):
    pass


def et_now() -> pd.Timestamp:
    return pd.Timestamp.now(tz="America/New_York")


def is_live(now: pd.Timestamp) -> bool:
    """NBA maçı sürüyor olabilir mi (ABD Doğu 12:00–02:00)."""
    return not (2 <= now.hour < 12)


class Fetcher:
    """Chrome profilinin çerezleriyle düz HTTP; istekler arasında ``delay`` saniye beklenir."""

    def __init__(self, delay: float = 0.8):
        import requests
        from playwright.sync_api import Error as PlaywrightError, sync_playwright

        from fdo.ingest.yahoo_session import find_chrome, profile_dir

        chrome = find_chrome()
        if chrome is None:
            raise RuntimeError("Google Chrome bulunamadı; FDO_CHROME ile chrome.exe yolunu ver.")
        try:
            with sync_playwright() as p:
                ctx = p.chromium.launch_persistent_context(str(profile_dir()), executable_path=str(chrome),
                                                           headless=True)
                cookies = ctx.cookies()
                ua = ctx.new_page().evaluate("navigator.userAgent").replace("HeadlessChrome", "Chrome")
                ctx.close()
        except PlaywrightError as e:
            raise RuntimeError("Chrome profili açılamadı; giriş penceresi açıksa kapat. " + str(e)[:200]) from e
        if not any(c["name"] == "T" for c in cookies):
            raise NotLoggedIn("Yahoo oturumu yok: python scripts/yahoo_login.py ile giriş yap.")
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": ua, "Accept-Language": "en-US,en;q=0.9"})
        for c in cookies:
            self.session.cookies.set(c["name"], c["value"], domain=c["domain"], path=c["path"])
        self.delay = delay
        self.count = 0

    def __call__(self, path: str) -> str:
        if self.count:
            time.sleep(self.delay)
        self.count += 1
        r = self.session.get(BASE + path, timeout=30)
        if "login.yahoo.com" in r.url:
            raise NotLoggedIn("Yahoo oturumu düşmüş: python scripts/yahoo_login.py ile yeniden giriş yap.")
        r.raise_for_status()
        return r.text


@dataclass
class SyncResult:
    captured_at: str
    as_of: dt.date
    live: bool
    pages: int = 0
    written: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    batch_id: str | None = None                  # arşivdeki parti (Yahoo dosyaları yazıldıktan sonra)


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else None


def _write(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def snapshot(directory: Path, note: str = "") -> ArchiveResult:
    """Analiz girdilerinin o anki hâlini değiştirilemez arşive alır (``fdo.ingest.archive``); son partiyle aynıysa
    yeni parti açılmaz."""
    return archive(directory, source="yahoo_sync", note=note)


def player_pages(fetch: Callable[[str], str], league_id: str, season_year: int, captured: Callable[[], str]
                 ) -> tuple[list[dict], int]:
    """Sezon toplamı ve kalan sezon projeksiyonu sayfaları (``player_stat_pages.json`` biçimi)."""
    pages, n = [], 0
    for kind, stat in (("season_total", f"S_S_{season_year}"), (ROS, "S_PSR")):
        for count in range(0, MAX_PLAYERS, PAGE_SIZE):
            path = (f"/nba/{league_id}/players?status=ALL&pos=P&cut_type=33&stat1={stat}&myteam=0&sort=AR"
                    f"&sdir=1&count={count}")
            table = Y.parse_player_table(fetch(path), league_id)
            n += 1
            if not table or not table["rows"]:
                break
            pages.append({"kind": kind, "source_url": BASE + path, "captured_at": captured(), "table": table})
            if len(table["rows"]) < PAGE_SIZE:
                break
    return pages, n


def waiver_list(fetch: Callable[[str], str], league_id: str, today: dt.date) -> tuple[list[dict], int]:
    out, n = [], 0
    for count in range(0, 200, PAGE_SIZE):
        table = Y.parse_player_table(fetch(f"/nba/{league_id}/players?status=W&pos=P&stat1=S_PSR&sort=AR&sdir=1"
                                           f"&count={count}"), league_id)
        n += 1
        rows = table["rows"] if table else []
        for r in rows:
            until = Y.waiver_date(r.get("roster_status", ""), today)
            out.append({"player_id": r["player_id"], "player_name": r["player_name"],
                        "until": until.isoformat() if until else None})
        if len(rows) < PAGE_SIZE:
            break
    return out, n


def _result(teams: list[dict]) -> dict:
    a, b = teams
    wa, wb = a["category_wins"] or 0, b["category_wins"] or 0
    return {"team_a_category_wins": wa, "team_b_category_wins": wb, "tied_categories": 9 - wa - wb,
            "winner_team_id": a["team_id"] if wa > wb else b["team_id"] if wb > wa else None,
            "team_a_totals": a["totals"], "team_b_totals": b["totals"]}


def sync(directory: str | Path, fetch: Callable[[str], str], *, players: bool = True,
         now: pd.Timestamp | None = None, log: Callable[[str], None] = lambda s: None) -> SyncResult:
    directory = Path(directory)
    now = now if now is not None else et_now()
    as_of = now.date()
    stamp = lambda: dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    res = SyncResult(stamp(), as_of, is_live(now))
    old_rosters = _read(directory / "rosters.json")
    if old_rosters is None:
        raise FileNotFoundError("rosters.json yok: ilk anlık görüntü (lig listesi, sezon) gerekli.")
    leagues = [(str(lg["league_id"]), lg["league_name"], len(lg["teams"])) for lg in old_rosters["leagues"]]
    season = old_rosters["season"]
    snapshot(directory, f"senkronizasyon öncesi (kadro {old_rosters['roster_date']})")
    roster_leagues, standings, live = [], [], {}
    matchups_doc = _read(directory / "matchups.json")
    for lid, name, n_teams in leagues:
        log(f"{name}: lig sayfası")
        home = Y.parse_league_home(fetch(f"/nba/{lid}"), lid)
        res.pages += 1
        if home["week"] is None or not home["standings"]:
            raise RuntimeError(f"{name}: lig sayfası okunamadı (sayfa yapısı değişmiş olabilir).")
        teams = Y.parse_starting_rosters(fetch(f"/nba/{lid}/startingrosters"), lid)
        res.pages += 1
        if len(teams) != n_teams or not all(t["slots"] for t in teams):
            raise RuntimeError(f"{name}: başlangıç kadroları okunamadı ({len(teams)}/{n_teams} takım).")
        roster_leagues.append({"league_id": lid, "league_name": name, "league_url": f"{BASE}/nba/{lid}",
                               "source_url": f"{BASE}/nba/{lid}/startingrosters", "captured_at": stamp(),
                               "teams": teams})
        standings += [{"league_id": lid, **{k: v for k, v in r.items() if k != "team_name"}}
                      for r in home["standings"]]
        week = home["week"]
        log(f"{name}: {week}. hafta eşleşmeleri")
        current = []
        for a, b in home["matchups"]:
            rows = Y.parse_matchup(fetch(f"/nba/{lid}/matchup?date=totals&week={week}&mid1={a}&mid2={b}"), lid)
            res.pages += 1
            if len(rows) != 2:
                raise RuntimeError(f"{name}: {a}–{b} eşleşme tablosu okunamadı.")
            current.append({"team_a_id": rows[0]["team_id"], "team_b_id": rows[1]["team_id"],
                            "team_a_totals": rows[0]["totals"], "team_b_totals": rows[1]["totals"],
                            "team_a_category_wins": rows[0]["category_wins"],
                            "team_b_category_wins": rows[1]["category_wins"]})
        me = home["my_team"]
        team_info = Y.parse_team_page(fetch(f"/nba/{lid}/{me}")) if me else {}
        res.pages += 1 if me else 0
        waivers, n = waiver_list(fetch, lid, as_of)
        res.pages += n
        live[lid] = {"week": week, "my_team": me, **team_info, "matchups": current, "waivers": waivers}
        if matchups_doc:
            for m in matchups_doc["matchups"]:
                if str(m["league_id"]) != lid or int(m["week"]) >= week or m.get("team_a_totals"):
                    continue
                log(f"{name}: {m['week']}. hafta sonucu {m['team_a_id']}–{m['team_b_id']}")
                url = f"/nba/{lid}/matchup?date=totals&week={m['week']}&mid1={m['team_a_id']}&mid2={m['team_b_id']}"
                rows = Y.parse_matchup(fetch(url), lid)
                res.pages += 1
                by_id = {r["team_id"]: r for r in rows}
                if {m["team_a_id"], m["team_b_id"]} != set(by_id):
                    res.notes.append(f"{name}: {m['week']}. hafta {m['team_a_id']}–{m['team_b_id']} okunamadı.")
                    continue
                m.update(_result([by_id[m["team_a_id"]], by_id[m["team_b_id"]]]),
                         result_status="final", result_source_url=BASE + url, result_captured_at=stamp())
    stat_pages = None
    if players:
        log("Oyuncu sayfaları (sezon toplamı + kalan sezon projeksiyonu)")
        stat_pages, n = player_pages(fetch, leagues[0][0], int(season[:4]), stamp)
        res.pages += n
        kinds = {k: sum(len(p["table"]["rows"]) for p in stat_pages if p["kind"] == k) for k in ("season_total", ROS)}
        if min(kinds.values()) < 0.9 * MAX_PLAYERS:
            res.notes.append(f"Oyuncu sayfaları eksik ({kinds}); eski istatistikler korundu.")
            stat_pages = None
    # ---- yaz (doğrulamalar geçtikten sonra)
    _write(directory / "rosters.json", {**{k: v for k, v in old_rosters.items() if k != "leagues"},
                                        "roster_date": as_of.isoformat(), "captured_at": res.captured_at,
                                        "source": "Yahoo Fantasy Basketball / Starting Rosters (fdo sync)",
                                        "leagues": roster_leagues})
    res.written.append("rosters.json")
    if stat_pages:
        _write(directory / "player_stat_pages.json", stat_pages)
        res.written.append("player_stat_pages.json")
    pd.DataFrame(standings).to_csv(directory / "standings_live.csv", index=False, encoding="utf-8")
    res.written.append("standings_live.csv")
    if matchups_doc:
        weeks = sorted({int(m["week"]) for m in matchups_doc["matchups"] if m.get("team_a_totals")})
        matchups_doc.update(results_updated_at=res.captured_at, collected_result_weeks=weeks)
        _write(directory / "matchups.json", matchups_doc)
        res.written.append("matchups.json")
    _write(directory / "yahoo_live.json", {"captured_at": res.captured_at, "captured_et": now.isoformat(),
                                           "as_of": as_of.isoformat(), "live": res.live, "leagues": live})
    res.written.append("yahoo_live.json")
    res.batch_id = snapshot(directory, f"senkronizasyon sonrası (kadro {as_of.isoformat()})").batch_id
    if res.live:
        res.notes.append("Canlı maç saatinde çekildi: haftalık toplamlara bugünün kısmi skoru dahil olabilir.")
    return res
