"""``matchup.utilization`` tahmini (README §6.6.1): oynanan maçların aktif slotta sayılan oranı.

Mock draft kadroları (13 kişi) üzerinde haftalar simüle edilir. Her NBA takımı gün ``d``'de
``p_d`` olasılıkla oynar (gün yükü aşağıdaki varsayımsal hafta profilinden, ölçek
``games_per_week``, gün yükü haftadan haftaya ``--day-sd`` kadar oynar); oyuncu, takımı oynuyorsa ``gp / cap`` olasılıkla sahadadır.
Lineup kilidine göre aktif slotlara (pozisyon uygunluğuyla) atama:

* ``daily_today``   : her gün o gün oynayanlardan en büyük uygun atama.
* ``daily_tomorrow``: atama takvime göre önceden yapılır; son dakika yokluklar telafi edilemez.
* ``weekly``        : hafta başında beklenen maç sayısına göre tek atama.

Takvim varsayımsaldır (gerçek takvim V2); sonuç raporlanır, config'e elle yazılır.

    python scripts/estimate_utilization.py --data data/real/ --mocks 50
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment

from fdo.bots.mock import MockDraft
from fdo.bots.universe import build_universe
from fdo.config import load_config
from fdo.ingest import load_dataset

#: Varsayımsal NBA hafta profili: güne düşen maç sayısı (Pzt..Paz). Kalibre edilmemiş.
DAY_GAMES = (8, 6, 9, 5, 8, 6, 7)
LOCKS = ("daily_today", "daily_tomorrow", "weekly")


def best_assignment(elig: np.ndarray, weight: np.ndarray) -> np.ndarray:
    """Aktif slot × oyuncu uygunluk matrisi ve oyuncu ağırlığıyla en büyük atama; atanan oyuncu maskesi."""
    w = elig * weight[None, :]
    rows, cols = linear_sum_assignment(w, maximize=True)
    out = np.zeros(elig.shape[1], dtype=bool)
    keep = w[rows, cols] > 0
    out[cols[keep]] = True
    return out


def week_profile(games_per_week: float, day_sd: float, rng: np.random.Generator) -> np.ndarray:
    """Takımın gün ``d``'de oynama olasılığı; gün yükü haftadan haftaya ``N(0, day_sd)`` oynar."""
    games = np.clip(np.round(np.asarray(DAY_GAMES, float) + rng.normal(0, day_sd, 7)), 1, 15)
    day = games * 2 / 30
    return np.minimum(day * games_per_week / day.sum(), 1.0)


def schedule_weeks(teams: np.ndarray, cal) -> list[np.ndarray]:
    """Gerçek takvimden hafta başına ``(gün, oyuncu)`` takım-oynuyor matrisleri."""
    from fdo.schedule.calendar import normalize_team

    teams = [normalize_team(t) for t in teams]
    out = []
    for week in cal.weeks.index:
        days, plays = cal.playing(week)
        out.append(np.array([[d in plays.get(t, ()) for t in teams] for d in days], dtype=bool))
    return out


def simulate(rosters, cfg, weeks: int, rng: np.random.Generator, day_sd: float = 3.0,
             cal=None) -> dict[str, float]:
    """``cal`` (``SeasonCalendar``) verilirse varsayımsal profil yerine gerçek takvim haftaları kullanılır."""
    mp = cfg.model.matchup
    slots = [s for s in cfg.roster.active_slots for _ in range(cfg.roster.slots[s])]
    counted = dict.fromkeys(LOCKS, 0.0)
    played = 0.0
    for teams, positions, avail in rosters:
        elig = np.array([[bool(pos & cfg.roster.slot_eligibility[s]) for pos in positions] for s in slots],
                        dtype=float)
        uniq, team_idx = np.unique(teams, return_inverse=True)
        if cal is not None:
            week_iter = schedule_weeks(teams, cal)
        else:
            week_iter = []
            for _ in range(weeks):
                day = week_profile(mp.games_per_week, day_sd, rng)
                sched = rng.random((7, len(uniq))) < day[:, None]       # takım oynuyor mu
                week_iter.append(sched[:, team_idx])                     # 7 × oyuncu
        for scheduled in week_iter:
            on_court = scheduled & (rng.random(scheduled.shape) < avail[None, :])
            played += on_court.sum()
            weekly = best_assignment(elig, scheduled.sum(0) * avail + 1e-6 * avail)
            counted["weekly"] += on_court[:, weekly].sum()
            for d in range(len(scheduled)):
                counted["daily_today"] += best_assignment(elig, on_court[d].astype(float)).sum()
                pre = best_assignment(elig, scheduled[d] * (avail + 1e-6))
                counted["daily_tomorrow"] += (pre & on_court[d]).sum()
    return {k: v / played for k, v in counted.items()}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default="data/real/")
    ap.add_argument("--mocks", type=int, default=50)
    ap.add_argument("--weeks", type=int, default=20)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--day-sd", type=float, default=3.0, help="gün yükü (maç sayısı) haftalık sapması")
    ap.add_argument("--schedule", default=None, help="takvim CSV'si (manifest'li); verilirse gerçek haftalar")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(errors="replace")

    from run_mock_batch import find_files

    cfg = load_config()
    files = find_files(Path(args.data))
    ds, report = load_dataset(files["players"], files["projections"], files["adp"], config=cfg)
    if ds is None:
        print("Veri yüklenemedi:", *report.errors, sep="\n  - ")
        return 1
    universe = build_universe(ds, cfg)
    pos = ds.positions().to_dict()
    team = ds.players.set_index("player_id")["nba_team"].fillna("?").to_dict()
    gp = ds.projections.set_index("player_id")["projected_gp"].to_dict()
    cap = cfg.model.matchup.games_cap

    rosters = []
    for k in range(args.mocks):
        m = MockDraft(ds, cfg, args.seed + k, universe)
        m.play_to_end()
        for seat in range(1, cfg.league.teams + 1):
            ids = [p.player_id for p in m.log.picks if p.seat == seat]
            rosters.append((np.array([team[i] for i in ids]), [pos[i] for i in ids],
                            np.array([min(gp.get(i, 0.0), cap) / cap for i in ids])))
    cal = None
    if args.schedule:
        from fdo.ingest.load import load_table
        from fdo.schedule import build_calendar

        sched, _, srep = load_table(args.schedule, "schedule")
        if sched is None:
            print("Takvim yüklenemedi:", *srep.errors, sep="\n  - ")
            return 1
        cal = build_calendar(sched, cfg)
    res = simulate(rosters, cfg, args.weeks, np.random.default_rng(args.seed), args.day_sd, cal)
    print(f"{len(rosters)} kadro × {args.weeks} hafta, games_per_week={cfg.model.matchup.games_per_week}, "
          f"day_sd={args.day_sd}")
    for k, v in res.items():
        print(f"  {k:15s} utilization ≈ {v:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
