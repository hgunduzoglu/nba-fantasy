"""Game log'larından varyans kalibrasyonu (README §13.2).

Girdi ``gamelogs`` şemasıdır (oyuncu × maç). Çıktılar:

* ``φ_s``: istatistik başına aşırı yayılım, oyuncu başına ``s²/μ`` oranlarının medyanı
  (en az ``min_games`` maçı olan, ortalaması pozitif oyuncular). Varyans dosyası olmayan
  oyuncular için ``Var = φ_s · μ`` varsayılanını besler (``model.variance.phi``).
* Oyuncu başına maç başı varyans: oran ``d = s²/μ``, ``φ_s``'ye doğru büzülür
  ``d̂ = ((n−1)·d + n₀·φ_s) / (n − 1 + n₀)``; projeksiyon verilirse ``Var = d̂ · μ_proj``
  (oyuncunun yeni rolüne ölçeklenir), yoksa ``d̂ · μ_log``. ``variance`` şemasında yazılır.
* Kategori korelasyonu: oyuncu içi standartlaştırılmış maç kalıntılarının havuzlanmış
  korelasyonu. Oran kategorileri ``makes − p̄·attempts``, TOV işaret ters (kazanma yönü).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from fdo.config import Config
from fdo.types import COUNTING_CATEGORY_STAT, STATS


@dataclass
class VarianceCalibration:
    phi: dict[str, float]
    variance: pd.DataFrame          # variance şeması: player_id, stat, per_game_var, n_games, seasons
    category_corr: pd.DataFrame     # kategori × kategori
    n_players: int
    n_games: int


def _clean(logs: pd.DataFrame, min_minutes: float) -> pd.DataFrame:
    df = logs.dropna(subset=list(STATS)).copy()
    if "minutes" in df and min_minutes > 0:
        df = df[df["minutes"].fillna(0) >= min_minutes]
    return df


def estimate_phi(logs: pd.DataFrame, min_games: int = 20) -> dict[str, float]:
    g = logs.groupby("player_id")
    n = g.size()
    ok = n[n >= min_games].index
    mean = g[list(STATS)].mean().loc[ok]
    var = g[list(STATS)].var(ddof=1).loc[ok]
    out = {}
    for s in STATS:
        r = (var[s] / mean[s])[mean[s] > 0].replace([np.inf, -np.inf], np.nan).dropna()
        out[s] = float(r.median()) if len(r) else 1.0
    return out


def player_variance(logs: pd.DataFrame, phi: dict[str, float], *, n0: float = 10.0,
                    projections: pd.DataFrame | None = None) -> pd.DataFrame:
    g = logs.groupby("player_id")
    n = g.size()
    mean = g[list(STATS)].mean()
    var = g[list(STATS)].var(ddof=1).fillna(0.0)
    seasons = g["season"].agg(lambda s: ",".join(sorted(set(map(str, s))))) if "season" in logs else None
    proj = projections.set_index("player_id")[list(STATS)] if projections is not None else None
    rows = []
    for pid in mean.index:
        k = float(n[pid])
        for s in STATS:
            mu = float(mean.loc[pid, s])
            d = float(var.loc[pid, s]) / mu if mu > 0 else phi[s]
            d_hat = ((k - 1) * d + n0 * phi[s]) / (k - 1 + n0)
            base = mu
            if proj is not None and pid in proj.index and pd.notna(proj.loc[pid, s]):
                base = float(proj.loc[pid, s])
            rows.append({"player_id": pid, "stat": s, "per_game_var": d_hat * base, "n_games": int(k),
                         "seasons": seasons[pid] if seasons is not None else ""})
    return pd.DataFrame(rows)


def category_contributions(logs: pd.DataFrame, config: Config) -> pd.DataFrame:
    """Maç başına kategori katkısı (kazanma yönünde): sayma statı, ``makes − p̄·att``, −TOV."""
    out = {}
    for cat in config.categories:
        if config.scoring.is_ratio(cat):
            spec = config.scoring.ratio_categories[cat]
            mk, at = spec["makes"].lower(), spec["attempts"].lower()
            pbar = logs[mk].sum() / logs[at].sum() if logs[at].sum() > 0 else 0.0
            out[cat] = logs[mk] - pbar * logs[at]
        else:
            out[cat] = logs[COUNTING_CATEGORY_STAT[cat]].astype(float)
        if cat in config.lower_is_better:
            out[cat] = -out[cat]
    return pd.DataFrame(out, index=logs.index)


def category_correlation(logs: pd.DataFrame, config: Config, min_games: int = 20) -> pd.DataFrame:
    contrib = category_contributions(logs, config)
    n = logs.groupby("player_id")["player_id"].transform("size")
    contrib = contrib[n >= min_games]
    pid = logs.loc[contrib.index, "player_id"]
    resid = contrib - contrib.groupby(pid).transform("mean")
    sd = contrib.groupby(pid).transform("std").replace(0, np.nan)
    z = (resid / sd).dropna()
    return z.corr().reindex(index=list(config.categories), columns=list(config.categories))


def calibrate(logs: pd.DataFrame, config: Config, *, min_games: int = 20, n0: float = 10.0,
              min_minutes: float = 0.0, projections: pd.DataFrame | None = None) -> VarianceCalibration:
    df = _clean(logs, min_minutes)
    phi = estimate_phi(df, min_games)
    var = player_variance(df, phi, n0=n0, projections=projections)
    corr = category_correlation(df, config, min_games)
    return VarianceCalibration(phi=phi, variance=var, category_corr=corr,
                               n_players=int(df["player_id"].nunique()), n_games=len(df))


def synthetic_gamelogs(projections: pd.DataFrame, n_games: int, rng: np.random.Generator, *,
                       dispersion: dict[str, float] | None = None, season: str = "SYN") -> pd.DataFrame:
    """Testler için: projeksiyon ortalamalı, ``Var = d_s · μ`` (negatif binom, d ≥ 1) maçlar.

    Atış statları tutarlı üretilir: ``FGM ~ Bin(FGA, p)``, ``FTM ~ Bin(FTA, p)``; puan
    ``2·FGM + FG3M + FTM``.
    """
    disp = {s: 1.0 for s in STATS} | (dispersion or {})
    rows = []
    base = pd.Timestamp("2025-10-21")

    def draw(mu: float, d: float) -> int:
        if mu <= 0:
            return 0
        if d <= 1.0 + 1e-9:
            return int(rng.poisson(mu))
        r = mu / (d - 1.0)
        return int(rng.negative_binomial(r, r / (r + mu)))

    for _, p in projections.iterrows():
        pfg = p["fgm"] / p["fga"] if p["fga"] > 0 else 0.0
        pft = p["ftm"] / p["fta"] if p["fta"] > 0 else 0.0
        p3 = min(1.0, p["fg3m"] / p["fgm"]) if p["fgm"] > 0 else 0.0
        for g in range(n_games):
            fga = draw(p["fga"], disp["fga"])
            fgm = int(rng.binomial(fga, pfg))
            fta = draw(p["fta"], disp["fta"])
            ftm = int(rng.binomial(fta, pft))
            fg3m = int(rng.binomial(fgm, p3))
            rows.append({"player_id": p["player_id"], "game_date": (base + pd.Timedelta(days=2 * g)).date().isoformat(),
                         "season": season, "fgm": fgm, "fga": fga, "ftm": ftm, "fta": fta, "fg3m": fg3m,
                         "pts": 2 * fgm + fg3m + ftm, "reb": draw(p["reb"], disp["reb"]),
                         "ast": draw(p["ast"], disp["ast"]), "stl": draw(p["stl"], disp["stl"]),
                         "blk": draw(p["blk"], disp["blk"]), "tov": draw(p["tov"], disp["tov"])})
    df = pd.DataFrame(rows)
    for s in STATS:
        df[s] = df[s].astype(float)
    return df
