"""API yanıtları için JSON'a uygun dönüşümler (NaN → null, numpy → Python)."""

from __future__ import annotations

import datetime as dt
import math

import numpy as np
import pandas as pd

from fdo.api.state import SOURCES
from fdo.trade.data import MODES
from fdo.trade.engine import TradeEngine, TradeResult
from fdo.trade.report import category_changes
from fdo.trade.strategy import CATEGORIES, PRESETS, Strategy
from fdo.types import CATEGORY_LABELS

PER_GAME = ("fgm", "fga", "ftm", "fta", "fg3m", "pts", "reb", "ast", "stl", "blk", "tov")
CAT_STAT = {"FG3M": "fg3m", "PTS": "pts", "REB": "reb", "AST": "ast", "STL": "stl", "BLK": "blk", "TOV": "tov"}


def clean(obj):
    """JSON'a uygun: NaN/inf → None, numpy sayıları → Python, tarih → ISO."""
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [clean(x) for x in obj]
    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        return float(obj) if math.isfinite(obj) else None
    if isinstance(obj, (dt.date, pd.Timestamp)):
        return obj.isoformat() if not pd.isna(obj) else None
    if obj is pd.NaT:
        return None
    return obj


def categories_meta() -> list[dict]:
    return [{"key": c, "label": CATEGORY_LABELS[c], "lower_is_better": c == "TOV"} for c in CATEGORIES]


def strategy_from(payload: dict | None) -> Strategy:
    """``{"preset": "Punt FT_PCT"}`` ya da ``{"name": .., "weights": [9]}``; yoksa dengeli."""
    if not payload:
        return Strategy()
    if payload.get("preset"):
        return Strategy.preset(payload["preset"])
    w = payload.get("weights")
    if w:
        return Strategy(str(payload.get("name") or "Özel"), tuple(float(x) for x in w))
    return Strategy()


def presets() -> list[dict]:
    return [{"name": n, "weights": list(Strategy.preset(n).weights)} for n in PRESETS]


def injury_info(eng: TradeEngine, pid: str) -> dict | None:
    inj = getattr(eng.data, "injuries", None)
    if inj is None or pid not in inj.index:
        return None
    r = inj.loc[pid]
    return {"kind": r["kind"], "return_date": r["return_date"], "text": r.get("status_text", ""),
            "injury": r.get("injury", "")}


def player_row(eng: TradeEngine, pid: str, source: str, z: pd.DataFrame, *, il: frozenset = frozenset(),
               ranks: pd.Series | None = None) -> dict:
    P = eng.data.players
    f = eng.data.stats[SOURCES[source]]
    row = f.loc[pid] if pid in f.index else None
    gp = float(row["gp"]) if row is not None and pd.notna(row["gp"]) else None
    per = {}
    if row is not None and gp and gp > 0:
        per = {s: float(row[s]) / gp if pd.notna(row[s]) else None for s in PER_GAME}
    stats = {c: per.get(CAT_STAT[c]) for c in CAT_STAT}
    for c, (m, a) in {"FG_PCT": ("fgm", "fga"), "FT_PCT": ("ftm", "fta")}.items():
        stats[c] = per[m] / per[a] if per.get(m) is not None and per.get(a) else None
    zrow = z.loc[pid] if pid in z.index else None
    return clean({
        "id": pid, "name": P.loc[pid, "name"], "nba_team": P.loc[pid, "nba_team"],
        "positions": [p for p in str(P.loc[pid, "yahoo_positions"]).split(",") if p],
        "status": P.loc[pid, "injury_status"] or "", "il": pid in il,
        "injury": injury_info(eng, pid), "modeled": bool(eng.modeled[eng.index[pid]]),
        "gp": gp, "stats": stats, "attempts": {k: per.get(k) for k in ("fgm", "fga", "ftm", "fta")},
        "z": {c: (float(zrow[c]) if zrow is not None and c in zrow else None) for c in CATEGORIES},
        "value": float(eng.market.get(pid, 0.0)),
        "rank": float(ranks[pid]) if ranks is not None and pid in ranks.index else None,
    })


def value_ranks(eng: TradeEngine) -> pd.Series:
    modeled = [p for p in eng.ids if eng.modeled[eng.index[p]]]
    return eng.market.loc[modeled].rank(ascending=False, method="first")


def trade_result(eng: TradeEngine, result: TradeResult, *, perceived: pd.Series | None = None) -> dict:
    a, b = result.request.team_a, result.request.team_b
    names = eng.data.players["name"]
    teams = {}
    for side, tid in (("a", a), ("b", b)):
        i = eng.team_index[tid]
        keep = np.arange(len(eng.team_ids)) != i
        pb = result.probabilities_before[i, keep].mean(axis=0)
        pa = result.probabilities_after[i, keep].mean(axis=0)
        m = result.metrics.loc[tid]
        adj = result.adjustments[tid]
        teams[side] = {
            "team_id": tid, "team": eng.league.teams[tid], "strategy": result.strategies[tid].name,
            "ecw_before": m.ecw_before, "ecw_after": m.ecw_after, "ecw_delta": m.ecw_delta,
            "win_before": m.win_before, "win_after": m.win_after, "win_delta": m.win_delta,
            "strategy_before": m.strategy_before, "strategy_after": m.strategy_after,
            "strategy_delta": m.strategy_delta, "fit_score": result.assessments["fit_scores"][tid],
            "categories": [{"key": c, "label": CATEGORY_LABELS[c], "before": float(x), "after": float(y)}
                           for c, x, y in zip(CATEGORIES, pb, pa)],
            "adjustments": {k: [{"id": p, "name": names[p]} for p in v] for k, v in adj.items()},
            "ranks": {mode: [{"key": c, "label": CATEGORY_LABELS[c], "value_before": r["önce"], "value_after": r["sonra"],
                              "rank_before": r["sıra önce"], "rank_after": r["sıra sonra"]}
                             for c, r in category_changes(result, mode, tid).iterrows()] for mode in MODES},
        }
    req = result.request
    balance = None
    if perceived is not None:
        given = float(perceived.reindex(list(req.give_a)).fillna(0).sum())
        taken = float(perceived.reindex(list(req.give_b)).fillna(0).sum())
        balance = given / taken if taken > 0 else None
    return clean({"teams": teams, "fairness": result.assessments["fairness_ratio"], "perceived_balance": balance,
                  "assessments": {k: v for k, v in result.assessments.items() if k != "fit_scores"},
                  "notes": result.notes, "modes": MODES})
