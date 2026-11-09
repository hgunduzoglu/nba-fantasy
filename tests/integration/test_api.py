"""Sezon içi web API'si (FastAPI TestClient, sentetik lig)."""
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from fdo.api.app import create_app  # noqa: E402
from unit.test_trade import trade_data  # noqa: E402,F401  paylaşılan sentetik lig


@pytest.fixture
def client(trade_data, tmp_path):  # noqa: F811
    app = create_app(data_dir=tmp_path, frontend_dir=tmp_path / "yok")
    state = app.state.fdo
    state.data = lambda injuries=True: trade_data
    state.signature = lambda: "test"
    return TestClient(app)


def test_meta_and_rosters(client):
    m = client.get("/api/meta").json()
    assert [lg["id"] for lg in m["leagues"]] == ["L"] and len(m["categories"]) == 9 and m["presets"]
    r = client.get("/api/leagues/L/roster/1?source=season").json()
    assert len(r["players"]) == 3 and set(r["players"][0]["stats"]) == {c["key"] for c in m["categories"]}
    p = r["players"][0]
    assert 0 < p["stats"]["FG_PCT"] < 1 and p["z"]["PTS"] is not None and p["modeled"]
    # bu sezon / sezon öncesi kaynağında algılanan değer ve sıra; kalan sezonda yok
    assert p["perceived_value"] > 0 and p["perceived_rank"] >= 1 and p["perceived_fallback"] is False
    ranks = sorted(x["perceived_rank"] for x in r["players"])
    assert len(set(ranks)) == len(ranks)
    assert client.get("/api/leagues/L/roster/1?source=preseason").json()["players"][0]["perceived_rank"] >= 1
    ros = client.get("/api/leagues/L/roster/1").json()["players"][0]
    assert ros["perceived_value"] is None and ros["perceived_rank"] is None
    assert client.get("/api/leagues/L/roster/9").status_code == 404
    assert client.get("/api/leagues/X/roster/1").status_code == 404
    assert client.get("/api/leagues/L/roster/1?source=bad").status_code == 422
    fa = client.get("/api/leagues/L/free-agents").json()["players"]
    assert fa and not {x["id"] for x in fa} & {"0", "1", "2"}


def test_trade_analyze_and_errors(client):
    body = {"team_a": "1", "team_b": "2", "give_a": ["0"], "give_b": ["3"],
            "strategy_b": {"preset": "Punt FT_PCT"}}
    j = client.post("/api/leagues/L/trade/analyze", json=body).json()
    a, b = j["teams"]["a"], j["teams"]["b"]
    assert a["team_id"] == "1" and b["strategy"] == "Punt FT_PCT"
    assert a["ecw_delta"] == pytest.approx(a["ecw_after"] - a["ecw_before"])
    assert len(a["categories"]) == 9 and set(a["ranks"]) == {"preseason", "season_total", "remaining_games_projection"}
    assert 0 <= j["fairness"] <= 1
    bad = client.post("/api/leagues/L/trade/analyze", json={**body, "give_a": []})
    assert bad.status_code == 400 and "en az bir" in bad.json()["detail"]
    assert client.post("/api/leagues/L/trade/season", json=body).status_code == 409   # fikstür yok
    assert client.get("/api/bilinmeyen").status_code == 404


def test_auto_punt_strategy_and_manual_roster_moves(client):
    body = {"team_a": "1", "team_b": "2", "give_a": ["0"], "give_b": ["3", "4"], "auto_balance": False,
            "drop_a": ["1"], "add_b": ["12"], "strategy_b": {"auto_punt": 2}}
    j = client.post("/api/leagues/L/trade/analyze", json=body).json()
    assert j["teams"]["b"]["strategy"].startswith("Otomatik: punt") and "+" in j["teams"]["b"]["strategy"]
    assert [x["id"] for x in j["teams"]["a"]["adjustments"]["drop"]] == ["1"]
    assert [x["id"] for x in j["teams"]["b"]["adjustments"]["add"]] == ["12"]
    taken = client.post("/api/leagues/L/trade/analyze", json={**body, "add_b": ["5"]})   # kadrolu oyuncu eklenemez
    assert taken.status_code == 400
    bad = client.post("/api/leagues/L/trade/analyze", json={**body, "strategy_b": {"auto_punt": 3}})
    assert bad.status_code == 422


def test_freshness_reports_components_and_decision_states(client):
    r = client.get("/api/freshness")
    assert r.status_code == 200
    body = r.json()
    assert set(body["decisions"]) >= {"trade", "adddrop", "lineup", "season"} and "varsayım" in body["assumption"]
    # sentetik ligin veri dizini boş: hiçbir bileşen yok, kararlar bekletilir ve neyin eksik olduğu söylenir
    assert body["components"] == {} and body["decisions"]["trade"]["state"] == "hold"
    assert any("Kadrolar yok" in x for x in body["decisions"]["trade"]["reasons"])
