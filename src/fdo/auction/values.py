"""Dolar değerleri (README §13.12).

* **Model değeri**: dengeli z toplamı ``V``'nin yedek seviyesine göre fazlası (VOR) lig parasına dağıtılır:
  ``$_i = min_bid + (V_i − V_yedek)⁺ / Σ(V − V_yedek)⁺ · (T·bütçe − N·min_bid)``; ``N = T·rounds``
  draft edilecek oyuncu, ``V_yedek`` ``N+1``. oyuncunun değeri. Yedek altı oyuncular ``min_bid``'dir.
* **Piyasa fiyatı**: Yahoo ortalama auction fiyatı (AAV) ligin toplam parasına ölçeklenir: ilk ``N``
  oyuncunun ``Σ(AAV − 1)⁺``'ı ``T·bütçe − N·min_bid``'e eşitlenir (AAV çoğunlukla 12 takımlı liglerden gelir).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def distributable(teams: int, budget: int, n_draft: int, min_bid: int) -> float:
    return float(teams * budget - n_draft * min_bid)


def model_dollars(value: pd.Series, *, teams: int, budget: int, rounds: int, min_bid: int) -> pd.Series:
    """``value``: oyuncu → dengeli değer ``V`` (yüksek iyi). Dönüş: oyuncu → $ (en az ``min_bid``)."""
    n = teams * rounds
    v = value.dropna().sort_values(ascending=False)
    repl = float(v.iloc[n]) if len(v) > n else float(v.iloc[-1])
    vor = (v - repl).clip(lower=0.0)
    vor.iloc[n:] = 0.0
    total = float(vor.sum())
    share = vor / total if total > 0 else vor * 0.0
    return (min_bid + share * distributable(teams, budget, n, min_bid)).reindex(value.index).fillna(min_bid)


def market_prices(aav: pd.Series, *, teams: int, budget: int, rounds: int, min_bid: int) -> pd.Series:
    """``aav``: oyuncu → Yahoo ortalama fiyatı. Dönüş: ligin parasına ölçeklenmiş beklenen fiyat."""
    n = teams * rounds
    a = aav.dropna().astype(float)
    top = a.sort_values(ascending=False).head(n)
    surplus = float((top - 1.0).clip(lower=0.0).sum())
    k = distributable(teams, budget, n, min_bid) / surplus if surplus > 0 else 1.0
    return (min_bid + k * (a - 1.0).clip(lower=0.0)).reindex(aav.index)


def inflation(money_left: float, slots_left: int, prices: np.ndarray, min_bid: int) -> float:
    """``(kalan para − min_bid·kalan slot) / Σ(fiyat − min_bid)`` — ``prices`` kalan en iyi ``slots_left``
    oyuncunun taban fiyatı. 1'den büyükse kalan oyuncular taban fiyatından pahalıya gider."""
    surplus = float(np.clip(np.asarray(prices, float) - min_bid, 0, None).sum())
    spend = money_left - min_bid * slots_left
    return spend / surplus if surplus > 0 else 1.0
