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


def test_minutes_ramp_compares_games_after_return_with_minutes_before():
    from check_durability import minutes_ramp
    rows = [{"name": "Team", "nba_team": "AAA", "game_date": d, "minutes": 30} for d in DAYS]
    hurt = DAYS[:10] + DAYS[22:]                                      # 12 maç yok
    rows += [{"name": "Hurt", "nba_team": "AAA", "game_date": d, "minutes": 15 if d in DAYS[22:24] else 30} for d in hurt]
    med, n = minutes_ramp(pd.DataFrame(rows), games=4)
    assert n == 1 and med == [.5, .5, 1.0, 1.0]
