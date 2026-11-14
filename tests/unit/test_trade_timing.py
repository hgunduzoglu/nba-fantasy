"""Takas puanının zamanlaması: kalan sezon dönemleri, dönem vektörleri ve dönem ağırlıklı olasılıklar."""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from fdo.inseason.injuries import apply_injuries
from fdo.inseason.weeks import league_weeks, trade_segments
from fdo.trade import TradeEngine, TradeRequest
from fdo.trade.engine import Segment
from unit.test_inseason import data  # noqa: F401  paylaşılan sentetik lig

EARLY = Segment(dt.date(2026, 10, 31), dt.date(2026, 11, 4), 5 / 7, "erken")
LATE = Segment(dt.date(2026, 11, 5), dt.date(2027, 4, 11), 158 / 7, "geç")


def _late_return(data, pid="1", day=dt.date(2026, 11, 6)):  # noqa: F811
    return apply_injuries(data, pd.DataFrame([{"player_id": pid, "kind": "out_until", "return_date": day}])
                          .set_index("player_id"))


def test_one_segment_or_none_keeps_the_untimed_engine(data):  # noqa: F811
    plain = TradeEngine(data, "L", utilization=1)
    one = TradeEngine(data, "L", utilization=1, segments=(EARLY,))
    assert not plain.timed and not one.timed and one.seg_vecs is None
    np.testing.assert_allclose(one.baseline_p, plain.baseline_p)


def test_segment_vectors_split_the_season_by_games_after_return(data):  # noqa: F811
    d = _late_return(data)
    eng = TradeEngine(d, "L", utilization=1, segments=(EARLY, LATE))
    assert eng.timed
    weeks = np.array([EARLY.weeks, LATE.weeks])
    total = np.tensordot(weeks, eng.seg_vecs, axes=1)                                # dönemlerin toplam üretimi
    ok = eng.modeled
    np.testing.assert_allclose(total[ok], eng.vecs[ok] * eng.horizon_weeks)          # hiçbir şey kaybolmaz
    i = eng.index["1"]
    assert np.all(eng.seg_vecs[0, i] == 0) and eng.seg_vecs[1, i, 0] > 0               # 6 Kasım'da dönen: erken 0
    j = eng.index["0"]                                                                 # sağlam: iki dönemde de oynar
    assert eng.seg_vecs[0, j, 0] > 0 and eng.seg_vecs[1, j, 0] > 0


def test_timed_scores_are_zero_for_no_change_and_weight_the_segments(data):  # noqa: F811
    d = _late_return(data)
    eng = TradeEngine(d, "L", utilization=1, segments=(EARLY, LATE))
    from fdo.trade.strategy import Strategy
    s = {"1": Strategy(), "2": Strategy()}
    _, m = eng.score_many(eng.league.rosters, s)
    assert all(abs(x["ecw_delta"]) < 1e-12 and abs(x["win_delta"]) < 1e-12 for x in m.values())
    r = eng.analyze(TradeRequest("1", "2", ("1",), ("4",)))
    assert np.isfinite(r.metrics.loc["1", "ecw_delta"]) and np.isnan(np.diag(r.matchup_after)).all()
    # puan dönemlerin ağırlıklı ortalaması: elle hesapla
    p, p5 = eng._probs(eng.baseline_seg)
    w = np.array([EARLY.weight, LATE.weight]) / (EARLY.weight + LATE.weight)
    from fdo.matchup.ecw import ecw_matrix
    manual = w[0] * ecw_matrix(eng.baseline_seg[0], eng.config) + w[1] * ecw_matrix(eng.baseline_seg[1], eng.config)
    np.testing.assert_allclose(p, manual)
    rows = eng._probs(eng.baseline_seg, rows=[0])[1]
    np.testing.assert_allclose(rows[0], p5[0]) and np.isnan(rows[1]).all()


def test_late_returner_is_worth_less_when_the_season_is_timed(data):  # noqa: F811
    # 1. takım geç dönen 1'i verip 4'ü alır: zamanlı puanda erken dönemde 1'in katkısı yok
    d = _late_return(data, day=dt.date(2027, 3, 1))
    plain = TradeEngine(d, "L", utilization=1)
    timed = TradeEngine(d, "L", utilization=1, segments=(EARLY, LATE))
    req = TradeRequest("2", "1", ("4",), ("1",))                                      # 2. takım geç döneni alır
    gain = lambda e: e.analyze(req).metrics.loc["2", "ecw_delta"]
    assert gain(timed) != pytest.approx(gain(plain))


def test_trade_segments_follow_the_league_weeks(data):  # noqa: F811
    lg = data.leagues["L"]
    weeks = league_weeks(data.schedule, lg.settings, lg.config)
    seg = trade_segments(weeks, data.as_of)
    assert seg[0].start == data.as_of and all(a.end < b.start for a, b in zip(seg, seg[1:]))
    po = [s for s in seg if "playoff" in s.label]
    assert len(po) == len(weeks.playoff_weeks) and seg[-1].end == weeks.weeks["end"].max()
    assert sum(s.weight for s in seg) == pytest.approx(((seg[-1].end - data.as_of).days + 1) / 7)
    blocks = trade_segments(weeks, data.as_of, block=4, playoff_weight=2.0)
    assert len(blocks) < len(seg) and [s for s in blocks if "playoff" in s.label][0].weight == pytest.approx(
        2 * sum(s.weight for s in po))
