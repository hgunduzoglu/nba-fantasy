"""Rakip stratejisi tahmini: koltuk başına bot profili sonrası (posterior) (README §6.4.4).

Gözlenen her rakip pick'i ``(k, koltuk b, oyuncu i)`` için, o andaki gerçek draft durumunda
(kadrolar, pozisyon kuralı, punt durumu) her profil ``p`` ile ``M`` bağımsız Thurstone çekilişi
yapılır ve botun ``i``'yi seçme frekansı ``f_p`` ölçülür. Olabilirlik ``ε + (1−ε)·f_p``
(``ε``: modelin açıklayamadığı seçimlere tolerans), sonrası ``∝ öncel · Π olabilirlik``;
öncel lig bot karışımıdır (``bots.mix``).

Yaklaşım: profil gürültüsü her pick'te yeniden çekilir (gerçek botta kalıcıdır), yani pick'ler
koşullu bağımsız sayılır; bu, sonrasını biraz fazla keskinleştirebilir (``temper`` < 1 yumuşatır).

Punt tahmini profilden bağımsızdır: koltuğun kadrosunun dengeli kategori z toplamında en zayıf
kategori, ikinci en zayıftan belirgin geride ise (``punt_gap``) "olası punt" sayılır.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from fdo.bots.league_mix import mix_list
from fdo.bots.thurstone import BatchDraft, scaled_t
from fdo.bots.universe import BotUniverse
from fdo.config import Config
from fdo.draft.events import DraftLog


@dataclass
class OpponentModel:
    names: tuple[str, ...]
    prior: np.ndarray                 # (P,)
    loglik: np.ndarray                # (T, P)
    n_picks: np.ndarray               # (T,) değerlendirilen pick sayısı
    z_sum: np.ndarray                 # (T, n_cat) kadro dengeli z toplamı
    categories: tuple[str, ...]
    user_seat: int
    temper: float = 1.0
    punt_gap: float = 1.5

    @property
    def posterior(self) -> np.ndarray:
        """``(T, P)``; kullanıcı koltuğu için öncel."""
        logp = np.log(np.where(self.prior > 0, self.prior, 1e-300))[None, :] + self.temper * self.loglik
        logp = np.where(self.prior[None, :] > 0, logp, -np.inf)
        logp -= logp.max(axis=1, keepdims=True)
        w = np.exp(logp)
        return w / w.sum(axis=1, keepdims=True)

    def seat_probs(self) -> np.ndarray:
        """Simülasyonlarda kullanılacak ``(T, P)``; kullanıcı koltuğu satırı sıfır (motor atar)."""
        p = self.posterior.copy()
        p[self.user_seat - 1] = 0.0
        return p

    def punt_guess(self, seat: int) -> tuple[str | None, float]:
        z = self.z_sum[seat - 1]
        if self.n_picks[seat - 1] < 3 or not np.isfinite(z).all():
            return None, 0.0
        order = np.argsort(z)
        gap = float(z[order[1]] - z[order[0]])
        return (self.categories[order[0]] if gap >= self.punt_gap else None), gap

    def table(self, seat_names: dict[int, str] | None = None) -> pd.DataFrame:
        post = self.posterior
        rows = []
        for t in range(post.shape[0]):
            seat = t + 1
            if seat == self.user_seat:
                continue
            best = int(np.argmax(post[t]))
            punt, gap = self.punt_guess(seat)
            rows.append({"seat": seat, "takım": (seat_names or {}).get(seat, f"S{seat}"),
                         "pick": int(self.n_picks[t]), "en olası profil": self.names[best],
                         "olasılık": float(post[t, best]), "olası punt": punt or "—",
                         **{n: float(post[t, j]) for j, n in enumerate(self.names) if self.prior[j] > 0}})
        return pd.DataFrame(rows)


def mix_prior(config: Config, names: tuple[str, ...]) -> np.ndarray:
    labels = mix_list(config)
    prior = np.array([labels.count(n) for n in names], dtype=float)
    return prior / prior.sum()


@dataclass
class ProfileTracker:
    """Artımlı çıkarım: log uzadıkça yalnızca yeni pick'ler işlenir; geri alınırsa baştan kurulur."""

    universe: BotUniverse
    config: Config
    n_draws: int = 200
    seed: int = 0
    floor: float = 0.02
    temper: float = 1.0
    picks: tuple[str, ...] = field(default=(), init=False)
    model: OpponentModel | None = field(default=None, init=False)

    def __post_init__(self):
        self._reset()

    def _reset(self) -> None:
        cfg, u = self.config, self.universe
        self.engine = BatchDraft(u, cfg, self.n_draws, self.seed)
        pt = self.engine.ptab
        self.names = pt.names
        self.prior = mix_prior(cfg, pt.names)
        rng = np.random.default_rng(self.seed + 1)
        self.q = {}
        for p in np.flatnonzero(self.prior > 0):
            base = u.default_rank if pt.uses_default_rank[p] else u.adp
            eps = scaled_t(rng, pt.t_df[p], (self.n_draws, u.n))
            self.q[int(p)] = base[None, :] + u.sigma[None, :] * pt.sigma_mult[p] * eps
        T = cfg.league.teams
        self.loglik = np.zeros((T, len(pt.names)))
        self.n_picks = np.zeros(T, dtype=int)
        self.picks = ()

    def update(self, log: DraftLog) -> OpponentModel:
        ids = tuple(p.player_id for p in log.picks)
        if ids[: len(self.picks)] != self.picks:
            self._reset()
        eng, u = self.engine, self.universe
        user = self.config.league.my_seat
        for p in log.picks[len(self.picks):]:
            i = u.index[p.player_id]
            seat_i = p.seat - 1
            if p.seat != user:
                for prof, q in self.q.items():
                    eng.profile[:, seat_i] = prof
                    eng.q_raw[:, seat_i, :] = q
                    score, ok = eng.scores()
                    choice = np.argmin(np.where(ok, score, np.inf), axis=1)
                    f = float(np.mean(choice == i))
                    self.loglik[seat_i, prof] += np.log(self.floor + (1 - self.floor) * f)
                self.n_picks[seat_i] += 1
            eng.force(i)
        self.picks = ids
        self.model = OpponentModel(names=self.names, prior=self.prior, loglik=self.loglik.copy(),
                                   n_picks=self.n_picks.copy(), z_sum=eng.z_sum[0].copy(),
                                   categories=u.categories, user_seat=user, temper=self.temper)
        return self.model
