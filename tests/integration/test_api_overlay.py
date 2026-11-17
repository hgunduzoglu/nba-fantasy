"""Senaryo katmanı (README §13.53): başlıktaki takaslar ve rol çarpanları yalnız o isteğe uygulanır."""
import json

import pandas as pd
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from fdo.api.app import create_app  # noqa: E402
from fdo.trade.data import ROS  # noqa: E402
from unit.test_inseason import data  # noqa: E402,F401  paylaşılan sentetik lig
from unit.test_season import _fixtures  # noqa: E402


@pytest.fixture
def client(data, tmp_path):  # noqa: F811
    _fixtures(range(1, 20)).to_csv(tmp_path / "fixtures.csv", index=False)
    pd.DataFrame({"league_id": "L", "team_id": ["1", "2", "3", "4"], "wins": [7, 2, 5, 4],
                  "losses": [2, 7, 4, 5], "ties": 0}).to_csv(tmp_path / "standings.csv", index=False)
    app = create_app(data_dir=tmp_path, frontend_dir=tmp_path / "yok")
    st = app.state.fdo
    st.plain_data = lambda injuries=True, delay=None: data
    st.signature = lambda: "test"
    return TestClient(app)


TRADE = {"league": "L", "team_a": "1", "team_b": "2", "give_a": ["0"], "give_b": ["4"]}


def _h(obj):
    return {"X-FDO-Scenario": json.dumps(obj)}


def _ids(c, team, headers=None):
    return {p["id"] for p in c.get(f"/api/leagues/L/roster/{team}", headers=headers or {}).json()["players"]}


def test_trade_step_applies_only_to_its_request(client):
    before = _ids(client, "1")
    after = _ids(client, "1", _h({"trades": [TRADE]}))
    assert "0" in before and "4" not in before and "4" in after and "0" not in after
    assert _ids(client, "1") == before                                   # sızıntı yok, önbellek bozulmaz
    assert _ids(client, "2", _h({"trades": [TRADE]})) >= {"0"}


def test_empty_overlay_is_identical(client):
    body = {"team_a": "1", "team_b": "3", "give_a": ["1"], "give_b": ["9"]}
    a = client.post("/api/leagues/L/trade/analyze", json=body).json()
    b = client.post("/api/leagues/L/trade/analyze", json=body, headers=_h({})).json()
    a.pop("decision_id", None), b.pop("decision_id", None)
    assert a == b
    assert _ids(client, "1", _h({"trades": [], "roles": {}})) == _ids(client, "1")


def test_moved_player_step_is_skipped(client):
    stale = {**TRADE, "give_a": ["5"]}                                  # "5" takım 1'de değil
    out = client.post("/api/scenario/check", json={"trades": [TRADE, stale]}).json()
    assert [s["status"] for s in out["trades"]] == ["applied", "skipped"]
    assert "takas Yahoo'da işlenmiş olabilir" in out["trades"][1]["reason"]
    assert _ids(client, "1", _h({"trades": [stale]})) == _ids(client, "1")


def test_role_factor_scales_rest_of_season_only(client, data):  # noqa: F811
    h = _h({"roles": {"0": 2.0}})
    original = data.stats[ROS].loc["0"].copy()
    row = lambda headers=None: next(p for p in client.get("/api/leagues/L/roster/1", headers=headers or {}).json()["players"]
                                    if p["id"] == "0")
    base, up = row(), row(h)
    assert up["value"] > base["value"]
    season = lambda headers=None: next(p for p in client.get("/api/leagues/L/roster/1?source=season",
                                                             headers=headers or {}).json()["players"] if p["id"] == "0")
    assert season(h)["stats"] == season()["stats"]                       # bu sezonun kaynağı değişmez
    pd.testing.assert_series_equal(data.stats[ROS].loc["0"], original)  # ham veri değişmez
    out = client.post("/api/scenario/check", json={"roles": {"0": 2.0, "zz": 1.5}}).json()
    assert {r["player_id"]: r["status"] for r in out["roles"]} == {"0": "applied", "zz": "error"}


def test_records_refused_and_bad_header(client):
    body = {"team_a": "1", "team_b": "3", "give_a": ["1"], "give_b": ["9"]}
    r = client.post("/api/leagues/L/trade/offer", json=body, headers=_h({"trades": [TRADE]}))
    assert r.status_code == 409
    a = client.post("/api/leagues/L/trade/analyze", json=body, headers=_h({"trades": [TRADE]})).json()
    assert a.get("decision_id") is None
    assert client.get("/api/leagues/L/roster/1", headers={"X-FDO-Scenario": "{bozuk"}).status_code == 400
    assert client.get("/api/leagues/L/roster/1", headers=_h({"roles": {"0": 9}})).status_code == 400
