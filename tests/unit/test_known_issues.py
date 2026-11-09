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
from fdo.trade.suggest import CompleteOptions, complete_trade
from unit.test_trade import trade_data  # noqa: F401  paylaşılan sentetik lig


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="KI-1: tamamlama, karşı tarafın hem modelde hem kendi algısında kaybettiği takası normal öneri "
                          "olarak listeliyor (gerçek vaka: METU IE, Banchero → Giannis, rakibin gözünde 0,82)")
def test_ki1_counterpart_needs_a_reason_to_accept(trade_data):  # noqa: F811
    eng = TradeEngine(trade_data, "L", utilization=1, horizon_weeks=4)
    r = complete_trade(eng, "2", "1", ("3",), (), options=CompleteOptions())
    # Rakip için gerekçe: modelde kazanç ya da kendi gözünde (algılanan değer) en az eşit karşılık.
    unjustified = [s for s in r.suggestions if s.other_strategy_delta < 0 and s.perceived_balance < 1]
    assert not unjustified, [(s.request.give_a, s.request.give_b, round(s.other_strategy_delta, 3),
                              round(s.perceived_balance, 3)) for s in unjustified]


def _players(rows):
    return pd.DataFrame(rows, columns=["player_id", "name", "nba_team"]).set_index("player_id")


def _cbs(name, team):
    return pd.DataFrame([{"name": name, "nba_team": team, "status_text": "Expected to be out until at least Nov 20",
                          "injury": "Knee", "updated": "Sun, Nov 9"}])


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="KI-2: aynı adlı iki oyuncu varken ve takım tutmazken CBS satırı ilk adaya bağlanıyor")
def test_ki2_ambiguous_injury_name_is_not_assigned():
    players = _players([("10", "Jalen Williams", "OKC"), ("11", "Jalen Williams", "DEN")])
    matched = match_players(_cbs("Jalen Williams", "LAL"), players, dt.date(2026, 10, 20))
    assert matched.empty


def test_unique_injury_name_still_matches():
    players = _players([("10", "Jalen Williams", "OKC"), ("12", "Nic Claxton", "BKN")])
    matched = match_players(_cbs("Jalen Williams", "OKC"), players, dt.date(2026, 10, 20))
    assert list(matched.index) == ["10"]


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="KI-3: eşleşmeyen sakatlık satırları sessizce düşüyor; kapsam raporu yok")
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


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="KI-4: aynı gün ikinci senkronizasyon o günün anlık görüntüsünün üzerine yazıyor; ham veri "
                          "değiştirilemez biçimde saklanmıyor")
def test_ki4_same_day_resync_keeps_the_first_capture(tmp_path):
    day = "2026-11-09"
    first, second = b'{"roster_date": "2026-11-09", "v": 1}', b'{"roster_date": "2026-11-09", "v": 2}'
    (tmp_path / "rosters.json").write_bytes(first)
    snapshot(tmp_path, day, overwrite=True)               # ilk senkronizasyonun sonu
    snapshot(tmp_path, day)                               # ikinci senkronizasyon: yazmadan önceki yedek
    (tmp_path / "rosters.json").write_bytes(second)
    snapshot(tmp_path, day, overwrite=True)               # ikinci senkronizasyonun sonu
    assert first in _all_bytes(tmp_path)                  # anlık görüntü düzeninden bağımsız: ilk hâl bir yerde durmalı
