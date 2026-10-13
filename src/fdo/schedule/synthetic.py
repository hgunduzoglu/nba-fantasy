"""Sentetik NBA takvimi (testler ve demo için; gerçek takvim değildir)."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

#: Varsayımsal gün yükü (Pzt..Paz ortalama maç), ``scripts/estimate_utilization.py`` ile aynı.
DAY_GAMES = (8, 6, 9, 5, 8, 6, 7)


def synthetic_schedule(teams: list[str], start: dt.date, rng: np.random.Generator, *,
                       games_per_team: int = 82, max_days: int = 175) -> pd.DataFrame:
    """Her takım ~``games_per_team`` maç; aynı gün bir takım en fazla bir maç oynar.

    Gün ``d``'de takım, kalan maç / kalan gün oranı ve gün yüküyle orantılı olasılıkla
    seçilir; seçilenler rastgele eşlenir.
    """
    n = len(teams)
    left = np.full(n, games_per_team)
    load = np.asarray(DAY_GAMES, float) / np.mean(DAY_GAMES)
    rows = []
    for day in range(max_days):
        if left.sum() < 2:
            break
        date = start + dt.timedelta(days=day)
        p = np.clip(left / max(1, max_days - day) * load[date.weekday()], 0, 1)
        pick = np.flatnonzero((rng.random(n) < p) & (left > 0))
        rng.shuffle(pick)
        for a, b in zip(pick[0::2], pick[1::2]):
            home, away = (a, b) if rng.random() < 0.5 else (b, a)
            rows.append({"game_date": date.isoformat(), "home_team": teams[home], "away_team": teams[away],
                         "game_id": f"SYN{len(rows) + 1:05d}"})
            left[[a, b]] -= 1
    return pd.DataFrame(rows)
