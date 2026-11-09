"""Sınırlı ve tekrarlanabilir paket taraması. İnsan kabul ihtimali uydurulmaz.

Üç öneri türü (``SearchOptions.mode``):

* ``mutual`` — karşılıklı fayda: iki takımın da kalan sezon strateji kazancı eşikleri geçer, paket
  piyasa (ROS) değeri dengelidir; ``min_opponent_view > 0`` ise rakibin gözündeki denge (algılanan değer:
  aldığı / verdiği) de eşiği geçmelidir — model kazanç görse de rakibin isimlere bakıp reddedeceği takaslar elenir.
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
    min_opponent_view: float = 0.0          # karşılıklı faydada rakibin gözünde en az denge (0 = kapalı)

    def __post_init__(self):
        if (self.mode not in MODES or self.perceived not in PERCEPTIONS or self.min_perceived_balance < 0
                or self.min_edge < 0 or self.min_opponent_view < 0):
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
    rejected_view: int = 0                   # karşılıklı faydada rakibin gözünde dengesiz
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


def _minimal(found: list[Suggestion]) -> list[Suggestion]:
    """Puana göre sıralı; değer katmayan ek oyuncuyla şişirilmiş takaslar çıkarılır: aynı rakiple daha küçük bir
    paketi zaten listede olan ya da aynı verdiğin paketle sonucu birebir aynı olan (yalnız eklenen değersiz oyuncu
    farklı) takas. Eşit puanda küçük paket önce gelir."""
    ordered = sorted(found, key=lambda x: (-round(x.score, 9), len(x.request.give_a) + len(x.request.give_b)))
    kept: list[Suggestion] = []
    seen: set[tuple] = set()
    for s in ordered:
        r = s.request
        twin = (r.team_b, frozenset(r.give_a), round(s.own_strategy_delta, 6), round(s.other_strategy_delta, 6),
                round(s.own_win_delta, 6), round(s.other_win_delta, 6))
        if twin in seen or any(k.request.team_b == r.team_b and set(k.request.give_a) <= set(r.give_a)
                               and set(k.request.give_b) <= set(r.give_b) for k in kept):
            continue
        seen.add(twin)
        kept.append(s)
    return kept


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
    if mode != "mutual" or options.min_opponent_view > 0:
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
                if options.min_opponent_view > 0:
                    taken = float(perceived.loc[list(give_b)].sum())
                    balance = float(perceived.loc[list(give_a)].sum()) / taken if taken > 0 else 0.0
                    if balance < options.min_opponent_view:
                        result.rejected_view += 1
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
                rosters, _, il = engine.resolve(req, {team_id: strategy, tid: os})
            except TradeError:
                result.rejected_roster += 1
                continue
            _, metrics = engine.score(rosters, team_id, tid, strategy, os, il)
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
            if len(result.suggestions) > options.max_results * 4:
                result.suggestions = _minimal(result.suggestions)[:options.max_results * 2]
        active = remaining
        if progress:
            progress(result.examined, options.max_evaluations)
    result.limit_reached = bool(active) and result.examined >= options.max_evaluations
    result.suggestions = _minimal(result.suggestions)[:options.max_results]
    if not result.suggestions:
        result.message = ("Bu aralıkta iki tarafa da fayda sağlayan ve rakibin gözünde de dengeli görünen takas "
                          "bulunamadı. Eşikler (rakibin gözünde en az denge dahil) ve varsayılan rakip stratejisi "
                          "sonuçları etkiler." if mode == "mutual" else
                          f"Bu aralıkta '{MODES[mode]}' koşullarını sağlayan takas bulunamadı. Yanlış fiyatlama "
                          "eşiğini ya da rakibin gözündeki denge eşiğini gevşetmeyi dene.")
    return result


# ----------------------------------------------------------------- seçili oyunculardan tamamlama
#: Tamamlama önerisinin türü (sıralamada önce gelen): iki taraf da kazanır / yalnız sen / sen kaybedersin.
TIERS = {"mutual": 0, "own": 1, "loss": 2}


@dataclass(frozen=True)
class CompleteOptions:
    """Seçili oyuncular sabit; eklenen oyuncularla paket en çok ``max_side``'a ``max_side`` olur. Tek taraf seçiliyse
    yalnız karşı taraf doldurulur; iki taraf seçiliyse iki tarafa toplam en çok ``max_extra`` oyuncu eklenir
    (dengeleme). Tek oyunculuk eklemelerde bütün kadro, daha büyüklerde taraf başına ``shortlist`` aday taranır."""

    max_side: int = 3
    max_extra: int = 3
    shortlist: int = 10
    max_evaluations: int = 4000
    max_results: int = 12
    min_fairness: float = .55               # değer dengesi (küçük / büyük paket): modelin (ROS) ya da piyasanın
                                            # (algılanan) gözünde, hangisi yüksekse (README §13.30)
    min_view: float = .8                    # rakibin gözünde (algılanan) aldığı / verdiği; 0 = kapalı
    perceived: str = "blend"
    auto_balance: bool = True
    ecw_weight: float = .65

    def __post_init__(self):
        if (not 1 <= self.max_side <= 3 or not 1 <= self.max_extra <= 3 or not 2 <= self.shortlist <= 20
                or self.max_evaluations < 1 or self.max_results < 1 or not 0 <= self.min_fairness <= 1
                or self.min_view < 0 or self.perceived not in PERCEPTIONS or not 0 <= self.ecw_weight <= 1):
            raise ValueError("Geçersiz tamamlama ayarları")


@dataclass
class CompleteResult:
    suggestions: list[Suggestion] = field(default_factory=list)
    current: Suggestion | None = None        # yalnız seçili oyuncularla takas (iki taraf da seçiliyse)
    kind: str = "balance"                    # get: karşılığında ne alırım · give: ne veririm · balance: dengele
    examined: int = 0
    rejected_fairness: int = 0
    rejected_view: int = 0
    rejected_roster: int = 0
    limit_reached: bool = False
    message: str = ""


def _extra_sizes(n_a: int, n_b: int, max_side: int, max_extra: int) -> list[tuple[int, int]]:
    """Eklenecek oyuncu sayıları ``(senden, ondan)``, küçük paketten büyüğe."""
    out = []
    for total in range(1, 2 * max_side + 1):
        for ka in range(total + 1):
            kb = total - ka
            if n_a + ka > max_side or n_b + kb > max_side:
                continue
            if not n_b and (ka or not kb):          # yalnız senin oyuncuların seçili: karşılığı ondan
                continue
            if not n_a and (kb or not ka):          # yalnız onun oyuncuları seçili: karşılığı senden
                continue
            if n_a and n_b and total > max_extra:
                continue
            out.append((ka, kb))
    return out


def _gains(engine: TradeEngine, req: TradeRequest, sa: Strategy, sb: Strategy, w: float):
    rosters, _, il = engine.resolve(req, {req.team_a: sa, req.team_b: sb})
    _, metrics = engine.score(rosters, req.team_a, req.team_b, sa, sb, il)
    m, o = metrics[req.team_a], metrics[req.team_b]
    ga = w * m["strategy_delta"] / 9 + (1 - w) * m["win_delta"]
    gb = w * o["strategy_delta"] / 9 + (1 - w) * o["win_delta"]
    return m, o, ga, gb


def _tiered(req: TradeRequest, m: dict, o: dict, ga: float, gb: float, fair: float, view: float,
            sb: Strategy) -> Suggestion:
    if ga > 0 and gb > 0:
        tier, value = "mutual", (min(ga, gb) + float(np.sqrt(ga * gb))) * (.5 + .5 * fair)
    elif ga > 0:
        tier, value = "own", ga * fair
    else:
        tier, value = "loss", ga
    return Suggestion(req, value, m["strategy_delta"], o["strategy_delta"], m["win_delta"], o["win_delta"], fair, sb,
                      tier, view)


def complete_trade(engine: TradeEngine, team_a: str, team_b: str, give_a: tuple[str, ...], give_b: tuple[str, ...], *,
                   strategy_a: Strategy | None = None, strategy_b: Strategy | None = None,
                   options: CompleteOptions | None = None, analysis_date: dt.date | None = None) -> CompleteResult:
    """Seçili oyuncularla başlayan takası tamamlar ya da dengeler (README §13.27).

    Yalnız senin oyuncuların seçiliyse karşılığında ondan istenebilecekler, yalnız onunkiler seçiliyse senden
    verilebilecekler, iki taraf da seçiliyse iki tarafa oyuncu eklenerek dengeli paketler (ör. 2'ye 1 → 2'ye 2, 3'e 2,
    3'e 3). Eşikler değer dengesi ve rakibin gözündeki dengedir (kabul edilebilirlik). Sıra: iki taraf da kazanır,
    yalnız sen kazanırsın, sen kaybedersin; tür içinde ``suggest_trades``'teki puan. Aynı ya da daha iyi türde daha
    küçük paketi listede olan takas (değer katmayan ek oyuncu) çıkarılır."""
    options = options or CompleteOptions()
    sa, sb = strategy_a or Strategy(), strategy_b or Strategy()
    rosters = engine.league.rosters
    if team_a == team_b or team_a not in engine.team_index or team_b not in engine.team_index:
        raise TradeError("Tamamlama için ligdeki iki farklı takım seçilmeli")
    fixed_a, fixed_b = tuple(dict.fromkeys(give_a)), tuple(dict.fromkeys(give_b))
    if not fixed_a and not fixed_b:
        raise TradeError("Önce en az bir oyuncu seç")
    if not set(fixed_a) <= set(rosters[team_a]) or not set(fixed_b) <= set(rosters[team_b]):
        raise TradeError("Seçilen oyuncu o takımın kadrosunda değil")
    if len(fixed_a) > options.max_side or len(fixed_b) > options.max_side:
        raise TradeError(f"Tamamlama en çok {options.max_side} oyunculu paketlerle çalışır")
    result = CompleteResult(kind="get" if not fixed_b else "give" if not fixed_a else "balance")
    if engine.deadline(analysis_date)[1]:
        result.message = "Lig takas son tarihi geçmiş; öneri üretilmedi."
        return result
    perceived = perceived_prices(engine, options.perceived)
    w, auto = options.ecw_weight, options.auto_balance

    def view(ga_: tuple[str, ...], gb_: tuple[str, ...]) -> float:
        """Rakibin gözünde: aldığı (senin verdiğin) / verdiği algılanan değer."""
        taken = float(perceived.reindex(list(gb_)).fillna(0).sum())
        return float(perceived.reindex(list(ga_)).fillna(0).sum()) / taken if taken > 0 else 0.0

    def balance(req: TradeRequest, v: float) -> float:
        """Değer dengesi: modelin (ROS) ya da piyasanın (algılanan) gözünde, hangisi yüksekse. Piyasanın dengeli
        gördüğü ama modelin bir tarafı üstün bulduğu takaslar (isim değeriyle sat-yüksek) böylece elenmez."""
        return max(engine.fairness(req), min(v, 1 / v) if v > 0 else 0.0)

    if fixed_a and fixed_b:
        req = TradeRequest(team_a, team_b, fixed_a, fixed_b, auto_drop=auto, auto_fill=auto)
        try:
            m, o, ga, gb = _gains(engine, req, sa, sb, w)
            v = view(fixed_a, fixed_b)
            result.current = _tiered(req, m, o, ga, gb, balance(req, v), v, sb)
        except TradeError:
            result.current = None

    def pool(tid: str, fixed: tuple[str, ...], strategy: Strategy, k: int) -> list[str]:
        if k == 1:
            return [p for p in rosters[tid] if p not in fixed and engine.modeled[engine.index[p]]]
        return [p for p in _shortlist(engine, tid, strategy, options.shortlist + len(fixed)) if p not in fixed]

    found: list[Suggestion] = []
    for ka, kb in _extra_sizes(len(fixed_a), len(fixed_b), options.max_side, options.max_extra):
        combos = itertools.product(itertools.combinations(pool(team_a, fixed_a, sa, ka), ka),
                                   itertools.combinations(pool(team_b, fixed_b, sb, kb), kb))
        for extra_a, extra_b in combos:
            if result.examined >= options.max_evaluations:
                result.limit_reached = True
                break
            result.examined += 1
            ga_, gb_ = fixed_a + extra_a, fixed_b + extra_b
            req = TradeRequest(team_a, team_b, ga_, gb_, auto_drop=auto, auto_fill=auto)
            v = view(ga_, gb_)
            fair = balance(req, v)
            if fair < options.min_fairness:
                result.rejected_fairness += 1
                continue
            if options.min_view > 0 and v < options.min_view:
                result.rejected_view += 1
                continue
            try:
                m, o, ga, gb = _gains(engine, req, sa, sb, w)
            except TradeError:
                result.rejected_roster += 1
                continue
            found.append(_tiered(req, m, o, ga, gb, fair, v, sb))
        if result.limit_reached:
            break
    found.sort(key=lambda s: (TIERS[s.mode], -s.score, len(s.request.give_a) + len(s.request.give_b)))
    sets = {id(s): (frozenset(s.request.give_a), frozenset(s.request.give_b)) for s in found}

    def inside(small: Suggestion, big: Suggestion) -> bool:
        (sa_, sb_), (ba, bb) = sets[id(small)], sets[id(big)]
        return small is not big and sa_ <= ba and sb_ <= bb

    def bloated(s: Suggestion) -> bool:
        """Aynı sonucu veren daha küçük paket var: eklenen oyuncu değer katmıyor (ör. otomatik bırakılan)."""
        return any(inside(t, s) and TIERS[t.mode] <= TIERS[s.mode]
                   and abs(t.own_strategy_delta - s.own_strategy_delta) < .01
                   and abs(t.other_strategy_delta - s.other_strategy_delta) < .01 for t in found)

    kept: list[Suggestion] = []
    for s in found:
        if any(inside(k, s) and TIERS[k.mode] <= TIERS[s.mode] for k in kept) or bloated(s):
            continue
        kept.append(s)
        if len(kept) >= options.max_results:
            break
    result.suggestions = kept
    if not kept:
        result.message = (f"Bu seçimle değer dengesi en az %{options.min_fairness * 100:.0f}"
                          + (f" ve rakibin gözünde en az {options.min_view:.2f}" if options.min_view > 0 else "")
                          + " olan bir tamamlama bulunamadı. Başka oyuncu seç ya da eşikleri gevşet.")
    return result
