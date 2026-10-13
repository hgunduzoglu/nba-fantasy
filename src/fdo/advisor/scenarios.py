"""Alternatif kadro senaryoları — hafif (README §6.7.5, M6).

Tam draft rollout'u: kullanıcı her turn'de miyopik π politikasını uygular, botlar
oynar. Final kadrolar "kaybedilen kategori imzası"na (P < lost_threshold olan
kategoriler) göre gruplanır. Bu bir **ulaşılabilirlik** göstergesidir; optimal
plan iddiası taşımaz.
"""

from __future__ import annotations

import itertools
import time
from collections import defaultdict
from dataclasses import dataclass

import numpy as np
import pandas as pd

from fdo.advisor.pairs import setup_problem
from fdo.advisor.simulate import (
    STREAM_SCENARIO,
    AdvisorContext,
    make_engine,
    sub_seed,
    team_vectors,
    vec_or_fill,
)
from fdo.draft.events import DraftLog
from fdo.draft.order import turns_for_seat
from fdo.matchup.ecw import ecw_vs
from fdo.roster.assignment import feasible_group_table
from fdo.types import CATEGORY_LABELS


@dataclass
class Archetype:
    signature: tuple[str, ...]          # kaybedilen kategoriler
    label: str
    frequency: float
    mean_ecw: float
    cat_p: np.ndarray                    # ortalama kategori P
    typical_roster: list[str]


@dataclass
class ScenarioResult:
    archetypes: list[Archetype]
    n_sims: int
    seed: int
    elapsed: float

    def table(self, categories) -> pd.DataFrame:
        rows = []
        for a in self.archetypes:
            row = {"arketip": a.label, "frekans": a.frequency, "ortalama ECW": a.mean_ecw}
            row.update({CATEGORY_LABELS.get(c, c): p for c, p in zip(categories, a.cat_p)})
            rows.append(row)
        return pd.DataFrame(rows)


def archetype_label(signature: tuple[str, ...]) -> str:
    if not signature:
        return "dengeli (kaybedilen kategori yok)"
    return "punt " + "+".join(CATEGORY_LABELS.get(c, c) for c in signature) + " benzeri"


def rollout_to_end(ctx: AdvisorContext, log: DraftLog, S: int, seed: int, *, punt: tuple[str, ...] = (),
                   weights: dict[str, float] | None = None, progress=None):
    """Draft sonuna kadar rollout: kullanıcı her turn'de ``punt`` dışındaki kategorilerin beklenen
    galibiyetini en büyükleyen seçimi yapar (``punt = ()`` → miyopik ECW π). Dönüş: ``(P (S, T−1, C),
    kullanıcı kadro matrisi, motor)``; P her zaman 9 kategorinin hepsiyle hesaplanır."""
    cfg = ctx.config
    adv = cfg.model.advisor
    lg = cfg.league
    prob = setup_problem(ctx, log, ctx.base_fill)
    keep = np.array([0.0 if c in punt else float((weights or {}).get(c, 1.0)) for c in cfg.categories])

    def policy_score(vecs_):
        p = ecw_vs(vecs_, prob.opp_static, cfg)                       # (..., T−1, C)
        return (p * keep).sum(axis=-1).mean(axis=-1)

    user = prob.user
    eng = make_engine(ctx, log, S, sub_seed(seed, STREAM_SCENARIO), cache_jitter=False)
    vecs, fill = ctx.vecs, ctx.base_fill
    turns = [t for t in turns_for_seat(user, lg.teams, lg.rounds, lg.third_round_reversal)
             if t[-1] >= eng.k]
    all_user_picks = [n for t in turns for n in t]
    uni = ctx.universe
    feas_cache: dict[tuple, np.ndarray] = {}

    def feasible(counts: np.ndarray, n_pick: int, remaining_after: int) -> np.ndarray:
        key = (counts.tobytes(), n_pick, remaining_after)
        if key not in feas_cache:
            base = [uni.groups[g] for g, c in enumerate(counts) for _ in range(int(c))]
            feas_cache[key] = feasible_group_table(prob.roster_model, base, uni.groups, n_pick,
                                                   remaining_after)
        return feas_cache[key]

    for ti, turn in enumerate(turns):
        if progress:
            progress("Senaryo rollout", ti + 1, len(turns))
        turn = tuple(n for n in turn if n >= eng.k)
        eng.run_until(turn[0], skip_seat=None)
        later = [n for n in all_user_picks if n > turn[-1]]
        roster = eng.roster_matrix(user, upto=turn[0])
        roster_picks = eng.seat_picks(user)[: roster.shape[1]]
        roster_vec = vec_or_fill(vecs, roster, roster_picks[None, :], fill).sum(axis=1)
        choices = np.full((S, len(turn)), -1, dtype=np.int64)
        for s in range(S):
            base = roster_vec[s] + fill.sum(later)
            avail = (eng.taken_at[s] == 0) & ctx.has_vec
            idx = np.flatnonzero(avail)
            if len(idx) < len(turn):
                continue
            single = policy_score(base[None, :] + fill.sum(turn[1:]) + vecs[idx])
            short = idx[np.argsort(-single, kind="stable")[: adv.next_policy_top_l]]
            combos = list(itertools.combinations(short.tolist(), len(turn)))
            table = feasible(eng.counts[s, user - 1], len(turn), len(later))
            ok = [c for c in combos if table[tuple(uni.group[list(c)])]]
            combos = ok or combos
            V = np.stack([vecs[list(c)].sum(axis=0) for c in combos])
            best = combos[int(np.argmax(policy_score(base[None, :] + V)))]
            choices[s, : len(best)] = best
        for j in range(len(turn)):
            eng.force(choices[:, j])
    eng.run_until(eng.total + 1)

    teams = team_vectors(eng, vecs, fill, eng.total + 1)
    user_vec = teams[:, user - 1, :]
    opp = teams[:, prob.opp_seats - 1, :]
    return ecw_vs(user_vec, opp, cfg), eng.roster_matrix(user), eng


def run_scenarios(ctx: AdvisorContext, log: DraftLog, *, n_sims: int | None = None,
                  seed: int | None = None, top: int = 5, progress=None) -> ScenarioResult:
    t0 = time.perf_counter()
    cfg = ctx.config
    S = int(n_sims or cfg.model.advisor.scenario_full_sims)
    seed = ctx.seed if seed is None else int(seed)
    P, rosters, _ = rollout_to_end(ctx, log, S, seed, progress=progress)   # (S, T−1, n_cat)
    cat_p = P.mean(axis=1)
    ecw = P.sum(axis=-1).mean(axis=-1)
    cats = list(cfg.categories)
    lost = cfg.model.matchup.lost_threshold
    groups: dict[tuple[str, ...], list[int]] = defaultdict(list)
    for s in range(S):
        sig = tuple(c for c, p in zip(cats, cat_p[s]) if p < lost)
        groups[sig].append(s)
    names = ctx.dataset.names()
    out = []
    for sig, members in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:top]:
        m = np.array(members)
        typical = m[np.argmin(np.abs(ecw[m] - ecw[m].mean()))]
        ids = [str(ctx.universe.ids[i]) for i in rosters[typical] if i >= 0]
        out.append(Archetype(signature=sig, label=archetype_label(sig), frequency=len(m) / S,
                             mean_ecw=float(ecw[m].mean()), cat_p=cat_p[m].mean(axis=0),
                             typical_roster=[str(names.get(p, p)) for p in ids]))
    return ScenarioResult(archetypes=out, n_sims=S, seed=seed, elapsed=time.perf_counter() - t0)


#: Karşılaştırılan planlar: dengeli, tek kategori punt'ları ve yaygın ikili punt'lar.
COMMON_PAIRS = (("FT_PCT", "TOV"), ("FG_PCT", "FT_PCT"), ("FG3M", "FT_PCT"), ("AST", "TOV"), ("PTS", "FG3M"),
                ("BLK", "REB"))


@dataclass
class PlanResult:
    table: pd.DataFrame          # plan, E[W], fark (dengeliye göre, CRN) ± SE, P10, P90, kategori P'leri
    n_sims: int
    seed: int
    elapsed: float

    @property
    def best(self) -> pd.Series:
        return self.table.iloc[0]


def compare_punt_plans(ctx: AdvisorContext, log: DraftLog, *, n_sims: int = 100, seed: int | None = None,
                       plans=None, custom_weights: dict[str, float] | None = None, progress=None) -> PlanResult:
    """Her plan aynı ``n_sims`` draft senaryosunda (CRN) sona kadar oynanır; kullanıcının sonraki pick'leri
    plandaki punt dışı kategorilerin beklenen galibiyetini en büyükler. Final kadro 9 kategoriyle
    değerlendirilir: E[W] (rakip başına beklenen kategori galibiyeti) ve dengeli plana göre eşleşmeli fark.
    ``custom_weights``: kullanıcının strateji ağırlıkları "benim stratejim" planı olarak eklenir."""
    t0 = time.perf_counter()
    cfg = ctx.config
    seed = ctx.seed if seed is None else int(seed)
    cats = list(cfg.categories)
    if plans is None:
        plans = [(), *((c,) for c in cats), *(p for p in COMMON_PAIRS if set(p) <= set(cats))]
    plans = [tuple(p) for p in plans]
    if custom_weights:
        plans.append("custom")
    W = {}
    rows = []
    for i, plan in enumerate(plans):
        if progress:
            progress("Plan", i + 1, len(plans))
        if plan == "custom":
            P, _, _ = rollout_to_end(ctx, log, n_sims, seed, weights=custom_weights)
            label = "benim stratejim"
        else:
            P, _, _ = rollout_to_end(ctx, log, n_sims, seed, punt=plan)
            label = archetype_label(plan).replace(" benzeri", "") if plan else "dengeli"
        W[plan] = P.sum(axis=-1).mean(axis=-1)                      # (S,)
        rows.append({"plan": label,
                     "punt": plan, "E[W]": float(W[plan].mean()),
                     "P10": float(np.quantile(W[plan], 0.1)), "P90": float(np.quantile(W[plan], 0.9)),
                     **{CATEGORY_LABELS.get(c, c): float(v) for c, v in zip(cats, P.mean(axis=(0, 1)))}})
    base = W[()]
    for r in rows:
        d = W[r["punt"]] - base
        r["fark"] = float(d.mean())
        r["fark_SE"] = float(d.std(ddof=1) / np.sqrt(len(d))) if len(d) > 1 else 0.0
    table = pd.DataFrame(rows).sort_values("E[W]", ascending=False).reset_index(drop=True)
    cols = ["plan", "E[W]", "fark", "fark_SE", "P10", "P90", *[CATEGORY_LABELS.get(c, c) for c in cats], "punt"]
    return PlanResult(table=table[cols], n_sims=n_sims, seed=seed, elapsed=time.perf_counter() - t0)
