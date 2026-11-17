"""Korunan oyuncular (README §13.54): öneri, tamamlama ve çok takımlı aramada takasa konmaz."""
from fdo.trade import TradeEngine
from fdo.trade.multi import MultiSearchOptions, suggest_multi
from fdo.trade.suggest import CompleteOptions, SearchOptions, complete_trade, suggest_trades
from unit.test_inseason import data  # noqa: F401


def _ids(s):
    return set(s.request.give_a) | set(s.request.give_b)


def test_suggestions_skip_protected(data):  # noqa: F811
    eng = TradeEngine(data, "L", utilization=1)
    open_ = suggest_trades(eng, "1", options=SearchOptions(min_strategy_gain=0, min_fairness=0, require_reason=False,
                                                           min_perceived_balance=0, max_view=0))
    used = set().union(*(_ids(s) for s in open_.suggestions)) if open_.suggestions else set()
    guard = frozenset(sorted(used)[:3]) or frozenset({"0", "4"})
    got = suggest_trades(eng, "1", options=SearchOptions(min_strategy_gain=0, min_fairness=0, require_reason=False,
                                                         min_perceived_balance=0, max_view=0, protected=guard))
    assert all(not (_ids(s) & guard) for s in got.suggestions)


def test_completion_and_multi_skip_protected(data):  # noqa: F811
    eng = TradeEngine(data, "L", utilization=1)
    guard = frozenset({"5", "6"})
    got = complete_trade(eng, "1", "2", ("0",), (), options=CompleteOptions(min_fairness=0, min_view=0, max_view=0,
                                                                            require_reason=False, protected=guard))
    assert all(not (set(s.request.give_b) & guard) for s in got.suggestions)
    m = suggest_multi(eng, "1", options=MultiSearchOptions(shapes=((1, 1, 1),), min_fairness=0, min_strategy_gain=0,
                                                          protected=guard))
    assert all(not ({p for p, _, _ in s.request.moves} & guard) for s in m.suggestions)
