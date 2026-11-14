"""Dönüş sonrası oynama oranı ölçümü (scripts/check_durability.py)."""
import datetime as dt

import pandas as pd

from check_durability import post_return

DAYS = [dt.date(2025, 11, 1) + dt.timedelta(days=i) for i in range(40)]


def _logs(plays: dict[str, list[dt.date]]) -> pd.DataFrame:
    return pd.DataFrame([{"name": n, "nba_team": "AAA", "game_date": d, "minutes": 20} for n, ds in plays.items() for d in ds])


def test_post_return_rate_after_the_longest_absence():
    prev = _logs({"Hurt": DAYS[:30], "Iron": DAYS, "Team": DAYS})                     # önceki sezon: 30/40
    cur = _logs({"Hurt": DAYS[:5] + DAYS[20:40:2], "Iron": DAYS, "Team": DAYS})       # 15 maç yok, sonra yarısı
    r = post_return(prev, cur).set_index("name")
    assert list(r.index) == ["Hurt"]
    assert r.loc["Hurt", "prev_rate"] == .75 and r.loc["Hurt", "streak"] == 15
    assert r.loc["Hurt", "after_rate"] == .5 and r.loc["Hurt", "after_games"] == 20
