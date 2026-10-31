"""Punt ve özel kategori tercihleri; fiziksel kategori olasılıklarını değiştirmez."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

CATEGORIES = ("FG_PCT", "FT_PCT", "FG3M", "PTS", "REB", "AST", "STL", "BLK", "TOV")
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

    @property
    def normalized(self) -> np.ndarray:
        w = np.asarray(self.weights, float)
        return w / w.sum()
