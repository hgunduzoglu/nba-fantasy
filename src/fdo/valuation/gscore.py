"""G-score (README §6.2.4).

``G = (x − μ) / sqrt(σ² + κ·τ²)``, ``τ² = mean_{j∈P} Var_within(j)`` (x ile aynı tabanda).
Rosenof, *Improving Algorithms for Fantasy Basketball*, arXiv:2307.02188.

**κ makaleden doğrulanmadı**; UI κ değerini gösterir. τ = 0 iken G == Z.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from fdo.config import Config
from fdo.matchup.player_week import ratio_game_variance
from fdo.types import COUNTING_CATEGORY_STAT
from fdo.valuation.pool import PoolStats, category_values, ratio_stats


def within_variance(proj: pd.DataFrame, var_pg: pd.DataFrame, x_index: pd.Index,
                    stats: PoolStats, config: Config, basis: str) -> pd.DataFrame:
    """Kategori başına oyuncu içi varyans, ``x`` ile aynı tabanda (index ``player_id``)."""
    p = proj.set_index("player_id").reindex(x_index)
    v = var_pg.reindex(x_index)
    scale = p["projected_gp"].astype(float) if basis == "total" else 1.0
    out = {}
    for cat in config.categories:
        if config.scoring.is_ratio(cat):
            mk, at = ratio_stats(config, cat)
            per_game = ratio_game_variance(p[mk], p[at], v[at], stats.pbar[cat])
            out[cat] = pd.Series(per_game, index=x_index) * scale
        else:
            out[cat] = v[COUNTING_CATEGORY_STAT[cat]].astype(float) * scale
    return pd.DataFrame(out, index=x_index)


def tau_squared(within: pd.DataFrame, stats: PoolStats) -> dict[str, float]:
    pool = within.loc[within.index.intersection(list(stats.pool_ids))]
    return {c: float(pool[c].mean()) for c in within.columns}


def g_scores(x: pd.DataFrame, stats: PoolStats, tau2: dict[str, float], config: Config,
             kappa: float) -> pd.DataFrame:
    vals = category_values(x, config, stats.pbar)
    out = {}
    for cat in config.categories:
        denom = float(np.sqrt(stats.std[cat] ** 2 + kappa * tau2.get(cat, 0.0)))
        if cat in stats.flat_categories and denom < 1e-9:
            out[cat] = pd.Series(0.0, index=x.index)
            continue
        g = (vals[cat] - stats.mean[cat]) / denom
        out[cat] = -g if cat in config.lower_is_better else g
    return pd.DataFrame(out, index=x.index)
