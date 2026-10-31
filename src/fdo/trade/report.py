"""UI/CLI için karşılaştırma tabloları ve taşınabilir senaryo çıktısı."""

from __future__ import annotations

import json
import math
from dataclasses import asdict

import numpy as np
import pandas as pd

from fdo.trade.engine import TradeEngine, TradeResult
from fdo.trade.strategy import CATEGORIES


def category_changes(result: TradeResult, mode: str, team_id: str) -> pd.DataFrame:
    before, after = result.before[mode], result.after[mode]
    return pd.DataFrame({"önce": before.totals.loc[team_id], "sonra": after.totals.loc[team_id],
                         "değer farkı": after.totals.loc[team_id] - before.totals.loc[team_id],
                         "sıra önce": before.ranks.loc[team_id], "sıra sonra": after.ranks.loc[team_id],
                         "sıra kazancı": before.ranks.loc[team_id] - after.ranks.loc[team_id]})


def opponent_changes(engine: TradeEngine, result: TradeResult, team_id: str) -> pd.DataFrame:
    i = engine.team_index[team_id]
    keep = [j for j, tid in enumerate(engine.team_ids) if tid != team_id]
    before, after = result.probabilities_before[i, keep], result.probabilities_after[i, keep]
    df = pd.DataFrame((after - before) * 100, columns=CATEGORIES,
                      index=[engine.league.teams[engine.team_ids[j]] for j in keep])
    df.insert(0, "ECW önce", before.sum(axis=1))
    df.insert(1, "ECW sonra", after.sum(axis=1))
    df.insert(2, "P(5+) önce", result.matchup_before[i, keep] * 100)
    df.insert(3, "P(5+) sonra", result.matchup_after[i, keep] * 100)
    return df


def _clean(obj):
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (tuple, list)):
        return [_clean(x) for x in obj]
    if isinstance(obj, (float, np.floating)):
        return float(obj) if math.isfinite(obj) else None
    if isinstance(obj, np.integer):
        return int(obj)
    return obj


def export_result(engine: TradeEngine, result: TradeResult) -> str:
    payload = {"schema_version": 1, "league_id": engine.league.league_id,
               "data_as_of": engine.data.as_of.isoformat(), "fingerprint": engine.data.fingerprint,
               "sources": engine.data.sources, "request": asdict(result.request),
               "strategies": {t: asdict(s) for t, s in result.strategies.items()},
               "metrics": result.metrics.to_dict(orient="index"), "assessments": result.assessments,
               "adjustments": result.adjustments, "rosters_after": result.rosters_after,
               "comparisons": {mode: {t: category_changes(result, mode, t).to_dict(orient="index")
                                      for t in result.strategies} for mode in result.before},
               "opponents": {t: opponent_changes(engine, result, t).to_dict(orient="index")
                             for t in result.strategies}, "assumptions": result.notes}
    return json.dumps(_clean(payload), ensure_ascii=False, indent=2, allow_nan=False)
