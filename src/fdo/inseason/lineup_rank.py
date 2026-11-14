"""Finalist önerilerini günlük kadroyla yeniden sıralama.

Hızlı takas puanı (``TradeEngine.score_many``) sezonluk ortalama kategori olasılığıdır; pozisyon ve maç çakışması
yüzünden bench'te kalan maçları görmez. Arama bittikten sonra finalistler kalan normal sezon haftalarında haftalık
modelin günlük kadro atamasıyla (``SeasonSim.lineup_profile``, simülasyon yok) yeniden ölçülür ve bu farka göre
sıralanır. Kadrolar, bedava hamleler ve alım hakkı sezon simülasyonuyla aynıdır.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from fdo.inseason.season import SeasonSim
from fdo.trade import Strategy, TradeError
from fdo.trade.engine import RosterInvariantError, TradeEngine
from fdo.trade.suggest import Suggestion


@dataclass(frozen=True)
class LineupDelta:
    """Takımın kalan normal sezonda rakip başına haftalık kategori farkı, günlük kadroyla."""
    strategy: float     # senin stratejinin ağırlıklarıyla (``strategy_delta`` ile aynı ölçek; sıralama ölçüsü)
    ecw: float          # ağırlıksız (``SeasonResult.ecw`` farkı)


def lineup_deltas(sim: SeasonSim, engine: TradeEngine, team: str, strategy: Strategy,
                  suggestions: list[Suggestion]) -> list[LineupDelta | None]:
    """Her öneri için ``team``'in günlük kadro farkı (çözülemeyen ya da kalan haftası olmayan öneri ``None``).
    Taban (takassız) profil rakip ve rakip stratejisi başına bir kez hesaplanır: waiver sırası takasla aynıdır."""
    bases: dict[tuple, np.ndarray | None] = {}
    i = sim.tix[team]
    out: list[LineupDelta | None] = []
    for s in suggestions:
        r = s.request
        first, pair = (team, r.team_b), {team: strategy, r.team_b: s.other_strategy}
        try:
            key = (r.team_b, s.other_strategy)
            if key not in bases:
                bases[key] = sim.lineup_profile(first=first, strategies=pair)
            rosters, _, il = engine.resolve(r, pair)
            after = sim.lineup_profile(rosters, injuries=il, first=first, strategies=pair)
        except (TradeError, ValueError, RosterInvariantError):
            out.append(None)
            continue
        if after is None or bases[key] is None:
            out.append(None)
            continue
        d = (after - bases[key])[i]
        out.append(LineupDelta(float(d @ strategy.normalized * 9), float(d.sum())))
    return out


def rerank(suggestions: list[Suggestion], deltas: list[LineupDelta | None],
           limit: int | None = None) -> tuple[list[Suggestion], list[LineupDelta | None]]:
    """Günlük kadro farkına göre büyükten küçüğe; ölçülemeyenler sona, kendi aralarında hızlı puan sırasıyla."""
    order = sorted(range(len(suggestions)),
                   key=lambda k: (deltas[k] is None, -(deltas[k].strategy if deltas[k] else 0.0), k))[:limit]
    return [suggestions[k] for k in order], [deltas[k] for k in order]
