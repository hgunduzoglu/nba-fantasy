"""Dönüşü bekleyen oyuncunun maç maç dönmüş olma olasılığı (ölçülmüş gecikme dağılımından).

Dağılım ``fdo.inseason.injuries.return_pmf`` ile okunur ve ``TradeData.sources["injuries"]["delay_pmf"]``'te taşınır;
takas motoru, haftalık model ve kalan sezon kısıtı aynı hesabı buradan kullanır.
"""

from __future__ import annotations

import numpy as np


def presence(n: int, pmf: dict[int, float] | None) -> np.ndarray:
    """En erken tarihten sonraki ``n`` takım maçının her birinde oyuncunun dönmüş olma olasılığı ``P(T ≤ i)``
    (``pmf`` yoksa hepsi 1). Kuyruk ("en az K maç") K. maçtan itibaren dönmüş sayılır."""
    if not pmf:
        return np.ones(n)
    tail = max(pmf)
    cdf = np.cumsum([pmf.get(k, 0.0) for k in range(tail + 1)])
    return np.array([cdf[min(i, tail)] for i in range(n)])


def expected_left(n: int, pmf: dict[int, float] | None) -> float:
    """En erken tarihten sonraki ``n`` maçtan beklenen oynanacak maç (``presence`` toplamı)."""
    return float(presence(n, pmf).sum())
