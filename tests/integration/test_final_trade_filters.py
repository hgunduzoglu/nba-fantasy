"""Final eligibility must survive changed lineup gains and acquisition plans."""
import pytest

from fdo.inseason.lineup_rank import LineupDelta
from fdo.trade import Strategy, TradeRequest
from fdo.trade.suggest import CompleteResult, SearchResult, Suggestion
from integration.test_api_inseason import client  # noqa: F401
from unit.test_inseason import data  # noqa: F401


def _suggestion(view=.94, req=None):
    return Suggestion(req or TradeRequest("1", "2", ("0",), ("4",)), .2, .2, .2, .1, .1, 1,
                      Strategy(), mode="buy_low", perceived_balance=view, acceptability="high")


def _search(monkeypatch, rows, deltas):
    monkeypatch.setattr("fdo.api.inseason.suggest_trades", lambda *a, **kw: SearchResult(suggestions=rows))
    monkeypatch.setattr("fdo.api.inseason.lineup_deltas", lambda *a: deltas)


@pytest.mark.parametrize("mode", ["buy_low", "sell_high"])
@pytest.mark.parametrize("view,require,keep", [(.94, True, False), (.949999, True, False),
                                             (.95, True, True), (.96, True, True), (.94, False, True)])
def test_reason_is_rechecked_at_the_final_095_threshold(client, monkeypatch, mode, view, require, keep):
    s = _suggestion(view)
    _search(monkeypatch, [s], [LineupDelta(.2, .2, {"1": .2, "2": -.1})])
    out = client.post("/api/leagues/L/trade/suggest", json={"team": "1", "mode": mode,
                                                          "require_reason": require}).json()
    assert bool(out["suggestions"]) == keep
    assert out["rejected_final"]["reason"] == (not keep)
    if keep:
        assert out["suggestions"][0]["acceptability"] == ("medium" if view >= .95 else "low")


@pytest.mark.parametrize("own,other,minimum,reason", [(-.1, .2, .005, "gain"), (.004, .2, .005, "gain"),
                                                   (.2, -.1, .005, "mode"), (.2, .004, .005, "mode")])
def test_final_mutual_mode_and_benefit_thresholds_are_enforced(client, monkeypatch, own, other, minimum, reason):
    _search(monkeypatch, [_suggestion()], [LineupDelta(own, own, {"1": own, "2": other})])
    out = client.post("/api/leagues/L/trade/suggest", json={"team": "1", "min_gain": minimum,
                                                          "require_reason": False}).json()
    assert not out["suggestions"] and out["rejected_final"][reason] == 1


def test_invalid_final_acquisition_plan_is_rejected_instead_of_returning_500(client, monkeypatch):
    eng = client.app.state.fdo.engine("L")
    eng.adds_used["1"] = eng.budget("1").weekly_limit
    req = TradeRequest("1", "2", ("0", "1"), ("4",), add_a=("16",), auto_drop=True, auto_fill=True)
    _search(monkeypatch, [_suggestion(req=req)], [LineupDelta(.2, .2, {"1": .2, "2": .1})])
    response = client.post("/api/leagues/L/trade/suggest", json={"team": "1"})
    assert response.status_code == 200
    out = response.json()
    assert not out["suggestions"] and out["rejected_roster"] == out["rejected_final"]["roster"] == 1


def test_rejected_finalists_do_not_use_up_the_result_limit(client, monkeypatch):
    rows = [_suggestion() for _ in range(21)]
    deltas = [LineupDelta(.3, .3, {"1": .3, "2": -.1}) for _ in range(20)]
    deltas.append(LineupDelta(.2, .2, {"1": .2, "2": .1}))
    _search(monkeypatch, rows, deltas)
    out = client.post("/api/leagues/L/trade/suggest", json={"team": "1", "mode": "buy_low"}).json()
    assert len(out["suggestions"]) == 1 and out["rejected_final"]["reason"] == 20
    assert out["suggestions"][0]["acceptability"] == "medium"


@pytest.mark.parametrize("require,keep", [(True, False), (False, True)])
def test_completion_refilters_reasons_but_keeps_the_selected_scenario_for_inspection(client, monkeypatch, require, keep):
    s = _suggestion()
    monkeypatch.setattr("fdo.api.inseason.complete_trade", lambda *a, **kw:
                        CompleteResult(kind="balance", suggestions=[s], current=s))
    monkeypatch.setattr("fdo.api.inseason.lineup_deltas", lambda *a:
                        [LineupDelta(.2, .2, {"1": .2, "2": -.1}) for _ in a[-1]])
    out = client.post("/api/leagues/L/trade/complete", json={"team_a": "1", "team_b": "2", "give_a": ["0"],
        "give_b": ["4"], "require_reason": require}).json()
    assert bool(out["suggestions"]) == keep
    assert out["current"]["acceptability"] == "low" and out["current"]["tier"] == "own"
