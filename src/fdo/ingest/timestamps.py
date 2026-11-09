"""Dosya bazında zaman bilgisi: kaynağın anlattığı an ve verinin çekildiği an.

* ``source_as_of``: kaynağın hangi zamanın gerçeğini anlattığı (kadro tarihi, son maç günü, projeksiyon tarihi).
* ``captured_at``: verinin kaynaktan alındığı an (dosyanın kendi içindeki kayıt).
* ``file_modified_at``: dosyanın diskte değiştiği an. Kaynak zamanı bilinmiyorsa onun yerine geçmez; ayrı alandır.

Dosyanın içinde kayıt yoksa alan ``None`` kalır. Zamanlar dosyadaki biçimiyle (ISO metin) döner.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

import pandas as pd

#: Dosya adı kalıbı → bileşen. İlk eşleşen geçerli.
COMPONENTS = (
    ("rosters.json", "rosters"), ("player_stat_pages.json", "player_stats"), ("yahoo_live.json", "live_week"),
    ("matchups.json", "results"), ("league_info.json", "league_settings"), ("standings*.csv", "standings"),
    ("injuries*.csv", "injuries"), ("gamelogs_nba_*.csv", "nba_logs"), ("news*.json", "news"),
    ("projections_yahoo_*.csv", "preseason_projection"), ("players_yahoo_*.csv", "player_master"),
    ("adp_yahoo_*.csv", "adp"), ("draft_results.csv", "draft"), ("schedule*.csv", "schedule"),
    ("variance*.csv", "variance"), ("fixtures*.csv", "fixtures"), ("transactions.csv", "transactions"),
)


def component(name: str) -> str:
    for pattern, comp in COMPONENTS:
        if Path(name).match(pattern):
            return comp
    return "other"


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _max(path: Path, column: str) -> str | None:
    try:
        values = pd.read_csv(path, usecols=[column], dtype=str)[column].dropna()
    except (ValueError, KeyError):
        return None
    return str(values.max()) if len(values) else None


def file_times(path: str | Path) -> dict:
    path = Path(path)
    comp = component(path.name)
    out = {"component": comp, "source_as_of": None, "captured_at": None, "rows": None,
           "file_modified_at": dt.datetime.fromtimestamp(path.stat().st_mtime, dt.timezone.utc)
           .isoformat(timespec="seconds")}
    try:
        if comp == "rosters":
            d = _json(path)
            out.update(source_as_of=d.get("roster_date"), captured_at=d.get("captured_at"),
                       rows=sum(sum(1 for s in t["slots"] if s.get("player_id"))
                                for lg in d.get("leagues", []) for t in lg["teams"]))
        elif comp == "player_stats":
            pages = _json(path)
            stamps = [p.get("captured_at") for p in pages if p.get("captured_at")]
            out.update(captured_at=max(stamps) if stamps else None, rows=sum(len(p["table"]["rows"]) for p in pages))
        elif comp == "live_week":
            d = _json(path)
            out.update(source_as_of=d.get("as_of"), captured_at=d.get("captured_at"))
        elif comp == "results":
            d = _json(path)
            out.update(captured_at=d.get("results_updated_at") or d.get("exported_at"))
        elif comp == "league_settings":
            d = _json(path)
            out.update(captured_at=d.get("updated_at") or d.get("captured_at"))
        elif comp == "news":
            d = _json(path)
            out.update(captured_at=d.get("fetched_at"), rows=len(d.get("items", [])))
        elif comp == "injuries":
            out.update(captured_at=_max(path, "captured_at"))
        elif comp == "nba_logs":
            out.update(source_as_of=_max(path, "game_date"))
        elif comp in ("preseason_projection", "adp"):
            out.update(source_as_of=_max(path, "as_of"))
    except (OSError, ValueError, KeyError, TypeError):
        pass                                      # bozuk dosya: zaman bilinmiyor; doğrulama ayrı raporlar
    if comp in ("injuries", "preseason_projection", "adp", "player_master") and out["source_as_of"] is None \
            and out["captured_at"] is None:
        m = re.search(r"(\d{4}-\d{2}-\d{2})", path.name)      # yalnız ad tarihi: çekim günü olarak işaretlenir
        if m:
            out["captured_on"] = m[1]
    return out
