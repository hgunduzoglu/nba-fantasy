"""Optimal slot ataması ve kadro tamamlanabilirliği (README §6.5).

Atama bir bipartite eşleme problemidir: satırlar oyuncular, sütunlar slot
örnekleridir. Maliyet sırası spesifik < esnek (G/F) < UTIL < BN; uygun olmayan
hücre çok büyük maliyet alır. Bench maliyeti, aktif slot sayısını
maksimize etmeyi garanti edecek kadar büyüktür.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from scipy.optimize import linear_sum_assignment

from fdo.config import Config
from fdo.roster.eligibility import slot_instances, slot_tier

TIER_COST = {"specific": 1.0, "flex": 2.0, "util": 3.0, "bench": 100.0}
INELIGIBLE = 1e6


@dataclass(frozen=True)
class Assignment:
    slots: tuple[str | None, ...]          # oyuncu sırasıyla atanan slot (None = sığmadı)
    open_active: Counter                    # doldurulamayan aktif slotlar

    @property
    def n_open_active(self) -> int:
        return sum(self.open_active.values())


class RosterModel:
    """Config'e bağlı slot yapısı; pozisyon kümeleri listesi üzerinde çalışır."""

    def __init__(self, config: Config):
        self.config = config
        self.instances = slot_instances(config)
        self.allowed = [config.roster.slot_eligibility[s] for s in self.instances]
        self.cost = np.array([TIER_COST[slot_tier(s, config)] for s in self.instances])
        self.is_active = np.array([s in config.roster.active_slots for s in self.instances])
        self.n_active = int(self.is_active.sum())

    def assign(self, positions: list[frozenset[str]]) -> Assignment:
        return self._solve(positions)

    def _solve(self, positions: list[frozenset[str]]) -> Assignment:
        n = len(positions)
        if n == 0:
            return Assignment(slots=(), open_active=Counter(
                s for s, a in zip(self.instances, self.is_active) if a))
        m = len(self.instances)
        cost = np.full((n, m), INELIGIBLE)
        for i, pos in enumerate(positions):
            for j, allowed in enumerate(self.allowed):
                if pos & allowed:
                    cost[i, j] = self.cost[j]
        rows, cols = linear_sum_assignment(cost)
        slots: list[str | None] = [None] * n
        used = np.zeros(m, dtype=bool)
        for r, c in zip(rows, cols):
            if cost[r, c] < INELIGIBLE:
                slots[r] = self.instances[c]
                used[c] = True
        open_active = Counter(s for j, s in enumerate(self.instances) if self.is_active[j] and not used[j])
        return Assignment(slots=tuple(slots), open_active=open_active)

    def open_active_count(self, positions: list[frozenset[str]]) -> int:
        return _open_count(self, tuple(sorted(",".join(sorted(p)) for p in positions)))

    def can_complete(self, positions: list[frozenset[str]], n_remaining_picks: int) -> bool:
        """Eksik aktif slot sayısı kalan pick sayısını aşmıyor mu (yalnızca sayısal)."""
        if len(positions) + n_remaining_picks > len(self.instances):
            n_remaining_picks = max(0, len(self.instances) - len(positions))
        return self.open_active_count(positions) <= n_remaining_picks


@lru_cache(maxsize=500_000)
def _open_count(model: RosterModel, key: tuple[str, ...]) -> int:
    positions = [frozenset(k.split(",")) for k in key]
    return model._solve(positions).n_open_active


def best_assignment(positions: list[frozenset[str]], config: Config) -> Assignment:
    return RosterModel(config).assign(positions)


def open_active_slots(positions: list[frozenset[str]], config: Config) -> Counter:
    return RosterModel(config).assign(positions).open_active


def can_complete(positions: list[frozenset[str]], n_remaining_picks: int, config: Config) -> bool:
    return RosterModel(config).can_complete(positions, n_remaining_picks)


class GroupOracle:
    """Pozisyon grubu sayımlarından hızlı kadro analizi (botlar ve simülasyon için).

    ``groups[g]`` bir pozisyon kümesidir. Kadro, grup başına sayım vektörü ile
    temsil edilir. ``analyze(counts)`` → ``(eksik aktif slot sayısı,
    fills[g] = g grubundan bir oyuncu eklemek eksik aktif slotu azaltır mı)``.
    """

    def __init__(self, groups: list[frozenset[str]], config: Config):
        self.groups = list(groups)
        self.model = RosterModel(config)
        self._cache: dict[bytes, tuple[int, np.ndarray]] = {}

    def _open(self, counts: np.ndarray) -> int:
        positions = [self.groups[g] for g, c in enumerate(counts) for _ in range(int(c))]
        return self.model.open_active_count(positions)

    def analyze(self, counts: np.ndarray) -> tuple[int, np.ndarray]:
        key = counts.tobytes()
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        base = self._open(counts)
        fills = np.zeros(len(self.groups), dtype=bool)
        if base > 0:
            for g in range(len(self.groups)):
                c = counts.copy()
                c[g] += 1
                fills[g] = self._open(c) < base
        res = (base, fills)
        self._cache[key] = res
        return res
