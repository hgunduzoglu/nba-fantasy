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
    st.data = lambda injuries=True, delay=None: data
    st.signature = lambda: "test"
    return TestClient(app)


def test_roster_marks_durability_cut(data, tmp_path):  # noqa: F811
    data.stats["preseason"].loc["0", "gp"] = 41.0
    app = create_app(data_dir=tmp_path, frontend_dir=tmp_path / "yok")
    app.state.fdo.data = lambda injuries=True, delay=None: apply_durability(data)
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


def test_drops_ranks_candidates_for_returning_player(client):
    r = client.post("/api/leagues/L/adddrop/drops", json={"team": "2", "week": 3}).json()
    assert r["activate"] == ["7"] and r["il"][0]["ready"] and r["il"][0]["activated"] and r["need"] == 0
    assert {x["player"]["id"] for x in r["rows"]} == {"4", "5", "6", "7"} and len(r["recommended"]) == 1
    assert next(x for x in r["rows"] if x["player"]["id"] == "7")["returning"]
    losses = [x["ros_loss"] for x in r["rows"]]
    assert losses == sorted(losses) and all(x > 0 for x in losses)
    assert r["recommended"][0] == next(x["player"]["id"] for x in r["rows"] if x["open_slots"] == 0)
    off = client.post("/api/leagues/L/adddrop/drops", json={"team": "2", "week": 3, "activate": []}).json()
    assert off["activate"] == [] and {x["player"]["id"] for x in off["rows"]} == {"4", "5", "6"}
    assert client.post("/api/leagues/L/adddrop/drops", json={"team": "2", "activate": ["4"]}).status_code == 400


def test_drops_need_when_roster_is_full(data, tmp_path):  # noqa: F811
    import dataclasses

    lg = data.leagues["L"]
    data.leagues["L"] = dataclasses.replace(lg, rosters={**lg.rosters, "1": lg.rosters["1"] + ("16",)},
                                            injury_rosters={**lg.injury_rosters, "1": frozenset({"16"})})
    app = create_app(data_dir=tmp_path, frontend_dir=tmp_path / "yok")
    app.state.fdo.data = lambda injuries=True, delay=None: data
    app.state.fdo.signature = lambda: "test"
    r = TestClient(app).post("/api/leagues/L/adddrop/drops", json={"team": "1", "week": 3}).json()
    assert r["capacity"] == 4 and r["active_count"] == 4 and r["activate"] == ["16"] and r["need"] == 1
    assert len(r["rows"]) == 5 and len(r["recommended"]) == 1
    out = next(x for x in r["rows"] if x["player"]["id"] == "2")                 # "O": bu hafta oynamıyor
    assert out["games"] == 0 and out["week_loss"] == pytest.approx(0, abs=1e-9)


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


def test_season_effect_of_many_trades_is_paired_with_the_single_trade(client):
    one = {"team_a": "1", "team_b": "2", "give_a": ["0"], "give_b": ["4"]}
    single = client.post("/api/leagues/L/trade/season", json={**one, "n_sims": 300}).json()
    body = {"trades": [one, {**one, "give_b": []}, {**one, "give_a": ["1"]}], "n_sims": 300}
    r = client.post("/api/leagues/L/trade/season/many", json=body)
    assert r.status_code == 200
    rows = r.json()["trades"]
    assert [x["index"] for x in rows] == [0, 1, 2] and "en az bir" in rows[1]["error"]
    a = rows[0]["teams"]["a"]
    assert a["team_id"] == "1" and {"champion", "seed"} <= set(a)
    assert a["champion"]["delta"] == pytest.approx(a["champion"]["after"] - a["champion"]["before"])
    assert a["champion"]["delta"] == pytest.approx(single["teams"]["a"]["effect"]["champion"]["delta"])
    assert a["champion"]["se"] >= 0 and isinstance(a["champion"]["clear"], bool)
    assert client.post("/api/leagues/L/trade/season/many", json={"trades": []}).status_code == 422
    logged = [e for e in client.app.state.fdo.decisions.entries("scenario") if e["action"] == "trade_season_many"]
    assert logged and logged[-1]["result"]["trades"][1]["error"]


def test_trade_complete_endpoint(client):
    body = {"team_a": "1", "team_b": "2", "give_a": ["0"], "give_b": [], "min_fairness": 0, "min_view": 0}
    r = client.post("/api/leagues/L/trade/complete", json=body).json()
    assert r["kind"] == "get" and r["current"] is None and r["suggestions"]
    s = r["suggestions"][0]
    assert [p["added"] for p in s["give_a"]] == [False] and all(p["added"] for p in s["give_b"])
    assert set(s["my_categories"]) and s["tier"] in ("mutual", "own", "loss")
    both = client.post("/api/leagues/L/trade/complete", json={**body, "give_b": ["4"]}).json()
    assert both["kind"] == "balance" and both["current"] is not None
    assert client.post("/api/leagues/L/trade/complete", json={**body, "give_a": []}).status_code == 400


def test_trade_scenarios_and_basis(client):
    body = {"team_a": "1", "team_b": "2", "give_a": ["0"], "give_b": ["4"]}
    s = client.post("/api/leagues/L/trade/scenarios", json=body).json()
    assert [b["basis"] for b in s["bases"]] == ["ros", "season", "recent", "blend", "late"]
    assert s["bases"][-1]["label"] == "Geç dönüş (+7 gün)"                     # etiketli senaryo, oran değiştirmez
    assert {p["id"] for p in s["players"]} == {"0", "4"} and set(s["players"][0]["rates"]) == {"ros", "season", "recent", "blend"}
    a = client.post("/api/leagues/L/trade/analyze", json={**body, "basis": "season"}).json()
    assert a["basis"] == "season" and isinstance(a["teams"]["a"]["returns"], list)
    assert client.post("/api/leagues/L/trade/analyze", json={**body, "basis": "late"}).status_code == 200
    assert client.get("/api/meta").json()["returns"] == {"delay_days": 0, "late_days": 7}
    assert client.post("/api/leagues/L/trade/analyze", json={**body, "basis": "uydurma"}).status_code == 422


def test_trade_report_background_and_access(client, tmp_path, monkeypatch):
    import time

    import fdo.api.report as report_api
    import fdo.inseason.trade_report as tr
    from unit.test_trade_report import REPORT

    monkeypatch.setattr(report_api, "available", lambda: True)
    monkeypatch.setattr(tr, "generate", lambda packet, **kw: (REPORT, {"model": "claude-opus-5-5", "input": 1, "output": 1,
                                                                       "cache_read": 0, "cache_write": 0}, None))
    body = {"team_a": "1", "team_b": "2", "give_a": ["0"], "give_b": ["4"]}
    assert client.post("/api/leagues/L/trade/report", json={**body, "give_b": []}).status_code == 400
    r = client.post("/api/leagues/L/trade/report", json=body).json()
    for _ in range(100):
        if r["status"] != "running":
            break
        time.sleep(0.05)
        r = client.get(f"/api/trade/report/{r['key']}").json()
    assert r["status"] == "done" and r["report"]["decision"] == "karşı teklif ver"
    c = r["report"]["counter_offers"][0]
    assert c["valid"] and c["give"][0]["id"] == "0" and c["get"][0]["id"] == "4"
    assert r["number_check"]["checked"] >= 0 and isinstance(r["number_check"]["unmatched"], list)
    assert client.post("/api/leagues/L/trade/report", json=body).json()["status"] == "done"     # kayıttan, ücretsiz
    assert (tmp_path / "trade_reports.json").exists()

    ro = TestClient(create_app(data_dir=tmp_path, frontend_dir=tmp_path / "yok", read_only=True))
    ro.app.state.fdo.data = client.app.state.fdo.data
    ro.app.state.fdo.signature = lambda: "test"
    monkeypatch.delenv("FDO_REPORT_CODE", raising=False)
    assert ro.get("/api/meta").json()["report"] == {"available": False, "needs_code": False}
    assert ro.post("/api/leagues/L/trade/report", json=body).status_code == 403
    monkeypatch.setenv("FDO_REPORT_CODE", "gizli")
    assert ro.post("/api/leagues/L/trade/report", json=body).status_code == 401
    ok = ro.post("/api/leagues/L/trade/report", json=body, headers={"X-Report-Code": "gizli"})
    assert ok.status_code == 200 and ok.json()["status"] == "done"
