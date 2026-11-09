"""Bileşen bazında güncellik ve karar türüne göre çalışma durumu (``fdo.ingest.freshness``)."""
import datetime as dt
import json

import pytest

from fdo.ingest.freshness import ages, assess, components, report, rules

NOW = dt.datetime(2026, 11, 10, 12, 0, tzinfo=dt.timezone.utc)


@pytest.fixture
def d(tmp_path):
    (tmp_path / "rosters.json").write_text(json.dumps({"roster_date": "2026-11-10", "captured_at": "2026-11-10T09:00:00Z",
                                                       "leagues": []}), encoding="utf-8")
    (tmp_path / "injuries_cbs_2026-11-08.csv").write_text("name,captured_at\nA,2026-11-08T12:00:00+00:00\n",
                                                          encoding="utf-8")
    (tmp_path / "injuries_cbs_2026-11-10.csv").write_text("name,captured_at\nA,2026-11-10T10:00:00+00:00\n",
                                                          encoding="utf-8")
    (tmp_path / "yahoo_live.json").write_text(json.dumps({"captured_at": "2026-11-09T00:00:00+00:00",
                                                          "as_of": "2026-11-08"}), encoding="utf-8")
    (tmp_path / "gamelogs_nba_2025-26.csv").write_text("name,game_date\nA,2026-04-12\n", encoding="utf-8")
    (tmp_path / "gamelogs_nba_2026-27.csv").write_text("name,game_date\nA,2026-11-09\n", encoding="utf-8")
    (tmp_path / "schedule_nba_2026-27.csv").write_text("game_date\n2026-10-20\n", encoding="utf-8")
    return tmp_path


def test_each_component_has_its_own_time_and_basis(d):
    a = ages(components(d, "2026-27"), NOW)
    assert a["rosters"]["age_hours"] == 3.0 and a["rosters"]["basis"] == "captured"
    assert a["injuries"]["file"] == "injuries_cbs_2026-11-10.csv" and a["injuries"]["age_hours"] == 2.0
    assert a["live_week"]["age_hours"] == 36.0
    assert a["nba_logs"]["file"] == "gamelogs_nba_2026-27.csv" and a["nba_logs"]["basis"] == "source"
    assert a["schedule"]["basis"] == "file"                               # dosyada zaman yok: disk zamanı, işaretli
    assert "player_stats" not in a


def test_decision_states_follow_their_own_thresholds(d):
    out = assess(ages(components(d, "2026-27"), NOW))
    assert out["adddrop"]["state"] == "hold"                              # oyuncu sayfaları yok
    assert any("Oyuncu istatistikleri" in r and "yok" in r for r in out["adddrop"]["reasons"])
    assert any("Bu haftanın skoru" in r and "36 saatlik" in r for r in out["adddrop"]["reasons"])
    lineup = out["lineup"]
    assert lineup["state"] == "hold" and lineup["refresh"]                # canlı hafta 36 sa > 24 sa
    custom = {"lineup": {"rosters": (6, 24), "live_week": (6, 48)}}
    assert assess(ages(components(d, "2026-27"), NOW), custom)["lineup"]["state"] == "conditional"


def test_rules_file_overrides_defaults_and_read_only_refresh_text(d, tmp_path):
    f = tmp_path / "freshness.yaml"
    f.write_text("adddrop:\n  rosters: [1, 2]\n  player_stats:\n", encoding="utf-8")
    r = rules(f)
    assert r["adddrop"]["rosters"] == (1, 2) and r["adddrop"]["player_stats"] == (None, None)
    assert r["trade"] == rules(tmp_path / "yok.yaml")["trade"]
    rep = report(d, season="2026-27", now=NOW, read_only=True, rule_path=f)
    add = rep["decisions"]["adddrop"]
    assert add["state"] == "hold" and any("bilgisayarda" in x for x in add["refresh"])
    assert "varsayım" in rep["assumption"]
