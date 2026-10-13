"""Oyuncu haftalık ortalama ve varyansı (README §6.6.1–§6.6.2).

Bu modül yalnızca projeksiyonları ve opsiyonel varyans dosyasını okur.
Kategori ağırlıklarını ve ADP'yi okumaz.

Haftalık vektör düzeni (``WEEK_DIM = 24``):

* ``0..6``  : sayma statlarının haftalık ortalaması (fg3m, pts, reb, ast, stl, blk, tov)
* ``7..13`` : aynı statların haftalık varyansı
* ``14..18``: FG bileşenleri ``M_fgm, M_fga, a, b, c``
* ``19..23``: FT bileşenleri ``M_ftm, M_fta, a, b, c``

Oran kategorisi için, ``r`` referans oranı ile ``Y = FGM − r·FGA``:

``Var_week(Y; r) = a − 2·r·b + r²·c`` burada (maç başına ``p = FGM/FGA``, ``v = Var(FGA)``)
``a = k·(FGA·p(1−p) + p²·v)``, ``b = k·p·v``, ``c = k·v``.
Bu bileşenler doğrusal olduğundan takım toplamı basit toplamadır.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from fdo.config import Config, MatchupParams
from fdo.types import STATS

COUNT_STATS: tuple[str, ...] = ("fg3m", "pts", "reb", "ast", "stl", "blk", "tov")
N_COUNT = len(COUNT_STATS)
MEAN_SLICE = slice(0, N_COUNT)
VAR_SLICE = slice(N_COUNT, 2 * N_COUNT)
RATIO_OFFSETS: dict[str, int] = {"fg": 2 * N_COUNT, "ft": 2 * N_COUNT + 5}
WEEK_DIM = 2 * N_COUNT + 10


def per_game_variance(proj: pd.DataFrame, variance: pd.DataFrame | None,
                      phi: dict[str, float]) -> tuple[pd.DataFrame, pd.Series]:
    """Maç başına varyans tablosu (index ``player_id``, kolonlar ``STATS``).

    Varyans dosyası yoksa aşırı yayılımlı Poisson varsayılanı ``φ_s · x_s`` kullanılır.
    İkinci dönüş değeri, oyuncunun tüm statları dosyadan geliyorsa ``True`` olan maskedir.
    """
    x = proj.set_index("player_id")[list(STATS)].astype(float)
    phis = np.array([float(phi.get(s, 1.0)) for s in STATS])
    var = x * phis
    calibrated = pd.Series(False, index=x.index)
    if variance is not None and len(variance):
        v = variance[variance["player_id"].isin(x.index) & variance["stat"].isin(STATS)]
        if len(v):
            wide = v.pivot_table(index="player_id", columns="stat", values="per_game_var",
                                 aggfunc="last")
            for stat in wide.columns:
                col = wide[stat].dropna()
                var.loc[col.index, stat] = col.values
            full = wide.reindex(columns=list(STATS)).notna().all(axis=1)
            calibrated.loc[full[full].index] = True
    return var, calibrated


def ratio_game_variance(makes, attempts, att_var, r):
    """``Var_game(Y) = FGA·p(1−p) + (p − r)²·Var(FGA)`` (FGA=0 → 0)."""
    makes = np.asarray(makes, dtype=float)
    attempts = np.asarray(attempts, dtype=float)
    p = np.divide(makes, attempts, out=np.zeros_like(makes), where=attempts > 0)
    return attempts * p * (1 - p) + (p - r) ** 2 * np.asarray(att_var, dtype=float)


def weekly_games(projected_gp, params: MatchupParams, games_per_week=None):
    """``k_i = utilization · G_i · min(gp, cap)/cap``.

    ``G_i`` takvim yoksa sabit ``games_per_week``; takvim varsa oyuncunun takımının eşleşme
    başına ortalama maç sayısıdır (V2, §13.4).
    """
    gp = np.minimum(np.asarray(projected_gp, dtype=float), params.games_cap)
    g = params.games_per_week if games_per_week is None else np.asarray(games_per_week, dtype=float)
    return params.utilization * g * gp / params.games_cap


def weekly_vectors(proj: pd.DataFrame, var_pg: pd.DataFrame, config: Config,
                   games: pd.Series | None = None, games_var: pd.Series | None = None) -> pd.DataFrame:
    """Oyuncu başına 24 boyutlu haftalık vektör (index ``player_id``).

    ``games`` / ``games_var``: oyuncu → takımın eşleşme başına maç sayısı ortalaması ve varyansı
    (takvimden). ``matchup.games_variance`` açıksa sayılan maç ``N = c·g`` (``c = utilization·a``)
    rastgele kabul edilir: ``Var(X) = E[N]·σ² + Var(N)·μ²``; oran bileşenlerine de aynı terim
    eklenir. Oyuncular arası maç sayısı kovaryansı (aynı hafta) modellenmez.
    """
    mp = config.model.matchup
    p = proj.set_index("player_id")
    v = var_pg.reindex(p.index)
    g = None if games is None else games.reindex(p.index).fillna(mp.games_per_week).to_numpy(float)
    k = weekly_games(p["projected_gp"].to_numpy(), mp, g)
    kv = np.zeros(len(p))
    if mp.games_variance and games_var is not None:
        c = k / (g if g is not None else mp.games_per_week)
        kv = c ** 2 * games_var.reindex(p.index).fillna(0.0).to_numpy(float)
    out = np.zeros((len(p), WEEK_DIM))
    for j, s in enumerate(COUNT_STATS):
        mu = p[s].to_numpy(float)
        out[:, j] = k * mu
        out[:, N_COUNT + j] = k * v[s].to_numpy(float) + kv * mu ** 2
    for key, (makes, att) in {"fg": ("fgm", "fga"), "ft": ("ftm", "fta")}.items():
        o = RATIO_OFFSETS[key]
        m = p[makes].to_numpy(float)
        a_ = p[att].to_numpy(float)
        va = v[att].to_numpy(float)
        pr = np.divide(m, a_, out=np.zeros_like(m), where=a_ > 0)
        out[:, o + 0] = k * m
        out[:, o + 1] = k * a_
        out[:, o + 2] = k * (a_ * pr * (1 - pr) + pr ** 2 * va) + kv * m ** 2
        out[:, o + 3] = k * pr * va + kv * m * a_
        out[:, o + 4] = k * va + kv * a_ ** 2
    return pd.DataFrame(out, index=p.index)


def ratio_mean_var(vec: np.ndarray, key: str, r) -> tuple[np.ndarray, np.ndarray]:
    """Haftalık (takım) vektöründen ``E[Y]`` ve ``Var(Y)``; ``r`` yayınlanabilir."""
    o = RATIO_OFFSETS[key]
    m, a_, A, B, C = (vec[..., o + i] for i in range(5))
    return m - r * a_, A - 2 * r * B + r * r * C
