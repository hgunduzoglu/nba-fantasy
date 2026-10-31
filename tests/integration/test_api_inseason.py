"""Sezon içi API uç noktaları: öneriler, yanlış fiyatlama, bu hafta + streaming, boştakiler, sezon, sıralamalar."""
import pandas as pd
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from fdo.api.app import create_app  # noqa: E402
from unit.test_inseason import data  # noqa: E402,F401  paylaşılan sentetik lig
from unit.test_season import _fixtures  # noqa: E402


@pytest.fixture
def client(data, tmp_path):  # noqa: F811
    _fixtures(range(1, 20)).to_csv(tmp_path / "fixtures.csv", index=False)
    pd.DataFrame({"league_id": "L", "team_id": ["1", "2", "3", "4"], "wins": [7, 2, 5, 4],
                  "losses": [2, 7, 4, 5], "ties": 0}).to_csv(tmp_path / "standings.csv", index=False)
    app = create_app(data_dir=tmp_path, frontend_dir=tmp_path / "yok")
    st = app.state.fdo
    st.data = lambda injuries=True: data
    st.signature = lambda: "test"
    return TestClient(app)


def test_weekly_and_stream(client):
    w = client.post("/api/leagues/L/weekly", json={"team": "1", "week": 3}).json()
    assert w["week"] == 3 and len(w["days"]) == 7 and w["acquisitions_limit"] == 4
    assert w["opponent"] in {"2", "3", "4"} and w["fixture_opponent"] == w["opponent"]
    o = w["outlook"]
    assert len(o["p"]) == 9 and o["expected_wins"] == pytest.approx(sum(o["p"]))
    assert len(o["grid"]["mine"][0]["marks"]) == 7 and len(w["default_droppable"]) == 3
    s = client.post("/api/leagues/L/weekly/stream", json={"team": "1", "week": 3, "droppable": w["default_droppable"]}).json()
    assert s["left"] == 4 and len(s["moves"]) <= 4 and s["after"]["expected_wins"] >= s["before"]["expected_wins"] - 1e-9
    assert client.post("/api/leagues/L/weekly", json={"team": "1", "week": 99}).status_code == 400


def test_waiver_season_rankings(client):
    wv = client.post("/api/leagues/L/waiver", json={"team": "2", "strategy": {"preset": "Punt FT_PCT"}}).json()
    assert wv["rows"] and set(wv["rows"][0]["dp"]) >= {"FG_PCT", "TOV"}
    assert all(r["drop"]["id"] != "7" for r in wv["rows"])                       # IL'deki oyuncu bırakılmaz
    auto = client.post("/api/leagues/L/waiver", json={"team": "2", "strategy": {"auto_punt": 1}})
    assert auto.status_code == 200 and auto.json()["rows"]
    se = client.get("/api/leagues/L/season?team=1&n=300").json()
    assert se["standings_known"] and se["start_week"] == 2 and len(se["table"]) == 4
    assert sum(r["p_champion"] for r in se["table"]) == pytest.approx(1)
    rk = client.get("/api/leagues/L/rankings?source=ros").json()
    assert len(rk["teams"]) == 4 and "ecw" in rk["teams"][0]
    assert "ecw" not in client.get("/api/leagues/L/rankings?source=season").json()["teams"][0]


def test_suggest_and_mispricing(client):
    r = client.post("/api/leagues/L/trade/suggest", json={"team": "1", "max_evaluations": 200, "min_fairness": 0.1,
                                                         "min_gain": 0.00001}).json()
    assert r["examined"] <= 200 and isinstance(r["suggestions"], list)
    for s in r["suggestions"]:
        assert s["own_delta"] > 0 and s["other_delta"] > 0 and s["give_a"] and s["give_b"]
    bad = client.post("/api/leagues/L/trade/suggest", json={"team": "1", "mode": "x"})
    assert bad.status_code == 400
    m = client.get("/api/leagues/L/trade/mispricing?team=1").json()
    assert set(m) == {"sell_high", "buy_low"} and all(x["team_id"] == "1" for x in m["sell_high"])


def test_suggest_rows_carry_category_playoff_and_view_details(client):
    r = client.post("/api/leagues/L/trade/suggest", json={"team": "1", "max_evaluations": 300, "min_fairness": 0.1,
                                                         "min_gain": 0.00001, "strategy": {"auto_revive": 1}}).json()
    assert r["strategy"]["name"].startswith("Canlandır") and max(r["strategy"]["weights"]) == 3
    for s in r["suggestions"]:
        assert set(s["my_categories"]) == set(s["other_categories"]) == {
            "FG_PCT", "FT_PCT", "FG3M", "PTS", "REB", "AST", "STL", "BLK", "TOV"}
        assert isinstance(s["playoff_games"], int) and s["position_gap"] >= 0
        assert s["perceived_view"] is None or s["perceived_view"] > 0


def test_multi_team_analyze_season_and_suggest(client):
    body = {"moves": [{"player": "0", "from_team": "1", "to_team": "2"},
                      {"player": "4", "from_team": "2", "to_team": "3"},
                      {"player": "8", "from_team": "3", "to_team": "1"}],
            "strategies": {"1": {"auto_revive": 1}, "3": {"auto_punt": 1}}}
    a = client.post("/api/leagues/L/trade/multi/analyze", json=body).json()
    assert a["n_teams"] == 3 and [t["team_id"] for t in a["teams"]] == ["1", "2", "3"]
    me = a["teams"][0]
    assert me["strategy"].startswith("Canlandır") and a["teams"][2]["strategy"].startswith("Otomatik")
    assert [p["id"] for p in me["sent"]] == ["0"] and me["received"][0]["from"] == "3"
    assert len(me["categories"]) == 9 and set(me["ranks"]) >= {"remaining_games_projection"}
    assert sum(c["after"] - c["before"] for c in me["categories"]) == pytest.approx(me["ecw_delta"])
    assert isinstance(me["playoff_games"], int)
    se = client.post("/api/leagues/L/trade/multi/season", json={**body, "n_sims": 300}).json()
    assert len(se["teams"]) == 3 and all(0 <= t["playoff_after"] <= 1 for t in se["teams"])
    bad = client.post("/api/leagues/L/trade/multi/analyze", json={"moves": body["moves"][:2]})
    assert bad.status_code == 400                                     # 3. takım hiçbir şey vermiyor
    s = client.post("/api/leagues/L/trade/multi/suggest", json={"team": "1", "shortlist": 4, "shortlist4": 3,
                                                               "min_fairness": 0, "min_gain": 0}).json()
    assert s["scanned"] > 0 and isinstance(s["suggestions"], list) and "1-1-1" in s["shapes"]
    for row in s["suggestions"]:
        assert all(t["strategy_delta"] >= 0 for t in row["teams"]) and len(row["moves"]) >= 3
    assert client.post("/api/leagues/L/trade/multi/suggest", json={"team": "1", "shapes": ["3-3-3"]}).status_code == 400


def test_trade_fixture_changes_for_both_sides(client):
    body = {"team_a": "1", "team_b": "2", "give_a": ["0"], "give_b": ["4"]}
    r = client.post("/api/leagues/L/trade/fixtures", json=body).json()
    assert [t["team_id"] for t in r["teams"]] == ["1", "2"]
    me = r["teams"][0]
    assert me["weeks"] and all(0 <= w["p_before"] <= 1 and 0 <= w["p_after"] <= 1 for w in me["weeks"])
    assert me["wins_before"] == pytest.approx(sum(w["p_before"] for w in me["weeks"]))
    assert all(w["partner"] == (w["opponent"] == "2") for w in me["weeks"])
    season = client.get("/api/leagues/L/season?team=1&n=200").json()["schedule"]
    assert [w["p_win"] for w in season] == pytest.approx([w["p_before"] for w in me["weeks"]])
    multi = {"moves": [{"player": "0", "from_team": "1", "to_team": "2"}, {"player": "4", "from_team": "2", "to_team": "3"},
                       {"player": "8", "from_team": "3", "to_team": "1"}]}
    m = client.post("/api/leagues/L/trade/multi/fixtures", json=multi).json()
    assert [t["team_id"] for t in m["teams"]] == ["1", "2", "3"]
    assert client.post("/api/leagues/L/trade/fixtures", json={**body, "give_b": []}).status_code == 400
