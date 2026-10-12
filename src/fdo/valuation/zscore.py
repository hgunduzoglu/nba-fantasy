"""Z-score (README §6.2.3).

Sayma kategorileri ``z = (x − μ)/σ``, TOV ters yön, oran kategorileri hacim
ağırlıklı katkı ``I = makes − p̄·attempts`` üzerinden.
"""

from __future__ import annotations

import pandas as pd

from fdo.config import Config
from fdo.valuation.pool import PoolStats, category_values


def z_scores(x: pd.DataFrame, stats: PoolStats, config: Config) -> pd.DataFrame:
    """Kategori başına z (index ``player_id``). σ < 1e-9 olan kategoride z = 0."""
    vals = category_values(x, config, stats.pbar)
    out = {}
    for cat in config.categories:
        if cat in stats.flat_categories:
            out[cat] = pd.Series(0.0, index=x.index)
            continue
        z = (vals[cat] - stats.mean[cat]) / stats.std[cat]
        out[cat] = -z if cat in config.lower_is_better else z
    return pd.DataFrame(out, index=x.index)
