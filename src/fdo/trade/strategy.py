"""Punt ve özel kategori tercihleri; fiziksel kategori olasılıklarını değiştirmez."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

CATEGORIES = ("FG_PCT", "FT_PCT", "FG3M", "PTS", "REB", "AST", "STL", "BLK", "TOV")
#: Profilden punt tespiti (``Strategy.detect``): bu olasılığın altındaki kategori bırakılmış sayılır, en çok 3.
DETECT_THRESHOLD = .25
DETECT_MAX = 3
PRESETS = {"Dengeli": (), **{f"Punt {c}": (c,) for c in CATEGORIES},
           "Punt FT% + TO": ("FT_PCT", "TOV"), "Punt FG% + BLK": ("FG_PCT", "BLK"),
           "Punt PTS + 3PM": ("PTS", "FG3M"), "Punt AST + TO": ("AST", "TOV")}


@dataclass(frozen=True)
class Strategy:
    name: str = "Dengeli"
    weights: tuple[float, ...] = (1.0,) * 9

    def __post_init__(self):
        w = np.asarray(self.weights, float)
        if w.shape != (9,) or not np.isfinite(w).all() or (w < 0).any() or (w > 3).any() or w.sum() <= 0:
            raise ValueError("9 sonlu ağırlık [0, 3] aralığında olmalı; en az biri pozitif olmalı")

    @classmethod
    def preset(cls, name: str) -> "Strategy":
        return cls(name, tuple(0.0 if c in PRESETS[name] else 1.0 for c in CATEGORIES))

    @classmethod
    def adaptive(cls, category_probabilities: np.ndarray, n_punts: int = 1) -> "Strategy":
        weak = np.argsort(category_probabilities, kind="stable")[:n_punts]
        return cls("Otomatik punt (varsayım)", tuple(0.0 if j in weak else 1.0 for j in range(9)))

    @classmethod
    def detect(cls, category_probabilities: np.ndarray, threshold: float = DETECT_THRESHOLD,
               max_punts: int = DETECT_MAX) -> "Strategy":
        """Profilden punt tespiti: lig ortalamasına karşı kazanma olasılığı ``threshold``'un altındaki en zayıf
        kategoriler (en çok ``max_punts``) bırakılmış sayılır; yoksa dengeli. Kaç kategori bırakıldığı takımdan takıma
        değişir (ör. yalnız AST ya da FT% + 3PM + PTS)."""
        p = np.asarray(category_probabilities, float)
        weak = [j for j in np.argsort(p, kind="stable")[:max_punts] if p[j] < threshold]
        if not weak:
            return cls()
        return cls("Profilden punt (varsayım)", tuple(0.0 if j in weak else 1.0 for j in range(9)))

    @classmethod
    def revive(cls, category_probabilities: np.ndarray, n: int = 1, weight: float = 3.0) -> "Strategy":
        """Punt'un tersi: en zayıf kategori(ler) ``weight`` kat önemlidir (vazgeçilmiş görünen kategoriyi geri kazanma)."""
        weak = np.argsort(category_probabilities, kind="stable")[:n]
        return cls("Zayıfı canlandır (varsayım)", tuple(weight if j in weak else 1.0 for j in range(9)))

    @property
    def normalized(self) -> np.ndarray:
        w = np.asarray(self.weights, float)
        return w / w.sum()
