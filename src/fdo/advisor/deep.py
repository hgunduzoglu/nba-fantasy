"""Tam ufuk rollout ve kademeli yarılama (README §13.3, V2).

V1 rollout'u sonraki turn'e kadar simüle eder ve sonrasını doldurma profilleriyle tamamlar.
Bu modül her aday çift için draft'ı **sonuna kadar** simüle eder:

1. çift kullanıcı koltuğuna zorlanır; botlar kullanıcının her sonraki pick'ine kadar oynar,
2. kullanıcının her sonraki pick'inde π (açgözlü ECW): simülasyonda uygun ve kadroyu
   tamamlanabilir bırakan oyuncular arasından ``ECW(mevcut kadro + i + kalan pick doldurması)``'nı
   en büyükleyen seçilir (aday kısa listesi her pick'te ΔECW ile yeniden kurulur),
3. ``W_s = ECW(kullanıcının 13 gerçek oyuncusu, rakiplerin 13 gerçek oyuncusu)`` — doldurma yok.

**Kademeli yarılama.** Çiftler önce ``rungs[0]`` simülasyonla değerlendirilir; ortalamaya göre
en iyi yarısı (en az 2) sonraki basamağa geçer ve ``rungs[1]`` **yeni** simülasyon alır
(``sim_offset``; önceki simülasyonlar yeniden hesaplanmaz, CRN korunur). Elenen çiftin
sonucu elendiği basamaktaki simülasyonlarla raporlanır.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from fdo.advisor.pairs import AdvisorResult, setup_problem
from fdo.advisor.rollout import Problem
from fdo.advisor.simulate import STREAM_ROLLOUT, AdvisorContext, make_engine, sub_seed, team_vectors, vec_or_fill
from fdo.bots.thurstone import BatchDraft
from fdo.draft.events import DraftLog
from fdo.matchup.ecw import ecw_vs

NEG = -np.inf


def user_vector(prob: Problem, engine: BatchDraft, upto: int) -> np.ndarray:
    """``(S, 24)``: kullanıcının ``upto``'dan önceki seçimleri (gerçek vektör, projeksiyonsuz → doldurma)."""
    ks = engine.seat_picks(prob.user)
    ks = ks[ks < upto]
    if len(ks) == 0:
        return np.zeros((engine.S, prob.ctx.vecs.shape[1]))
    picked = engine.pick_player[:, ks - 1]
    return vec_or_fill(prob.ctx.vecs, picked, ks[None, :], prob.fill).sum(axis=1)


def greedy_pick(prob: Problem, engine: BatchDraft, n: int, rest: list[int], shortlist_k: int) -> np.ndarray:
    """Kullanıcının ``n`` numaralı pick'i için simülasyon başına açgözlü ECW seçimi ``(S,)``."""
    ctx = prob.ctx
    S = engine.S
    cur = user_vector(prob, engine, n)
    rest_vec = prob.fill_sum(rest)
    avail = engine.taken_at == 0                                       # (S, n_players)
    mean_base = cur.mean(axis=0) + rest_vec
    cand = np.flatnonzero(avail.any(axis=0) & ctx.has_vec)
    d = prob.ecw_static(mean_base[None, :] + ctx.vecs[cand])
    short = cand[np.argsort(-d, kind="stable")[:shortlist_k]]

    seat_i = prob.user - 1
    remaining_after = engine.rounds - engine.n_picked[:, seat_i].astype(np.int64) - 1
    ok = avail[:, short].copy()
    if engine.enforce_feasibility:
        groups = engine.u.group[short]
        for s in range(S):
            opens, fills, _ = engine.oracle.analyze(engine.counts[s, seat_i])
            ok[s] &= (opens - fills[groups]) <= remaining_after[s]
    base = cur + rest_vec                                              # (S, 24)
    vals = prob.ecw_static(base[:, None, :] + ctx.vecs[short][None, :, :])   # (S, K)
    vals = np.where(ok, vals, NEG)
    best = np.argmax(vals, axis=1)
    choice = short[best]
    bad = ~np.isfinite(vals[np.arange(S), best])
    if bad.any():                                                      # kısa liste tükendi: bot skoru
        score, bot_ok = engine.scores()
        fb = np.argmin(np.where(bot_ok, score, np.inf), axis=1)
        choice = np.where(bad, fb, choice)
    return choice


def full_rollout(prob: Problem, log: DraftLog, pair: tuple[int, ...], n_sims: int, seed: int,
                 sim_offset: int, shortlist_k: int) -> np.ndarray:
    """Bir çift için ``(n_sims,)`` tam ufuk ``W`` değerleri (simülasyonlar ``sim_offset``'ten)."""
    ctx = prob.ctx
    eng = make_engine(ctx, log, n_sims, seed, sim_offset=sim_offset)
    for p in pair:
        eng.force(int(p))
    later = list(prob.after_turn)
    for j, n in enumerate(later):
        eng.run_until(n)
        eng.force(greedy_pick(prob, eng, n, later[j + 1:], shortlist_k))
    eng.run_until(eng.total + 1)
    teams = team_vectors(eng, ctx.vecs, prob.fill, eng.total + 1)        # (S, T, 24)
    user = teams[:, prob.user - 1, :]
    opp = teams[:, prob.opp_seats - 1, :]
    return ecw_vs(user, opp, ctx.config).sum(axis=-1).mean(axis=-1)


@dataclass
class DeepPair:
    label: str
    players: tuple[str, ...]
    W: np.ndarray
    rung: int                    # ulaştığı son basamak (0-tabanlı)
    v1_mean: float | None = None

    @property
    def mean(self) -> float:
        return float(self.W.mean())

    @property
    def se(self) -> float:
        return float(self.W.std(ddof=1) / np.sqrt(len(self.W))) if len(self.W) > 1 else 0.0


@dataclass
class DeepResult:
    pairs: list[DeepPair]
    rungs: tuple[int, ...]
    elapsed: float
    params: dict = field(default_factory=dict)

    def table(self) -> pd.DataFrame:
        rows = []
        for p in self.pairs:
            rows.append({"pair": p.label, "E[W] tam ufuk": p.mean, "SE": p.se, "sims": len(p.W),
                         "basamak": p.rung + 1, "E[W] V1": p.v1_mean})
        df = pd.DataFrame(rows)
        return df.sort_values(["basamak", "E[W] tam ufuk"], ascending=[False, False], kind="mergesort")


def successive_halving(evaluate, items: list, rungs: tuple[int, ...], min_keep: int = 2):
    """``evaluate(item, n, offset) → (n,)``; döner: item → (W birikimi, ulaşılan basamak)."""
    W = {i: np.zeros(0) for i in range(len(items))}
    reached = {i: 0 for i in range(len(items))}
    alive = list(range(len(items)))
    offset = 0
    for r, n in enumerate(rungs):
        for i in alive:
            W[i] = np.concatenate([W[i], evaluate(items[i], n, offset)])
            reached[i] = r
        offset += n
        if r < len(rungs) - 1:
            keep = max(min_keep, len(alive) // 2)
            alive = sorted(alive, key=lambda i: -W[i].mean())[:keep]
            if len(alive) <= 1:
                break
    return W, reached


def deep_recommend(ctx: AdvisorContext, log: DraftLog, base: AdvisorResult, *, n_pairs: int | None = None,
                   rungs: tuple[int, ...] | None = None, seed: int | None = None, progress=None) -> DeepResult:
    """V1 sonucunun ilk ``n_pairs`` çiftini tam ufuk rollout ve kademeli yarılama ile yeniden sıralar."""
    t0 = time.perf_counter()
    adv = ctx.config.model.advisor
    n_pairs = n_pairs or adv.deep_pairs
    rungs = tuple(rungs or adv.deep_rungs)
    seed = sub_seed(ctx.seed if seed is None else int(seed), STREAM_ROLLOUT + 100)
    fill = ctx.base_fill
    prob = setup_problem(ctx, log, fill)
    u = ctx.universe
    chosen = base.pairs[:n_pairs]
    combos = [tuple(int(u.index[p]) for p in pr.players) for pr in chosen]
    calls = {"n": 0}
    total_calls, alive = 0, len(combos)
    for _ in rungs:
        total_calls += alive
        alive = max(2, alive // 2) if alive > 1 else alive

    def evaluate(combo, n, offset):
        calls["n"] += 1
        if progress:
            progress(calls["n"], total_calls)
        return full_rollout(prob, log, combo, n, seed, offset, adv.deep_shortlist_k)

    W, reached = successive_halving(evaluate, combos, rungs)
    pairs = [DeepPair(label=pr.label, players=pr.players, W=W[i], rung=reached[i], v1_mean=pr.mean)
             for i, pr in enumerate(chosen)]
    pairs.sort(key=lambda p: (-p.rung, -p.mean))
    return DeepResult(pairs=pairs, rungs=rungs, elapsed=time.perf_counter() - t0,
                      params={"seed": seed, "shortlist_k": adv.deep_shortlist_k, "pick": log.next_pick})
