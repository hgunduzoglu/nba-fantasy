"""Kazanma olasılığı ve ECW (README §6.6.3, §6.6.5).

Normal yaklaşım: ``P(A kazanır) = Φ(E[D] / sqrt(Var(D)))``. TOV için işaret ters
(``config.lower_is_better``). Oran kategorilerinde havuzlanmış oran
``r = (ΣFGM_A + ΣFGM_B)/(ΣFGA_A + ΣFGA_B)`` ve ``Y = FGM − r·FGA`` kullanılır.

ECW = kategori olasılıklarının toplamı (beklenti doğrusal olduğundan kategoriler
arası bağımsızlık gerektirmez). Bu modül kategori ağırlıklarını **okumaz** (İlke 3).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.special import ndtr

from fdo.config import Config
from fdo.matchup.player_week import COUNT_STATS, N_COUNT, RATIO_OFFSETS, ratio_mean_var
from fdo.types import COUNTING_CATEGORY_STAT


@dataclass(frozen=True)
class CategorySpec:
    name: str
    kind: str          # count | ratio
    index: int         # count: COUNT_STATS indeksi; ratio: kullanılmaz
    key: str           # ratio: "fg" | "ft"
    lower_better: bool


def category_specs(config: Config) -> list[CategorySpec]:
    out = []
    for cat in config.categories:
        low = cat in config.lower_is_better
        if config.scoring.is_ratio(cat):
            makes = config.scoring.ratio_categories[cat]["makes"].lower()
            out.append(CategorySpec(cat, "ratio", -1, makes[:-1], low))
        else:
            stat = COUNTING_CATEGORY_STAT[cat]
            out.append(CategorySpec(cat, "count", COUNT_STATS.index(stat), "", low))
    return out


def _prob(mean: np.ndarray, var: np.ndarray) -> np.ndarray:
    """``Φ(mean/sqrt(var))``; ``var = 0`` → 1 / 0 / 0.5 (dejenere durum)."""
    mean = np.asarray(mean, dtype=float)
    var = np.asarray(var, dtype=float)
    pos = var > 0
    safe = np.where(pos, var, 1.0)
    p = ndtr(mean / np.sqrt(safe))
    degenerate = np.where(mean > 0, 1.0, np.where(mean < 0, 0.0, 0.5))
    return np.where(pos, p, degenerate)


def p_win(a: np.ndarray, b: np.ndarray, config: Config) -> np.ndarray:
    """A'nın B'yi kategori başına yenme olasılığı; ``(..., 24)`` girdiler yayınlanır → ``(..., n_cat)``."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    out = []
    for spec in category_specs(config):
        if spec.kind == "count":
            j = spec.index
            d = a[..., j] - b[..., j]
            v = a[..., N_COUNT + j] + b[..., N_COUNT + j]
        else:
            o = RATIO_OFFSETS[spec.key]
            makes = a[..., o] + b[..., o]
            att = a[..., o + 1] + b[..., o + 1]
            r = np.divide(makes, att, out=np.zeros(np.broadcast(makes, att).shape), where=att > 0)
            ea, va = ratio_mean_var(a, spec.key, r)
            eb, vb = ratio_mean_var(b, spec.key, r)
            d = ea - eb
            v = va + vb
        if spec.lower_better:
            d = -d
        out.append(_prob(d, v))
    return np.stack(np.broadcast_arrays(*out), axis=-1)


def ecw_vs(team: np.ndarray, opponents: np.ndarray, config: Config) -> np.ndarray:
    """``team (..., 24)`` vs ``opponents (..., K, 24)`` → ``P (..., K, n_cat)``."""
    return p_win(np.asarray(team)[..., None, :], opponents, config)


def ecw_from_p(p: np.ndarray) -> np.ndarray:
    """``P (..., K, n_cat)`` → rakipler üzerinden ortalama beklenen kategori galibiyeti ``(...)``."""
    return p.sum(axis=-1).mean(axis=-1)


def ecw_matrix(teams: np.ndarray, config: Config) -> np.ndarray:
    """``(T, 24)`` → ``(T, T, n_cat)`` P değerleri; köşegen NaN."""
    p = p_win(teams[:, None, :], teams[None, :, :], config)
    idx = np.arange(len(teams))
    p[idx, idx, :] = np.nan
    return p


def team_ecw(matrix: np.ndarray) -> np.ndarray:
    """``ECW(A) = (1/(T−1)) · Σ_{j≠A} Σ_c P_c(A, j)``."""
    return np.nansum(matrix, axis=2).sum(axis=1) / (matrix.shape[0] - 1)


def opponent_category_mean(matrix: np.ndarray) -> np.ndarray:
    """Takım × kategori, rakipler üzerinden ortalama P."""
    return np.nanmean(matrix, axis=1)


def p_at_least(p: np.ndarray, k: int = 5) -> np.ndarray:
    """``P(≥k kategori)`` — **bağımsızlık varsayar** (``assumes_independence``); optimizasyonda kullanılmaz."""
    p = np.asarray(p, dtype=float)
    n = p.shape[-1]
    dist = np.zeros(p.shape[:-1] + (n + 1,))
    dist[..., 0] = 1.0
    for c in range(n):
        pc = p[..., c][..., None]
        shifted = np.concatenate([np.zeros(dist.shape[:-1] + (1,)), dist[..., :-1]], axis=-1)
        dist = dist * (1 - pc) + shifted * pc
    return dist[..., k:].sum(axis=-1)


def classify(p: float, winnable: float = 0.6, lost: float = 0.4) -> str:
    if p >= winnable:
        return "kazanılabilir"
    if p <= lost:
        return "kaybedilmiş"
    return "sınırda"
