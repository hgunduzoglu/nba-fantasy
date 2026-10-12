"""V2 backtest arayüzü (README §13.1). V1'de yalnızca protokol tanımlıdır.

Strateji karşılaştırması (Z-greedy, G-greedy, ECW-advisor) aynı bot ligine karşı
yapılacak ve gerçekleşen haftalık istatistiklerle değerlendirilecektir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class EvaluationResult:
    season: str
    #: koltuk → gerçekleşen sezon boyu beklenen/gerçek kategori galibiyeti
    category_wins: dict[int, float] = field(default_factory=dict)
    #: koltuk → kategori → kazanma oranı
    category_rates: dict[int, dict[str, float]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


@runtime_checkable
class SeasonEvaluator(Protocol):
    def evaluate(self, rosters: dict[int, list[str]], season: str) -> EvaluationResult: ...
