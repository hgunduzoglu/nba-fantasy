"""Finalist önerilerini günlük kadroyla yeniden sıralama.

Hızlı takas puanı (``TradeEngine.score_many``) sezonluk ortalama kategori olasılığıdır; pozisyon ve maç çakışması
yüzünden bench'te kalan maçları görmez. Arama bittikten sonra finalistler kalan normal sezon haftalarında haftalık
modelin günlük kadro atamasıyla (``SeasonSim.lineup_profile``, simülasyon yok) yeniden ölçülür ve bu farka göre
sıralanır. Kadrolar, bedava hamleler ve alım hakkı sezon simülasyonuyla aynıdır. İki takımlı öneri, tamamlama ve çok
takımlı öneri aynı ölçüyü kullanır.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TypeVar

import numpy as np

from fdo.inseason.season import SeasonSim
from fdo.trade import Strategy, TradeError
from fdo.trade.engine import RosterInvariantError, TradeEngine
from fdo.trade.multi import MultiSuggestion, resolve_multi
from fdo.trade.suggest import Suggestion

T = TypeVar("T")


@dataclass(frozen=True)
class LineupDelta:
    """Takımın kalan normal sezonda rakip başına haftalık kategori farkı, günlük kadroyla."""
    strategy: float     # takımın stratejisinin ağırlıklarıyla (``strategy_delta`` ile aynı ölçek; sıralama ölçüsü)
    ecw: float          # ağırlıksız (``SeasonResult.ecw`` farkı)


class LineupMeter:
    """``team``'in günlük kadro farkını ölçer. Takassız taban, takastaki takımlar ve stratejileri başına bir kez
    hesaplanır (waiver sırası takaslı koşuyla aynı olmalı)."""

    def __init__(self, sim: SeasonSim, team: str):
        self.sim, self.team = sim, team
        self.i = sim.tix[team]
        self._bases: dict[tuple, np.ndarray | None] = {}

    def measure(self, first: tuple[str, ...], strategies: dict[str, Strategy],
                resolve: Callable[[], tuple[dict, dict]]) -> LineupDelta | None:
        """``resolve``: takas sonrası ``(kadrolar, IL)``. Çözülemeyen ya da kalan haftası olmayan takas ``None``."""
        key = tuple((t, strategies[t]) for t in first)
        try:
            if key not in self._bases:
                self._bases[key] = self.sim.lineup_profile(first=first, strategies=strategies)
            rosters, il = resolve()
            after = self.sim.lineup_profile(rosters, injuries=il, first=first, strategies=strategies)
        except (TradeError, ValueError, RosterInvariantError):
            return None
        base = self._bases[key]
        if after is None or base is None:
            return None
        d = (after - base)[self.i]
        return LineupDelta(float(d @ strategies[self.team].normalized * 9), float(d.sum()))


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
