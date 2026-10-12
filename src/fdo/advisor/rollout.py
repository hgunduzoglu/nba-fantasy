"""Sonraki turn'e kadar rollout ve miyopik politika π (README §6.7.3 adım 4, §6.7.4).

Her aday çift için (CRN ile, aynı ``S`` simülasyon):

1. ``a, b`` havuzdan çıkarılır (kullanıcı koltuğuna zorlanır),
2. ``u₁``'e kadar rakip pick'leri simüle edilir,
3. ``u₁`` anındaki uygun havuzdan π uygulanır: ΔECW'ye göre ilk ``L`` oyuncu
   arasından ECW'yi maksimize eden çift (miyopik),
4. ``W_s = ECW(R ∪ {a,b} ∪ π_s ∪ fill, rakipler: simüle kadrolar ∪ fill)``.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from fdo.advisor.simulate import AdvisorContext, team_vectors
from fdo.advisor.survival import go_pick_quantiles, survival
from fdo.bots.thurstone import BatchDraft
from fdo.matchup.ecw import ecw_vs, p_at_least
from fdo.matchup.fill import FillTable

NEG = -np.inf


@dataclass
class Problem:
    """Bir advisor çağrısının sabit girdileri."""

    ctx: AdvisorContext
    fill: FillTable
    user: int
    turn: tuple[int, ...]                  # mevcut turn'ün kalan pick'leri
    next_turn: tuple[int, ...] | None
    roster: np.ndarray                      # kullanıcının mevcut kadrosu (evren indeksleri)
    roster_vec: np.ndarray                  # (24,) gerçek oyuncular (+ projeksiyonsuzlar için fill)
    after_turn: tuple[int, ...]             # turn'den sonraki kullanıcı pick'leri
    after_next: tuple[int, ...]             # sonraki turn'den sonraki kullanıcı pick'leri
    opp_seats: np.ndarray                   # (T−1,) rakip koltukları
    opp_static: np.ndarray                  # (T−1, 24) mevcut kadro + doldurma
    available: np.ndarray                   # (n,) bool, mevcut state'te uygun

    def ecw_static(self, user_vecs: np.ndarray) -> np.ndarray:
        """Statik rakiplere karşı ECW, ``(..., 24)`` → ``(...)``."""
        p = ecw_vs(user_vecs, self.opp_static, self.ctx.config)
        return p.sum(axis=-1).mean(axis=-1)

    def fill_sum(self, picks) -> np.ndarray:
        return self.fill.sum(picks)


def delta_ecw(prob: Problem, base_vec: np.ndarray, compare_pick: int, mask: np.ndarray) -> np.ndarray:
    """``ΔECW(i | R) = ECW(R ∪ {i}) − ECW(R ∪ {F(n)})``; maskesiz/projeksiyonsuz → NaN."""
    ctx = prob.ctx
    out = np.full(ctx.universe.n, np.nan)
    idx = np.flatnonzero(mask & ctx.has_vec)
    if len(idx) == 0:
        return out
    ref = prob.ecw_static(base_vec + prob.fill.means[compare_pick])
    out[idx] = prob.ecw_static(base_vec[None, :] + ctx.vecs[idx]) - ref
    return out


@dataclass
class PolicySetup:
    shortlist: np.ndarray       # evren indeksleri, ΔECW'ye göre azalan
    delta: np.ndarray           # shortlist ΔECW değerleri
    values: np.ndarray          # |u|=2: (K, K) çift ECW (alt üçgen −∞); |u|=1: (K,)
    base_vec: np.ndarray        # π hariç kullanıcı vektörü (sonraki turn sonrası fill dahil)
    fallback_vec: np.ndarray    # π doldurma ile (shortlist yetmezse)


def policy_setup(prob: Problem, pair_vec: np.ndarray, available: np.ndarray) -> PolicySetup:
    """π için kısa liste: ``u₁``'de en az bir simülasyonda uygun olan (``available``)
    oyuncular arasından ``R ∪ {a, b}``'ye göre ΔECW sırasıyla ilk ``K``."""
    adv = prob.ctx.config.model.advisor
    u = prob.next_turn
    r2_vec = prob.roster_vec + pair_vec
    rest_after_u1 = [n for n in prob.after_turn if n != u[0]]
    single_base = r2_vec + prob.fill_sum(rest_after_u1)
    d = delta_ecw(prob, single_base, u[0], available)
    order = np.argsort(np.where(np.isnan(d), np.inf, -d), kind="stable")
    k = min(adv.policy_shortlist_k, int(np.sum(~np.isnan(d))))
    short = order[:k]
    base_u = r2_vec + prob.fill_sum(prob.after_next)
    V = prob.ctx.vecs[short]
    if len(u) == 2:
        vals = np.full((k, k), NEG)
        iu = np.triu_indices(k, 1)
        if len(iu[0]):
            vals[iu] = prob.ecw_static(base_u[None, :] + V[iu[0]] + V[iu[1]])
    else:
        vals = prob.ecw_static(base_u[None, :] + V) if k else np.zeros(0)
    fallback = base_u + prob.fill_sum(u)
    return PolicySetup(shortlist=short, delta=d[short], values=vals, base_vec=base_u,
                       fallback_vec=fallback)


def apply_policy(ps: PolicySetup, avail_short: np.ndarray, top_l: int, n_pick: int,
                 vecs: np.ndarray) -> tuple[np.ndarray, list[tuple[int, ...]]]:
    """Simülasyon başına π: ilk ``L`` uygun oyuncu arasından en iyi |u|'luk seçim."""
    S = avail_short.shape[0]
    in_l = avail_short & (np.cumsum(avail_short, axis=1) <= top_l)
    user = np.repeat(ps.fallback_vec[None, :], S, axis=0)
    choices: list[tuple[int, ...]] = [()] * S
    K = len(ps.shortlist)
    if K == 0:
        return user, choices
    if n_pick == 2:
        m = np.where(in_l[:, :, None] & in_l[:, None, :], ps.values[None, :, :], NEG)
        flat = m.reshape(S, -1)
        best = np.argmax(flat, axis=1)
        ok = np.isfinite(flat[np.arange(S), best])
        c, d = np.divmod(best, K)
        rows = np.flatnonzero(ok)
        user[rows] = ps.base_vec + vecs[ps.shortlist[c[rows]]] + vecs[ps.shortlist[d[rows]]]
        for r in rows:
            choices[r] = tuple(sorted((int(ps.shortlist[c[r]]), int(ps.shortlist[d[r]]))))
    else:
        m = np.where(in_l, ps.values[None, :], NEG)
        best = np.argmax(m, axis=1)
        ok = np.isfinite(m[np.arange(S), best])
        rows = np.flatnonzero(ok)
        user[rows] = ps.base_vec + vecs[ps.shortlist[best[rows]]]
        for r in rows:
            choices[r] = (int(ps.shortlist[best[r]]),)
    return user, choices


def largest_gap_tiers(values: np.ndarray, n_tiers: int) -> np.ndarray:
    """Azalan sıralı değerleri en büyük ``n_tiers − 1`` boşluktan kademelere böler (1-tabanlı)."""
    n = len(values)
    if n == 0:
        return np.zeros(0, dtype=int)
    gaps = values[:-1] - values[1:]
    cuts = np.sort(np.argsort(-gaps, kind="stable")[: max(0, min(n_tiers, n) - 1)])
    tiers = np.ones(n, dtype=int)
    for c in cuts:
        tiers[c + 1:] += 1
    return tiers


@dataclass
class RolloutOutcome:
    pair: tuple[int, ...]
    W: np.ndarray                       # (S,)
    cat_p: np.ndarray                   # (S, n_cat) rakip ortalaması
    pool: pd.DataFrame = field(default_factory=pd.DataFrame)
    pool_tiers: pd.DataFrame = field(default_factory=pd.DataFrame)
    next_choices: pd.DataFrame = field(default_factory=pd.DataFrame)
    survival: np.ndarray | None = None  # (n,) u₁ anında
    survival_se: np.ndarray | None = None
    #: P(≥5 kategori), rakip ortalaması — **bağımsızlık varsayar**, optimizasyonda kullanılmaz
    p_at_least_5: np.ndarray | None = None


def rollout_pair(prob: Problem, engine: BatchDraft, snap0: dict, pair: tuple[int, ...]) -> RolloutOutcome:
    ctx = prob.ctx
    cfg = ctx.config
    adv = cfg.model.advisor
    u = prob.next_turn
    engine.restore(snap0)
    for p in pair:
        engine.force(int(p))
    stop = u[0] if u else engine.total + 1
    engine.run_until(stop)

    pair_vec = ctx.vecs[list(pair)].sum(axis=0)
    out_pool = pd.DataFrame()
    out_tiers = pd.DataFrame()
    out_next = pd.DataFrame()
    surv = se = None
    if u:
        surv, se = survival(engine)
        ps = policy_setup(prob, pair_vec, surv > 0)
        avail_short = engine.taken_at[:, ps.shortlist] == 0
        user_vec, choices = apply_policy(ps, avail_short, adv.next_policy_top_l, len(u), ctx.vecs)
        out_pool, out_tiers = pool_tables(prob, engine, ps, surv, se)
        out_next = choice_table(choices, ctx)
    else:
        user_vec = np.repeat((prob.roster_vec + pair_vec + prob.fill_sum(prob.after_turn))[None, :],
                             engine.S, axis=0)

    teams = team_vectors(engine, ctx.vecs, prob.fill, stop)
    opp = teams[:, prob.opp_seats - 1, :]
    P = ecw_vs(user_vec, opp, cfg)                  # (S, T−1, n_cat)
    return RolloutOutcome(pair=tuple(int(p) for p in pair), W=P.sum(axis=-1).mean(axis=-1),
                          cat_p=P.mean(axis=1), pool=out_pool, pool_tiers=out_tiers,
                          next_choices=out_next, survival=surv, survival_se=se,
                          p_at_least_5=p_at_least(P, 5).mean(axis=1))


def pool_tables(prob: Problem, engine: BatchDraft, ps: PolicySetup, surv: np.ndarray,
                se: np.ndarray) -> tuple[pd.DataFrame, pd.DataFrame]:
    """"48/49 havuzu": uygunluk tablosu ve kademe görünümü (README §6.7.4 madde 1–2).

    Tablo, ``u₁``'de en az bir simülasyonda uygun olan oyuncular arasından ΔECW'ye göre
    ilk ``pool_table_size`` oyuncudur (kesin gidecek oyuncular havuzun parçası değildir).
    """
    ctx = prob.ctx
    adv = ctx.config.model.advisor
    u = ctx.universe
    top = ps.shortlist[: adv.pool_table_size]
    if len(top) == 0:
        return pd.DataFrame(), pd.DataFrame()
    q = go_pick_quantiles(engine.taken_at[:, top])
    names = ctx.dataset.names()
    pos = ctx.dataset.positions()
    ids = u.ids[top]
    tiers = largest_gap_tiers(ps.delta[: len(top)], adv.pool_tiers)
    pool = pd.DataFrame({
        "player_id": ids,
        "name": names.reindex(ids).to_numpy(),
        "positions": [",".join(sorted(p)) for p in pos.reindex(ids)],
        "delta_ecw": ps.delta[: len(top)],
        "tier": tiers,
        "p_surv": surv[top],
        "se": se[top],
        "adp_eff": u.adp[top],
        "adp_status": u.status[top],
        "go_p10": q[0],
        "go_p50": q[1],
        "go_p90": q[2],
    })
    avail = engine.taken_at[:, top] == 0                  # (S, m)
    rows = []
    for t in np.unique(tiers):
        cols = tiers == t
        cnt = avail[:, cols].sum(axis=1)
        rows.append({"tier": int(t), "players": int(cols.sum()),
                     "delta_ecw_max": float(ps.delta[: len(top)][cols].max()),
                     "expected_available": float(cnt.mean()),
                     "p_at_least_1": float(np.mean(cnt >= 1)),
                     "p_at_least_2": float(np.mean(cnt >= 2))})
    return pool, pd.DataFrame(rows)


def choice_table(choices: list[tuple[int, ...]], ctx: AdvisorContext, top: int = 10) -> pd.DataFrame:
    """π'nin seçtiği sonraki çiftlerin frekansı (README §6.7.4 madde 3)."""
    S = len(choices)
    cnt = Counter(c for c in choices if c)
    names = ctx.dataset.names()
    rows = []
    for combo, n in cnt.most_common(top):
        ids = [ctx.universe.ids[i] for i in combo]
        rows.append({"players": " + ".join(str(names.get(p, p)) for p in ids),
                     "player_ids": tuple(ids), "count": n, "probability": n / S})
    missing = sum(1 for c in choices if not c)
    if missing:
        rows.append({"players": "(doldurma — kısa listede yeterli oyuncu yok)", "player_ids": (),
                     "count": missing, "probability": missing / S})
    return pd.DataFrame(rows)
