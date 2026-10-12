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


def run_scenarios(ctx: AdvisorContext, log: DraftLog, *, n_sims: int | None = None,
                  seed: int | None = None, top: int = 5, progress=None) -> ScenarioResult:
    t0 = time.perf_counter()
    cfg = ctx.config
    adv = cfg.model.advisor
    lg = cfg.league
    S = int(n_sims or adv.scenario_full_sims)
    seed = ctx.seed if seed is None else int(seed)
    prob = setup_problem(ctx, log, ctx.base_fill)
    user = prob.user
    eng = make_engine(ctx, log, S, sub_seed(seed, STREAM_SCENARIO), cache_jitter=False)
    vecs, fill = ctx.vecs, ctx.base_fill
    turns = [t for t in turns_for_seat(user, lg.teams, lg.rounds, lg.third_round_reversal)
             if t[-1] >= eng.k]
    all_user_picks = [n for t in turns for n in t]

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
            single = prob.ecw_static(base[None, :] + fill.sum(turn[1:]) + vecs[idx])
            short = idx[np.argsort(-single, kind="stable")[: adv.next_policy_top_l]]
            combos = list(itertools.combinations(short.tolist(), len(turn)))
            V = np.stack([vecs[list(c)].sum(axis=0) for c in combos])
            best = combos[int(np.argmax(prob.ecw_static(base[None, :] + V)))]
            choices[s, : len(best)] = best
        for j in range(len(turn)):
            eng.force(choices[:, j])
    eng.run_until(eng.total + 1)

    teams = team_vectors(eng, vecs, fill, eng.total + 1)
    user_vec = teams[:, user - 1, :]
    opp = teams[:, prob.opp_seats - 1, :]
    P = ecw_vs(user_vec, opp, cfg)                      # (S, T−1, n_cat)
    cat_p = P.mean(axis=1)
    ecw = P.sum(axis=-1).mean(axis=-1)
    cats = list(cfg.categories)
    lost = cfg.model.matchup.lost_threshold
    groups: dict[tuple[str, ...], list[int]] = defaultdict(list)
    for s in range(S):
        sig = tuple(c for c, p in zip(cats, cat_p[s]) if p < lost)
        groups[sig].append(s)
    names = ctx.dataset.names()
    rosters = eng.roster_matrix(user)
    out = []
    for sig, members in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:top]:
        m = np.array(members)
        typical = m[np.argmin(np.abs(ecw[m] - ecw[m].mean()))]
        ids = [str(ctx.universe.ids[i]) for i in rosters[typical] if i >= 0]
        out.append(Archetype(signature=sig, label=archetype_label(sig), frequency=len(m) / S,
                             mean_ecw=float(ecw[m].mean()), cat_p=cat_p[m].mean(axis=0),
                             typical_roster=[str(names.get(p, p)) for p in ids]))
    return ScenarioResult(archetypes=out, n_sims=S, seed=seed, elapsed=time.perf_counter() - t0)
