"""Sakatlık analizi: aday seçimi, eskime, sahte istemciyle pause_turn / refusal / bozuk JSON, maliyet."""
from __future__ import annotations

import datetime as dt
import json
from types import SimpleNamespace

import pandas as pd

from fdo.inseason import injury_intel as ii


def _response(stop, text="", model="claude-fable-5-2", searches=1):
    usage = SimpleNamespace(input_tokens=1000, output_tokens=500, cache_read_input_tokens=0,
                            cache_creation_input_tokens=0, server_tool_use=SimpleNamespace(web_search_requests=searches))
    content = [SimpleNamespace(type="text", text=text)] if text else [SimpleNamespace(type="server_tool_use")]
    return SimpleNamespace(stop_reason=stop, content=content, usage=usage, model=model)


class FakeClient:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        return self.responses.pop(0)


def _analysis(pid):
    return {"id": pid, "injury": "hamstring strain", "status": "out", "latest_report_date": "2026-11-08",
            "official_timeline": "4 weeks", "return_earliest": "2026-12-06", "return_latest": "2026-12-20",
            "return_confidence": "medium", "minutes_restriction": "likely", "b2b_rest": "likely", "b2b_rest_weeks": 2,
            "reinjury_risk": "high", "summary_tr": "Aralık ortasına kadar yok.",
            "sources": [{"url": "https://example.com/a", "title": "t", "date": "2026-11-08"}]}


ROWS = [{"id": "1", "name": "A", "team": "AAA", "yahoo_status": "O", "cbs": None, "fantasy_team": "1"},
        {"id": "2", "name": "B", "team": "BBB", "yahoo_status": "Q", "cbs": None, "fantasy_team": "1"}]


def test_pause_turn_continues_and_results_are_stored(tmp_path):
    body = json.dumps({"players": [_analysis("1"), _analysis("2")]})
    client = FakeClient([_response("pause_turn"), _response("end_turn", body)])
    out = ii.refresh(tmp_path, ROWS, client=client, today=dt.date(2026, 11, 16))
    assert out["analyzed"] == 2 and len(client.calls) == 2
    assert client.calls[1]["messages"][1]["role"] == "assistant"            # aynı konuşma sürdü
    assert client.calls[0]["tools"][0]["type"] == "web_search_20260209"
    store = ii.load_store(tmp_path)
    assert store["items"]["1"]["analysis"]["b2b_rest"] == "likely" and store["usage"][0]["calls"] == 2
    assert out["cost"] > 0
    again = FakeClient([])
    assert ii.refresh(tmp_path, ROWS, client=again)["pending"] == 0 and not again.calls     # taze: çağrı yok
    changed = [{**ROWS[0], "yahoo_status": "Q"}]
    assert ii.refresh(tmp_path, changed, client=FakeClient([_response("end_turn", body)]))["pending"] == 1


def test_refusal_and_bad_json_store_nothing(tmp_path):
    for resp in (_response("refusal"), _response("end_turn", "{not json"), _response("max_tokens", "{}")):
        out = ii.refresh(tmp_path, ROWS[:1], client=FakeClient([resp]), force=True)
        assert out["analyzed"] == 0
    assert ii.load_store(tmp_path)["items"] == {} and len(ii.load_store(tmp_path)["usage"]) == 3


def test_candidates_take_injured_or_listed_players_only():
    players = pd.DataFrame({"name": ["A", "B", "C"], "nba_team": ["AAA", "BBB", "CCC"],
                            "injury_status": ["O", "", ""]}, index=["1", "2", "3"])
    inj = pd.DataFrame({"injury": ["Knee"], "status_text": ["out until"], "return_date": [dt.date(2026, 12, 1)]},
                       index=["2"])
    eng = SimpleNamespace(data=SimpleNamespace(players=players, injuries=inj),
                          league=SimpleNamespace(rosters={"1": ("1", "2", "3")}))
    rows = ii.candidates(eng, ["1"])
    assert [r["id"] for r in rows] == ["1", "2"] and rows[1]["cbs"]["return_date"] == "2026-12-01"


def test_api_lists_candidates_and_guards_the_paid_refresh(tmp_path, monkeypatch):
    from fdo.api import injury
    store = {"items": {}, "usage": [{"at": dt.date.today().isoformat() + "T08:00", "model": "claude-fable-5-2",
                                      "input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "searches": 400}]}
    assert injury.spent_today(store) == 4.0                      # 400 arama × $0,01
    monkeypatch.setenv(injury.DAILY_CAP_ENV, "2.5")
    assert injury.daily_cap() == 2.5
    monkeypatch.setenv(injury.DAILY_CAP_ENV, "x")
    assert injury.daily_cap() == injury.DEFAULT_CAP
