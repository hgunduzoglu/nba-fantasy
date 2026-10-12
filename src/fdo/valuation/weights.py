"""Kategori ağırlıkları ve punt presetleri (README §6.2.5).

``w_c ∈ [0, 3]``; ``w_c = 0`` kategori punt edildi demektir. Ağırlıklar yalnızca
ranking değerini (``V``) etkiler; matchup modeline aktarılmaz (İlke 3).
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from fdo.config import Config


class WeightError(ValueError):
    pass


def balanced(config: Config) -> dict[str, float]:
    return {c: 1.0 for c in config.categories}


def preset(config: Config, name: str) -> dict[str, float]:
    presets = config.model.valuation.presets
    if name not in presets:
        raise WeightError(f"Bilinmeyen preset: {name}")
    w = balanced(config)
    w.update({k: float(v) for k, v in (presets[name] or {}).items()})
    return validate_weights(config, w)


def validate_weights(config: Config, weights: dict[str, float]) -> dict[str, float]:
    p = config.model.valuation
    unknown = set(weights) - set(config.categories)
    if unknown:
        raise WeightError(f"Bilinmeyen kategori: {sorted(unknown)}")
    out = balanced(config)
    for c, w in weights.items():
        w = float(w)
        if not p.weight_min <= w <= p.weight_max:
            raise WeightError(f"{c}: ağırlık [{p.weight_min}, {p.weight_max}] dışında ({w})")
        out[c] = w
    return out


def punted(weights: dict[str, float]) -> list[str]:
    return [c for c, w in weights.items() if w == 0]


def weighted_value(scores: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    """``V_i = Σ_c w_c · s_ic``; ``w_c = 0`` olan kategori V'ye hiç girmez."""
    total = pd.Series(0.0, index=scores.index)
    for c, w in weights.items():
        if w != 0:
            total += w * scores[c]
    return total


def save_preset(path: str | Path, name: str, weights: dict[str, float]) -> None:
    Path(path).write_text(json.dumps({"name": name, "weights": weights}, indent=2), encoding="utf-8")


def load_preset(config: Config, path: str | Path) -> tuple[str, dict[str, float]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return str(data["name"]), validate_weights(config, data["weights"])
