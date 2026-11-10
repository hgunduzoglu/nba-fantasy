"""Referans vaka çalıştırıcısı (``fdo.evaluation.cases``): beklenti kontrolü, özet, karşılaştırma."""
import json

import pytest

from fdo.evaluation.cases import check, compare, load_cases, package, record, run, summarize


def _row(a, b, **kw):
    return {"give_a": [{"id": x, "name": f"N{x}"} for x in a], "give_b": [{"id": x, "name": f"N{x}"} for x in b], **kw}


RESPONSE = {"suggestions": [_row(["1"], ["9"], tier="own", own_delta=.3, other_delta=-.5),
                            _row(["1"], ["8", "7"], tier="mutual")], "examined": 40, "current": None}


def test_package_ignores_order_and_accepts_plain_ids():
    assert package(_row(["2", "1"], ["9"])) == package({"give_a": ["1", "2"], "give_b": [9]})


def test_absent_and_present_expectations():
    assert check({"absent": {"give_a": ["1"], "give_b": ["9"]}}, RESPONSE) is False
    assert check({"absent": {"give_a": ["1"], "give_b": ["5"]}}, RESPONSE) is True
    assert check({"present": {"give_a": ["1"], "give_b": ["7", "8"]}}, RESPONSE) is True
    with pytest.raises(ValueError):
        check({"maybe": {}}, RESPONSE)


def test_summary_keeps_ids_metrics_and_scalar_meta():
    s = summarize(RESPONSE)
    assert s["n_suggestions"] == 2 and s["examined"] == 40 and "current" in s
    assert s["suggestions"][0] == {"give_a": ["1"], "give_b": ["9"], "names": ["N1", "N9"], "tier": "own",
                                   "own_delta": .3, "other_delta": -.5}


class FakeClient:
    def __init__(self, status=200):
        self.status = status

    def post(self, path, json):
        class R:
            status_code = self.status
            text = "hata"

            def json(_):
                return RESPONSE
        return R()


def test_run_records_checks_and_http_errors():
    case = {"id": "c", "path": "/x", "body": {}, "expect": [{"absent": {"give_a": ["1"], "give_b": ["9"]},
                                                             "reason": "rakip için gerekçesiz"}]}
    ok = run(FakeClient(), [case])[0]
    assert ok["status"] == 200 and ok["checks"][0]["ok"] is False and ok["result"]["n_suggestions"] == 2
    bad = run(FakeClient(500), [case])[0]
    assert bad["error"] == "hata" and bad["checks"][0]["ok"] is None and "result" not in bad


def test_compare_lists_check_flips_and_package_changes():
    case = {"id": "c", "path": "/x", "expect": [{"absent": {"give_a": ["1"], "give_b": ["9"]}, "reason": "r"}]}
    old = record(run(FakeClient(), [case]), data_signature="s", as_of="2026-11-10")
    new = json.loads(json.dumps(old))
    new["cases"][0]["checks"][0]["ok"] = True
    new["cases"][0]["result"]["suggestions"] = new["cases"][0]["result"]["suggestions"][1:]
    lines = compare(old, new)
    assert any("False → True" in x for x in lines) and any("− ('1',) → ('9',)" in x for x in lines)
    assert not any("Uyarı" in x for x in lines)
    new["data_signature"] = "t"
    assert any("Uyarı" in x for x in compare(old, new))


def test_shadow_compares_the_model_order_with_the_season_order():
    from fdo.evaluation.cases import shadow
    same = shadow([.03, .02, .01])
    assert same["spearman"] == pytest.approx(1) and same["model_top_season_rank"] == 1
    flipped = shadow([.01, .02, .03, None])
    assert flipped["spearman"] == pytest.approx(-1) and flipped["model_top_season_rank"] == 3 and flipped["n"] == 3
    assert shadow([None, .01])["spearman"] is None
    assert shadow([.02, None, .01])["model_top_season_rank"] == 1


def test_season_trades_keep_the_teams_and_strategies():
    from fdo.evaluation.cases import season_trades
    comp = season_trades("/api/leagues/L/trade/complete",
                         {"team_a": "1", "team_b": "2", "strategy_b": {"preset": "x"}}, [_row(["1"], ["9"])])
    assert comp == [{"team_a": "1", "team_b": "2", "strategy_a": None, "strategy_b": {"preset": "x"},
                     "give_a": ["1"], "give_b": ["9"], "auto_balance": True, "injuries": True}]
    sug = season_trades("/api/leagues/L/trade/suggest", {"team": "1"},
                        [_row(["1"], ["9"], team_b="3", other_strategy="P", other_weights=[1] * 9)])
    assert sug[0]["team_b"] == "3" and sug[0]["strategy_b"] == {"name": "P", "weights": [1] * 9}


def test_run_with_season_adds_effects_and_shadow():
    class SeasonClient(FakeClient):
        def post(self, path, json):
            if not path.endswith("/season/many"):
                return super().post(path, json)
            eff = lambda d: {"playoff": {"before": .5, "after": .5 + d, "delta": d, "se": .01, "clear": True},
                             "champion": {"before": .1, "after": .1, "delta": 0, "se": 0, "clear": False}}

            class R:
                status_code = 200

                def json(_):
                    return {"trades": [{"index": 0, "teams": {"a": eff(.01), "b": eff(0)}},
                                       {"index": 1, "error": "çözülemedi"}]}
            return R()

    case = {"id": "c", "path": "/api/leagues/L/trade/complete", "body": {"team_a": "1", "team_b": "2"}}
    e = run(SeasonClient(), [case], season_sims=300)[0]
    rows = e["result"]["suggestions"]
    assert rows[0]["season"]["playoff"] == {"delta": .01, "se": .01, "clear": True}
    assert rows[1]["season"] == {"error": "çözülemedi"} and e["shadow"]["playoff"]["n"] == 1
    assert "shadow" not in run(FakeClient(), [case])[0]


def test_case_ids_must_be_unique(tmp_path):
    p = tmp_path / "cases.json"
    p.write_text(json.dumps([{"id": "a", "path": "/x"}, {"id": "a", "path": "/y"}]), encoding="utf-8")
    with pytest.raises(ValueError):
        load_cases(p)
