"""Geçmiş haftalar: takımın her hafta kategori değerleri ve ligdeki sırası (README §13.23).

Kaynak: ``matchups.json``'daki biten haftaların takım toplamları (Yahoo senkronizasyonu, §13.20) ve içinde
bulunulan haftanın şu ana kadarki toplamları (``yahoo_live.json``; ``partial``). Kategori değeri: FG% = FGM/FGA,
FT% = FTM/FTA, diğerleri hafta toplamı. Sıra 1 = ligin en iyisi (TO'da en az); eşitlikte en iyi sıra paylaşılır.
Sezon satırı biten haftaların toplamlarının toplamıdır (oranlar isabet/deneme toplamından).
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from fdo.inseason.live import LiveLeague
from fdo.trade.strategy import CATEGORIES

COUNTS = {"FG3M": "fg3m", "PTS": "pts", "REB": "reb", "AST": "ast", "STL": "stl", "BLK": "blk", "TOV": "tov"}
FIELDS = ("fgm", "fga", "ftm", "fta", *COUNTS.values())


def category_values(totals: dict[str, float]) -> dict[str, float]:
    t = {k: float(totals.get(k) or 0) for k in FIELDS}
    out = {"FG_PCT": t["fgm"] / t["fga"] if t["fga"] else float("nan"),
           "FT_PCT": t["ftm"] / t["fta"] if t["fta"] else float("nan")}
    out.update({c: t[k] for c, k in COUNTS.items()})
    return out


def rank_table(totals: dict[str, dict[str, float]]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Takım → toplamlar ⇒ (değerler, sıralar) tabloları (index takım, sütun kategori)."""
    values = pd.DataFrame({t: category_values(v) for t, v in totals.items()}).T[list(CATEGORIES)]
    ranks = values.rank(ascending=False, method="min")
    ranks["TOV"] = values["TOV"].rank(ascending=True, method="min")
    return values, ranks


def finished_weeks(directory: str | Path, league_id: str) -> dict[int, list[dict]]:
    """Hafta → o haftanın sonuçlanmış eşleşmeleri (takım toplamlarıyla)."""
    path = Path(directory) / "matchups.json"
    if not path.exists():
        return {}
    out: dict[int, list[dict]] = {}
    for m in json.loads(path.read_text(encoding="utf-8-sig")).get("matchups", []):
        if str(m["league_id"]) == str(league_id) and m.get("team_a_totals") and m.get("team_b_totals"):
            out.setdefault(int(m["week"]), []).append(m)
    return dict(sorted(out.items()))


def team_history(directory: str | Path, league_id: str, team_id: str, live: LiveLeague | None = None) -> dict:
    weeks = finished_weeks(directory, league_id)
    rows, season = [], {}
    for week, ms in weeks.items():
        totals, result = {}, None
        for m in ms:
            a, b = str(m["team_a_id"]), str(m["team_b_id"])
            totals[a], totals[b] = m["team_a_totals"], m["team_b_totals"]
            if team_id in (a, b):
                mine_a = team_id == a
                result = {"opponent": b if mine_a else a,
                          "wins": m.get("team_a_category_wins" if mine_a else "team_b_category_wins"),
                          "losses": m.get("team_b_category_wins" if mine_a else "team_a_category_wins"),
                          "ties": m.get("tied_categories")}
        for t, v in totals.items():
            acc = season.setdefault(t, dict.fromkeys(FIELDS, 0.0))
            for k in FIELDS:
                acc[k] += float(v.get(k) or 0)
        rows.append(_row(week, totals, team_id, result, partial=False))
    if live is not None and live.totals and live.week not in weeks:
        opp = live.opponents.get(team_id)
        result = {"opponent": opp, "wins": live.category_wins.get(team_id), "losses": live.category_wins.get(opp),
                  "ties": None} if opp else None
        rows.append(_row(live.week, live.totals, team_id, result, partial=True))
    return {"weeks": [r for r in rows if r is not None],
            "season": _row(0, season, team_id, None, partial=False) if team_id in season else None}


def _row(week: int, totals: dict[str, dict], team_id: str, result: dict | None, partial: bool) -> dict | None:
    if team_id not in totals:
        return None
    values, ranks = rank_table(totals)
    return {"week": week, "partial": partial, "n_teams": len(values), "result": result,
            "values": values.loc[team_id].to_dict(), "ranks": ranks.loc[team_id].to_dict(),
            "median": values.median().to_dict(), "best": {c: (values[c].min() if c == "TOV" else values[c].max())
                                                          for c in CATEGORIES}}
