"""Sınırlı ve tekrarlanabilir paket taraması. İnsan kabul ihtimali uydurulmaz.

Üç öneri türü (``SearchOptions.mode``):

* ``mutual`` — karşılıklı fayda: iki takımın da kalan sezon strateji kazancı eşikleri geçer, paket
  piyasa (ROS) değeri dengelidir.
* ``sell_high`` — sat yüksek: verdiğin paketteki bir oyuncu olduğundan iyi görünür (algılanan fiyat −
  ROS değeri ≥ ``min_edge``); rakip, baktığı değere göre takası adil ya da kârlı görür (algılanan denge
  ≥ ``min_perceived_balance``); sen kalan sezonda kazanırsın. Rakibin ROS kazancı şart değildir.
* ``buy_low`` — al düşük: aldığın paketteki bir oyuncu olduğundan kötü görünür (ROS − algılanan ≥
  ``min_edge``); aynı algılanan denge ve senin kazancın şartı.

Algılanan değer ``fdo.trade.perception`` (bu sezon / sezon öncesi / ikisinin ortalaması).
"""

from __future__ import annotations

import datetime as dt
import itertools
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from fdo.trade.engine import TradeEngine, TradeError, TradeRequest
from fdo.trade.perception import PERCEPTIONS, perceived_prices
from fdo.trade.strategy import Strategy

MODES = {"mutual": "Karşılıklı fayda", "sell_high": "Sat yüksek", "buy_low": "Al düşük"}


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
    mode: str = "mutual"
    perceived: str = "blend"
    min_perceived_balance: float = .9
    min_edge: float = 1.0

    def __post_init__(self):
        if (self.mode not in MODES or self.perceived not in PERCEPTIONS or self.min_perceived_balance < 0
                or self.min_edge < 0):
            raise ValueError("Geçersiz öneri türü ya da algılanan değer ayarı")
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
    mode: str = "mutual"
    perceived_balance: float = float("nan")     # rakibin gözünde: aldığı / verdiği algılanan değer
    key_players: tuple[str, ...] = ()            # yanlış fiyatlanan (sat-yüksek / al-düşük) oyuncular


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


def _shortlist(engine: TradeEngine, tid: str, strategy: Strategy, size: int, priority=None) -> list[str]:
    """``priority``: öne alınacak oyuncular (sat-yüksek / al-düşük adayları), sırasıyla."""
    ids = [p for p in engine.league.rosters[tid] if engine.modeled[engine.index[p]]]
    fit = engine._utility(ids, strategy).sort_values(ascending=False, kind="stable")
    market = engine.market.loc[ids].sort_values(ascending=False, kind="stable")
    # Büyük varlıklar, stratejiye uyanlar ve düşük maliyetli tamamlayıcılar birlikte yer alır.
    first = [p for p in (priority or []) if p in set(ids)][: size // 2]
    ordered = list(dict.fromkeys([*first, *fit.index[:size // 2], *market.index[:size // 2],
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
    if engine.deadline(analysis_date)[1]:
        result.message = "Lig takas son tarihi geçmiş; yeni takas önerisi üretilmedi."
        return result
    strategies = opponent_strategies or {}
    mode = options.mode
    perceived = edge = None
    if mode != "mutual":
        perceived = perceived_prices(engine, options.perceived)
        edge = (perceived - engine.market).dropna()
    sell = list(edge[edge >= options.min_edge].sort_values(ascending=False).index) if mode == "sell_high" else []
    buy = list(edge[edge <= -options.min_edge].sort_values().index) if mode == "buy_low" else []
    own = _shortlist(engine, team_id, strategy, options.shortlist, sell)
    generators = []
    for tid in others:
        os = strategies.get(tid, Strategy())
        other = _shortlist(engine, tid, os, options.shortlist, buy)
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
            balance, keys = float("nan"), ()
            if mode == "mutual":
                if fair < options.min_fairness:
                    result.rejected_fairness += 1
                    continue
            else:
                given = float(perceived.loc[list(give_a)].sum())
                taken = float(perceived.loc[list(give_b)].sum())
                balance = given / taken if taken > 0 else 0.0
                if balance < options.min_perceived_balance:
                    result.rejected_fairness += 1
                    continue
                side = give_a if mode == "sell_high" else give_b
                sign = 1.0 if mode == "sell_high" else -1.0
                keys = tuple(p for p in side if sign * float(edge.get(p, 0.0)) >= options.min_edge)
                if not keys:
                    continue
            try:
                rosters, _, _ = engine.resolve(req, {team_id: strategy, tid: os})
            except TradeError:
                result.rejected_roster += 1
                continue
            _, metrics = engine.score(rosters, team_id, tid, strategy, os)
            m, o = metrics[team_id], metrics[tid]
            # sat-yüksek / al-düşük: rakibin kalan sezonda kazanması şart değil (kendi gözünde adil)
            sides = (m, o) if mode == "mutual" else (m,)
            if (min(x["strategy_delta"] for x in sides) < options.min_strategy_gain
                    or min(x["win_delta"] for x in sides) < options.min_win_gain):
                continue
            result.eligible += 1
            w = options.ecw_weight
            ga = w * m["strategy_delta"] / 9 + (1 - w) * m["win_delta"]
            gb = w * o["strategy_delta"] / 9 + (1 - w) * o["win_delta"]
            if mode == "mutual":
                if min(ga, gb) <= 0:
                    continue
                value = (min(ga, gb) + float(np.sqrt(ga * gb))) * (.5 + .5 * fair)
            else:
                if ga <= 0:
                    continue
                value = ga * min(1.0, balance)
            result.suggestions.append(Suggestion(req, value, m["strategy_delta"], o["strategy_delta"],
                                                  m["win_delta"], o["win_delta"], fair, os, mode, balance, keys))
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
        result.message = ("Bu aralıkta iki tarafa da fayda sağlayan takas bulunamadı. Eşikler ve varsayılan rakip "
                          "stratejisi sonuçları etkiler." if mode == "mutual" else
                          f"Bu aralıkta '{MODES[mode]}' koşullarını sağlayan takas bulunamadı. Yanlış fiyatlama "
                          "eşiğini ya da rakibin gözündeki denge eşiğini gevşetmeyi dene.")
    return result
