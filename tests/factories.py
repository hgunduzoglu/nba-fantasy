"""Testler için küçük, elle kurulan veri parçaları."""

from __future__ import annotations

import pandas as pd

from fdo.types import STATS


def proj_row(pid: str, gp: float = 70.0, *, fgm=5.0, fga=10.0, ftm=2.0, fta=2.5, fg3m=1.5,
             pts=None, reb=5.0, ast=3.0, stl=1.0, blk=0.5, tov=2.0) -> dict:
    if pts is None:
        pts = 2 * fgm + fg3m + ftm
    return dict(player_id=pid, projected_gp=gp, minutes=30.0, fgm=fgm, fga=fga, ftm=ftm, fta=fta,
                fg3m=fg3m, pts=pts, reb=reb, ast=ast, stl=stl, blk=blk, tov=tov,
                projection_source="test", as_of="2026-10-01", is_synthetic=True)


def proj_frame(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    for s in ("projected_gp", "minutes", *STATS):
        df[s] = df[s].astype(float)
    return df


def varied_projections(n: int = 60, seed: int = 0) -> pd.DataFrame:
    import numpy as np

    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        fga = rng.uniform(4, 20)
        fgm = fga * rng.uniform(0.40, 0.58)
        fta = rng.uniform(1, 8)
        ftm = fta * rng.uniform(0.6, 0.9)
        fg3m = min(fgm, rng.uniform(0, 3))
        rows.append(proj_row(f"p_{i:04d}", gp=rng.uniform(50, 80), fgm=fgm, fga=fga, ftm=ftm,
                             fta=fta, fg3m=fg3m, reb=rng.uniform(2, 12), ast=rng.uniform(1, 9),
                             stl=rng.uniform(0.4, 2), blk=rng.uniform(0.1, 2.5),
                             tov=rng.uniform(0.8, 4)))
    return proj_frame(rows)
