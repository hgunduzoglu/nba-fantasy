"""Simülasyon gerçekçiliği metrikleri (README §7).

Bot parametreleri **yalnızca** bu ölçümler üzerinden ayarlanır. Hedef değerler
gerçek veriyle doğrulanmamıştır; gerçek draft log'u olmadan "botlar Yahoo
insanları gibi seçiyor" iddiasında bulunulmaz.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import stats

from fdo.bots.thurstone import BatchDraft
from fdo.bots.universe import BotUniverse
from fdo.config import Config, RealismParams
from fdo.roster.assignment import RosterModel
from fdo.types import POSITIONS


@dataclass
class MockBatch:
    pick_player: np.ndarray           # (M, total)
    order: np.ndarray                 # (total,) seat
    profiles: np.ndarray              # (M, T) profil adları
    seed: int
    consistency: dict = field(default_factory=dict)

    @property
    def n_mocks(self) -> int:
        return self.pick_player.shape[0]


def run_mock_batch(universe: BotUniverse, config: Config, n_mocks: int, seed: int,
                   chunk: int = 250, progress=None) -> MockBatch:
    """``n_mocks`` tam bot draft'ı (kullanıcı koltuğu dahil) üretir."""
    picks, profiles = [], []
    top1 = ranks = 0
    n_bot_picks = 0
    for start in range(0, n_mocks, chunk):
        m = min(chunk, n_mocks - start)
        b = BatchDraft(universe, config, m, seed, sim_offset=start)
        b.run_until(b.total + 1)
        picks.append(b.pick_player.copy())
        profiles.append(np.array([b.profile_names(r) for r in range(m)], dtype=object))
        t1, rk, nb = _consistency(b)
        top1 += t1
        ranks += rk
        n_bot_picks += nb
        if progress:
            progress(min(start + m, n_mocks), n_mocks)
    return MockBatch(
        pick_player=np.vstack(picks), order=b.order, profiles=np.vstack(profiles), seed=seed,
        consistency={"top1_agreement": top1 / max(n_bot_picks, 1),
                     "mean_perceived_rank": ranks / max(n_bot_picks, 1)},
    )


def _consistency(b: BatchDraft) -> tuple[int, float, int]:
    """Seçilen oyuncunun, botun kalıcı algılanan sırasındaki (uygunlar arası) yeri."""
    top1, rank_sum, n = 0, 0.0, 0
    rows = np.arange(b.S)
    for k in range(1, b.total + 1):
        seat_i = b.order[k - 1] - 1
        chosen = b.pick_player[:, k - 1]
        avail = (b.taken_at == 0) | (b.taken_at >= k)
        q = b.q_raw[:, seat_i, :]
        qc = q[rows, chosen]
        better = np.sum(avail & (q < qc[:, None]), axis=1)
        top1 += int(np.sum(better == 0))
        rank_sum += float(np.sum(better))
        n += b.S
    return top1, rank_sum, n


# --------------------------------------------------------------------------
# pick bazında tablo
# --------------------------------------------------------------------------

def pick_table(batch: MockBatch, universe: BotUniverse, teams: int) -> pd.DataFrame:
    M, total = batch.pick_player.shape
    pk = np.tile(np.arange(1, total + 1), M)
    pl = batch.pick_player.ravel()
    A = universe.adp[pl]
    sig = universe.sigma[pl]
    return pd.DataFrame({
        "mock": np.repeat(np.arange(M), total),
        "pick": pk,
        "round": (pk - 1) // teams + 1,
        "seat": np.tile(batch.order, M),
        "player": pl,
        "A": A,
        "sigma": sig,
        "pick_minus_A": pk - A,
        "z_reach": (A - pk) / sig,
        "status": universe.status[pl],
    })


def reach_class(z_reach: float, params: RealismParams) -> str:
    """Board rengi: ``bad`` (> 2.5σ erken), ``warn`` (1.5–2.5σ), ``slide`` (2.5σ geç), ``neutral``."""
    if z_reach > params.reach_z_bad:
        return "bad"
    if z_reach > params.reach_z_warn:
        return "warn"
    if -z_reach > params.slide_z:
        return "slide"
    return "neutral"


def round_distribution(pt: pd.DataFrame, params: RealismParams) -> pd.DataFrame:
    g = pt.groupby("round")
    return pd.DataFrame({
        "median": g["pick_minus_A"].median(),
        "p10": g["pick_minus_A"].quantile(0.10),
        "p90": g["pick_minus_A"].quantile(0.90),
        "bad_reach_rate": g["z_reach"].apply(lambda z: float(np.mean(z > params.reach_z_bad))),
        "warn_reach_rate": g["z_reach"].apply(
            lambda z: float(np.mean((z > params.reach_z_warn) & (z <= params.reach_z_bad)))),
        "slide_rate": g["z_reach"].apply(lambda z: float(np.mean(-z > params.slide_z))),
    })


def extreme_reach(batch: MockBatch, universe: BotUniverse, params: RealismParams,
                  teams: int) -> dict:
    """ADP ≈ merkez ± yarı genişlik oyuncuların ilk ``teams`` pick'te gitme sıklığı."""
    lo = params.extreme_adp_center - params.extreme_adp_halfwidth
    hi = params.extreme_adp_center + params.extreme_adp_halfwidth
    targets = np.flatnonzero((universe.adp >= lo) & (universe.adp <= hi))
    first = batch.pick_player[:, :teams]
    hits = np.isin(first, targets).sum()
    denom = batch.n_mocks * max(len(targets), 1)
    return {"adp_range": (lo, hi), "n_players": int(len(targets)), "hits": int(hits),
            "rate_per_player_mock": hits / denom}


def diversity(batch: MockBatch, top_n: int, max_pairs: int = 2000, seed: int = 0) -> dict:
    M = batch.n_mocks
    if M < 2:
        return {"jaccard_mean": np.nan, "kendall_tau_mean": np.nan, "pairs": 0}
    rng = np.random.default_rng(seed)
    all_pairs = M * (M - 1) // 2
    if all_pairs <= max_pairs:
        pairs = [(i, j) for i in range(M) for j in range(i + 1, M)]
    else:
        a = rng.integers(0, M, max_pairs * 2)
        b = rng.integers(0, M, max_pairs * 2)
        pairs = [(i, j) for i, j in zip(a, b) if i != j][:max_pairs]
    top = batch.pick_player[:, :top_n]
    jac, taus = [], []
    for i, j in pairs:
        si, sj = set(top[i]), set(top[j])
        inter = si & sj
        jac.append(len(inter) / len(si | sj))
        if len(inter) >= 3:
            pi = {p: k for k, p in enumerate(top[i])}
            pj = {p: k for k, p in enumerate(top[j])}
            common = sorted(inter)
            tau = stats.kendalltau([pi[p] for p in common], [pj[p] for p in common]).statistic
            if not np.isnan(tau):
                taus.append(tau)
    return {"jaccard_mean": float(np.mean(jac)), "kendall_tau_mean": float(np.mean(taus)) if taus else np.nan,
            "pairs": len(pairs)}


def position_distribution(batch: MockBatch, universe: BotUniverse, teams: int) -> pd.DataFrame:
    """Tur bazında pozisyon payları (çoklu pozisyon eşit bölünür)."""
    G = len(universe.groups)
    share = np.zeros((G, len(POSITIONS)))
    for g, grp in enumerate(universe.groups):
        for p in grp:
            share[g, POSITIONS.index(p)] = 1.0 / len(grp)
    groups = universe.group[batch.pick_player]                  # (M, total)
    rounds = (np.arange(batch.pick_player.shape[1]) // teams) + 1
    rows = []
    for r in np.unique(rounds):
        gsel = groups[:, rounds == r].ravel()
        rows.append(share[gsel].mean(axis=0))
    return pd.DataFrame(rows, index=pd.Index(np.unique(rounds), name="round"), columns=list(POSITIONS))


def incomplete_rosters(batch: MockBatch, universe: BotUniverse, config: Config) -> int:
    model = RosterModel(config)
    n = 0
    for seat in range(1, config.league.teams + 1):
        cols = np.flatnonzero(batch.order == seat)
        for row in batch.pick_player[:, cols]:
            pos = [universe.groups[universe.group[p]] for p in row]
            if model.open_active_count(pos) > 0:
                n += 1
    return n


def profile_reach(pt: pd.DataFrame, batch: MockBatch, params: RealismParams) -> pd.DataFrame:
    prof = batch.profiles[pt["mock"].to_numpy(), pt["seat"].to_numpy() - 1]
    df = pt.assign(profile=prof)
    g = df.groupby("profile")
    return pd.DataFrame({
        "picks": g.size(),
        "median_pick_minus_A": g["pick_minus_A"].median(),
        "bad_reach_rate": g["z_reach"].apply(lambda z: float(np.mean(z > params.reach_z_bad))),
    })


def compare_external(pt: pd.DataFrame, external: pd.DataFrame, universe: BotUniverse) -> dict:
    """Gerçek draft log'u ile ``pick − A`` dağılımı KS testi (opsiyonel, V2 kalibrasyon girdisi)."""
    ext = external[external["player_id"].isin(universe.index)]
    if ext.empty:
        return {"n_external": 0}
    A = universe.adp[[universe.index[p] for p in ext["player_id"]]]
    ext_diff = ext["overall_pick"].to_numpy(float) - A
    res = stats.ks_2samp(pt["pick_minus_A"].to_numpy(), ext_diff)
    return {"n_external": int(len(ext)), "ks_statistic": float(res.statistic),
            "p_value": float(res.pvalue)}


@dataclass
class RealismMetrics:
    rounds: pd.DataFrame
    extreme: dict
    diversity: dict
    positions: pd.DataFrame
    incomplete: int
    consistency: dict
    profiles: pd.DataFrame
    worst_reaches: pd.DataFrame
    n_mocks: int
    seed: int
    external: dict | None = None


def compute_metrics(batch: MockBatch, universe: BotUniverse, config: Config,
                    external: pd.DataFrame | None = None) -> RealismMetrics:
    params = config.model.realism
    teams = config.league.teams
    pt = pick_table(batch, universe, teams)
    worst = (pt.sort_values("z_reach", ascending=False).head(25)
             .assign(player_id=lambda d: universe.ids[d["player"].to_numpy()])
             [["mock", "pick", "round", "seat", "player_id", "A", "sigma", "z_reach", "status"]])
    return RealismMetrics(
        rounds=round_distribution(pt, params),
        extreme=extreme_reach(batch, universe, params, teams),
        diversity=diversity(batch, params.diversity_top_n),
        positions=position_distribution(batch, universe, teams),
        incomplete=incomplete_rosters(batch, universe, config),
        consistency=batch.consistency,
        profiles=profile_reach(pt, batch, params),
        worst_reaches=worst.reset_index(drop=True),
        n_mocks=batch.n_mocks,
        seed=batch.seed,
        external=compare_external(pt, external, universe) if external is not None else None,
    )
