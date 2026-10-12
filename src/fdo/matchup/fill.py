"""Eksik kadroların doldurma profilleri (README §6.6.4).

``F(n)``: ``n`` numaralı pick'te seçilmesi beklenen oyuncunun haftalık ortalama ve
varyans vektörü. Tablo, bot draft simülasyonlarında her pick'te seçilen
oyuncuların vektörlerinin ortalamasıdır ve ``±w`` pencereyle yumuşatılır.

Bu modül simülasyon yapmaz; seçim matrisini dışarıdan alır (matchup → bots
bağımlılığı yoktur). Doldurma profili **nötrdür**: punt eğilimlerini modellemez.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from fdo.matchup.player_week import WEEK_DIM


@dataclass(frozen=True)
class FillTable:
    means: np.ndarray          # (total + 1, 24); satır 0 kullanılmaz
    samples: np.ndarray        # (total + 1,) ham örnek sayısı
    source: str                # base | conditional
    n_sims: int
    window: int

    @property
    def total(self) -> int:
        return self.means.shape[0] - 1

    def rows(self, picks) -> np.ndarray:
        picks = np.asarray(list(picks), dtype=np.int64)
        return self.means[picks] if len(picks) else np.zeros((0, WEEK_DIM))

    def sum(self, picks) -> np.ndarray:
        return self.rows(picks).sum(axis=0)


def fill_table_from_picks(pick_player: np.ndarray, player_vecs: np.ndarray, window: int, *,
                          start_pick: int = 1, base: FillTable | None = None,
                          source: str = "base") -> FillTable:
    """``pick_player (M, total)`` seçim matrisinden doldurma tablosu.

    ``player_vecs`` satırı NaN olan (projeksiyonsuz) oyuncular ve ``-1`` (boş) hücreler
    ortalamaya girmez. ``start_pick``'ten önceki pick'ler (koşullu tabloda örneksiz)
    ``base`` tablodan alınır.
    """
    M, total = pick_player.shape
    sums = np.zeros((total + 1, WEEK_DIM))
    counts = np.zeros(total + 1)
    for k in range(start_pick, total + 1):
        col = pick_player[:, k - 1]
        col = col[col >= 0]
        v = player_vecs[col]
        v = v[~np.isnan(v).any(axis=1)]
        sums[k] = v.sum(axis=0)
        counts[k] = len(v)

    means = np.zeros((total + 1, WEEK_DIM))
    for k in range(1, total + 1):
        lo, hi = max(start_pick, k - window), min(total, k + window)
        c = counts[lo:hi + 1].sum() if hi >= lo else 0
        if k >= start_pick and c > 0:
            means[k] = sums[lo:hi + 1].sum(axis=0) / c
        elif base is not None:
            means[k] = base.means[k]
    # örneksiz kalan pick'ler (çok küçük M) en yakın dolu satırdan
    empty = [k for k in range(1, total + 1) if not means[k].any()]
    filled = [k for k in range(1, total + 1) if means[k].any()]
    for k in empty:
        if filled:
            nearest = min(filled, key=lambda f: abs(f - k))
            means[k] = means[nearest]
    return FillTable(means=means, samples=counts, source=source, n_sims=M, window=window)
