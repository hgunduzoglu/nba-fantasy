"""Sezon değerlendiricileri (README §13.1). ``SeasonEvaluator`` protokolünü uygular.

Her ikisi de **all-play** H2H skorlar: her hafta her takım diğer 15 takımla kategori bazında
karşılaştırılır (galibiyet 1, beraberlik ``tie_value``). ``category_wins[seat]`` eşleşme başına
ortalama kategori galibiyetidir (0–9; ECW ile aynı ölçek).

* ``ProjectionNoiseEvaluator`` — gerçekleşen değerler **simüle edilir**: oyuncunun gerçek maç başı
  üretimi projeksiyon × log-normal hata, maç oranı Beta; haftalık toplamlar normal yaklaşımla
  çekilir. Projeksiyon hatası modelden geldiği için sonuçlar **iyimserdir** (not olarak eklenir).
* ``GameLogEvaluator`` — gerçekleşen maç kayıtları: fantasy haftaları ``assign_weeks``; her gün
  oynayan oyuncular günlük lineup çözücüsüyle aktif slotlara yerleştirilir ve yalnızca sayılan
  maçlar toplanır.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from fdo.config import Config
from fdo.evaluation.interface import EvaluationResult
from fdo.matchup.ecw import category_specs
from fdo.matchup.player_week import COUNT_STATS, N_COUNT, RATIO_OFFSETS, per_game_variance, weekly_vectors
from fdo.schedule.calendar import assign_weeks
from fdo.schedule.lineup import active_eligibility, day_assignment
from fdo.types import COUNTING_CATEGORY_STAT, STATS


def category_table(weekly: dict[int, pd.DataFrame], config: Config) -> dict[int, pd.DataFrame]:
    """Takım → (hafta × kategori) değerleri; oranlar toplamdan."""
    out = {}
    for seat, w in weekly.items():
        cols = {}
        for spec in category_specs(config):
            if spec.kind == "count":
                cols[spec.name] = w[COUNTING_CATEGORY_STAT[spec.name]]
            else:
                mk, at = ("fgm", "fga") if spec.key == "fg" else ("ftm", "fta")
                cols[spec.name] = w[mk] / w[at].replace(0, np.nan)
        out[seat] = pd.DataFrame(cols)
    return out


def all_play(cats: dict[int, pd.DataFrame], config: Config, season: str, notes=()) -> EvaluationResult:
    seats = sorted(cats)
    tie = config.unverified.tie_value if config.unverified.tie_value is not None else 0.5
    names = list(config.categories)
    arr = np.stack([cats[s][names].to_numpy(float) for s in seats])          # (T, W, C)
    sign = np.array([-1.0 if c in config.lower_is_better else 1.0 for c in names])
    a = arr[:, None] * sign
    b = arr[None, :] * sign
    score = np.where(a > b, 1.0, np.where(a == b, tie, 0.0))
    score = np.where(np.isnan(a) | np.isnan(b), tie, score)                  # (T, T, W, C)
    T = len(seats)
    idx = np.arange(T)
    score[idx, idx] = np.nan
    per_cat = np.nanmean(score, axis=(1, 2))                                 # (T, C)
    res = EvaluationResult(season=season, notes=list(notes))
    for t, s in enumerate(seats):
        res.category_wins[s] = float(per_cat[t].sum())
        res.category_rates[s] = {c: float(per_cat[t, j]) for j, c in enumerate(names)}
    return res


class ProjectionNoiseEvaluator:
    """Gerçekleşen = projeksiyon + gürültü (iyimser). ``seed`` aynıysa aynı "gerçek sezon"."""

    def __init__(self, projections: pd.DataFrame, config: Config, *, seed: int = 0, weeks: int = 20,
                 projection_sd: float = 0.12, gp_kappa: float = 8.0, variance: pd.DataFrame | None = None):
        self.config = config
        self.weeks = weeks
        rng = np.random.default_rng(seed)
        proj = projections.set_index("player_id")
        n = len(proj)
        err = np.exp(projection_sd * rng.standard_normal(n) - projection_sd ** 2 / 2)
        cap = config.model.matchup.games_cap
        abar = np.clip(proj["projected_gp"].to_numpy(float) / cap, 0.05, 0.98)
        a = rng.beta(abar * gp_kappa, (1 - abar) * gp_kappa)
        true = proj.copy()
        for s in STATS:
            true[s] = proj[s] * err
        true["projected_gp"] = a * cap
        var, _ = per_game_variance(true.reset_index(), variance, config.model.variance.phi)
        self.vecs = weekly_vectors(true.reset_index(), var, config)
        self.rng = np.random.default_rng(seed + 1)

    def evaluate(self, rosters: dict[int, list[str]], season: str) -> EvaluationResult:
        weekly = {}
        for seat, ids in rosters.items():
            v = self.vecs.reindex([i for i in ids if i in self.vecs.index]).to_numpy().sum(axis=0)
            mean = {s: v[j] for j, s in enumerate(COUNT_STATS)}
            var = {s: v[N_COUNT + j] for j, s in enumerate(COUNT_STATS)}
            cols = {s: np.maximum(0, mean[s] + np.sqrt(max(var[s], 0)) * self.rng.standard_normal(self.weeks))
                    for s in mean}
            for key, (mk, at) in (("fg", ("fgm", "fga")), ("ft", ("ftm", "fta"))):
                o = RATIO_OFFSETS[key]
                m_mean, a_mean, A, B, C = v[o:o + 5]
                att = np.maximum(1e-9, a_mean + np.sqrt(max(C, 0)) * self.rng.standard_normal(self.weeks))
                p = m_mean / a_mean if a_mean > 0 else 0.0
                sd_m = np.sqrt(max(A - 2 * p * B + p * p * C, 0))      # Var(FGM − p·FGA)
                cols[at] = att
                cols[mk] = np.clip(p * att + sd_m * self.rng.standard_normal(self.weeks), 0, att)
            weekly[seat] = pd.DataFrame(cols)
        return all_play(category_table(weekly, self.config), self.config, season,
                        notes=["Gerçekleşen değerler projeksiyon + gürültüden simüle edildi (iyimser)."])


class GameLogEvaluator:
    """Gerçekleşen maç kayıtlarıyla haftalık all-play; günlük lineup çözücü (``daily_today``)."""

    def __init__(self, gamelogs: pd.DataFrame, positions: pd.Series, config: Config,
                 priority: pd.Series | None = None):
        self.config = config
        g = gamelogs.copy()
        g["game_date"] = pd.to_datetime(g["game_date"]).dt.normalize()
        g["week"] = assign_weeks(g["game_date"], config)
        self.logs = g
        self.positions = positions
        self.priority = priority

    def evaluate(self, rosters: dict[int, list[str]], season: str) -> EvaluationResult:
        weekly = {}
        weeks = sorted(self.logs["week"].unique())
        for seat, ids in rosters.items():
            ids = [i for i in ids if i in self.positions.index]
            elig = active_eligibility([self.positions[i] for i in ids], self.config)
            pr = None if self.priority is None else self.priority.reindex(ids).fillna(0).to_numpy(float)
            sub = self.logs[self.logs["player_id"].isin(ids)]
            counted = []
            for day, games in sub.groupby("game_date"):
                playing = np.isin(ids, games["player_id"].to_numpy())
                mask = day_assignment(elig, playing, pr)
                keep = set(np.asarray(ids)[mask])
                counted.append(games[games["player_id"].isin(keep)])
            c = pd.concat(counted) if counted else sub.iloc[:0]
            weekly[seat] = c.groupby("week")[list(STATS)].sum().reindex(weeks, fill_value=0.0)
        return all_play(category_table(weekly, self.config), self.config, season)
