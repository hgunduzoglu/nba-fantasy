"""Sakatlık dönüşü: en erken tarih ile gerçek dönüşün ölçümü (sansürlü), varsayım dosyası ve tarih kaydırma."""
from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from fdo.inseason.injuries import return_assumptions, return_delay, shift_returns
from fdo.inseason.returns import load_reports, median_delay, observed_returns, return_curve

START = dt.date(2026, 10, 20)
PLAYERS = pd.DataFrame({"name": ["Ann Able", "Bob Baker", "Cy Cole", "Dee Dunn", "Eve Ely"],
                        "nba_team": ["AAA", "AAA", "BBB", "BBB", "AAA"]}, index=["1", "2", "3", "4", "5"])
DAYS = [dt.date(2026, 11, d) for d in range(1, 11)]                     # iki takım da her gün oynar


def _logs() -> pd.DataFrame:
    rows = []
    plays = {"Ann Able": ("AAA", dt.date(2026, 11, 2)), "Bob Baker": ("AAA", dt.date(2026, 11, 6)),
             "Dee Dunn": ("BBB", dt.date(2026, 11, 1)), "Eve Ely": ("AAA", DAYS[0])}
    for name, (team, first) in plays.items():
        rows += [{"name": name, "nba_team": team, "game_date": d, "minutes": 20} for d in DAYS if d >= first]
    rows += [{"name": "Cy Cole", "nba_team": "BBB", "game_date": d, "minutes": 0} for d in DAYS]   # kadroda, oynamıyor
    return pd.DataFrame(rows)


def _report(rows) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["name", "nba_team", "status_text"])


REPORTS = [
    (dt.date(2026, 10, 31), _report([("Ann Able", "AAA", "Expected to be out until at least Nov 2"),
                                     ("Bob Baker", "AAA", "Expected to be out until at least Nov 3"),
                                     ("Cy Cole", "BBB", "Expected to be out until at least Nov 5"),
                                     ("Dee Dunn", "BBB", "Expected to be out until at least Nov 4"),
                                     ("Zed Unknown", "BBB", "Expected to be out until at least Nov 4"),
                                     ("Eve Ely", "AAA", "Game Time Decision")])),
    (dt.date(2026, 11, 7), _report([("Bob Baker", "AAA", "Expected to be out until at least Nov 3"),     # aynı tarih
                                    ("Cy Cole", "BBB", "Expected to be out until at least Nov 20")])),    # gelecekte
]


def test_observed_returns_measure_delay_and_censor_the_rest():
    obs = observed_returns(REPORTS, _logs(), PLAYERS, START).set_index("name")
    assert list(obs.index) == ["Ann Able", "Bob Baker", "Cy Cole", "Dee Dunn"]      # bilinmeyen, DTD, tekrar, gelecek yok
    assert obs.loc["Ann Able", ["returned", "delay_days", "games_missed"]].tolist() == [True, 0, 0]
    assert obs.loc["Bob Baker", ["returned", "delay_days", "games_missed"]].tolist() == [True, 3, 3]
    assert obs.loc["Cy Cole", ["returned", "delay_days", "games_missed"]].tolist() == [False, 6, 6]   # en az (sansür)
    assert obs.loc["Dee Dunn", "delay_days"] == -3 and obs.loc["Dee Dunn", "games_missed"] == 0     # erken döndü
    assert observed_returns(REPORTS, pd.DataFrame(), PLAYERS, START).empty


def test_return_curve_and_median_count_censored_players_only_while_observed():
    obs = observed_returns(REPORTS, _logs(), PLAYERS, START)
    curve = return_curve(obs, "games_missed", (0, 1, 3)).set_index("k")
    # 0 maçta 4 kişiden 2'si döndü; 3. maçta izlenen 2 kişiden biri: 1 − 0,5·0,5
    assert curve["returned_share"].tolist() == pytest.approx([.5, .5, .75])
    assert curve.loc[3, "at_risk"] == 2
    assert median_delay(obs) == 0
    assert median_delay(obs[obs["name"].isin(["Bob Baker", "Cy Cole"])]) == 3       # 3. günde ikiden biri döndü
    assert median_delay(obs[obs["name"] == "Cy Cole"]) is None                     # hiç dönüş gözlenmedi


def test_reports_come_from_the_folder_and_the_archive(tmp_path):
    from fdo.ingest.archive import archive
    for day, rep in REPORTS:
        rep.to_csv(tmp_path / f"injuries_cbs_{day}.csv", index=False)
    archive(tmp_path, source="test")
    (tmp_path / "injuries_cbs_2026-11-07.csv").unlink()                       # yalnız arşivde kaldı
    got = load_reports(tmp_path)
    assert [d for d, _ in got] == [d for d, _ in REPORTS]
    assert got[1][1]["name"].tolist() == ["Bob Baker", "Cy Cole"]


def test_assumptions_file_and_shifted_returns(tmp_path):
    assert return_assumptions(tmp_path / "yok.yaml") == {"delay_days": 0, "late_days": 7}
    cfg = tmp_path / "returns.yaml"
    cfg.write_text("delay_days: 3\nlate_days: -2\nbilinmeyen: 1\n", encoding="utf-8")
    assert return_assumptions(cfg) == {"delay_days": 3, "late_days": 0} and return_delay(cfg) == 3
    inj = pd.DataFrame({"kind": ["out_until", "season", "day_to_day"],
                        "return_date": [dt.date(2026, 11, 4), None, None]}, index=["1", "2", "3"])
    out = shift_returns(inj, 5)
    assert out.loc["1", "return_date"] == dt.date(2026, 11, 9) and out.loc["1", "stated_return"] == dt.date(2026, 11, 4)
    assert out.loc["2", "return_date"] is None and inj.loc["1", "return_date"] == dt.date(2026, 11, 4)
    assert shift_returns(inj, 0)["return_date"].tolist() == inj["return_date"].tolist()
