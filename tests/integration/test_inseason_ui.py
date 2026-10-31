"""Bu Hafta ve Boştaki Oyuncular sayfaları (tarayıcısız, sentetik lig)."""
from pathlib import Path

import pytest

from fdo.trade import TradeEngine
from fdo.ui import trade_common
from unit.test_inseason import data  # noqa: F401  paylaşılan sentetik lig

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
UI = Path(__file__).resolve().parents[2] / "src" / "fdo" / "ui"


@pytest.fixture
def ui_env(data, monkeypatch):  # noqa: F811
    monkeypatch.setattr(trade_common, "_data", lambda directory, signature: data)
    monkeypatch.setattr(trade_common, "_engine", lambda d, fingerprint, lid, utilization:
                        TradeEngine(d, lid, utilization=utilization))
    monkeypatch.setattr(trade_common, "DATA_DIR", Path(__file__).parent)       # fikstür dosyası yok
    return data


def run(page):
    at = AppTest.from_file(str(UI / page), default_timeout=60).run()
    assert not at.exception, [e.value for e in at.exception]
    assert not at.error, [e.value for e in at.error]
    return at


def test_weekly_page_outlook_and_stream(ui_env):
    at = run("pages/17_Weekly.py")
    assert any(m.label == "Haftayı kazanma P(5+)" for m in at.metric)
    assert any("P(kazan)" in df.value.index for df in at.dataframe)
    next(s for s in at.selectbox if s.label == "Hafta").set_value(3).run()
    next(b for b in at.button if b.label == "Streaming planını hesapla").click().run()
    assert not at.exception, [e.value for e in at.exception]
    key, plan = at.session_state["wk_plan"]
    assert plan.strategy_score >= 0


def test_free_agents_page(ui_env):
    at = run("pages/18_Free_Agents.py")
    cols = [df.value.columns for df in at.dataframe]
    assert any("Strateji Δ" in c and "Bırak" in c for c in cols)
    next(s for s in at.selectbox if s.label == "Pozisyon").set_value("G").run()
    assert not at.exception, [e.value for e in at.exception]
