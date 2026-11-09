"""Yahoo senkronizasyonunun canlı hafta dosyası (``yahoo_live.json``)."""
from __future__ import annotations

import datetime as dt
import json

from fdo.inseason.live import load_live


def write_live(directory, as_of="2026-10-31", week=2, used=1):
    doc = {"captured_at": "2026-10-31T14:00:00+00:00", "as_of": as_of, "live": False, "leagues": {"L": {
        "week": week, "my_team": "1", "adds_used": used, "adds_limit": 4, "fab": 87,
        "matchups": [{"team_a_id": "1", "team_b_id": "2", "team_a_category_wins": 6, "team_b_category_wins": 3,
                      "team_a_totals": {"pts": 300.0, "fgm": 100.0, "fga": 210.0},
                      "team_b_totals": {"pts": 250.0, "fgm": 90.0, "fga": 200.0}},
                     {"team_a_id": "3", "team_b_id": "4", "team_a_category_wins": 4, "team_b_category_wins": 4,
                      "team_a_totals": {"pts": 10.0}, "team_b_totals": {"pts": 20.0}}],
        "waivers": [{"player_id": "16", "player_name": "x", "until": "2026-11-02"},
                    {"player_id": "17", "player_name": "y", "until": None}]}}}
    (directory / "yahoo_live.json").write_text(json.dumps(doc), encoding="utf-8")


def test_load_live(tmp_path):
    assert load_live(tmp_path) == {}
    write_live(tmp_path)
    lv = load_live(tmp_path)["L"]
    assert (lv.week, lv.as_of, lv.my_team, lv.fab) == (2, dt.date(2026, 10, 31), "1", 87)
    assert lv.totals["2"]["pts"] == 250 and lv.opponents == {"1": "2", "2": "1", "3": "4", "4": "3"}
    assert lv.category_wins["1"] == 6
    assert lv.waivers == {"16": dt.date(2026, 11, 2), "17": None}
    assert lv.adds_left("1", 4) == 3 and lv.adds_left("2", 4) is None


def test_week_start_dashes_count_as_zero():
    """Haftanın ilk maçından önce Yahoo bütün toplamları "-" gösterir (NaN): birikmiş skor 0, model NaN üretmez."""
    import math

    import numpy as np

    from fdo.inseason.live import has_stats
    from fdo.inseason.weekly import ACC_FIELDS, accumulated_vector

    dashes = {k: math.nan for k in ACC_FIELDS}
    v = accumulated_vector(dashes)
    assert np.isfinite(v).all() and not v.any()
    assert not has_stats(dashes) and not has_stats({"pts": None}) and has_stats({"pts": 0.0})
