"""İstatistik kaynaklarının tutarlılık kontrolleri (``fdo.trade.data.quality_issues``)."""
import numpy as np
import pandas as pd

from fdo.trade.data import quality_issues
from fdo.types import STATS


def _frame(**over):
    row = {"gp": 10., "fgm": 50., "fga": 100., "ftm": 20., "fta": 25., "fg3m": 10., "pts": 130., "reb": 40.,
           "ast": 30., "stl": 8., "blk": 5., "tov": 12.}
    rows = {"a": dict(row)}
    for pid, fields in over.items():
        rows[pid] = {**row, **fields}
    return pd.DataFrame.from_dict(rows, orient="index")[["gp", *STATS]]


def test_clean_source_has_no_issues_and_rounding_is_tolerated():
    assert quality_issues(_frame(), "X") == []
    tiny = _frame(b={"gp": 1., "fgm": .2, "fga": .3, "ftm": .1, "fta": .1, "fg3m": .1, "pts": .4, "reb": .1,
                     "ast": 0., "stl": 0., "blk": 0., "tov": 0.})                  # 0,2·2 + 0,1 + 0,1 = 0,6 ≈ 0,4
    assert quality_issues(tiny, "X") == []


def test_each_inconsistency_is_reported_with_names():
    f = _frame(b={"fg3m": 60., "pts": 180.}, c={"pts": 200.}, d={"gp": 0.}, e={"ftm": 30., "pts": 140.},
               f={"reb": np.nan})
    names = pd.Series({"b": "Üçlükçü", "c": "Sayıcı", "d": "Hayalet", "e": "Atıcı", "f": "Eksik"})
    issues = quality_issues(f, "Kaynak", names)
    text = " | ".join(issues)
    assert "1 oyuncuda 3PM > FGM (Üçlükçü)" in text and "sayı, şut bileşenleriyle uyuşmuyor (Sayıcı)" in text
    assert "maç oynamadan" in text and "Hayalet" in text and "tutarsız şut/sayım verisi (Atıcı)" in text
    assert "1 oyuncuda eksik sayısal alan" in text
    assert all(x.startswith("Kaynak:") for x in issues)
