"""Kategori değerlemesi: Z (varsayılan), G (alternatif), ağırlıklar (README §6.2).

Bu paket yalnızca projeksiyonları okur; ADP tablosuna erişmez (İlke 1, §9.3).
Z ve G yalnızca Projection Explorer'da ve bot profillerinde kullanılır (İlke 2).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from fdo.config import Config
from fdo.matchup.player_week import per_game_variance
from fdo.valuation.gscore import g_scores, tau_squared, within_variance
from fdo.valuation.pool import PoolStats, basis_frame, iterate_pool, value_rank
from fdo.valuation.weights import balanced, validate_weights, weighted_value
from fdo.valuation.zscore import z_scores


@dataclass
class ValuationResult:
    table: pd.DataFrame            # index player_id: V, rank, <kategoriler>, in_pool
    stats: PoolStats
    method: str
    basis: str
    weights: dict[str, float]
    kappa: float | None = None
    tau2: dict[str, float] | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def scores(self) -> pd.DataFrame:
        return self.table[list(self.weights)]


def pool_statistics(proj: pd.DataFrame, config: Config, *, basis: str | None = None,
                    pool_size: int | None = None) -> tuple[pd.DataFrame, PoolStats]:
    """Taban çerçevesi ve dengeli Z ile belirlenmiş havuz istatistikleri."""
    basis = basis or config.model.valuation.basis
    x = basis_frame(proj, basis)
    return x, iterate_pool(x, config, pool_size)


def value_players(proj: pd.DataFrame, config: Config, *, weights: dict[str, float] | None = None,
                  method: str | None = None, basis: str | None = None,
                  pool_size: int | None = None, variance: pd.DataFrame | None = None,
                  kappa: float | None = None) -> ValuationResult:
    vp = config.model.valuation
    method = method or vp.method
    basis = basis or vp.basis
    w = validate_weights(config, weights) if weights is not None else balanced(config)
    x, stats = pool_statistics(proj, config, basis=basis, pool_size=pool_size)

    warnings = []
    for cat in stats.flat_categories:
        warnings.append(f"{cat}: havuzda σ≈0 — kategori ayrıştırmıyor (z = 0)")
    if not stats.converged:
        warnings.append(f"Havuz iterasyonu {stats.n_iter} adımda sabitlenmedi")

    tau2 = None
    if method == "z":
        scores = z_scores(x, stats, config)
    elif method == "g":
        kappa = vp.g_kappa if kappa is None else float(kappa)
        var_pg, _ = per_game_variance(proj, variance, config.model.variance.phi)
        within = within_variance(proj, var_pg, x.index, stats, config, basis)
        tau2 = tau_squared(within, stats)
        scores = g_scores(x, stats, tau2, config, kappa)
    else:
        raise ValueError(f"method: z | g ({method!r})")

    v = weighted_value(scores, w)
    table = scores.copy()
    table.insert(0, "V", v)
    table.insert(1, "rank", value_rank(v))
    table["in_pool"] = table.index.isin(stats.pool_ids)
    table = table.sort_values("rank")
    return ValuationResult(table=table, stats=stats, method=method, basis=basis, weights=w,
                           kappa=kappa if method == "g" else None, tau2=tau2, warnings=warnings)


def balanced_value_rank(proj: pd.DataFrame, config: Config) -> pd.Series:
    """Dengeli Z değer sırası (1 = en iyi). ADP imputasyonu ve bot profilleri için."""
    res = value_players(proj, config, method="z")
    return res.table["rank"].astype(int)
