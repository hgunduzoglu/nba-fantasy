"""Thurstone gürültülü sıralama ve vektörleştirilmiş bot draft motoru (README §6.4.1).

Her simülasyon ``s`` ve koltuk ``b`` için draft başında **kalıcı** bir algılanan sıra çekilir:

    q_bi = A_i + σ_i · ε_bi,     ε ~ t_ν (ölçeklenmiş, varyans 1)

Her pick'te küçük bir anlık titreşim eklenir: ``q_bi(t) = q_bi + ρ·σ_i·η``. Bot,
uygun ve kadro tamamlanabilirliğini bozmayan oyuncular arasından en küçük

    score = q̃ − need_bonus + penalty

değerine sahip olanı seçer. Simetrik ADP uzaklığı yoktur (İlke 6), sert yasak
yoktur (İlke 7).

Seed hiyerarşisi (İlke 9): ``master_seed → simülasyon s → pick k``. Simülasyon
düzeyi rastgelelik ``SeedSequence(master, spawn_key=(s,))``, pick düzeyi titreşim
``SeedSequence(master, spawn_key=(s, k))`` ile üretilir; bu sayede undo/replay ve
farklı aday çiftlerin değerlendirilmesi aynı rastgele sayıları görür (CRN).
"""

from __future__ import annotations

import numpy as np

from fdo.bots.league_mix import assign_profiles
from fdo.bots.profiles import profile_table
from fdo.bots.universe import BotUniverse
from fdo.config import Config
from fdo.draft.order import pick_order
from fdo.roster.assignment import GroupOracle
from fdo.roster.eligibility import slot_instances
from fdo.types import POSITIONS


def scaled_t(rng: np.random.Generator, df: float, size) -> np.ndarray:
    """Varyansı 1 olacak şekilde ölçeklenmiş Student-t (ν > 2)."""
    if df <= 2:
        raise ValueError("t_df > 2 olmalı (varyans tanımlı olmalı)")
    return rng.standard_t(df, size) * np.sqrt((df - 2.0) / df)


def sim_rng(seed: int, s: int) -> np.random.Generator:
    return np.random.Generator(np.random.PCG64(np.random.SeedSequence(seed, spawn_key=(s,))))


def pick_rng(seed: int, s: int, k: int) -> np.random.Generator:
    return np.random.Generator(np.random.PCG64(np.random.SeedSequence(seed, spawn_key=(s, k))))


class BatchDraft:
    """``S`` paralel draft simülasyonu.

    Durum dizileri:
      * ``taken_at[s, i]``: oyuncu i'nin seçildiği pick (0 = uygun)
      * ``counts[s, seat, g]``: kadrodaki pozisyon grubu sayımları
      * ``pick_player[s, k-1]``: k. pick'te seçilen oyuncu (-1 = boş/atlanmış)
    """

    def __init__(self, universe: BotUniverse, config: Config, n_sims: int, seed: int, *,
                 sim_offset: int = 0, cache_jitter: bool = False, seat_profile_probs: np.ndarray | None = None):
        """``seat_profile_probs (T, P)``: rakip stratejisi tahmini (§6.4.4); verilen koltuklarda profil
        karışım yerine bu dağılımdan çekilir (satırı sıfır olan koltuk karışımdan alır)."""
        self.u = universe
        self.cfg = config
        lg = config.league
        self.T = lg.teams
        self.rounds = lg.rounds
        self.total = lg.total_picks
        self.order = np.array(pick_order(lg.teams, lg.rounds, lg.third_round_reversal))
        self.S = int(n_sims)
        self.seed = int(seed)
        self.sim_ids = np.arange(sim_offset, sim_offset + self.S)
        self.bp = config.model.bots
        self.ptab = profile_table(self.bp)
        self.oracle = GroupOracle(universe.groups, config)
        self.cache_jitter = cache_jitter
        # Yahoo pozisyon kuralı uygulanıyorsa (§3.2) tamamlanabilirlik botlar için de zorunludur.
        self.enforce_feasibility = bool(self.bp.enforce_completion_feasibility
                                        or config.unverified.position_limits_enforced_in_draft)
        self._jitter_cache: dict[int, np.ndarray] = {}

        inst = slot_instances(config)
        specific = {p: sum(1 for s in inst if config.roster.slot_eligibility[s] == frozenset({p})
                           and s in config.roster.active_slots) for p in POSITIONS}
        self.stack_cap = np.array([specific[p] + 1 for p in POSITIONS], dtype=float)
        self.pure_group = np.array([universe.groups.index(frozenset({p}))
                                    if frozenset({p}) in universe.groups else -1 for p in POSITIONS])

        n = universe.n
        self.profile = np.empty((self.S, self.T), dtype=np.int64)
        self.q_raw = np.empty((self.S, self.T, n))
        for row, s in enumerate(self.sim_ids):
            rng = sim_rng(self.seed, int(s))
            names = assign_profiles(config, rng)
            for seat in range(self.T):
                p = self.ptab.index(names[seat])
                if seat_profile_probs is not None and seat_profile_probs[seat].sum() > 0:
                    w = seat_profile_probs[seat] / seat_profile_probs[seat].sum()
                    p = int(rng.choice(len(w), p=w))
                self.profile[row, seat] = p
                base = universe.default_rank if self.ptab.uses_default_rank[p] else universe.adp
                eps = scaled_t(rng, self.ptab.t_df[p], n)
                self.q_raw[row, seat] = base + universe.sigma * self.ptab.sigma_mult[p] * eps
        self.reset()

    # ------------------------------------------------------------------ durum
    def reset(self) -> None:
        S, T, n, G = self.S, self.T, self.u.n, len(self.u.groups)
        self.k = 1
        self.taken_at = np.zeros((S, n), dtype=np.int16)
        self.counts = np.zeros((S, T, G), dtype=np.int16)
        self.n_picked = np.zeros((S, T), dtype=np.int16)
        self.z_sum = np.zeros((S, T, len(self.u.categories)))
        self.punt_cat = np.full((S, T), -1, dtype=np.int64)
        self.pick_player = np.full((S, self.total), -1, dtype=np.int64)

    _STATE = ("k", "taken_at", "counts", "n_picked", "z_sum", "punt_cat", "pick_player")

    def snapshot(self) -> dict:
        return {name: (getattr(self, name).copy() if name != "k" else self.k) for name in self._STATE}

    def restore(self, snap: dict) -> None:
        for name in self._STATE:
            v = snap[name]
            setattr(self, name, v.copy() if name != "k" else v)

    @property
    def is_complete(self) -> bool:
        return self.k > self.total

    @property
    def current_seat(self) -> int:
        return int(self.order[self.k - 1])

    def round_of(self, k: int) -> int:
        return (k - 1) // self.T + 1

    def available(self) -> np.ndarray:
        return self.taken_at == 0

    # ---------------------------------------------------------------- seçimler
    def _record(self, players: np.ndarray) -> None:
        seat_i = self.current_seat - 1
        rows = np.flatnonzero(players >= 0)
        p = players[rows]
        if np.any(self.taken_at[rows, p] > 0):
            raise ValueError(f"Pick {self.k}: zaten seçilmiş oyuncu")
        self.taken_at[rows, p] = self.k
        np.add.at(self.counts, (rows, seat_i, self.u.group[p]), 1)
        self.n_picked[rows, seat_i] += 1
        self.z_sum[rows, seat_i] += self.u.zcat[p]
        self.pick_player[:, self.k - 1] = players
        self.k += 1

    def force(self, players) -> None:
        """Sıradaki pick'i dışarıdan belirle: tek indeks (tüm sim'ler) ya da ``(S,)`` dizi."""
        if self.is_complete:
            raise ValueError("Draft tamamlandı")
        arr = np.broadcast_to(np.asarray(players, dtype=np.int64), (self.S,)).copy()
        self._record(arr)

    def skip(self) -> None:
        """Pick'i oyuncu almadan geç (yalnızca survival ön elemesi için)."""
        self.pick_player[:, self.k - 1] = -1
        self.k += 1

    def _jitter(self, k: int) -> np.ndarray:
        hit = self._jitter_cache.get(k)
        if hit is not None:
            return hit
        out = np.empty((self.S, self.u.n))
        for row, s in enumerate(self.sim_ids):
            out[row] = pick_rng(self.seed, int(s), k).standard_normal(self.u.n)
        if self.cache_jitter:
            self._jitter_cache[k] = out
        return out

    def scores(self) -> tuple[np.ndarray, np.ndarray]:
        """Sıradaki koltuk için ``(skor (S, n), uygunluk maskesi (S, n))``."""
        u, bp, pt = self.u, self.bp, self.ptab
        seat_i = self.current_seat - 1
        rnd = self.round_of(self.k)
        prof = self.profile[:, seat_i]
        q = self.q_raw[:, seat_i, :]

        lam = pt.lam[prof]
        if np.any(lam > 0):
            R = np.broadcast_to(u.value_rank, q.shape).copy()
            pb = pt.is_punt[prof]
            if np.any(pb) and rnd > bp.punt_after_round:
                undecided = pb & (self.punt_cat[:, seat_i] < 0)
                if np.any(undecided):
                    self.punt_cat[undecided, seat_i] = np.argmin(self.z_sum[undecided, seat_i], axis=1)
                rows = np.flatnonzero(pb & (self.punt_cat[:, seat_i] >= 0))
                R[rows] = u.punt_rank[self.punt_cat[rows, seat_i]]
            q = q + lam[:, None] * (R - q)

        sigma_eff = u.sigma[None, :] * pt.sigma_mult[prof][:, None]
        score = q + bp.jitter_rho * sigma_eff * self._jitter(self.k)

        counts = self.counts[:, seat_i, :]
        opens = np.empty(self.S, dtype=np.int64)
        fills = np.empty((self.S, len(u.groups)), dtype=bool)
        needs = np.empty((self.S, len(u.groups)), dtype=bool)
        for row in range(self.S):
            opens[row], fills[row], needs[row] = self.oracle.analyze(counts[row])
        fill_mat = fills[:, u.group]
        need = bp.beta_need * pt.need_mult[prof] * (rnd / self.rounds)
        score = score - need[:, None] * needs[:, u.group]

        if bp.beta_stack > 0:
            pure_counts = np.where(self.pure_group[None, :] >= 0,
                                   counts[:, np.maximum(self.pure_group, 0)], 0).astype(float)
            pen = bp.beta_stack * np.maximum(0.0, pure_counts - self.stack_cap[None, :] + 1)
            pp = u.pure_pos
            score = score + np.where(pp[None, :] >= 0, pen[:, np.maximum(pp, 0)], 0.0)

        ok = self.taken_at == 0
        if self.enforce_feasibility:
            remaining_after = self.rounds - self.n_picked[:, seat_i].astype(np.int64) - 1
            feasible = (opens[:, None] - fill_mat) <= remaining_after[:, None]
            cand = ok & feasible
            has = cand.any(axis=1)
            ok = np.where(has[:, None], cand, ok)
        return score, ok

    def bot_step(self) -> np.ndarray:
        score, ok = self.scores()
        score = np.where(ok, score, np.inf)
        choice = np.argmin(score, axis=1)
        self._record(choice)
        return choice

    def run_until(self, stop_pick: int, *, skip_seat: int | None = None) -> None:
        """``stop_pick``'e kadar (hariç) botları oynat. ``skip_seat`` koltuğu atlanır."""
        stop_pick = min(stop_pick, self.total + 1)
        while self.k < stop_pick:
            if skip_seat is not None and self.current_seat == skip_seat:
                self.skip()
            else:
                self.bot_step()

    # --------------------------------------------------------------- yardımcı
    def seat_picks(self, seat: int) -> np.ndarray:
        """Koltuğun pick numaraları (1-tabanlı)."""
        return np.flatnonzero(self.order == seat) + 1

    def roster_matrix(self, seat: int, upto: int | None = None) -> np.ndarray:
        """``(S, m)`` koltuğun ``upto``'dan önce seçtiği oyuncular (-1 = boş)."""
        ks = self.seat_picks(seat)
        if upto is not None:
            ks = ks[ks < upto]
        return self.pick_player[:, ks - 1]

    def profile_names(self, row: int = 0) -> list[str]:
        return [self.ptab.names[p] for p in self.profile[row]]
