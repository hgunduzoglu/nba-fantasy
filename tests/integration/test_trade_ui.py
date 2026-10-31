"""Yeni giriş, üç ayrı menü ve etkileşimli takas akışları (tarayıcısız)."""
from pathlib import Path

import pytest

from fdo.trade import TradeEngine
from fdo.ui import trade_common
from unit.test_trade import trade_data  # shared deterministic domain fixture

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
UI = Path(__file__).resolve().parents[2] / "src" / "fdo" / "ui"


@pytest.fixture
def ui_env(trade_data, monkeypatch):
    monkeypatch.setattr(trade_common, "_data", lambda directory, signature: trade_data)
    monkeypatch.setattr(trade_common, "_engine", lambda data, fingerprint, lid, utilization:
                        TradeEngine(data, lid, utilization=utilization, horizon_weeks=4))
    return trade_data


@pytest.mark.parametrize("page", ["app.py", "pages/10_Trade_Home.py", "pages/11_Preseason_Ranks.py",
                                  "pages/12_Current_Ranks.py", "pages/13_ROS_Ranks.py",
                                  "pages/14_Trade_Analyzer.py", "pages/15_Trade_Suggestor.py",
                                  "pages/16_Trade_Data.py"])
def test_trade_page_renders(ui_env, page):
    at = AppTest.from_file(str(UI / page), default_timeout=30).run()
    assert not at.exception, [e.value for e in at.exception]
    assert not at.error, [e.value for e in at.error]


def test_analyzer_full_flow_and_three_modes(ui_env):
    at = AppTest.from_file(str(UI / "pages/14_Trade_Analyzer.py"), default_timeout=30).run()
    at.multiselect[0].set_value(["0"])
    at.multiselect[3].set_value(["3"])
    next(b for b in at.button if b.label == "Takası analiz et").click().run()
    assert not at.exception, [e.value for e in at.exception]
    result = at.session_state["trade_analysis_result"][1]
    assert set(result.after) == {"preseason", "season_total", "remaining_games_projection"}
    assert len(at.tabs) == 3
    assert any("P(5+)" in m.label for m in at.metric)
    assert any("sıra kazancı" in df.value.columns for df in at.dataframe)
    next(b for b in at.button if b.label == "Senaryoyu karşılaştırmaya ekle").click().run()
    assert len(at.session_state["trade_saved_scenarios"]) == 1
    # Changing the proposal must hide the previous analysis.
    at.multiselect[0].set_value(["1"]).run()
    assert not at.metric


def test_suggestor_search_flow(ui_env):
    at = AppTest.from_file(str(UI / "pages/15_Trade_Suggestor.py"), default_timeout=30).run()
    next(n for n in at.selectbox if n.label == "Analiz edeceğin takım").set_value("2").run()
    next(n for n in at.number_input if n.label == "En fazla taranacak paket").set_value(200)
    next(n for n in at.slider if n.label == "En düşük paket değer dengesi").set_value(.1)
    next(b for b in at.button if b.label == "Karşılıklı faydalı takasları bul").click().run()
    assert not at.exception, [e.value for e in at.exception]
    found = at.session_state["trade_search_result"][1]
    assert found.examined <= 200
    assert found.suggestions
    assert len(at.tabs) == 3
    assert all(s.own_strategy_delta > 0 and s.other_strategy_delta > 0 for s in found.suggestions)


def test_real_league_switching_and_rank_views():
    from fdo.config import REPO_ROOT

    if not (REPO_ROOT / "data/real/league_info.json").exists():
        pytest.skip("Kişisel veri snapshot'ı yok")
    at = AppTest.from_file(str(UI / "pages/13_ROS_Ranks.py"), default_timeout=60).run()
    for lid, teams in (("93992", 14), ("220594", 14), ("229303", 16), ("104375", 12)):
        next(s for s in at.selectbox if s.label == "Lig").set_value(lid).run()
        assert not at.exception, [e.value for e in at.exception]
        assert not at.error, [e.value for e in at.error]
        assert len(at.dataframe[0].value) == teams
