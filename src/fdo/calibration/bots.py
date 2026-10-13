"""Gerçek draft log'larından bot kalibrasyonu (README §13.6).

**σ₀, σ₁ uyumu (simülasyonlu momentler yöntemi).** σ₀/σ₁ yalnızca ``adp_std``'si olmayan
oyuncuların σ'sını belirler (Yahoo verisinde hepsi; §6.4.1). Gözlenen log'larda her seçilen oyuncu için
``d = pick − A`` hesaplanır; ``A`` bandına göre (``band_size`` pick) ``d``'nin P10/P50/P90'ı
hedef momentlerdir. Bir ``(σ₀, σ₁)`` ızgarasının her noktasında aynı seed'le (CRN) ``n_sims``
tam bot draft'ı simüle edilir ve aynı momentler hesaplanır. Kayıp, band gözlem sayısıyla
ağırlıklı karesel farktır. Draft'ta seçilmeyen oyuncular (sansürlü) iki tarafta da dışlanır.

**Survival güvenilirliği.** Kontrol pick'lerinde (varsayılan: kullanıcının pick'leri)
``P(oyuncu n. pick'te hâlâ uygun)`` tahmini simülasyonlardan, gerçekleşen değer log'lardan
alınır; tahmin aralıklarına göre gözlenen frekans ve Brier skoru raporlanır.
"""

from __future__ import annotations

import dataclasses
import itertools
from dataclasses import dataclass

import numpy as np
import pandas as pd

from fdo.bots.thurstone import BatchDraft
from fdo.bots.universe import BotUniverse, player_sigma
from fdo.config import Config
from fdo.draft.events import DraftLog
from fdo.draft.order import picks_for_seat
from fdo.ingest.load import Dataset

QUANTILES = (0.1, 0.5, 0.9)


def logs_to_matrix(logs: list[DraftLog], universe: BotUniverse) -> tuple[np.ndarray, int]:
    """``(L, total)`` evren indeksleri (-1 = boş ya da evrende olmayan oyuncu) ve atlanan pick sayısı."""
    total = logs[0].total_picks if logs else 0
    out = np.full((len(logs), total), -1, dtype=np.int64)
    missing = 0
    for row, log in enumerate(logs):
        for p in log.picks:
            i = universe.index.get(p.player_id)
            if i is None:
                missing += 1
            else:
                out[row, p.overall_pick - 1] = i
    return out, missing


def taken_pick(matrix: np.ndarray, n_players: int) -> np.ndarray:
    """``(M, n)``: oyuncunun seçildiği pick (seçilmediyse 0)."""
    M, total = matrix.shape
    out = np.zeros((M, n_players), dtype=np.int64)
    rows, ks = np.nonzero(matrix >= 0)
    out[rows, matrix[rows, ks]] = ks + 1
    return out


def deviation_moments(matrix: np.ndarray, universe: BotUniverse, band_size: int = 16) -> pd.DataFrame:
    """ADP bandı başına ``pick − A`` dağılımı: n, P10, P50, P90."""
    total = matrix.shape[1]
    rows, ks = np.nonzero(matrix >= 0)
    players = matrix[rows, ks]
    a = universe.adp[players]
    d = (ks + 1) - a
    keep = a <= total
    band = ((np.ceil(a[keep]) - 1) // band_size).astype(int)
    df = pd.DataFrame({"band": band, "d": d[keep]})
    g = df.groupby("band")["d"]
    out = pd.DataFrame({"n": g.size(), **{f"p{int(q * 100)}": g.quantile(q) for q in QUANTILES}})
    out.index = [f"{b * band_size + 1}–{(b + 1) * band_size}" for b in out.index]
    return out


def moment_loss(obs: pd.DataFrame, sim: pd.DataFrame) -> float:
    cols = [f"p{int(q * 100)}" for q in QUANTILES]
    common = obs.index.intersection(sim.index)
    if len(common) == 0:
        return float("inf")
    diff = (obs.loc[common, cols] - sim.loc[common, cols]) ** 2
    w = obs.loc[common, "n"] / obs.loc[common, "n"].sum()
    return float((diff.sum(axis=1) * w).sum())


def with_sigma(universe: BotUniverse, dataset: Dataset, config: Config) -> BotUniverse:
    return dataclasses.replace(universe, sigma=player_sigma(dataset.adp.reindex(universe.ids), config))


def simulate_matrix(universe: BotUniverse, config: Config, n_sims: int, seed: int) -> np.ndarray:
    eng = BatchDraft(universe, config, n_sims, seed)
    eng.run_until(eng.total + 1)
    return eng.pick_player.copy()


@dataclass
class BotFit:
    grid: pd.DataFrame              # sigma0, sigma1, loss
    best: dict[str, float]
    observed: pd.DataFrame          # gözlenen momentler
    fitted: pd.DataFrame            # en iyi parametrelerle simülasyon momentleri
    current: pd.DataFrame           # mevcut config ile simülasyon momentleri
    n_logs: int
    missing_picks: int
    #: σ'sı σ₀ + σ₁·A ile belirlenen (``adp_std``'si olmayan) oyuncu payı; düşükse uyum zayıftır
    param_share: float = 1.0


def fit_sigma(logs: list[DraftLog], dataset: Dataset, universe: BotUniverse, config: Config, *,
              sigma0_grid=(0.5, 1.0, 1.5, 2.5, 4.0), sigma1_grid=(0.04, 0.08, 0.12, 0.18, 0.25),
              n_sims: int = 60, seed: int = 1, band_size: int = 16, progress=None) -> BotFit:
    obs_mat, missing = logs_to_matrix(logs, universe)
    obs = deviation_moments(obs_mat, universe, band_size)
    rows = []
    sims: dict[tuple[float, float], pd.DataFrame] = {}
    grid = list(itertools.product(sigma0_grid, sigma1_grid))
    for i, (s0, s1) in enumerate(grid):
        if progress:
            progress(i + 1, len(grid))
        cfg = config.with_overrides({"model": {"bots": {"sigma0": float(s0), "sigma1": float(s1)}}})
        mom = deviation_moments(simulate_matrix(with_sigma(universe, dataset, cfg), cfg, n_sims, seed),
                                universe, band_size)
        sims[(s0, s1)] = mom
        rows.append({"sigma0": s0, "sigma1": s1, "loss": moment_loss(obs, mom)})
    table = pd.DataFrame(rows).sort_values("loss", kind="mergesort").reset_index(drop=True)
    b = table.iloc[0]
    current = deviation_moments(simulate_matrix(universe, config, n_sims, seed), universe, band_size)
    std = dataset.adp.reindex(universe.ids).get("adp_std")
    share = float(std.isna().mean()) if std is not None else 1.0
    return BotFit(grid=table, best={"sigma0": float(b["sigma0"]), "sigma1": float(b["sigma1"])},
                  observed=obs, fitted=sims[(b["sigma0"], b["sigma1"])], current=current,
                  n_logs=len(logs), missing_picks=missing, param_share=share)


def survival_reliability(sim_matrix: np.ndarray, obs_matrix: np.ndarray, checkpoints, n_players: int, *,
                         n_bins: int = 10) -> tuple[pd.DataFrame, float]:
    """Tahmin edilen ``P(uygun @ n)`` aralıklarında gözlenen frekans; Brier skoru (0–1 arası tahminler)."""
    st = taken_pick(sim_matrix, n_players)
    ot = taken_pick(obs_matrix, n_players)
    preds, outs = [], []
    for n in checkpoints:
        p = ((st == 0) | (st >= n)).mean(axis=0)
        o = (ot == 0) | (ot >= n)
        mask = (p > 0.01) & (p < 0.99)
        preds.append(np.broadcast_to(p[mask], o[:, mask].shape).ravel())
        outs.append(o[:, mask].ravel().astype(float))
    pred = np.concatenate(preds) if preds else np.zeros(0)
    out = np.concatenate(outs) if outs else np.zeros(0)
    if len(pred) == 0:
        return pd.DataFrame(columns=["bin", "n", "predicted", "observed"]), float("nan")
    edges = np.linspace(0, 1, n_bins + 1)
    b = np.clip(np.digitize(pred, edges) - 1, 0, n_bins - 1)
    df = pd.DataFrame({"bin": b, "pred": pred, "obs": out})
    g = df.groupby("bin")
    table = pd.DataFrame({"n": g.size(), "predicted": g["pred"].mean(), "observed": g["obs"].mean()})
    table.index = [f"{edges[i]:.1f}–{edges[i + 1]:.1f}" for i in table.index]
    return table, float(np.mean((pred - out) ** 2))


def user_checkpoints(config: Config) -> list[int]:
    lg = config.league
    return picks_for_seat(lg.my_seat, lg.teams, lg.rounds, lg.third_round_reversal)


def matrix_to_logs(matrix: np.ndarray, universe: BotUniverse, config: Config, source: str = "import") -> list[DraftLog]:
    """Simülasyon seçim matrisinden ``DraftLog``'lar (testler ve sentetik log üretimi için)."""
    out = []
    for row in matrix:
        log = DraftLog.new(config)
        for i in row:
            if i < 0:
                break
            log = log.make_pick(str(universe.ids[i]), source)
        out.append(log)
    return out
