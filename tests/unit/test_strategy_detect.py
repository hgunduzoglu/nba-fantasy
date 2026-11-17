"""Profilden punt tespiti (README §13.54): belirgin zayıf kategoriler 0–3, yoksa dengeli."""
import numpy as np
import pytest

from fdo.api.schemas import StrategyIn
from fdo.api.serialize import assumed_strategies, strategy_from
from fdo.trade import Strategy, TradeEngine
from unit.test_inseason import data  # noqa: F401


def test_detect_counts_only_clearly_weak_categories():
    p = np.array([.5, .06, .04, .2, .6, .5, .4, .7, .5])
    s = Strategy.detect(p)
    assert s.weights == (1, 0, 0, 0, 1, 1, 1, 1, 1)
    assert Strategy.detect(np.full(9, .5)) == Strategy()                     # belirgin zayıf yok → dengeli
    assert sum(w == 0 for w in Strategy.detect(np.full(9, .1)).weights) == 3  # en çok 3


def test_detect_through_api_helpers(data):  # noqa: F811
    eng = TradeEngine(data, "L", utilization=1)
    s = strategy_from({"auto_punt": "detect"}, eng, "1")
    assert s.name.startswith("Profilden")
    got = assumed_strategies(eng, "detect", ["2", "3"])
    assert set(got) == {"2", "3"} and all(isinstance(v, Strategy) for v in got.values())
    assert StrategyIn(auto_punt="detect").auto_punt == "detect" and StrategyIn(auto_punt=2).auto_punt == 2
    with pytest.raises(ValueError):
        StrategyIn(auto_punt=3)
