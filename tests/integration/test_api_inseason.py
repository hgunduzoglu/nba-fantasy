"""Sezon içi API uç noktaları: öneriler, yanlış fiyatlama, bu hafta + streaming, boştakiler, sezon, sıralamalar."""
import pandas as pd
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from fdo.api.app import create_app  # noqa: E402
from fdo.inseason.durability import apply_durability  # noqa: E402
from unit.test_inseason import data  # noqa: E402,F401  paylaşılan sentetik lig
from unit.test_live import write_live  # noqa: E402
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


def test_roster_marks_durability_cut(data, tmp_path):  # noqa: F811
    data.stats["preseason"].loc["0", "gp"] = 41.0
    app = create_app(data_dir=tmp_path, frontend_dir=tmp_path / "yok")
    app.state.fdo.data = lambda injuries=True: apply_durability(data)
    app.state.fdo.signature = lambda: "test"
    c = TestClient(app)
    p = next(x for x in c.get("/api/leagues/L/roster/1").json()["players"] if x["id"] == "0")
    assert p["durability"]["rate"] == pytest.approx(.5, abs=.05) and p["durability"]["yahoo_gp"] > p["gp"]
    s = next(x for x in c.get("/api/leagues/L/roster/1?source=season").json()["players"] if x["id"] == "0")
    assert s["durability"] is None


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


def test_weekly_uses_the_synced_score_unless_entered(client, tmp_path):
    w = client.post("/api/leagues/L/weekly", json={"team": "1"}).json()
    assert w["live"] is None
    st = client.app.state.fdo
    write_live(tmp_path, week=w["current_week"], used=1)
    st.signature = lambda: "synced"                                             # dosya yazılınca imza değişir
    w = client.post("/api/leagues/L/weekly", json={"team": "1", "opponent": "2"}).json()
    assert w["live"]["mine"]["pts"] == 300 and w["live"]["adds_used"] == 1 and not w["live"]["manual"]
    assert w["outlook"]["totals"]["mine"]["PTS"] >= 300
    manual = client.post("/api/leagues/L/weekly", json={"team": "1", "opponent": "2", "acc_mine": {"pts": 5}}).json()
    assert manual["live"]["manual"] and manual["outlook"]["totals"]["mine"]["PTS"] < w["outlook"]["totals"]["mine"]["PTS"]
    s = client.post("/api/leagues/L/weekly/stream", json={"team": "1", "opponent": "2", "droppable": []}).json()
    assert s["left"] == 3                                                       # 4 − Yahoo'daki 1 alım
    other = client.post("/api/leagues/L/weekly", json={"team": "1", "week": w["current_week"] + 1}).json()
    assert other["live"] is None                                                # yalnız içinde bulunulan hafta
    write_live(tmp_path, as_of="2026-10-30", week=w["current_week"])
    st.signature = lambda: "synced-old"
    assert client.post("/api/leagues/L/weekly", json={"team": "1"}).json()["live"] is None   # başka çekim


def test_sitstart(client):
    r = client.post("/api/leagues/L/sitstart", json={"team": "1", "week": 3}).json()
    assert len(r["days"]) == 7 and r["slot_names"] == ["PG", "C"] and r["today"] is None   # veri tarihi 3. haftada değil
    assert r["after"]["strategy_score"] >= r["before"]["strategy_score"] - 1e-9
    p = r["players"][0]
    assert len(p["cells"]) == 7 and set(p["dp"]) >= {"FG_PCT", "TOV"}
    assert all(c["slot"] in ("PG", "C") for q in r["players"] for c in q["cells"] if c["state"] == "start")


def test_adddrop_week_modes_and_waiver_dates(client, tmp_path):
    w = client.post("/api/leagues/L/adddrop/week", json={"team": "1", "week": 3}).json()
    assert w["mode"] == "win" and w["objective"] == "Dengeli" and not w["synced"] and w["adds_left"] == 4
    assert len(w["categories"]) == 9 and w["chosen"] and len(w["droppable"]) == 3
    assert all(r["add"]["availability"]["kind"] == "FA" for r in w["singles"])
    c = client.post("/api/leagues/L/adddrop/week",
                    json={"team": "1", "week": 3, "mode": "critical", "categories": ["BLK"], "plan": False}).json()
    assert c["objective"] == "Kritik: BLK" and c["plan"] is None and c["chosen"] == ["BLK"]
    assert client.post("/api/leagues/L/adddrop/week", json={"team": "1", "mode": "critical",
                                                            "categories": ["XYZ"]}).status_code == 400
    write_live(tmp_path, week=w["current_week"], used=1)                         # 16: waiver, 2 Kasım'dan itibaren
    client.app.state.fdo.signature = lambda: "synced"
    s = client.post("/api/leagues/L/adddrop/week", json={"team": "1"}).json()
    assert s["synced"] and s["adds_left"] == 3 and s["fab"] == 87
    for r in s["singles"]:
        if r["add"]["id"] == "16":
            assert r["add"]["availability"] == {"kind": "W", "from": "2026-11-02"} and r["day"] >= "2026-11-02"
    ros = client.post("/api/leagues/L/waiver", json={"team": "1"}).json()
    assert ros["adds_left"] == 3 and ros["fab"] == 87 and ros["synced"]
    kinds = {r["add"]["id"]: r["add"]["availability"]["kind"] for r in ros["rows"]}
    assert kinds.get("16", "W") == "W" and set(kinds.values()) <= {"FA", "W"}


def test_history_without_and_with_results(client, tmp_path):
    assert client.get("/api/leagues/L/history?team=1").json()["weeks"] == []
    t = {"fgm": 40, "fga": 100, "ftm": 8, "fta": 10, "fg3m": 5, "pts": 100, "reb": 30, "ast": 20, "stl": 5, "blk": 3,
         "tov": 10}
    import json
    (tmp_path / "matchups.json").write_text(json.dumps({"matchups": [
        {"league_id": "L", "week": 1, "team_a_id": "1", "team_b_id": "2", "team_a_totals": t,
         "team_b_totals": {**t, "pts": 50}, "team_a_category_wins": 1, "team_b_category_wins": 0, "tied_categories": 8}]}),
        encoding="utf-8")
    h = client.get("/api/leagues/L/history?team=1").json()
    assert h["weeks"][0]["ranks"]["PTS"] == 1 and h["weeks"][0]["result"]["opponent_name"] == "Takım 2"
    assert h["weeks"][0]["start"] == "2026-10-20" and h["season"]["values"]["PTS"] == 100


def test_news_tags_by_owner_and_status(client, tmp_path):
    import datetime as dt
    import json

    when = dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes")
    a = {"player": "P0", "team": "AAA", "type": "injury", "status": "out", "return_estimate": "2026-11-12",
         "games_out": 2, "beneficiaries": ["P16"], "hurt": [], "impact": -1, "summary_tr": "P0 yok"}
    store = {"fetched_at": when, "usage": [], "items": {
        "u1": {"id": "u1", "source": "cbs", "url": "u1", "player_name": "P0", "player_team": "AAA", "headline": "h",
               "body": "b", "published": when, "fetched_at": when, "analysis": a},
        "u2": {"id": "u2", "source": "cbs", "url": "u2", "player_name": "P5", "player_team": "BBB",
               "headline": "Scores", "body": "", "published": "2020-01-01T00:00+00:00", "fetched_at": when,
               "analysis": None}}}
    (tmp_path / "news.json").write_text(json.dumps(store), encoding="utf-8")
    r = client.get("/api/leagues/L/news?team=1").json()
    assert [e["id"] for e in r["events"]] == ["u1"]                              # eski haber pencere dışında
    e = r["events"][0]
    assert e["player"]["owner"] == "me" and e["beneficiaries"][0]["owner"] == "FA" and e["tags"] == ["fa", "mine"]
    assert e["games_out"] == 2 and e["summary"] == "P0 yok" and r["roles"] == []
    st = client.get("/api/news/status").json()
    assert st["items"] == 2 and st["analyzed"] == 1 and st["cost_7d"] == 0


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
