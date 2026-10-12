"""Referans havuz ve havuz istatistikleri (README §6.2.1–§6.2.2).

Valuation yalnızca projeksiyonları okur (İlke 1). Havuz istatistikleri her zaman
**dengeli** ağırlıklarla belirlenir; kullanıcı ağırlıkları havuzu değiştirmez.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from fdo.config import Config
from fdo.types import COUNTING_CATEGORY_STAT, STATS

SIGMA_EPS = 1e-9


@dataclass(frozen=True)
class PoolStats:
    mean: dict[str, float]
    std: dict[str, float]
    pbar: dict[str, float]          # oran kategorileri: Σmakes / Σattempts
    size: int
    pool_ids: tuple[str, ...]
    n_iter: int = 0
    converged: bool = True
    flat_categories: tuple[str, ...] = field(default=())   # σ < 1e-9


def basis_frame(proj: pd.DataFrame, basis: str) -> pd.DataFrame:
    """İstatistikleri seçilen tabana çevirir (index ``player_id``).

    ``total`` (varsayılan): maç başına × ``projected_gp``. ``per_game``: maç başına.
    Eksik zorunlu statı olan oyuncular düşürülür (0 kabul edilmez).
    """
    p = proj.set_index("player_id")
    cols = ["projected_gp", *STATS]
    p = p[cols].astype(float).dropna().sort_index()
    x = p[list(STATS)]
    if basis == "total":
        x = x.mul(p["projected_gp"], axis=0)
    elif basis != "per_game":
        raise ValueError(f"basis: total | per_game ({basis!r})")
    return x


def ratio_stats(config: Config, cat: str) -> tuple[str, str]:
    spec = config.scoring.ratio_categories[cat]
    return spec["makes"].lower(), spec["attempts"].lower()


def category_values(x: pd.DataFrame, config: Config, pbar: dict[str, float]) -> pd.DataFrame:
    """Kategori başına ham değer: sayma statı ya da oran kategorisi için ``I = makes − p̄·att``."""
    out = {}
    for cat in config.categories:
        if config.scoring.is_ratio(cat):
            mk, at = ratio_stats(config, cat)
            out[cat] = x[mk] - pbar[cat] * x[at]
        else:
            out[cat] = x[COUNTING_CATEGORY_STAT[cat]]
    return pd.DataFrame(out, index=x.index)


def compute_pool_stats(x: pd.DataFrame, pool_ids, config: Config) -> PoolStats:
    pool = x.loc[list(pool_ids)]
    pbar = {}
    for cat in config.categories:
        if config.scoring.is_ratio(cat):
            mk, at = ratio_stats(config, cat)
            att = pool[at].sum()
            pbar[cat] = float(pool[mk].sum() / att) if att > 0 else 0.0
    vals = category_values(pool, config, pbar)
    mean = {c: float(vals[c].mean()) for c in config.categories}
    std = {c: float(vals[c].std(ddof=0)) for c in config.categories}
    flat = tuple(c for c in config.categories if not std[c] >= SIGMA_EPS)
    return PoolStats(mean=mean, std=std, pbar=pbar, size=len(pool), pool_ids=tuple(pool.index),
                     flat_categories=flat)


def balanced_z_total(x: pd.DataFrame, stats: PoolStats, config: Config) -> pd.Series:
    """Dengeli ağırlıklarla toplam Z (havuz iterasyonu ve ADP imputasyonu için)."""
    vals = category_values(x, config, stats.pbar)
    total = pd.Series(0.0, index=x.index)
    for cat in config.categories:
        if cat in stats.flat_categories:
            continue
        z = (vals[cat] - stats.mean[cat]) / stats.std[cat]
        total += -z if cat in config.lower_is_better else z
    return total


def iterate_pool(x: pd.DataFrame, config: Config, size: int | None = None,
                 max_iter: int | None = None) -> PoolStats:
    """``P₀`` = tüm oyuncular; ``P_{k+1}`` = dengeli Z'ye göre ilk N; sabitlenince dur (≤ max_iter)."""
    size = int(size or config.pool_size)
    max_iter = int(max_iter or config.model.valuation.max_pool_iterations)
    current = tuple(sorted(x.index))
    stats = compute_pool_stats(x, current, config)
    for it in range(1, max_iter + 1):
        v = balanced_z_total(x, stats, config)
        nxt = tuple(sorted(v.sort_values(ascending=False, kind="mergesort").index[:size]))
        if nxt == current:
            return _with_iter(stats, it, True)
        current = nxt
        stats = compute_pool_stats(x, current, config)
    return _with_iter(stats, max_iter, False)


def _with_iter(stats: PoolStats, n_iter: int, converged: bool) -> PoolStats:
    return PoolStats(mean=stats.mean, std=stats.std, pbar=stats.pbar, size=stats.size,
                     pool_ids=stats.pool_ids, n_iter=n_iter, converged=converged,
                     flat_categories=stats.flat_categories)


def value_rank(score: pd.Series) -> pd.Series:
    """Değer sırası (1 = en iyi), eşitlikte player_id ile kararlı."""
    order = score.sort_values(ascending=False, kind="mergesort")
    return pd.Series(np.arange(1, len(order) + 1), index=order.index).reindex(score.index)
