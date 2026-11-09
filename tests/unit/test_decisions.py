"""Karar günlüğü (``fdo.evaluation.decisions``): yalnız ekleme, türler ayrı, kapatılabilir."""
import datetime as dt
import json

import pytest

from fdo.evaluation.decisions import DecisionLog

CODE = {"commit": "abc1234", "dirty": False}


def test_records_are_appended_per_month_with_context(tmp_path):
    log = DecisionLog(tmp_path, enabled=True, code=CODE)
    t = dt.datetime(2026, 11, 10, 9, 30, tzinfo=dt.timezone.utc)
    a = log.record("recommendation", "trade_complete", "L", {"give_a": ["1"]}, {"n_suggestions": 2},
                   data_signature="sig", data_as_of="2026-11-10", batch_id="b1", now=t)
    b = log.record("scenario", "trade_analyze", "L", {"give_a": ["1"], "give_b": ["9"]}, {"fairness": .8},
                   data_signature="sig", data_as_of="2026-11-10", now=t + dt.timedelta(days=25))
    assert a and b and a != b
    assert sorted(p.name for p in (tmp_path / "decisions").iterdir()) == ["2026-11.jsonl", "2026-12.jsonl"]
    first = json.loads((tmp_path / "decisions" / "2026-11.jsonl").read_text(encoding="utf-8"))
    assert first["decision_id"] == a and first["code"] == CODE and first["batch_id"] == "b1"
    assert first["created_at"] == "2026-11-10T09:30:00+00:00" and first["data_signature"] == "sig"
    assert [e["kind"] for e in log.entries()] == ["recommendation", "scenario"]
    assert [e["decision_id"] for e in log.entries("scenario")] == [b]


def test_disabled_log_and_unknown_kind(tmp_path, monkeypatch):
    off = DecisionLog(tmp_path, enabled=False, code=CODE)
    assert off.record("recommendation", "x", "L", {}, {}, data_signature="s", data_as_of="d") is None
    assert not (tmp_path / "decisions").exists()
    monkeypatch.setenv("FDO_DECISION_LOG", "0")
    assert DecisionLog(tmp_path).enabled is False
    with pytest.raises(ValueError):
        DecisionLog(tmp_path, enabled=True, code=CODE).record("guess", "x", "L", {}, {}, data_signature="s",
                                                              data_as_of="d")
