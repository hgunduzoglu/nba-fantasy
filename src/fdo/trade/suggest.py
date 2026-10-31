"""Sınırlı ve tekrarlanabilir paket taraması. İnsan kabul ihtimali uydurulmaz."""

from __future__ import annotations

import datetime as dt
import itertools
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from fdo.trade.engine import TradeEngine, TradeError, TradeRequest
from fdo.trade.strategy import Strategy


@dataclass(frozen=True)
class SearchOptions:
    package_sizes: tuple[tuple[int, int], ...] = ((1, 1), (2, 1), (1, 2), (2, 2))
    shortlist: int = 8
    max_evaluations: int = 8000
    max_results: int = 20
    min_fairness: float = .55
    min_strategy_gain: float = .005
    min_win_gain: float = 0.0
    auto_balance: bool = True
    ecw_weight: float = .65

    def __post_init__(self):
        if (not self.package_sizes or any(a not in (1, 2, 3) or b not in (1, 2, 3) for a, b in self.package_sizes)
                or not 2 <= self.shortlist <= 20 or self.max_evaluations < 1 or self.max_results < 1
                or not 0 <= self.min_fairness <= 1 or not 0 <= self.ecw_weight <= 1
                or self.min_strategy_gain < 0 or not -1 <= self.min_win_gain <= 1):
            raise ValueError("Geçersiz öneri arama ayarları")


@dataclass
class Suggestion:
    request: TradeRequest
    score: float
    own_strategy_delta: float
    other_strategy_delta: float
    own_win_delta: float
    other_win_delta: float
    fairness: float
    other_strategy: Strategy


@dataclass
class SearchResult:
    suggestions: list[Suggestion] = field(default_factory=list)
    examined: int = 0
    eligible: int = 0
    rejected_fairness: int = 0
    rejected_roster: int = 0
    limit_reached: bool = False
    opponent_counts: dict[str, int] = field(default_factory=dict)
    message: str = ""


def _shortlist(engine: TradeEngine, tid: str, strategy: Strategy, size: int) -> list[str]:
    ids = [p for p in engine.league.rosters[tid] if engine.modeled[engine.index[p]]]
    fit = engine._utility(ids, strategy).sort_values(ascending=False, kind="stable")
    market = engine.market.loc[ids].sort_values(ascending=False, kind="stable")
    # Büyük varlıklar, stratejiye uyanlar ve düşük maliyetli tamamlayıcılar birlikte yer alır.
    ordered = list(dict.fromkeys([*fit.index[:size // 2], *market.index[:size // 2],
                                  *fit.index[-2:], *fit.index]))
    return ordered[:size]


def suggest_trades(engine: TradeEngine, team_id: str, *, strategy: Strategy | None = None,
                   opponent_strategies: dict[str, Strategy] | None = None,
                   opponents: tuple[str, ...] | None = None, options: SearchOptions | None = None,
                   analysis_date: dt.date | None = None,
                   progress: Callable[[int, int], None] | None = None) -> SearchResult:
    options, strategy = options or SearchOptions(), strategy or Strategy()
    if team_id not in engine.team_index:
        raise TradeError("Takım bu ligde yok")
    others = tuple(t for t in (opponents or engine.team_ids) if t != team_id)
    if any(t not in engine.team_index for t in others):
        raise TradeError("Rakip bu ligde yok")
    result = SearchResult(opponent_counts=dict.fromkeys(others, 0))
    deadline = engine.league.settings.get("Trade End Date", "")
    if deadline:
        try:
            expired = (analysis_date or engine.data.as_of) > dt.datetime.strptime(deadline, "%B %d, %Y").date()
        except ValueError:
            expired = False
        if expired:
            result.message = "Lig takas son tarihi geçmiş; yeni takas önerisi üretilmedi."
            return result
    strategies = opponent_strategies or {}
    own = _shortlist(engine, team_id, strategy, options.shortlist)
    generators = []
    for tid in others:
        os = strategies.get(tid, Strategy())
        other = _shortlist(engine, tid, os, options.shortlist)
        for a, b in options.package_sizes:
            aa = [p for p in engine.league.rosters[team_id] if engine.modeled[engine.index[p]]] if a == b == 1 else own
            bb = [p for p in engine.league.rosters[tid] if engine.modeled[engine.index[p]]] if a == b == 1 else other
            combos = itertools.product(itertools.combinations(aa, a), itertools.combinations(bb, b))
            generators.append((tid, os, iter(combos)))
    # Rakip ve paket türleri sırayla taranır; bütçe ilk birkaç rakipte tüketilmez.
    active = generators
    while active and result.examined < options.max_evaluations:
        remaining = []
        for tid, os, gen in active:
            if result.examined >= options.max_evaluations:
                remaining.append((tid, os, gen))
                continue
            pair = next(gen, None)
            if pair is None:
                continue
            remaining.append((tid, os, gen))
            give_a, give_b = pair
            result.examined += 1
            result.opponent_counts[tid] += 1
            req = TradeRequest(team_id, tid, give_a, give_b,
                               auto_drop=options.auto_balance, auto_fill=options.auto_balance)
            fair = engine.fairness(req)
            if fair < options.min_fairness:
                result.rejected_fairness += 1
                continue
            try:
                rosters, _, _ = engine.resolve(req, {team_id: strategy, tid: os})
            except TradeError:
                result.rejected_roster += 1
                continue
            _, metrics = engine.score(rosters, team_id, tid, strategy, os)
            m, o = metrics[team_id], metrics[tid]
            if (min(m["strategy_delta"], o["strategy_delta"]) < options.min_strategy_gain
                    or min(m["win_delta"], o["win_delta"]) < options.min_win_gain):
                continue
            result.eligible += 1
            w = options.ecw_weight
            ga = w * m["strategy_delta"] / 9 + (1 - w) * m["win_delta"]
            gb = w * o["strategy_delta"] / 9 + (1 - w) * o["win_delta"]
            if min(ga, gb) <= 0:
                continue
            value = (min(ga, gb) + float(np.sqrt(ga * gb))) * (.5 + .5 * fair)
            result.suggestions.append(Suggestion(req, value, m["strategy_delta"], o["strategy_delta"],
                                                  m["win_delta"], o["win_delta"], fair, os))
            if len(result.suggestions) > options.max_results * 3:
                result.suggestions.sort(key=lambda x: x.score, reverse=True)
                result.suggestions = result.suggestions[:options.max_results]
        active = remaining
        if progress:
            progress(result.examined, options.max_evaluations)
    result.limit_reached = bool(active) and result.examined >= options.max_evaluations
    result.suggestions.sort(key=lambda x: x.score, reverse=True)
    result.suggestions = result.suggestions[:options.max_results]
    if not result.suggestions:
        result.message = "Bu aralıkta iki tarafa da fayda sağlayan takas bulunamadı. Eşikler ve varsayılan rakip stratejisi sonuçları etkiler."
    return result
