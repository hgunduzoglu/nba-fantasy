"""NBA normal sezon takvimini şemaya uygun CSV'ye ve manifest'e çevirir (README §13.4).

Kaynak, NBA'in herkese açık takvim JSON'udur (``scheduleLeagueV2.json``). Dosyayı tarayıcıdan
indirip ``--input`` ile verebilir ya da ``--download`` ile script'e indirtebilirsiniz. CDN bazı
ağlardan 403 döndürür; bu durumda (``nba_api`` kuruluysa) aynı yapıdaki stats.nba.com
``scheduleleaguev2`` endpoint'i kullanılır.
Kullanım şartları kararı **kullanıcınındır** (§5.1): ``--license-status`` verilmezse
manifest'e ``unknown`` yazılır ve UI uyarı gösterir.

    python scripts/fetch_nba_schedule.py --download --season 2026-27
    python scripts/fetch_nba_schedule.py --input scheduleLeagueV2.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pandas as pd
import yaml

from fdo.config import REPO_ROOT

URL = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json"


def parse(payload: dict) -> pd.DataFrame:
    """Normal sezon maçları (``gameId`` 002 ile başlar): tarih (ET), ev sahibi, deplasman.

    Takımları henüz belli olmayan maçlar (NBA Cup eleme turu) atlanır; takvim sonra yeniden çekilmelidir.
    """
    rows = []
    for day in payload["leagueSchedule"]["gameDates"]:
        for g in day["games"]:
            gid = str(g.get("gameId", ""))
            home, away = g["homeTeam"].get("teamTricode"), g["awayTeam"].get("teamTricode")
            if not gid.startswith("002") or not home or not away:
                continue
            date = str(g.get("gameDateEst") or day["gameDate"])
            date = pd.to_datetime(date.replace("Z", ""), format="mixed").date().isoformat()
            rows.append({"game_date": date, "home_team": home, "away_team": away, "game_id": gid})
    return pd.DataFrame(rows).sort_values(["game_date", "game_id"]).reset_index(drop=True)


def from_stats(season: str | None) -> dict:
    try:
        from nba_api.stats.endpoints import scheduleleaguev2
    except ImportError as e:
        raise SystemExit('nba_api kurulu değil: pip install -e ".[nba]"') from e
    if not season:
        raise SystemExit("stats.nba.com için --season gerekli (örn. 2026-27)")
    return scheduleleaguev2.ScheduleLeagueV2(league_id="00", season=season, timeout=90).get_dict()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--input", help="indirilmiş scheduleLeagueV2.json")
    src.add_argument("--download", action="store_true", help=f"{URL} adresinden indir")
    ap.add_argument("--season", default=None, help="manifest için sezon (varsayılan: config)")
    ap.add_argument("--out", default=str(REPO_ROOT / "data" / "real"))
    ap.add_argument("--manifests", default=str(REPO_ROOT / "data" / "manifests"))
    ap.add_argument("--license-status", default="unknown",
                    choices=["personal_use_confirmed", "assumed", "unknown"])
    ap.add_argument("--license-notes", default="Kullanım şartları doğrulanmadı (§5.1).")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(errors="replace")

    source_url = URL
    if args.download:
        try:
            req = urllib.request.Request(URL, headers={"User-Agent": "fdo-schedule/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                payload = json.loads(r.read().decode("utf-8"))
        except urllib.error.URLError as e:
            print(f"CDN erişilemedi ({e}); stats.nba.com scheduleleaguev2 deneniyor (nba_api)")
            payload = from_stats(args.season)
            source_url = "https://stats.nba.com/stats/scheduleleaguev2"
    else:
        payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    df = parse(payload)
    season = args.season or payload["leagueSchedule"].get("seasonYear", "")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"schedule_nba_{str(season).replace('/', '-')}.csv"
    df.to_csv(path, index=False)
    manifest = {
        "file": path.relative_to(REPO_ROOT).as_posix(), "kind": "schedule", "source_name": "NBA schedule JSON",
        "source_url": source_url, "retrieved_at": dt.date.today().isoformat(),
        "retrieved_by": "scripts/fetch_nba_schedule.py", "license_status": args.license_status,
        "license_notes": args.license_notes, "season": season, "is_synthetic": False,
    }
    mdir = Path(args.manifests)
    mdir.mkdir(parents=True, exist_ok=True)
    (mdir / f"{path.name}.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True),
                                            encoding="utf-8")
    teams = pd.concat([df["home_team"], df["away_team"]]).value_counts()
    print(f"{len(df)} maç, {len(teams)} takım (takım başına {teams.min()}–{teams.max()}) -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
