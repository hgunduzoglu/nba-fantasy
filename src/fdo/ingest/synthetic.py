"""Sentetik veri üretici (README §5.7).

* ``SYN_001 … SYN_n`` adlı oyuncular; gerçek ad, takım veya ID kullanılmaz (``nba_team = "SYN"``).
* İstatistikler parametrik bir modelden çekilir: dakika → hacim, pozisyon arketipine
  göre kategori profili, korelasyonlu gürültü. Gerçek oyunculardan kopyalanan değer yoktur.
* ``ADP``: dengeli değer sırası + N(0, σ(sıra)) gürültüsüyle bir pozisyon; kaynak 12 takımlı
  lig kapsamını taklit eder (% drafted, kesik ortalama ADP, kapsam dışı listelenmez).
* Her dosyada ``is_synthetic = true`` ve otomatik manifest bulunur.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from scipy import stats

from fdo.config import Config, load_config

POSITION_SHARES = {"PG": 0.20, "SG": 0.20, "SF": 0.18, "PF": 0.20, "C": 0.22}
MULTI_POSITION_SHARE = 0.35
SECOND_POSITION = {"PG": ["SG"], "SG": ["PG", "SF"], "SF": ["SG", "PF"], "PF": ["SF", "C"], "C": ["PF"]}

#: per-36 arketip profilleri:
#: fga, fg%, fta, ft%, 3PA payı, 3P%, reb, ast, stl, blk, tov
ARCHETYPES = {
    "PG": (15.0, 0.450, 4.5, 0.84, 0.40, 0.365, 4.5, 7.5, 1.40, 0.30, 3.0),
    "SG": (16.0, 0.450, 4.0, 0.83, 0.45, 0.370, 4.5, 4.0, 1.20, 0.40, 2.2),
    "SF": (14.0, 0.460, 3.8, 0.79, 0.38, 0.360, 6.5, 3.0, 1.20, 0.70, 2.0),
    "PF": (13.0, 0.490, 4.0, 0.75, 0.28, 0.350, 8.5, 2.5, 0.90, 1.00, 1.9),
    "C":  (12.0, 0.560, 4.5, 0.68, 0.08, 0.320, 11.5, 2.2, 0.80, 1.80, 2.1),
}

SYNTHETIC_SOURCE = "synthetic"
#: Taklit edilen ADP kaynağının kapsamı: 12 takım × 13 tur.
SOURCE_COVERAGE = 156.0


def _positions(n: int, rng: np.random.Generator) -> list[str]:
    names = list(POSITION_SHARES)
    primary = rng.choice(names, size=n, p=list(POSITION_SHARES.values()))
    out = []
    for p in primary:
        if rng.random() < MULTI_POSITION_SHARE:
            second = rng.choice(SECOND_POSITION[p])
            pair = sorted({p, second}, key=names.index)
            out.append(",".join(pair))
        else:
            out.append(str(p))
    return out


def _stats(primary: list[str], rng: np.random.Generator) -> pd.DataFrame:
    n = len(primary)
    talent = rng.standard_normal(n)
    minutes = np.clip(24 + 7 * talent + rng.normal(0, 2.5, n), 8, 38)
    usage = np.exp(0.15 * talent + rng.normal(0, 0.15, n))

    # korelasyonlu gürültü: fga, fta, reb, ast, stl, blk, tov
    corr = np.array([
        [1.0, 0.5, 0.0, 0.2, 0.1, 0.0, 0.5],
        [0.5, 1.0, 0.2, 0.1, 0.0, 0.1, 0.4],
        [0.0, 0.2, 1.0, -0.1, 0.0, 0.4, 0.0],
        [0.2, 0.1, -0.1, 1.0, 0.3, -0.1, 0.6],
        [0.1, 0.0, 0.0, 0.3, 1.0, 0.1, 0.1],
        [0.0, 0.1, 0.4, -0.1, 0.1, 1.0, 0.0],
        [0.5, 0.4, 0.0, 0.6, 0.1, 0.0, 1.0],
    ])
    sd = np.array([0.18, 0.30, 0.20, 0.30, 0.25, 0.40, 0.20])
    noise = np.exp(rng.multivariate_normal(np.zeros(7), corr * np.outer(sd, sd), size=n))

    prof = np.array([ARCHETYPES[p] for p in primary])
    scale = minutes / 36.0
    fga = prof[:, 0] * usage * noise[:, 0] * scale
    fg_pct = np.clip(prof[:, 1] + rng.normal(0, 0.025, n), 0.36, 0.68)
    fta = prof[:, 2] * usage * noise[:, 1] * scale
    ft_pct = np.clip(prof[:, 3] + rng.normal(0, 0.06, n), 0.45, 0.95)
    fg3a = fga * np.clip(prof[:, 4] * np.exp(rng.normal(0, 0.35, n)), 0, 0.75)
    fg3_pct = np.clip(prof[:, 5] + rng.normal(0, 0.03, n), 0.20, 0.45)

    fgm = np.round(fga * fg_pct, 2)
    fga = np.round(fga, 2)
    fg3m = np.round(np.minimum(fg3a * fg3_pct, fgm), 2)
    ftm = np.round(fta * ft_pct, 2)
    fta = np.round(fta, 2)
    gp = 82 - rng.exponential(6, n) - (rng.random(n) < 0.12) * rng.uniform(10, 40, n)
    return pd.DataFrame({
        "projected_gp": np.round(np.clip(gp, 20, 82), 1),
        "minutes": np.round(minutes, 1),
        "fgm": fgm, "fga": fga, "ftm": ftm, "fta": fta, "fg3m": fg3m,
        "pts": np.round(2 * fgm + fg3m + ftm, 2),
        "reb": np.round(prof[:, 6] * noise[:, 2] * scale, 2),
        "ast": np.round(prof[:, 7] * noise[:, 3] * scale, 2),
        "stl": np.round(prof[:, 8] * noise[:, 4] * scale, 2),
        "blk": np.round(prof[:, 9] * noise[:, 5] * scale, 2),
        "tov": np.round(prof[:, 10] * usage * noise[:, 6] * scale, 2),
    })


def synthetic_frames(n_players: int, rng: np.random.Generator, config: Config | None = None,
                     as_of: str | None = None) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """``(players, projections, adp)`` DataFrame'leri."""
    from fdo.valuation import balanced_value_rank

    config = config or load_config()
    as_of = as_of or dt.date.today().isoformat()
    width = max(3, len(str(n_players)))
    ids = [f"p_{i:04d}" for i in range(1, n_players + 1)]
    positions = _positions(n_players, rng)
    players = pd.DataFrame({
        "player_id": ids,
        "name": [f"SYN_{i:0{width}d}" for i in range(1, n_players + 1)],
        "nba_team": "SYN",
        "yahoo_positions": positions,
        "is_synthetic": True,
    })
    proj = _stats([p.split(",")[0] for p in positions], rng)
    proj.insert(0, "player_id", ids)
    proj["projection_source"] = SYNTHETIC_SOURCE
    proj["as_of"] = as_of
    proj["is_synthetic"] = True

    rank = balanced_value_rank(proj, config).reindex(ids).to_numpy(float)
    sigma = 1.5 + 0.12 * rank
    # ADP bir "ortalama pick pozisyonu"dur: gürültülü sıranın pozisyonu alınır, böylece
    # k. en küçük ADP ≈ k olur (bağımsız gürültü ADP ölçeğini sola kaydırırdı).
    noisy = rank + rng.normal(0, sigma)
    position = np.argsort(np.argsort(noisy)) + 1.0 + rng.uniform(-0.3, 0.3, n_players)
    # Kaynak, Yahoo Draft Analysis gibi çoğunlukla 12 takımlı liglerden derlenir: oyuncunun
    # pick pozisyonu ~ N(position, σ); yalnızca kapsam (12×13 pick) içinde seçildiği liglerde
    # sayılır. % drafted = P(pozisyon ≤ C); ADP = kesik ortalama E[pozisyon | pozisyon ≤ C];
    # %2'nin altındakiler listelenmez.
    beta = (SOURCE_COVERAGE - position) / sigma
    cdf = np.clip(stats.norm.cdf(beta), 1e-12, 1.0)
    lam = stats.norm.pdf(beta) / cdf
    pct = 100.0 * cdf
    adp = np.maximum(1.0, position - sigma * lam)
    std = sigma * np.sqrt(np.clip(1.0 - beta * lam - lam ** 2, 0.01, None))
    missing = pct < 2.0
    default_order = np.argsort(np.argsort(position + rng.normal(0, 2.0, n_players))) + 1.0
    adp_df = pd.DataFrame({
        "player_id": ids,
        "adp": np.where(missing, np.nan, np.round(adp, 1)),
        "adp_std": np.where(missing, np.nan, np.round(std, 2)),
        "adp_min": np.where(missing, np.nan, np.round(np.maximum(1, adp - 2 * std), 0)),
        "adp_max": np.where(missing, np.nan, np.round(adp + 2 * std, 0)),
        "pct_drafted": np.where(missing, np.nan, np.round(pct, 1)),
        "default_rank": default_order,
        "adp_source": SYNTHETIC_SOURCE,
        "adp_window": "synthetic",
        "as_of": as_of,
        "is_synthetic": True,
    })
    return players, proj, adp_df


def synthetic_manifest(kind: str, file: str, as_of: str, seed: int | None) -> dict:
    return {
        "file": file,
        "kind": kind,
        "source_name": SYNTHETIC_SOURCE,
        "source_url": None,
        "retrieved_at": as_of,
        "retrieved_by": f"scripts/make_synthetic.py (seed={seed})",
        "license_status": "personal_use_confirmed",
        "license_notes": "Repo içinde üretilen sentetik veri; gerçek oyuncu değeri değildir.",
        "season": None,
        "basis": "per_game",
        "is_synthetic": True,
    }


def make_synthetic(n_players: int, rng: np.random.Generator, config: Config | None = None,
                   as_of: str | None = None, seed: int | None = None):
    """Bellek içi sentetik ``Dataset`` (dosya yazmadan)."""
    from fdo.ingest.load import build_dataset

    config = config or load_config()
    as_of = as_of or dt.date.today().isoformat()
    players, proj, adp = synthetic_frames(n_players, rng, config, as_of)
    manifests = {k: synthetic_manifest(k, f"<memory>/{k}.csv", as_of, seed)
                 for k in ("players", "projections", "adp")}
    ds, report = build_dataset(players, proj, adp, config, manifests=manifests,
                               reference_date=dt.date.fromisoformat(as_of))
    if ds is None:
        raise RuntimeError(f"Sentetik veri doğrulanamadı: {report.errors}")
    return ds


def write_synthetic(out_dir: str | Path, n_players: int, seed: int, config: Config | None = None,
                    as_of: str | None = None) -> dict[str, Path]:
    """CSV'leri ve manifest'leri ``out_dir`` (ve ``out_dir/manifests``) altına yazar."""
    out = Path(out_dir)
    (out / "manifests").mkdir(parents=True, exist_ok=True)
    as_of = as_of or dt.date.today().isoformat()
    frames = synthetic_frames(n_players, np.random.default_rng(seed), config, as_of)
    paths = {}
    for kind, df in zip(("players", "projections", "adp"), frames):
        path = out / f"{kind}_synthetic.csv"
        df.to_csv(path, index=False)
        manifest = synthetic_manifest(kind, path.as_posix(), as_of, seed)
        with open(out / "manifests" / f"{path.name}.yaml", "w", encoding="utf-8") as f:
            yaml.safe_dump(manifest, f, sort_keys=False, allow_unicode=True)
        paths[kind] = path
    return paths
