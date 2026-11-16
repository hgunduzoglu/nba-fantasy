"""Finalist önerilerini günlük kadroyla yeniden sıralama.

Hızlı takas puanı (``TradeEngine.score_many``) sezonluk ortalama kategori olasılığıdır; pozisyon ve maç çakışması
yüzünden bench'te kalan maçları görmez. Arama bittikten sonra finalistler kalan normal sezon haftalarında haftalık
modelin günlük kadro atamasıyla (``SeasonSim.lineup_profile``, simülasyon yok) yeniden ölçülür ve bu farka göre
sıralanır. Kadrolar, bedava hamleler ve alım hakkı sezon simülasyonuyla aynıdır. İki takımlı öneri, tamamlama ve çok
takımlı öneri aynı ölçüyü kullanır.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TypeVar

import numpy as np

from fdo.inseason.season import SeasonSim
from fdo.trade import Strategy, TradeError
from fdo.trade.engine import RosterInvariantError, TradeEngine
from fdo.trade.multi import MultiSuggestion, resolve_multi
from fdo.trade.suggest import Suggestion, counterpart

T = TypeVar("T")


@dataclass(frozen=True)
class LineupDelta:
    """Takımın kalan normal sezonda rakip başına haftalık kategori farkı, günlük kadroyla."""
    strategy: float     # takımın stratejisinin ağırlıklarıyla (``strategy_delta`` ile aynı ölçek; sıralama ölçüsü)
    ecw: float          # ağırlıksız (``SeasonResult.ecw`` farkı)
    teams: dict[str, float] = field(default_factory=dict)


class LineupMeter:
    """``team``'in günlük kadro farkını ölçer. Takassız taban, takastaki takımlar ve stratejileri başına bir kez
    hesaplanır (waiver sırası takaslı koşuyla aynı olmalı)."""

    def __init__(self, sim: SeasonSim, team: str, weeks: tuple[int, ...] | None = None):
        self.sim, self.team, self.weeks = sim, team, weeks
        self.i = sim.tix[team]
        self._bases: dict[tuple, np.ndarray | None] = {}

    def measure(self, first: tuple[str, ...], strategies: dict[str, Strategy],
                resolve: Callable[[], tuple[dict, dict]]) -> LineupDelta | None:
        """``resolve``: takas sonrası ``(kadrolar, IL)``. Çözülemeyen ya da kalan haftası olmayan takas ``None``."""
        key = tuple((t, strategies[t]) for t in first)
        try:
            if key not in self._bases:
                self._bases[key] = self.sim.lineup_profile(first=first, strategies=strategies, weeks=self.weeks)
            rosters, il = resolve()
            after = self.sim.lineup_profile(rosters, injuries=il, first=first, strategies=strategies, weeks=self.weeks)
        except (TradeError, ValueError, RosterInvariantError):
            return None
        base = self._bases[key]
        if after is None or base is None:
            return None
        diff = after - base
        d = diff[self.i]
        teams = {t: float(diff[self.sim.tix[t]] @ strategies[t].normalized * 9) for t in first}
        return LineupDelta(teams[self.team], float(d.sum()), teams)


def final_decision(s: Suggestion, delta: LineupDelta | None, requested: bool) -> dict:
    """Authoritative classification, using the same final method for both teams."""
    if delta is None:
        fast_tier = s.mode if s.mode in ("mutual", "own", "loss") else (
            "loss" if s.own_strategy_delta <= 1e-8 else "mutual" if s.other_strategy_delta > 1e-8 else "own")
        return {"decision": "unmeasured" if requested else fast_tier,
                "evaluation_method": "fast_fallback" if requested else "fast",
                "acceptability": s.acceptability,
                "counterpart_reasons": [f"Hızlı model: {r}" for r in s.counterpart_reasons]}
    other = delta.teams.get(s.request.team_b)
    if other is None:
        return {"decision": "unmeasured", "evaluation_method": "fast_fallback",
                "acceptability": "low", "counterpart_reasons": ["Rakibin günlük kadro faydası ölçülemedi."]}
    tier = "loss" if delta.strategy <= 1e-8 else "mutual" if other > 1e-8 else "own"
    level, reasons = counterpart(other, other, s.perceived_balance)
    return {"decision": tier, "evaluation_method": "lineup", "acceptability": level,
            "counterpart_reasons": [f"Günlük kadro: {r}" for r in reasons], "other_lineup_delta": other,
            "own_lineup_delta": delta.strategy}


def ranked_method(deltas: Sequence[LineupDelta | None], requested: bool, fallback: str) -> str:
    if not requested:
        return fallback
    if not deltas or not any(d is not None for d in deltas):
        return "fast_fallback"
    return "lineup" if all(d is not None for d in deltas) else "lineup_partial"


def final_rejection(s: Suggestion, decision: dict, *, mode: str, require_reason: bool,
                    min_gain: float = 0.0, inspect_losses: bool = False) -> str | None:
    """Apply eligibility to the final measurements, independently of search ranking.

    Completion may expose explicitly labelled loss scenarios; ordinary mutual,
    sell-high and buy-low recommendations must still benefit the user.
    """
    own = decision.get("own_lineup_delta", s.own_strategy_delta)
    other = decision.get("other_lineup_delta", s.other_strategy_delta)
    if not np.isfinite(own) or (not inspect_losses and (own <= 1e-8 or own < min_gain)):
        return "gain"
    if mode == "mutual" and (not np.isfinite(other) or other <= 1e-8 or other < min_gain):
        return "mode"
    if require_reason and decision["acceptability"] == "low":
        return "reason"
    return None


def executable_plans(engine: TradeEngine, rosters: dict, injuries: dict, strategies: dict):
    """Validate the same immediate acquisition queue used for final scoring.

    Optional next-week actions stay conditional. Required FA additions cannot be
    deferred into that queue and still be presented as executable today.
    """
    plans = engine.waiver_plans(rosters, strategies, injuries)
    engine.check_rosters("son işlem planı", {t: (rosters[t], injuries[t]) for t in strategies},
                         {t: (p.week_roster, p.il) for t, p in plans.items()}, rosters)
    for t, p in plans.items():
        immediate = [f for _, f in p.moves[:p.now]]
        required = set(rosters[t]) - engine._owned
        if (not required <= set(immediate) or len(immediate) > engine.budget(t).remaining
                or any(engine.available_from.get(f, engine.data.as_of) > engine.data.as_of for f in immediate)):
            raise TradeError("Son işlem planı bu haftanın alım hakkı veya waiver koşullarını aşamaz")
    return plans


def lineup_deltas(sim: SeasonSim, engine: TradeEngine, team: str, strategy: Strategy,
                  suggestions: Sequence[Suggestion]) -> list[LineupDelta | None]:
    """İki takımlı öneriler (``suggest_trades``, ``complete_trade``): ``team`` takasın ``team_a``'sıdır."""
    meter = LineupMeter(sim, team)
    out = []
    for s in suggestions:
        r = s.request
        pair = {team: strategy, r.team_b: s.other_strategy}
        out.append(meter.measure((team, r.team_b), pair, lambda r=r, pair=pair: _pick2(engine.resolve(r, pair))))
    return out


def multi_lineup_deltas(sim: SeasonSim, engine: TradeEngine, team: str,
                        suggestions: Sequence[MultiSuggestion]) -> list[LineupDelta | None]:
    """Çok takımlı öneriler (``suggest_multi``): her önerinin kendi takım stratejileriyle."""
    meter = LineupMeter(sim, team)
    out = []
    for s in suggestions:
        req, st = s.request, s.strategies
        out.append(meter.measure(tuple(req.teams), st, lambda req=req, st=st: _pick2(resolve_multi(engine, req, st))))
    return out


def _pick2(resolved: tuple) -> tuple[dict, dict]:
    rosters, _, il = resolved
    return rosters, il


def rerank(suggestions: Sequence[T], deltas: Sequence[LineupDelta | None],
           limit: int | None = None) -> tuple[list[T], list[LineupDelta | None]]:
    """Günlük kadro farkına göre büyükten küçüğe; ölçülemeyenler sona, kendi aralarında gelen sırayla."""
    order = sorted(range(len(suggestions)),
                   key=lambda k: (deltas[k] is None, -(deltas[k].strategy if deltas[k] else 0.0), k))[:limit]
    return [suggestions[k] for k in order], [deltas[k] for k in order]
