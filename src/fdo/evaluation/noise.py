"""Takas farkının sinyal düzeyi: ileriye dönük testten ölçülen eşik (``config/noise.yaml``).

``scripts/backtest_forward.py --write-floor`` gerçekleşen haftalık kategori galibiyetine göre takasları farkın
büyüklüğüne göre dilimler ve işaret isabetinin belirgin biçimde arttığı eşiği yazar. Eşiğin altındaki öneriler gizlenmez,
"zayıf sinyal" olarak işaretlenir: bir haftalık sonuç gürültülüdür, sezon boyu birikmiş etki daha güvenilirdir.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from fdo.config import REPO_ROOT

NOISE_CONFIG = REPO_ROOT / "config" / "noise.yaml"


def floor(path: str | Path | None = None) -> float | None:
    path = Path(path) if path else NOISE_CONFIG
    if not path.exists():
        return None
    v = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("strategy_delta_floor")
    return None if v is None else float(v)


def signal(delta: float | None, threshold: float | None) -> str | None:
    """``clear`` (eşik ve üstü), ``weak`` (altı) ya da ölçü/eşik yoksa ``None``."""
    if delta is None or threshold is None or not np.isfinite(delta):
        return None
    return "clear" if abs(delta) >= threshold else "weak"


def agreement_bins(pairs: pd.DataFrame, column: str = "model",
                   edges: tuple[float, ...] = (0, .02, .05, .1, .2, .3, 10)) -> pd.DataFrame:
    """Kadroyu değiştiren takaslarda ``|column|`` dilimine göre gerçekleşen kategori etkisiyle işaret isabeti."""
    m = pairs[~np.isclose(pairs["realized_ecw"], 0)].copy()
    m["agree"] = np.sign(m[column]) == np.sign(m["realized_ecw"])
    m["bin"] = pd.cut(m[column].abs(), list(edges), right=False)
    return m.groupby("bin", observed=True)["agree"].agg(["size", "mean"]).reset_index()


def find_floor(bins: pd.DataFrame, target: float = .65, min_n: int = 50) -> float | None:
    """İşaret isabetinin ``target``'a ulaştığı ve üstündeki bütün dilimlerde kaldığı en küçük alt sınır."""
    ok = [(b.left, m >= target) for b, n, m in zip(bins["bin"], bins["size"], bins["mean"]) if n >= min_n]
    for k, (left, _) in enumerate(ok):
        if all(flag for _, flag in ok[k:]):
            return float(left)
    return None
