"""Advisor simülasyon çekirdeği (README §6.7.1).

* ``S`` simülasyon; her simülasyonun kalıcı bot gürültüsü ve RNG akışı bir kez çekilir.
* **CRN:** farklı aday çiftler aynı ``S`` bot örneğiyle değerlendirilir (aynı seed,
  aynı ``(s, k)`` titreşimi). Çiftler arasındaki tek fark havuzdan çıkan oyunculardır.
* Seed hiyerarşisi: ``master_seed → simülasyon s → pick k``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from fdo.bots.mock import replay_into
from fdo.bots.thurstone import BatchDraft
from fdo.bots.universe import BotUniverse, build_universe
from fdo.config import Config
from fdo.draft.events import DraftLog
from fdo.ingest.load import Dataset
from fdo.matchup.fill import FillTable, fill_table_from_picks
from fdo.matchup.player_week import WEEK_DIM, per_game_variance, weekly_vectors
from fdo.schedule import build_calendar, player_games

#: Ana seed'den türetilen alt akışlar (birbirine karışmasın diye).
STREAM_ROLLOUT = 0
STREAM_FILL_BASE = 1
STREAM_FILL_COND = 2
STREAM_SCENARIO = 3
STREAM_UNCERTAINTY = 4      # V2 sakatlık/rol çarpanları (§13.5)


def sub_seed(seed: int, stream: int) -> int:
    return int(np.random.SeedSequence(seed, spawn_key=(10_000 + stream,)).generate_state(1)[0])


def player_vectors(dataset: Dataset, config: Config, universe: BotUniverse) -> tuple[np.ndarray, bool]:
    """Evren sırasıyla ``(n, 24)`` haftalık vektörler; projeksiyonsuz oyuncu satırı NaN.

    İkinci değer: varyans dosyasıyla tam kalibre edilmiş mi (değilse ``uncalibrated``).
    """
    var, calibrated = per_game_variance(dataset.projections, dataset.variance,
                                        config.model.variance.phi)
    games = games_var = None
    if dataset.schedule is not None:     # V2 (§13.4): takımın eşleşme başına maç sayısı
        cal = build_calendar(dataset.schedule, config)
        games, games_var, _ = player_games(dataset.players, cal, config)
    wv = weekly_vectors(dataset.projections, var, config, games, games_var)
    out = np.full((universe.n, WEEK_DIM), np.nan)
    rows = [universe.index[p] for p in wv.index if p in universe.index]
    out[rows] = wv.loc[[p for p in wv.index if p in universe.index]].to_numpy()
    return out, bool(len(calibrated) and calibrated.all())


@dataclass
class AdvisorContext:
    dataset: Dataset
    config: Config
    universe: BotUniverse
    vecs: np.ndarray                 # (n, 24), NaN = projeksiyon yok
    variance_calibrated: bool
    base_fill: FillTable
    seed: int

    @property
    def has_vec(self) -> np.ndarray:
        return ~np.isnan(self.vecs).any(axis=1)


def make_engine(ctx: AdvisorContext, log: DraftLog | None, n_sims: int, seed: int, *,
                cache_jitter: bool = True, sim_offset: int = 0,
                seat_profile_probs: np.ndarray | None = None) -> BatchDraft:
    eng = BatchDraft(ctx.universe, ctx.config, n_sims, seed, cache_jitter=cache_jitter, sim_offset=sim_offset,
                     seat_profile_probs=seat_profile_probs)
    if log is not None and len(log):
        replay_into(eng, [p.player_id for p in log.picks])
    return eng


def build_fill(universe: BotUniverse, config: Config, vecs: np.ndarray, n_sims: int, seed: int, *,
               log: DraftLog | None = None, base: FillTable | None = None,
               seat_profile_probs: np.ndarray | None = None) -> FillTable:
    """Tüm koltuklar bot iken tam draft simülasyonlarından doldurma tablosu.

    ``log`` verilirse mevcut state'ten başlanır (koşullu tablo, README §6.6.4).
    """
    eng = BatchDraft(universe, config, n_sims, seed, seat_profile_probs=seat_profile_probs)
    start = 1
    if log is not None and len(log):
        replay_into(eng, [p.player_id for p in log.picks])
        start = eng.k
    eng.run_until(eng.total + 1)
    return fill_table_from_picks(eng.pick_player, vecs, config.model.advisor.fill_smoothing_window,
                                 start_pick=start, base=base,
                                 source="conditional" if start > 1 else "base")


def prepare_context(dataset: Dataset, config: Config, seed: int, *,
                    universe: BotUniverse | None = None, fill_sims: int | None = None) -> AdvisorContext:
    """Evren, oyuncu vektörleri ve taban doldurma tablosu (önbelleklenmeye uygun)."""
    universe = universe or build_universe(dataset, config)
    vecs, calibrated = player_vectors(dataset, config, universe)
    n = fill_sims or config.model.advisor.fill_sims_base
    base = build_fill(universe, config, vecs, n, sub_seed(seed, STREAM_FILL_BASE))
    return AdvisorContext(dataset=dataset, config=config, universe=universe, vecs=vecs,
                          variance_calibrated=calibrated, base_fill=base, seed=seed)


def vec_or_fill(vecs: np.ndarray, players: np.ndarray, picks: np.ndarray, fill: FillTable) -> np.ndarray:
    """Oyuncu vektörü; projeksiyonsuz ya da boş (-1) seçimde o pick'in doldurma profili."""
    players = np.asarray(players)
    picks = np.broadcast_to(np.asarray(picks), players.shape)
    v = vecs[np.maximum(players, 0)]
    bad = (players < 0) | np.isnan(v).any(axis=-1)
    return np.where(bad[..., None], fill.means[picks], v)


def team_vectors(engine: BatchDraft, vecs: np.ndarray, fill: FillTable, upto: int,
                 mult: np.ndarray | None = None) -> np.ndarray:
    """``(S, T, 24)``: ``upto``'dan önceki seçimler (gerçek vektör) + kalan pick'ler (doldurma).

    ``mult (S, n)``: V2 senaryo çarpanları (§13.5); gerçek oyuncu vektörleri simülasyon başına ölçeklenir.
    """
    T, total = engine.T, engine.total
    upto = min(upto, total + 1)
    onehot = np.zeros((total, T))
    onehot[np.arange(total), engine.order - 1] = 1.0
    out = np.zeros((engine.S, T, WEEK_DIM))
    if upto > 1:
        picked = engine.pick_player[:, : upto - 1]
        ks = np.arange(1, upto)
        v = vec_or_fill(vecs, picked, ks[None, :], fill)
        if mult is not None:
            real = (picked >= 0) & ~np.isnan(vecs[np.maximum(picked, 0)]).any(axis=-1)
            m = np.take_along_axis(mult, np.maximum(picked, 0), axis=1)
            v = v * np.where(real, m, 1.0)[..., None]
        out += np.einsum("skd,kt->std", v, onehot[: upto - 1])
    if upto <= total:
        out += (onehot[upto - 1:].T @ fill.means[upto:])[None, :, :]
    return out


def simulate_until(engine: BatchDraft, until_pick: int, *, skip_seat: int | None = None) -> BatchDraft:
    """Rakip seçimlerini ``until_pick``'e kadar (hariç) simüle eder (yerinde)."""
    engine.run_until(until_pick, skip_seat=skip_seat)
    return engine
