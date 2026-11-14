"""Menajer profili: işlem geçmişinden alım, bırakma, takas ve son işlem."""
import datetime as dt

import pandas as pd

from fdo.inseason.managers import profiles

ROWS = [
    ("1", "A PG Free Agent B SF To Waivers Team One Oct 31, 4:55 am logo"),
    ("1", "C C $3 Waiver D PG To Free Agent Team One Oct 21, 4:13 am logo"),
    ("2", "E SF Traded to Team Two Oct 29, 6:30 pm logo"),
    ("3", "F PG Vetoed Trade to Team Three Oct 30, 5:28 am logo"),
    ("9", "G PG Free Agent Other Oct 30, 5:28 am logo"),                      # ligde olmayan takım
]


def test_profiles_count_actions_per_team_and_keep_the_last_date():
    t = pd.DataFrame([{"league_id": "L", "team_ids": tid, "raw_text": text, "captured_at": "2026-10-31T13:00:00Z"}
                      for tid, text in ROWS])
    prof, captured = profiles(t, "L", ["1", "2", "3", "4"])
    assert captured == "2026-10-31T13:00:00Z"
    one = prof["1"]
    assert (one.adds, one.drops, one.trades, one.last_action) == (2, 2, 0, dt.date(2026, 10, 31))
    assert prof["2"].trades == 1 and prof["2"].adds == 0 and prof["3"].vetoed == 1
    assert prof["4"].last_action is None and prof["4"].adds == 0
    assert profiles(None, "L", ["1"])[1] is None
