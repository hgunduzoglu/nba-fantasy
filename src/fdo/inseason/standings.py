"""Mevcut H2H kategori sıralaması (W-L-T) — Yahoo standings anlık görüntülerinden (README §13.14).

Kaynaklar: ``yahoo_fantasy_snapshot.json`` (``leagues[].standings``), ``league_<id>_standings_raw.json`` ve
elle hazırlanabilecek ``standings*.csv`` (league_id, team_id, wins, losses, ties). Satırdaki kayıt
``"7-2-0"`` biçimindedir (kategori galibiyeti-mağlubiyeti-beraberliği); takım kimliği bağlantıdan okunur.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

_TEAM = re.compile(r"/nba/(\d+)/(\d+)/?$")
_REC = re.compile(r"^\s*(\d+)-(\d+)-(\d+)\s*$")
COLUMNS = ["league_id", "team_id", "wins", "losses", "ties"]


def _rows(rows, league_id: str | None = None) -> list[dict]:
    """Satır listesi ya da ``{"table": {"rows": [...]}}``; takım kimliği ``team_id`` alanı ya da bağlantıdan."""
    if isinstance(rows, dict):
        rows = (rows.get("table") or {}).get("rows", [])
    out = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        rec = next((m for c in r.get("cells", []) if (m := _REC.match(str(c)))), None)
        tid = str(r["team_id"]) if r.get("team_id") else None
        lid = None
        for link in ([] if tid else r.get("links", [])):
            if m := _TEAM.search(str(link.get("url", ""))):
                lid, tid = m.group(1), m.group(2)
                break
        if rec and tid:
            out.append({"league_id": str(league_id or lid), "team_id": tid, "wins": int(rec.group(1)),
                        "losses": int(rec.group(2)), "ties": int(rec.group(3))})
    return out


def load_standings(directory: str | Path) -> pd.DataFrame:
    directory = Path(directory)
    rows: list[dict] = []
    snap = directory / "yahoo_fantasy_snapshot.json"
    if snap.exists():
        data = json.loads(snap.read_text(encoding="utf-8-sig"))
        for lg in data.get("leagues", []):
            rows += _rows(lg.get("standings"), str(lg.get("league_id")))
    for path in sorted(directory.glob("league_*_standings_raw.json")):
        lid = path.name.split("_")[1]
        rows += _rows(json.loads(path.read_text(encoding="utf-8-sig")), lid)
    for path in sorted(directory.glob("standings*.csv")):
        df = pd.read_csv(path, dtype={"league_id": str, "team_id": str})
        if set(COLUMNS) <= set(df.columns):
            rows += df[COLUMNS].to_dict("records")
    if not rows:
        return pd.DataFrame(columns=COLUMNS)
    df = pd.DataFrame(rows).astype({"league_id": str, "team_id": str})
    # aynı takım birden çok kaynakta: en çok oynanmış kategori sayısı (en güncel) kalır
    df["games"] = df["wins"] + df["losses"] + df["ties"]
    df = df.sort_values("games").drop_duplicates(["league_id", "team_id"], keep="last")
    return df[COLUMNS].reset_index(drop=True)


def league_standings(standings: pd.DataFrame, league_id: str, team_ids) -> pd.DataFrame | None:
    """Ligin tüm takımları varsa ``team_id`` index'li W-L-T; eksikse ``None``."""
    sub = standings[standings["league_id"] == str(league_id)].set_index("team_id")
    teams = [str(t) for t in team_ids]
    if not set(teams) <= set(sub.index):
        return None
    return sub.loc[teams, ["wins", "losses", "ties"]]
