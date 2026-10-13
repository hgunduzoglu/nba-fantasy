"""Gerçek draft log'larından bot kalibrasyonu (README §13.6).

Log'lar farklı büyüklükte bir ligden gelebilir (``league_config``): simülasyon o ligin takım ve tur
sayısıyla yapılır; ``pick − A`` sapması pick sırası (kaçıncı seçilen oyuncu) üzerinden ölçüldüğü için
σ₀/σ₁ lig büyüklüğüne büyük ölçüde taşınır. Yahoo'nun otomatik seçtiği pick'ler (``import:auto``)
draft'ta kalır ama momentlere girmez.

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


def league_config(config: Config, teams: int, rounds: int | None = None) -> Config:
    """Farklı büyüklükteki lig log'ları için config (ör. Yahoo'da 16 takımlı mock yok, 14 var).

    Bot karışımı ``teams − 1`` rakibe en büyük kalan yöntemiyle ölçeklenir; kadro slot toplamı
    ``rounds``'a eşit olacak şekilde bench (``BN``) ayarlanır; kullanıcı koltuğu lige sığdırılır.
    """
    lg = config.league
    rounds = int(rounds or lg.rounds)
    if teams == lg.teams and rounds == lg.rounds:
        return config
    mix = {k: int(v) for k, v in config.model.bots.mix.items()}
    total = sum(mix.values())
    quota = {k: v * (teams - 1) / total for k, v in mix.items()}
    new = {k: int(np.floor(q)) for k, q in quota.items()}
    for k in sorted(quota, key=lambda k: -(quota[k] - new[k]))[: teams - 1 - sum(new.values())]:
        new[k] += 1
    slots = dict(config.roster.slots)
    bn = rounds - sum(n for s, n in slots.items() if s != "BN")
    if bn < 0:
        raise ValueError(f"{rounds} tur aktif slotları ({rounds - bn}) dolduramaz")
    slots["BN"] = bn
    return config.with_overrides({"league": {"teams": int(teams), "rounds": rounds,
                                             "my_seat": min(lg.my_seat, int(teams))},
                                  "roster": {"slots": slots}, "model": {"bots": {"mix": new}}})


def auto_mask(logs: list[DraftLog]) -> np.ndarray:
    """``(L, total)``: momentlerden dışlanan pick'ler — Yahoo'nun otomatik seçtikleri (``import:auto``) ve
    kullanıcının kendi pick'leri (``import:user``; strateji denemesi, rakip davranışı değil)."""
    total = logs[0].total_picks if logs else 0
    out = np.zeros((len(logs), total), dtype=bool)
    for row, log in enumerate(logs):
        for p in log.picks:
            out[row, p.overall_pick - 1] = p.source.startswith(("import:auto", "import:user"))
    return out


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


def deviation_moments(matrix: np.ndarray, universe: BotUniverse, band_size: int = 16,
                      exclude: np.ndarray | None = None) -> pd.DataFrame:
    """ADP bandı başına ``pick − A`` dağılımı: n, P10, P50, P90 (``exclude`` maskesindeki pick'ler hariç)."""
    total = matrix.shape[1]
    valid = matrix >= 0 if exclude is None else (matrix >= 0) & ~exclude
    rows, ks = np.nonzero(valid)
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
    grid: pd.DataFrame              # sigma0, sigma1, brier, moment_loss
    best: dict[str, float]
    observed: pd.DataFrame          # gözlenen momentler
    fitted: pd.DataFrame            # en iyi parametrelerle simülasyon momentleri
    current: pd.DataFrame           # mevcut config ile simülasyon momentleri
    n_logs: int
    missing_picks: int
    #: σ'sı σ₀ + σ₁·A ile belirlenen (``adp_std``'si olmayan) oyuncu payı; düşükse uyum zayıftır
    param_share: float = 1.0
    auto_picks: int = 0


def survival_brier(sim_matrix: np.ndarray, obs_matrix: np.ndarray, universe: BotUniverse, *,
                   step: int = 6, window: float = 40.0, max_adp: float = 200.0) -> float:
    """Sabit değerlendirme kümesinde ``P(uygun @ n)`` Brier skoru.

    Kontrol pick'leri ``n = 10, 10+step, …``; her ``n``'de ADP'si ``n ± window`` içinde (ve ≤ ``max_adp``)
    olan **tüm** oyuncular. Küme tahminden bağımsızdır, bu yüzden farklı σ'lar karşılaştırılabilir
    (``survival_reliability``'deki 0.01–0.99 süzgeci σ ile değişir, karşılaştırmaya uygun değildir).
    """
    st = taken_pick(sim_matrix, universe.n)
    ot = taken_pick(obs_matrix, universe.n)
    players = np.flatnonzero(universe.adp <= max_adp)
    out = []
    for n in range(10, obs_matrix.shape[1] + 1, step):
        sel = players[np.abs(universe.adp[players] - n) <= window]
        p = ((st[:, sel] == 0) | (st[:, sel] >= n)).mean(axis=0)
        o = ((ot[:, sel] == 0) | (ot[:, sel] >= n)).astype(float)
        out.append(((p - o) ** 2).ravel())
    return float(np.concatenate(out).mean()) if out else float("nan")


def fit_sigma(logs: list[DraftLog], dataset: Dataset, universe: BotUniverse, config: Config, *,
              sigma0_grid=(0.5, 1.5, 3.0, 5.0), sigma1_grid=(0.08, 0.12, 0.18, 0.25, 0.35),
              n_sims: int = 60, seed: int = 1, band_size: int = 16, objective: str = "brier",
              progress=None) -> BotFit:
    """``objective = "brier"`` (varsayılan): sabit kümede survival Brier'i en küçük nokta — advisor'ın
    kullandığı büyüklük. ``"moments"``: ``pick − A`` momentleri; gerçek log'larda (11 draft, 14 takım)
    σ'yı fazla daraltıp survival'ı kötüleştirdiği görüldü (README §13.6)."""
    if objective not in ("brier", "moments"):
        raise ValueError("objective: brier | moments")
    obs_mat, missing = logs_to_matrix(logs, universe)
    auto = auto_mask(logs)
    obs = deviation_moments(obs_mat, universe, band_size, exclude=auto)
    rows = []
    sims: dict[tuple[float, float], pd.DataFrame] = {}
    grid = list(itertools.product(sigma0_grid, sigma1_grid))
    for i, (s0, s1) in enumerate(grid):
        if progress:
            progress(i + 1, len(grid))
        cfg = config.with_overrides({"model": {"bots": {"sigma0": float(s0), "sigma1": float(s1)}}})
        mat = simulate_matrix(with_sigma(universe, dataset, cfg), cfg, n_sims, seed)
        mom = deviation_moments(mat, universe, band_size)
        sims[(s0, s1)] = mom
        rows.append({"sigma0": s0, "sigma1": s1, "brier": survival_brier(mat, obs_mat, universe),
                     "moment_loss": moment_loss(obs, mom)})
    key = "brier" if objective == "brier" else "moment_loss"
    table = pd.DataFrame(rows).sort_values(key, kind="mergesort").reset_index(drop=True)
    b = table.iloc[0]
    current = deviation_moments(simulate_matrix(universe, config, n_sims, seed), universe, band_size)
    std = dataset.adp.reindex(universe.ids).get("adp_std")
    share = float(std.isna().mean()) if std is not None else 1.0
    return BotFit(grid=table, best={"sigma0": float(b["sigma0"]), "sigma1": float(b["sigma1"])},
                  observed=obs, fitted=sims[(b["sigma0"], b["sigma1"])], current=current,
                  n_logs=len(logs), missing_picks=missing, param_share=share, auto_picks=int(auto.sum()))


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


def autopick_rule_matches(df: pd.DataFrame, log: DraftLog, universe: BotUniverse, positions,
                          config: Config) -> np.ndarray:
    """Her pick Yahoo'nun otomatik seçim kuralına birebir uyuyor mu: kadroyu tamamlanabilir bırakan
    oyuncular arasında Yahoo ön sıralaması (``default_rank`` = xrank) en iyi olan.

    Gerçek log'larda "Team N" (Yahoo botu) pick'lerinin %91.5'i bu kurala uyar; gerçek lig draft'ındaki
    insanların %17'si. ``df`` satırları ``log.picks`` ile aynı sıradadır ve ``fantasy_team`` içerir.
    """
    from fdo.roster.assignment import RosterModel

    model = RosterModel(config)
    rounds = config.league.rounds
    taken: set[str] = set()
    rosters: dict[str, list] = {}
    out = np.zeros(len(log.picks), dtype=bool)
    order = np.lexsort((universe.adp, universe.default_rank))
    for j, (p, team) in enumerate(zip(log.picks, df["fantasy_team"])):
        roster = rosters.setdefault(team, [])
        remaining = rounds - len(roster) - 1
        for i in order:
            pid = str(universe.ids[i])
            if pid in taken:
                continue
            if model.can_complete([*roster, positions[pid]], remaining):
                out[j] = pid == p.player_id
                break
        taken.add(p.player_id)
        if p.player_id in positions:
            roster.append(positions[p.player_id])
    return out


def infer_autopicks(df: pd.DataFrame, matches: np.ndarray, min_run: int = 3) -> np.ndarray:
    """Adı olan (insan görünen) takımlarda Yahoo kuralına art arda ``min_run`` kez birebir uyan seriler
    otomatik sayılır (mock'tan ayrılan ya da hiç gelmeyen menajer). Gerçek lig draft'ında insanların
    kurala uyma oranı ~%17 olduğundan 3'lü serinin tesadüf olasılığı ~%0.5'tir."""
    out = np.zeros(len(df), dtype=bool)
    for _, idx in df.groupby("fantasy_team", sort=False).groups.items():
        idx = np.sort(np.asarray(idx))
        m = matches[idx]
        start = None
        for k in range(len(idx) + 1):
            if k < len(idx) and m[k]:
                start = k if start is None else start
                continue
            if start is not None and k - start >= min_run:
                out[idx[start:k]] = True
            start = None
    return out
