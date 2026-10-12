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
    """Config'e bağlı slot yapısı; pozisyon kümeleri listesi üzerinde çalışır.

    ``positional_only=True`` iken her pozisyonu kabul eden UTIL slotları aktif
    sayılmaz: yalnızca pozisyonel ihtiyaç (PG/SG/G/SF/PF/F/C) ölçülür. Bot
    ``need_bonus``'u bunu kullanır; aksi hâlde UTIL açıkken herkes "ihtiyaç"
    karşılar ve bonus ayrıştırıcı olmaz.
    """

    def __init__(self, config: Config, positional_only: bool = False):
        self.config = config
        inst = slot_instances(config)
        if positional_only:
            inst = [s for s in inst if slot_tier(s, config) in ("specific", "flex")]
            inst += ["BN"] * config.league.rounds
        self.instances = inst
        bench_ok = frozenset().union(*config.roster.slot_eligibility.values())
        self.allowed = [config.roster.slot_eligibility.get(s, bench_ok) for s in self.instances]
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


def feasible_group_table(model: RosterModel, base: list[frozenset[str]], groups: list[frozenset[str]],
                         n_pick: int, remaining_after: int) -> np.ndarray:
    """``base`` kadroya ``n_pick`` (1 ya da 2) oyuncu eklenince kadro tamamlanabilir mi?

    Dönüş: ``n_pick == 1`` → ``(G,)``, ``n_pick == 2`` → ``(G, G)`` bool tablo (grup düzeyinde;
    oyuncu düzeyine ``table[group[i]]`` / ``table[group[i], group[j]]`` ile indirgenir).
    """
    G = len(groups)
    if n_pick == 1:
        return np.array([model.can_complete([*base, groups[g]], remaining_after) for g in range(G)])
    out = np.zeros((G, G), dtype=bool)
    for a in range(G):
        for b in range(a, G):
            out[a, b] = out[b, a] = model.can_complete([*base, groups[a], groups[b]], remaining_after)
    return out


class GroupFlow:
    """Grup sayımları üzerinde kapasiteli bipartite eşleme (aktif slot doldurma).

    ``linear_sum_assignment`` ile aynı **eksik aktif slot sayısını** verir (aktif slot
    doldurmayı maksimize eden atama), ama grup × slot tipi düzeyinde çalıştığı için çok daha
    hızlıdır. Ayrıca tek eşlemeden, her grup için "bir oyuncu eklemek eksik slotu azaltır mı"
    sorusunu artık-graf erişilebilirliğiyle cevaplar (augmenting path var mı).
    """

    def __init__(self, groups: list[frozenset[str]], config: Config, positional_only: bool = False):
        types = [s for s in config.roster.active_slots
                 if not positional_only or slot_tier(s, config) in ("specific", "flex")]
        self.types = types
        self.cap = [config.roster.slots[t] for t in types]
        self.elig = [[t for t, s in enumerate(types) if g & config.roster.slot_eligibility[s]]
                     for g in groups]
        self.total_cap = sum(self.cap)

    def solve(self, counts) -> tuple[int, list[bool]]:
        """``(eksik aktif slot, reduces[g])``."""
        G, T = len(self.elig), len(self.cap)
        x = [[0] * T for _ in range(G)]           # x[g][t]: g grubundan t tipine atanan oyuncu
        used = [0] * T
        matched = 0

        def augment(g: int, seen: list[bool]) -> bool:
            for t in self.elig[g]:
                if seen[t]:
                    continue
                seen[t] = True
                if used[t] < self.cap[t]:
                    x[g][t] += 1
                    used[t] += 1
                    return True
                for g2 in range(G):
                    if x[g2][t] > 0 and augment(g2, seen):
                        x[g2][t] -= 1
                        x[g][t] += 1
                        return True
            return False

        for g in range(G):
            for _ in range(int(counts[g])):
                if augment(g, [False] * T):
                    matched += 1
        open_ = self.total_cap - matched
        if open_ == 0:
            return 0, [False] * G
        # R: boş kapasitesi olan ya da içindeki bir oyuncu R'deki bir tipe kaydırılabilen tipler
        reach = [used[t] < self.cap[t] for t in range(T)]
        changed = True
        while changed:
            changed = False
            for t in range(T):
                if reach[t]:
                    continue
                for g2 in range(G):
                    if x[g2][t] > 0 and any(reach[t2] for t2 in self.elig[g2]):
                        reach[t] = changed = True
                        break
        return open_, [any(reach[t] for t in self.elig[g]) for g in range(G)]


class GroupOracle:
    """Pozisyon grubu sayımlarından hızlı kadro analizi (botlar ve simülasyon için).

    ``groups[g]`` bir pozisyon kümesidir. Kadro, grup başına sayım vektörü ile
    temsil edilir. ``analyze(counts)`` →

    * eksik aktif slot sayısı,
    * ``fills[g]``: g grubundan bir oyuncu eklemek eksik aktif slotu azaltır mı (feasibility),
    * ``needs[g]``: eksik **pozisyonel** slotu (UTIL hariç) azaltır mı (need_bonus).
    """

    def __init__(self, groups: list[frozenset[str]], config: Config):
        self.groups = list(groups)
        self.active = GroupFlow(self.groups, config)
        self.positional = GroupFlow(self.groups, config, positional_only=True)
        self._cache: dict[bytes, tuple[int, np.ndarray, np.ndarray]] = {}

    def analyze(self, counts: np.ndarray) -> tuple[int, np.ndarray, np.ndarray]:
        key = counts.tobytes()
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        base, fills = self.active.solve(counts)
        _, needs = self.positional.solve(counts)
        res = (base, np.array(fills, dtype=bool), np.array(needs, dtype=bool))
        self._cache[key] = res
        return res
