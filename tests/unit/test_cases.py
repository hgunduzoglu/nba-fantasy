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


def test_case_ids_must_be_unique(tmp_path):
    p = tmp_path / "cases.json"
    p.write_text(json.dumps([{"id": "a", "path": "/x"}, {"id": "a", "path": "/y"}]), encoding="utf-8")
    with pytest.raises(ValueError):
        load_cases(p)
