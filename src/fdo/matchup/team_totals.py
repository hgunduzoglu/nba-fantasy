"""Takım toplamları (README §6.6.3).

Takım haftalık vektörü = kadrodaki oyuncuların ve kalan pick'lerin doldurma
profillerinin toplamı. Oranlar **daima** toplamdan hesaplanır (İlke 4).
"""

from __future__ import annotations

import numpy as np

from fdo.config import Config
from fdo.matchup.ecw import category_specs
from fdo.matchup.player_week import N_COUNT, RATIO_OFFSETS, WEEK_DIM


def team_vector(player_vecs: np.ndarray, roster_idx, fill_vecs: np.ndarray | None = None) -> np.ndarray:
    """``player_vecs (n, 24)`` üzerinden kadro toplamı (+ opsiyonel doldurma satırları)."""
    idx = np.asarray(list(roster_idx), dtype=np.int64)
    total = player_vecs[idx].sum(axis=0) if len(idx) else np.zeros(WEEK_DIM)
    if fill_vecs is not None and len(fill_vecs):
        total = total + np.asarray(fill_vecs).sum(axis=0)
    return total


def category_means(vec: np.ndarray, config: Config) -> dict[str, float]:
    """Beklenen haftalık kategori değerleri; FG%/FT% = ΣM/ΣA (yüzde ortalaması değil)."""
    out = {}
    for spec in category_specs(config):
        if spec.kind == "count":
            out[spec.name] = float(vec[spec.index])
        else:
            o = RATIO_OFFSETS[spec.key]
            out[spec.name] = float(vec[o] / vec[o + 1]) if vec[o + 1] > 0 else float("nan")
    return out


def category_sd(vec: np.ndarray, config: Config) -> dict[str, float]:
    out = {}
    for spec in category_specs(config):
        if spec.kind == "count":
            out[spec.name] = float(np.sqrt(max(vec[N_COUNT + spec.index], 0.0)))
    return out
