"""Bilinen sorunlar: doğrulanmış hatalar, tekrar üretilebilir sentetik vakalar (KI-n).

Her vaka beklenen doğru davranışı yazar. Hata düzeltilmemişken ``xfail(strict=True)``: hata giderilince test
geçer, strict xfail bunu "XPASS" olarak bildirir ve işaret kaldırılmak zorunda kalır. Vakalar sentetiktir; gerçek
lig performansının kanıtı değildir, yalnızca hatanın mekanizmasını sabitler.
"""
import datetime as dt
from pathlib import Path

import pandas as pd
import pytest

from fdo.ingest.yahoo_sync import snapshot
from fdo.inseason.injuries import match_players
from fdo.trade import TradeEngine
from fdo.trade.suggest import PERCEIVED_EVEN, CompleteOptions, complete_trade
from unit.test_trade import trade_data  # noqa: F401  paylaşılan sentetik lig


def test_ki1_counterpart_needs_a_reason_to_accept(trade_data):  # noqa: F811
    eng = TradeEngine(trade_data, "L", utilization=1, horizon_weeks=4)
    r = complete_trade(eng, "2", "1", ("3",), (), options=CompleteOptions())
    # Rakip için gerekçe: modelde kazanç ya da kendi gözünde (algılanan değer) en az eşit karşılık.
    unjustified = [s for s in r.suggestions if s.other_strategy_delta < 0 and s.perceived_balance < PERCEIVED_EVEN]
    assert not unjustified, [(s.request.give_a, s.request.give_b, round(s.other_strategy_delta, 3),
                              round(s.perceived_balance, 3)) for s in unjustified]


def _players(rows):
    return pd.DataFrame(rows, columns=["player_id", "name", "nba_team"]).set_index("player_id")


def _cbs(name, team):
    return pd.DataFrame([{"name": name, "nba_team": team, "status_text": "Expected to be out until at least Nov 20",
                          "injury": "Knee", "updated": "Sun, Nov 9"}])


def test_ki2_ambiguous_injury_name_is_not_assigned():
    players = _players([("10", "Jalen Williams", "OKC"), ("11", "Jalen Williams", "DEN")])
    matched = match_players(_cbs("Jalen Williams", "LAL"), players, dt.date(2026, 10, 20))
    assert matched.empty


def test_unique_injury_name_still_matches():
    players = _players([("10", "Jalen Williams", "OKC"), ("12", "Nic Claxton", "BKN")])
    matched = match_players(_cbs("Jalen Williams", "OKC"), players, dt.date(2026, 10, 20))
    assert list(matched.index) == ["10"]


def test_ki3_unmatched_injury_rows_are_reported(tmp_path, trade_data):  # noqa: F811
    from fdo.inseason.injuries import with_injuries

    pd.concat([_cbs("P1", "SYN"), _cbs("Nobody Known", "SYN")]).to_csv(tmp_path / "injuries_cbs_2026-10-31.csv",
                                                                        index=False)
    out = with_injuries(trade_data, tmp_path)
    assert any("eşleşmeyen" in note and "Nobody Known" in note for note in out.issues), out.issues


def _all_bytes(root: Path) -> list[bytes]:
    import gzip

    out = []
    for p in root.rglob("*"):
        if p.is_file():
            raw = p.read_bytes()
            out.append(gzip.decompress(raw) if p.suffix == ".gz" else raw)
    return out


def test_ki4_same_day_resync_keeps_the_first_capture(tmp_path):
    day = "2026-11-09"
    first, second = b'{"roster_date": "2026-11-09", "v": 1}', b'{"roster_date": "2026-11-09", "v": 2}'
    (tmp_path / "rosters.json").write_bytes(first)
    snapshot(tmp_path, day)                               # ilk senkronizasyonun sonu
    snapshot(tmp_path, day)                               # ikinci senkronizasyon: yazmadan önceki yedek
    (tmp_path / "rosters.json").write_bytes(second)
    snapshot(tmp_path, day)                               # ikinci senkronizasyonun sonu
    assert first in _all_bytes(tmp_path)                  # anlık görüntü düzeninden bağımsız: ilk hâl bir yerde durmalı


def test_ki6_two_teams_do_not_take_the_same_free_agent(trade_data):  # noqa: F811
    import dataclasses

    from fdo.trade.strategy import Strategy

    lg = trade_data.leagues["L"]
    rosters = {**lg.rosters, "1": lg.rosters["1"][:2], "2": lg.rosters["2"][:2]}   # ikisinde de boş aktif yer
    trade_data.leagues["L"] = dataclasses.replace(lg, rosters=rosters)
    eng = TradeEngine(trade_data, "L", utilization=1, horizon_weeks=4)
    s = Strategy()
    alone = [{f for _, f in eng.waiver_best(rosters[t], frozenset(), s)[1]} for t in ("1", "2")]
    assert alone[0] & alone[1]                                       # bağımsız çözümde aynı oyuncu ikisine gider
    joint = eng.joint_waiver([("1", rosters["1"], frozenset(), s), ("2", rosters["2"], frozenset(), s)])
    assert not {f for _, f in joint["1"][1]} & {f for _, f in joint["2"][1]}
    assert {f for _, f in joint["1"][1]} == alone[0]                 # takası öneren takım önce
    _, m = eng.score_many(dict(rosters), {"1": s, "2": s})           # kadro değişmedi: fark sıfır
    assert abs(m["1"]["ecw_delta"]) < 1e-12 and abs(m["2"]["ecw_delta"]) < 1e-12
