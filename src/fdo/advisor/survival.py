"""Kalma olasılığı (README §6.7.2).

``P_surv(i, n) = (1/S) · Σ_s 1[i, simülasyon s'de n. pick'te hâlâ uygun]``,
``SE = sqrt(P(1−P)/S)``. Survival her zaman **koşulludur**: o ana kadar
alınan/alınacak oyuncular simülasyona girer.
"""

from __future__ import annotations

import numpy as np

from fdo.bots.thurstone import BatchDraft


def survival(engine: BatchDraft) -> tuple[np.ndarray, np.ndarray]:
    """Motorun şu anki pick'inde (``engine.k``) uygunluk oranı ve SE, ``(n,)``."""
    p = np.mean(engine.taken_at == 0, axis=0)
    return p, np.sqrt(p * (1 - p) / engine.S)


def go_pick_quantiles(taken_at: np.ndarray, qs=(0.1, 0.5, 0.9)) -> np.ndarray:
    """Oyuncunun gittiği pick'in kantilleri; ``taken_at = 0`` (gitmedi) +∞ sayılır.

    Dönüş ``(len(qs), n)``; ufkun ötesine düşen kantil ``inf``.
    """
    t = np.where(taken_at > 0, taken_at.astype(float), np.inf)
    return np.quantile(t, qs, axis=0, method="inverted_cdf")
