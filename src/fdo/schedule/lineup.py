"""Günlük lineup çözücü (README §13.4).

``lineup_lock = daily_today`` için her gün o gün oynayan oyuncular aktif slotlara
pozisyon uygunluğuyla en büyük atama ile yerleştirilir (``linear_sum_assignment``).
Aktif slot sayısından fazla oyuncu oynuyorsa öncelik (ör. değer) yüksek olan sayılır.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment

from fdo.config import Config
from fdo.roster.eligibility import slot_instances
from fdo.schedule.calendar import SeasonCalendar, normalize_team


def active_eligibility(positions: list[frozenset[str]], config: Config) -> np.ndarray:
    """``(aktif slot, oyuncu)`` uygunluk matrisi."""
    slots = [s for s in slot_instances(config) if s in config.roster.active_slots]
    elig = config.roster.slot_eligibility
    return np.array([[bool(p & elig[s]) for p in positions] for s in slots], dtype=bool)


def day_assignment(elig: np.ndarray, playing: np.ndarray, priority: np.ndarray | None = None) -> np.ndarray:
    """Bir gün için aktif slota yerleşen oyuncu maskesi ``(m,)``."""
    m = elig.shape[1]
    out = np.zeros(m, dtype=bool)
    if not playing.any():
        return out
    pr = np.ones(m) if priority is None else 1.0 + 1e-3 * (priority - priority.min()) / (np.ptp(priority) or 1.0)
    w = elig * (playing * pr)[None, :]
    rows, cols = linear_sum_assignment(w, maximize=True)
    keep = w[rows, cols] > 0
    out[cols[keep]] = True
    return out


def counted_games(positions: list[frozenset[str]], playing: np.ndarray, config: Config,
                  priority: np.ndarray | None = None) -> np.ndarray:
    """``playing (gün, oyuncu)`` → oyuncu başına aktif slotta sayılan maç."""
    elig = active_eligibility(positions, config)
    return np.sum([day_assignment(elig, day, priority) for day in np.asarray(playing, bool)], axis=0)


def roster_week_table(player_ids: list[str], positions: list[frozenset[str]], teams: list[str],
                      cal: SeasonCalendar, config: Config, priority: np.ndarray | None = None) -> pd.DataFrame:
    """Kadronun hafta başına takvimdeki maç sayısı, aktif slotta sayılan ve yedekte kalan maçları.

    Oyuncuların sağlıklı olduğu varsayılır (sakatlık projeksiyonun ``projected_gp``'sindedir).
    """
    teams = [normalize_team(t) if isinstance(t, str) else "" for t in teams]
    rows = []
    for week in cal.weeks.index:
        days, plays = cal.playing(week)
        playing = np.array([[d in plays.get(t, ()) for t in teams] for d in days], dtype=bool)
        counted = counted_games(positions, playing, config, priority)
        sched = playing.sum()
        rows.append({"week": int(week), "start": cal.weeks.loc[week, "start"].date(),
                     "end": cal.weeks.loc[week, "end"].date(), "playoff": bool(cal.weeks.loc[week, "playoff"]),
                     "scheduled": int(sched), "counted": int(counted.sum()),
                     "benched": int(sched - counted.sum())})
    return pd.DataFrame(rows).set_index("week")
