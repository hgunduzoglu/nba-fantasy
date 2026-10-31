"""Sezon Simülasyonu sayfası ve Takas Analizi'ndeki sezon etkisi (tarayıcısız, sentetik lig)."""
from pathlib import Path

import pandas as pd
import pytest

from fdo.trade import TradeEngine
from fdo.ui import trade_common
from unit.test_inseason import data  # noqa: F401  paylaşılan sentetik lig
from unit.test_season import _fixtures

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
UI = Path(__file__).resolve().parents[2] / "src" / "fdo" / "ui"


@pytest.fixture
def ui_env(data, monkeypatch, tmp_path):  # noqa: F811
    _fixtures(range(1, 20)).to_csv(tmp_path / "fixtures.csv", index=False)
    pd.DataFrame({"league_id": "L", "team_id": ["1", "2", "3", "4"], "wins": [7, 2, 5, 4],
                  "losses": [2, 7, 4, 5], "ties": 0}).to_csv(tmp_path / "standings.csv", index=False)
    monkeypatch.setattr(trade_common, "_data", lambda directory, signature: data)
    monkeypatch.setattr(trade_common, "_engine", lambda d, fingerprint, lid, utilization:
                        TradeEngine(d, lid, utilization=utilization))
    monkeypatch.setattr(trade_common, "DATA_DIR", tmp_path)
    return data


def test_season_page(ui_env):
    at = AppTest.from_file(str(UI / "pages/19_Season.py"), default_timeout=120).run()
    assert not at.exception, [e.value for e in at.exception]
    assert any(m.label.startswith("Playoff") for m in at.metric)
    assert any("P(şampiyon)" in df.value.columns for df in at.dataframe)
    assert any("Rakip" in df.value.columns for df in at.dataframe)


def test_trade_effect_in_analyzer(ui_env):
    at = AppTest.from_file(str(UI / "pages/14_Trade_Analyzer.py"), default_timeout=120).run()
    at.multiselect[0].set_value(["0"])
    at.multiselect[3].set_value(["4"])
    next(b for b in at.button if b.label == "Takası analiz et").click().run()
    next(b for b in at.button if b.label == "Sezon etkisini hesapla").click().run()
    assert not at.exception, [e.value for e in at.exception]
    eff = next(df.value for df in at.dataframe if "Δ playoff" in df.value.columns)
    assert len(eff) == 2
