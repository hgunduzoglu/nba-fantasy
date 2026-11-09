"""Takas ekranındaki seçimi tamamlama/dengeleme (README §13.27): sabit oyuncular korunur, eşikler uygulanır."""
import pytest

from fdo.trade.engine import TradeEngine, TradeError
from fdo.trade.suggest import CompleteOptions, _extra_sizes, complete_trade
from unit.test_inseason import data  # noqa: F401  paylaşılan sentetik lig
from unit.test_trade import trade_data  # noqa: F401  ikinci sentetik lig (KI-1 vakası)

OPEN = CompleteOptions(min_fairness=0.0, min_view=0.0)


@pytest.fixture
def eng(data):  # noqa: F811
    return TradeEngine(data, "L", utilization=1)


def test_extra_sizes_fill_the_empty_side_or_balance_both():
    assert _extra_sizes(1, 0, 3, 3) == [(0, 1), (0, 2), (0, 3)]               # verdiğin karşılığı: yalnız ondan
    assert _extra_sizes(0, 2, 3, 3) == [(1, 0), (2, 0), (3, 0)]               # aldığın karşılığı: yalnız senden
    two_one = _extra_sizes(2, 1, 3, 3)
    assert (0, 1) in two_one and (1, 1) in two_one and (1, 2) in two_one       # 2-2, 3-2, 3-3
    assert all(2 + a <= 3 and 1 + b <= 3 for a, b in two_one)
    assert _extra_sizes(1, 1, 3, 1) == [(0, 1), (1, 0)]                       # en çok bir ekleme


def test_complete_keeps_selection_and_fills_other_side(eng):
    r = complete_trade(eng, "1", "2", ("0",), (), options=OPEN)
    assert r.kind == "get" and r.current is None and r.examined > 0 and r.suggestions
    for s in r.suggestions:
        assert s.request.give_a == ("0",) and 1 <= len(s.request.give_b) <= 3
        assert set(s.request.give_b) <= set(eng.league.rosters["2"]) and s.mode in ("mutual", "own", "loss")
    order = [{"mutual": 0, "own": 1, "loss": 2}[s.mode] for s in r.suggestions]
    assert order == sorted(order)
    g = complete_trade(eng, "1", "2", (), ("4",), options=OPEN)
    assert g.kind == "give" and all(s.request.give_b == ("4",) and s.request.give_a for s in g.suggestions)


def test_balance_adds_to_both_sides_and_respects_thresholds(eng):
    r = complete_trade(eng, "1", "2", ("0", "1"), ("4",), options=OPEN)
    assert r.kind == "balance" and r.current is not None
    for s in r.suggestions:
        q = s.request
        assert {"0", "1"} <= set(q.give_a) and "4" in q.give_b and len(q.give_a) <= 3 and len(q.give_b) <= 3
        assert len(q.give_a) + len(q.give_b) > 3                               # en az bir oyuncu eklendi
    strict = complete_trade(eng, "1", "2", ("0", "1"), ("4",), options=CompleteOptions(min_fairness=0.8, min_view=0.0))
    assert all(s.fairness >= 0.8 for s in strict.suggestions)
    assert strict.suggestions or strict.message


def test_complete_rejects_bad_selection(eng):
    with pytest.raises(TradeError):
        complete_trade(eng, "1", "2", (), ())
    with pytest.raises(TradeError):
        complete_trade(eng, "1", "2", ("4",), ())                              # oyuncu kendi kadronda değil
    with pytest.raises(TradeError):
        complete_trade(eng, "1", "1", ("0",), ())


def test_counterpart_levels_name_both_reasons():
    from fdo.trade.suggest import counterpart

    assert counterpart(.1, .3, 1.05) == ("high", ("modelde kazanıyor (+0.30 kategori/hafta)",
                                                  "kendi gözünde aşağı yukarı eşit ya da fazla alıyor (1.05)"))
    assert counterpart(-.1, -.2, .96)[0] == "medium" and counterpart(.1, .2, .8)[0] == "medium"
    level, why = counterpart(-.1, -.49, .82)
    assert level == "low" and why[0].startswith("modelde kaybediyor") and "daha az" in why[1]
    assert counterpart(.1, .2, float("nan")) == ("medium", ("modelde kazanıyor (+0.20 kategori/hafta)",))


def test_unjustified_packages_are_counted_and_can_be_shown(trade_data):  # noqa: F811
    eng = TradeEngine(trade_data, "L", utilization=1, horizon_weeks=4)
    strict = complete_trade(eng, "2", "1", ("3",), ())
    loose = complete_trade(eng, "2", "1", ("3",), (), options=CompleteOptions(require_reason=False))
    assert strict.rejected_reason > 0 and loose.rejected_reason == 0
    assert all(s.acceptability in ("high", "medium") and s.counterpart_reasons for s in strict.suggestions)
    low = [s for s in loose.suggestions if s.acceptability == "low"]
    assert low and {s.request.give_b for s in low}.isdisjoint({s.request.give_b for s in strict.suggestions})


def test_overpay_in_the_market_is_not_listed(trade_data):  # noqa: F811
    eng = TradeEngine(trade_data, "L", utilization=1, horizon_weeks=4)
    loose = complete_trade(eng, "1", "2", ("0",), (), options=CompleteOptions(max_view=0, require_reason=False))
    strict = complete_trade(eng, "1", "2", ("0",), (), options=CompleteOptions(require_reason=False))
    assert any(s.perceived_balance > 1.25 for s in loose.suggestions)          # rakip bunları çok ucuza alırdı
    assert strict.rejected_overpay > 0 and all(s.perceived_balance <= 1.25 for s in strict.suggestions)
