"""Veri kontrolleri: modelsiz kadrolu oyuncu, IL slotunda uygun olmayan durum, rol ve takım değişimi."""
from __future__ import annotations

import dataclasses
import datetime as dt

import numpy as np
import pandas as pd

from fdo.inseason.data_checks import as_dicts, data_checks
from fdo.trade.data import ROS
from unit.test_inseason import data  # noqa: F401


def _logs(rows):
    return pd.DataFrame(rows, columns=["name", "nba_team", "game_date", "minutes"])


def _games(name, team, minutes, start=dt.date(2026, 10, 20)):
    return [(name, team, start + dt.timedelta(days=i), m) for i, m in enumerate(minutes)]


def test_unmodeled_and_il_slot_findings(data):  # noqa: F811
    data.stats[ROS].loc["3", "gp"] = 0.0
    data.players.loc["3", "injury_status"] = "NA"
    found = data_checks(data)                                    # "7" IL'de, durumu sağlıklı
    by = {(f.check, f.player_id): f for f in found}
    assert ("unmodeled", "3") in by and "NA" in by[("unmodeled", "3")].message
    assert ("il_slot", "7") in by and by[("il_slot", "7")].teams == (("L", "2", "Takım 2"),)
    data.players.loc["7", "injury_status"] = "Q"                       # sağlıklı olmayan her durum IL'e uygun
    assert not any(f.check == "il_slot" for f in data_checks(data))
    assert all(f.level == "warn" for f in found) and as_dicts(found, "other") == []


def test_role_team_and_idle_from_logs(data):  # noqa: F811
    data = dataclasses.replace(data, as_of=dt.date(2026, 11, 1))
    p0 = data.players.loc["0"]
    rows = _games("P0", "AAA", [12] * 6 + [28] * 5)              # dakika 12 → 28
    rows += _games("P1", "CCC", [30] * 11)                       # Yahoo'da BBB
    rows += _games("P4", "AAA", [25] * 8 + [0] * 3)              # takımının son 3 maçında yok
    found = data_checks(data, _logs(rows))
    checks = {(f.check, f.player_id) for f in found}
    assert p0["nba_team"] == "AAA" and ("role", "0") in checks
    assert ("team", "1") in checks and ("idle", "4") in checks
    assert not any(c == "role" and p in ("1", "4") for c, p in checks)


def test_filled_rows_are_info(data):  # noqa: F811
    tab = pd.DataFrame({"ros_filled": [True]}, index=["5"])
    found = data_checks(dataclasses.replace(data, durability=tab))
    f = next(x for x in found if x.player_id == "5")
    assert f.check == "filled" and f.level == "info" and np.isfinite(data.stats[ROS].loc["5", "gp"])
