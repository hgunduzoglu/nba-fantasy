"""Takas Önerileri: ayrı öneri türleri (sat yüksek) ve önerilerin playoff etkisi (tarayıcısız)."""
from pathlib import Path

import pandas as pd
import pytest

from fdo.trade import TradeEngine
from fdo.ui import trade_common
from unit.test_trade import trade_data  # noqa: F401  paylaşılan sentetik lig

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
UI = Path(__file__).resolve().parents[2] / "src" / "fdo" / "ui"


@pytest.fixture
def ui_env(trade_data, monkeypatch, tmp_path):  # noqa: F811
    base = TradeEngine(trade_data, "L", utilization=1, horizon_weeks=4)
    hot = min(base.league.rosters["1"], key=lambda p: base.market[p])
    trade_data.stats["season_total"].loc[hot, ["pts", "reb", "ast", "fg3m", "stl", "blk"]] *= 4
    trade_data.leagues["L"].settings["Playoffs"] = "2 teams - Week 6 (ends Sunday, Nov 29)"
    rows = []
    for w, pairs in enumerate([(("1", "2"), ("3", "4")), (("1", "3"), ("2", "4")), (("1", "4"), ("2", "3"))] * 2, 1):
        for a, b in pairs:
            rows.append({"league_id": "L", "team_id": a, "week": w, "opponent_team_id": b})
    pd.DataFrame(rows).to_csv(tmp_path / "fixtures.csv", index=False)
    monkeypatch.setattr(trade_common, "_data", lambda directory, signature: trade_data)
    monkeypatch.setattr(trade_common, "_engine", lambda data, fingerprint, lid, utilization:
                        TradeEngine(data, lid, utilization=utilization, horizon_weeks=4))
    monkeypatch.setattr(trade_common, "DATA_DIR", tmp_path)
    return hot


def test_sell_high_mode_and_playoff_effect(ui_env):
    hot = ui_env
    at = AppTest.from_file(str(UI / "pages/15_Trade_Suggestor.py"), default_timeout=60).run()
    next(r for r in at.radio if r.label == "Öneri türü").set_value("sell_high").run()
    next(s for s in at.selectbox if s.label == "Rakibin baktığı değer").set_value("season_total")
    next(s for s in at.slider if s.label == "Rakibin gözünde en düşük denge").set_value(.5)
    next(s for s in at.slider if s.label == "En az yanlış fiyatlama (değer birimi)").set_value(.5)
    next(n for n in at.number_input if n.label == "Senin için en az strateji ECW kazancı").set_value(0.0)
    next(n for n in at.number_input if n.label == "En fazla taranacak paket").set_value(300)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("sat-yüksek" in m.value for m in at.markdown)
    next(b for b in at.button if b.label == "Sat-yüksek takasları bul").click().run()
    assert not at.exception, [e.value for e in at.exception]
    found = at.session_state["trade_search_result"][1]
    assert found.suggestions and all(s.mode == "sell_high" and hot in s.request.give_a for s in found.suggestions)
    assert any("Rakibin gözünde denge" in df.value.columns for df in at.dataframe)
    next(b for b in at.button if b.label == "Önerilerin playoff etkisini hesapla").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Sen ΔP(playoff)" in df.value.columns for df in at.dataframe)
