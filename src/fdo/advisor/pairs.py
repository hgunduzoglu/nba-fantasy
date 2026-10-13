"""Aday üretimi ve çift önerisi (README §6.7.3).

Advisor **yalnızca ECW'yi** optimize eder (İlke 2). Z/G burada kullanılmaz.

1. Aday kümesi C: ΔECW ilk K₁ ∪ ADP aciliyeti (P_surv(sonraki turn) < 0.5 ve ΔECW ilk K₂) ∪ pinler
2. Çiftler: C'den sırasız 2'li kombinasyonlar; kadroyu tamamlanamaz yapanlar elenir
3. Hızlı statik skor ``Q(a,b) = ECW(R ∪ {a,b} ∪ fill) − ECW(R ∪ fill)``; ilk M + pinler
4. CRN'li rollout (bkz. ``rollout.py``)
5. ``E[W]``, P10/P50/P90, SE, regret ± CRN eşleşmeli SE ve kademe
"""

from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from fdo.advisor.rollout import Problem, RolloutOutcome, delta_ecw, rollout_pair
from fdo.advisor.simulate import (
    STREAM_FILL_COND,
    STREAM_ROLLOUT,
    STREAM_UNCERTAINTY,
    AdvisorContext,
    build_fill,
    make_engine,
    sub_seed,
    vec_or_fill,
)
from fdo.advisor.survival import survival
from fdo.advisor.uncertainty import multipliers
from fdo.draft.events import DraftLog
from fdo.draft.order import next_turn_after, picks_for_seat, turns_for_seat
from fdo.matchup.fill import FillTable
from fdo.roster.assignment import RosterModel, feasible_group_table


class AdvisorError(ValueError):
    pass


@dataclass
class PairResult:
    players: tuple[str, ...]
    names: tuple[str, ...]
    q_static: float
    mean: float
    se: float
    p10: float
    p50: float
    p90: float
    regret: float = 0.0
    regret_se: float = 0.0
    tier: int = 1
    pinned: bool = False
    feasible: bool = True
    outcome: RolloutOutcome | None = field(default=None, repr=False)

    @property
    def label(self) -> str:
        return " + ".join(self.names)


@dataclass
class AdvisorResult:
    turn: tuple[int, ...]
    next_turn: tuple[int, ...] | None
    pairs: list[PairResult]
    candidates: pd.DataFrame
    params: dict
    elapsed: float
    real_players: int
    roster_size: int
    sources: list[dict]
    uncalibrated: list[str]
    categories: tuple[str, ...]

    def pair_table(self) -> pd.DataFrame:
        return pd.DataFrame([{
            "tier": p.tier, "pair": p.label, "E[W]": p.mean, "SE": p.se, "P10": p.p10,
            "P50": p.p50, "P90": p.p90, "regret": p.regret, "regret_SE": p.regret_se,
            "Q_static": p.q_static, "pinned": p.pinned,
        } for p in self.pairs])

    def by_label(self, label: str) -> PairResult:
        return next(p for p in self.pairs if p.label == label)


# --------------------------------------------------------------------------
# problem kurulumu
# --------------------------------------------------------------------------

def current_turn(log: DraftLog, seat: int) -> tuple[int, ...]:
    k = log.next_pick
    for turn in turns_for_seat(seat, log.teams, log.rounds, log.third_round_reversal):
        if k in turn:
            return tuple(n for n in turn if n >= k)
    raise AdvisorError(f"Pick {k} kullanıcının turn'ü değil")


def setup_problem(ctx: AdvisorContext, log: DraftLog, fill: FillTable) -> Problem:
    cfg = ctx.config
    lg = cfg.league
    user = lg.my_seat
    if log.is_complete:
        raise AdvisorError("Draft tamamlandı")
    if log.next_seat != user:
        raise AdvisorError(f"Sıra kullanıcıda değil (pick {log.next_pick}, seat {log.next_seat})")
    k = log.next_pick
    turn = current_turn(log, user)
    nxt = next_turn_after(turn[-1], user, lg.teams, lg.rounds, lg.third_round_reversal)
    u = ctx.universe

    rosters: dict[int, list[tuple[int, int]]] = {s: [] for s in range(1, lg.teams + 1)}
    available = np.ones(u.n, dtype=bool)
    for p in log.picks:
        i = u.index[p.player_id]
        rosters[p.seat].append((i, p.overall_pick))
        available[i] = False

    def static_vec(seat: int) -> np.ndarray:
        items = rosters[seat]
        v = np.zeros(ctx.vecs.shape[1])
        if items:
            idx = np.array([i for i, _ in items])
            ks = np.array([n for _, n in items])
            v += vec_or_fill(ctx.vecs, idx, ks, fill).sum(axis=0)
        rem = [n for n in picks_for_seat(seat, lg.teams, lg.rounds, lg.third_round_reversal) if n >= k]
        return v + fill.sum(rem)

    user_picks = [n for n in picks_for_seat(user, lg.teams, lg.rounds, lg.third_round_reversal) if n >= k]
    after_turn = tuple(n for n in user_picks if n > turn[-1])
    after_next = tuple(n for n in after_turn if not nxt or n > nxt[-1])
    roster = np.array([i for i, _ in rosters[user]], dtype=np.int64)
    roster_vec = np.zeros(ctx.vecs.shape[1])
    if len(roster):
        roster_vec = vec_or_fill(ctx.vecs, roster, np.array([n for _, n in rosters[user]]), fill).sum(axis=0)
    opp_seats = np.array([s for s in range(1, lg.teams + 1) if s != user])
    return Problem(
        ctx=ctx, fill=fill, user=user, turn=turn, next_turn=nxt, roster=roster,
        roster_vec=roster_vec, after_turn=after_turn, after_next=after_next, opp_seats=opp_seats,
        opp_static=np.stack([static_vec(s) for s in opp_seats]), available=available,
        roster_model=RosterModel(cfg),
    )


# --------------------------------------------------------------------------
# adaylar ve çiftler
# --------------------------------------------------------------------------

def single_feasible(prob: Problem) -> np.ndarray:
    """Oyuncu bu pick'te tek başına alınınca kadro hâlâ tamamlanabilir mi (grup düzeyinde, ``(n,)``)."""
    u = prob.ctx.universe
    model = prob.roster_model or RosterModel(prob.ctx.config)
    base = position_sets(prob, prob.roster.tolist())
    remaining = len(prob.turn) - 1 + len(prob.after_turn)
    table = feasible_group_table(model, base, u.groups, 1, remaining)
    return table[u.group]


def candidate_set(prob: Problem, delta: np.ndarray, surv_next: np.ndarray | None,
                  pinned: list[int]) -> list[int]:
    """Aday kümesi; kadroyu tek başına tamamlanamaz yapan oyuncular (Yahoo pozisyon kuralı) dışarıda.

    Böylece geç turlarda aday kümesi kurala aykırı oyuncularla dolup hiç geçerli çift kalmaması önlenir.
    """
    adv = prob.ctx.config.model.advisor
    ok = single_feasible(prob)
    order = [int(i) for i in np.argsort(np.where(np.isnan(delta), np.inf, -delta), kind="stable")
             if not np.isnan(delta[i]) and ok[i]]
    top1 = order[: adv.k1_top_ecw]
    urgent = []
    if surv_next is not None:
        urgent = [i for i in order[: adv.k2_urgency_pool]
                  if surv_next[i] < adv.urgency_survival_threshold and i not in top1]
    out: list[int] = []
    for i in [*pinned, *top1, *urgent]:
        if i not in out and prob.available[i]:
            out.append(i)
    keep_pinned = [i for i in out if i in pinned]
    rest = [i for i in out if i not in pinned]
    return keep_pinned + rest[: max(0, adv.max_candidates - len(keep_pinned))]


def position_sets(prob: Problem, idx) -> list[frozenset[str]]:
    u = prob.ctx.universe
    return [u.groups[u.group[i]] for i in idx]


def feasible_combo(prob: Problem, model: RosterModel, combo: tuple[int, ...]) -> bool:
    remaining_after = len(prob.after_turn)
    pos = position_sets(prob, [*prob.roster.tolist(), *combo])
    return model.can_complete(pos, remaining_after)


def feasible_combos(prob: Problem, cands: list[int], delta: np.ndarray, per_group: int = 3
                    ) -> tuple[list[int], list[tuple[int, ...]]]:
    """Adaylardan kadroyu tamamlanabilir bırakan kombinasyonlar.

    Hiç yoksa (ör. iki C slotu açık ve adayların hiçbiri C değil) aday kümesi her pozisyon
    grubunun ΔECW'ye göre en iyi ``per_group`` oyuncusuyla genişletilir.
    """
    model = prob.roster_model
    size = len(prob.turn)

    def build(cs):
        combos = [tuple(sorted(c)) for c in itertools.combinations(cs, size)]
        return [c for c in combos if feasible_combo(prob, model, c)]

    feasible = build(cands)
    if feasible:
        return cands, feasible
    u = prob.ctx.universe
    ok = prob.available & ~np.isnan(delta)
    extra = []
    for g in range(len(u.groups)):
        idx = np.flatnonzero(ok & (u.group == g))
        extra += [int(i) for i in idx[np.argsort(-delta[idx], kind="stable")[:per_group]]]
    cands = cands + [i for i in extra if i not in cands]
    return cands, build(cands)


def static_scores(prob: Problem, combos: list[tuple[int, ...]]) -> np.ndarray:
    """``Q = ECW(R ∪ combo ∪ fill) − ECW(R ∪ fill)`` statik rakiplere karşı."""
    if not combos:
        return np.zeros(0)
    base = prob.roster_vec + prob.fill_sum(prob.after_turn)
    ref = prob.ecw_static(prob.roster_vec + prob.fill_sum(prob.turn + prob.after_turn))
    V = np.stack([prob.ctx.vecs[list(c)].sum(axis=0) for c in combos])
    return prob.ecw_static(base[None, :] + V) - ref


def assign_tiers(results: list[PairResult], se_mult: float) -> None:
    """İstatistiksel olarak ayırt edilemeyen çiftleri aynı kademeye koyar (fark < k·SE_fark)."""
    tier, leader = 0, None
    for r in results:
        if leader is None:
            tier, leader = 1, r
        else:
            d = leader.outcome.W - r.outcome.W
            se = float(np.std(d, ddof=1) / np.sqrt(len(d))) if len(d) > 1 else 0.0
            if float(d.mean()) >= se_mult * se and float(d.mean()) > 0:
                tier, leader = tier + 1, r
        r.tier = tier


# --------------------------------------------------------------------------
# ana giriş
# --------------------------------------------------------------------------

def recommend(ctx: AdvisorContext, log: DraftLog, *, mode: str = "fast", n_sims: int | None = None,
              seed: int | None = None, pinned_players=(), pinned_pairs=(),
              conditional_fill: bool = True, uncertainty: bool = False, progress=None) -> AdvisorResult:
    """Kullanıcının mevcut turn'ü için çift (ya da tek) önerisi.

    ``uncertainty``: V2 sakatlık/rol senaryoları (§13.5) — simülasyon başına oyuncu çarpanları.
    """
    t0 = time.perf_counter()
    cfg = ctx.config
    adv = cfg.model.advisor
    seed = ctx.seed if seed is None else int(seed)
    S = int(n_sims or (adv.sims_per_pair_fast if mode == "fast" else adv.sims_per_pair))
    u = ctx.universe
    names = ctx.dataset.names()

    def report(step: str, i: int = 0, n: int = 0) -> None:
        if progress:
            progress(step, i, n)

    fill = ctx.base_fill
    if conditional_fill and len(log):
        report("Koşullu doldurma tablosu")
        fill = build_fill(u, cfg, ctx.vecs, adv.fill_sims_conditional, sub_seed(seed, STREAM_FILL_COND),
                          log=log, base=ctx.base_fill)
    prob = setup_problem(ctx, log, fill)
    k = log.next_pick
    t1 = prob.turn[0]

    # ΔECW: mevcut pick'te oyuncu vs aynı pick'in doldurma profili
    base_vec = prob.roster_vec + prob.fill_sum([n for n in prob.turn + prob.after_turn if n != t1])
    delta = delta_ecw(prob, base_vec, t1, prob.available)

    engine = make_engine(ctx, log, S, sub_seed(seed, STREAM_ROLLOUT))
    snap0 = engine.snapshot()
    mult = multipliers(ctx, engine.sim_ids, sub_seed(seed, STREAM_UNCERTAINTY)) if uncertainty else None

    # aciliyet ön elemesi: kullanıcı pick'leri boş geçilerek sonraki turn'e kadar
    surv_next = None
    if prob.next_turn:
        report("Survival ön elemesi")
        engine.run_until(prob.next_turn[0], skip_seat=prob.user)
        surv_next, _ = survival(engine)
        engine.restore(snap0)

    pin_idx = [u.index[p] for p in pinned_players if p in u.index]
    pin_pairs = [tuple(sorted(u.index[p] for p in pp)) for pp in pinned_pairs
                 if all(p in u.index for p in pp)]
    cands = candidate_set(prob, delta, surv_next, pin_idx)
    size = len(prob.turn)
    model = prob.roster_model
    cands, feasible = feasible_combos(prob, cands, delta)
    q = static_scores(prob, feasible)
    order = np.argsort(-q, kind="stable")
    chosen = [feasible[i] for i in order[: adv.m_pairs_to_rollout]]
    for pp in pin_pairs:
        if len(pp) == size and pp not in chosen:
            chosen.append(pp)
    q_of = dict(zip(feasible, q))
    q_extra = static_scores(prob, [c for c in chosen if c not in q_of])
    q_of.update(zip([c for c in chosen if c not in q_of], q_extra))

    results: list[PairResult] = []
    for i, combo in enumerate(chosen):
        report("Rollout", i + 1, len(chosen))
        out = rollout_pair(prob, engine, snap0, combo, mult)
        W = out.W
        ids = tuple(str(u.ids[j]) for j in combo)
        results.append(PairResult(
            players=ids, names=tuple(str(names.get(p, p)) for p in ids), q_static=float(q_of[combo]),
            mean=float(W.mean()), se=float(W.std(ddof=1) / np.sqrt(S)) if S > 1 else 0.0,
            p10=float(np.quantile(W, 0.1)), p50=float(np.quantile(W, 0.5)),
            p90=float(np.quantile(W, 0.9)), pinned=combo in pin_pairs or bool(set(combo) & set(pin_idx)),
            feasible=combo in feasible or feasible_combo(prob, model, combo), outcome=out,
        ))
    results.sort(key=lambda r: -r.mean)
    if results:
        best = results[0].outcome.W
        for r in results:
            d = best - r.outcome.W
            r.regret = float(d.mean())
            r.regret_se = float(d.std(ddof=1) / np.sqrt(S)) if S > 1 else 0.0
        assign_tiers(results, adv.tier_se_mult)

    cand_df = candidate_table(ctx, cands, delta, surv_next, pin_idx)
    uncal = ["bot parametreleri (σ₀, σ₁, profil karışımı)", "utilization / games_per_week",
             "doldurma profilleri nötr"]
    if not ctx.variance_calibrated:
        uncal.insert(1, "varyans φ (varyans dosyası yok)")
    if uncertainty:
        uncal.append("sakatlık/rol senaryoları (κ, σ_r)")
    return AdvisorResult(
        turn=prob.turn, next_turn=prob.next_turn, pairs=results, candidates=cand_df,
        params={"mode": mode, "S": S, "seed": seed, "pick": k, "fill": fill.source,
                "fill_sims": fill.n_sims, "candidates": len(cands), "pairs_considered": len(feasible),
                "pairs_rolled_out": len(chosen), "next_policy_top_l": adv.next_policy_top_l,
                "uncertainty": uncertainty},
        elapsed=time.perf_counter() - t0,
        real_players=len(prob.roster) + size + (len(prob.next_turn) if prob.next_turn else 0),
        roster_size=cfg.league.rounds, sources=ctx.dataset.sources(), uncalibrated=uncal,
        categories=tuple(cfg.categories),
    )


def candidate_table(ctx: AdvisorContext, cands: list[int], delta: np.ndarray,
                    surv_next: np.ndarray | None, pinned: list[int]) -> pd.DataFrame:
    """Adaylar ve bekleme maliyeti ``wait_cost = ΔECW · (1 − P_surv(u₁))`` (yalnızca açıklama)."""
    u = ctx.universe
    names = ctx.dataset.names()
    pos = ctx.dataset.positions()
    ids = [str(u.ids[i]) for i in cands]
    S_surv = surv_next[cands] if surv_next is not None else np.full(len(cands), np.nan)
    d = delta[cands]
    return pd.DataFrame({
        "player_id": ids,
        "name": [names.get(p, p) for p in ids],
        "positions": [",".join(sorted(pos[p])) for p in ids],
        "delta_ecw": d,
        "p_surv_next": S_surv,
        "wait_cost": d * (1 - S_surv),
        "adp_eff": u.adp[cands],
        "adp_status": u.status[cands],
        "pinned": [i in pinned for i in cands],
    })
