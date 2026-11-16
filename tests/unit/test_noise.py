"""Takas farkının sinyal düzeyi: dilimlere göre işaret isabeti ve eşik."""
from __future__ import annotations

import numpy as np
import pandas as pd

from fdo.evaluation.noise import agreement_bins, find_floor, floor, signal


def test_floor_is_where_sign_agreement_stays_above_target(tmp_path):
    rng = np.random.default_rng(1)
    model = rng.uniform(-.5, .5, 4000)
    # büyük farklar gerçekleşenle aynı yönde, küçükler yazı tura
    realized = np.where(np.abs(model) >= .2, np.sign(model), rng.choice([-1.0, 1.0], len(model)))
    pairs = pd.DataFrame({"model": model, "realized_ecw": realized * .5})
    bins = agreement_bins(pairs)
    assert find_floor(bins) == .2
    assert signal(.25, .2) == "clear" and signal(-.1, .2) == "weak" and signal(None, .2) is None
    assert signal(.1, None) is None
    cfg = tmp_path / "noise.yaml"
    cfg.write_text("strategy_delta_floor: 0.3\n", encoding="utf-8")
    assert floor(cfg) == .3 and floor(tmp_path / "yok.yaml") is None
