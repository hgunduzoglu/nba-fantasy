"""Add/drop yardımcıları: waiver uygunluğu ve bu haftanın kritik kategorileri (README §13.22).

* **Uygunluk**: boştaki oyuncu ya hemen alınabilir (FA) ya da waiver'dadır; waiver'daki oyuncu Yahoo'nun gösterdiği
  günden (``W (Nov 9)``, senkronizasyon) itibaren kadroya girer. Tarih bilinmiyorsa bugün + lig ayarındaki waiver
  süresi varsayılır.
* **Kritik kategori**: her kategori için tek bir boştaki oyuncuyu kalan günlere kısıtsız eklemenin (bırakma ve
  lineup yok; üst sınır) en iyi 5 adayının ortalama kazanma olasılığı artışı. Kesinleşmiş kategoride (P ≈ 0 ya da 1)
  bu artış ~0'dır; en çok kıpırdatılabilen kategoriler kritiktir. Kritik moddaki hedef ağırlıkları seçilen
  kategorilerde 1, diğerlerinde 0.05 (diğerleri bütünüyle feda edilmesin, eşitlikte belirleyici olsun).
"""

from __future__ import annotations

import datetime as dt
import re

import numpy as np

from fdo.inseason.weekly import WeekModel, WeekOutlook
from fdo.trade.strategy import CATEGORIES, Strategy
from fdo.types import CATEGORY_LABELS

OTHER_WEIGHT = 0.05


def waiver_days(settings: dict[str, str]) -> int:
    """``Waiver Time``: ``"2 days"`` → 2, ``"No waivers"`` → 0."""
    m = re.match(r"\s*(\d+)", str(settings.get("Waiver Time", "")))
    return int(m.group(1)) if m else 0


def available_from(waivers: dict[str, dt.date | None], as_of: dt.date, settings: dict[str, str]
                   ) -> dict[str, dt.date]:
    """Waiver'daki oyuncu → kadroya girebileceği ilk gün (tarihsiz kayıt: bugün + waiver süresi)."""
    fallback = as_of + dt.timedelta(days=waiver_days(settings))
    return {p: (d or fallback) for p, d in waivers.items()}


def critical_categories(model: WeekModel, base: WeekOutlook, available: dict[str, dt.date] | None = None,
                        top: int = 5) -> np.ndarray:
    """Kategori başına tek bir boştaki oyuncuyla ulaşılabilecek kazanma olasılığı artışı ``(C,)``."""
    _, dp = model.shortlist(base, available, size=100_000)
    if not len(dp):
        return np.zeros(len(CATEGORIES))
    best = -np.sort(-dp, axis=0)[:top]
    return np.clip(best.mean(axis=0), 0, None)


def pick_critical(leverage: np.ndarray, k: int = 2, floor: float = 0.02) -> list[str]:
    order = [i for i in np.argsort(-leverage, kind="stable") if leverage[i] >= floor][:k]
    return [CATEGORIES[i] for i in order] or [CATEGORIES[int(np.argmax(leverage))]]


def critical_strategy(categories: list[str]) -> Strategy:
    weights = tuple(1.0 if c in categories else OTHER_WEIGHT for c in CATEGORIES)
    return Strategy("Kritik: " + " + ".join(CATEGORY_LABELS[c] for c in categories), weights)
