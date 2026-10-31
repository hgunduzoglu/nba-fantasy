"""Sezon simülasyonu: normal sezon kalan fikstür + playoff braketi (README §13.14).

* **Başlangıç**: tam sıralama varsa tamamlanan hafta ``(W+L+T)/9`` kabul edilir ve gerçek W-L-T'den
  başlanır; yoksa 1. haftadan itibaren her hafta simüle edilir.
* **Haftalık güç**: her takımın o haftaki vektörü ``WeekModel.team_week`` ile (gerçek NBA takvimi, günlük
  lineup, uygunluk). İçinde bulunulan hafta güncel sakatlık durumu ve IL ile; gelecek haftalarda bütün
  kadro (IL dahil) durumdan bağımsız (kaçırılacak maçlar ROS GP'de). Kadrolar sezon boyu sabit.
* **Eşleşme**: kategori olasılıkları ``p_win``; birlikte çekiliş Gauss kopulası (``category_corr``).
  Kategori beraberliği yok sayılır (9 tek sayı → eşleşmede beraberlik yok).
* **Sıralama**: (W + T/2) / (W+L+T), eşitlikte rastgele. **Playoff**: ilk ``n`` takım; braket ``2^tur``
  boyutunda, boş koltuklar bay. ``Playoff Reseeding: Yes`` ise her turda en yüksek – en düşük eşleşir,
  değilse standart sabit braket. Playoff haftaları kendi takvimiyle (son tur iki takvim haftası olabilir).
* Aynı ``seed`` ile iki senaryo aynı çekilişleri kullanır (CRN): takas etkisi eşleşmeli farktır.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.special import ndtri

from fdo.inseason.weekly import Stint, WeekModel
from fdo.inseason.weeks import LeagueWeeks
from fdo.matchup.ecw import ecw_vs, p_at_least


def bracket_order(size: int) -> list[int]:
    """Standart braket sırası: 8 → [1, 8, 4, 5, 2, 7, 3, 6]."""
    order = [1]
    while len(order) < size:
        n = 2 * len(order)
        order = [x for s in order for x in (s, n + 1 - s)]
    return order


def playoff_teams(settings: dict[str, str]) -> int:
    m = re.search(r"(\d+)\s+teams", str(settings.get("Playoffs", "")))
    return int(m.group(1)) if m else 0


@dataclass
class SeasonResult:
    table: pd.DataFrame              # index team_id: takım, mevcut ve beklenen kayıt, sıra, olasılıklar
    schedule: pd.DataFrame           # seçilen takımın kalan haftaları
    seeds: np.ndarray                # (S, T) normal sezon sonu sıra (1 tabanlı)
    champion: np.ndarray             # (S, T) bool
    start_week: int
    n_sims: int
    playoff_size: int
    notes: list[str] = field(default_factory=list)


class SeasonSim:
    def __init__(self, model: WeekModel, weeks: LeagueWeeks, fixtures: pd.DataFrame,
                 standings: pd.DataFrame | None, as_of: dt.date):
        self.model = model
        eng = model.engine
        self.engine, self.league = eng, eng.league
        self.teams = list(eng.team_ids)
        self.tix = {t: i for i, t in enumerate(self.teams)}
        self.weeks, self.as_of = weeks, as_of
        lid = self.league.league_id
        fx = fixtures[fixtures["league_id"] == str(lid)]
        self.regular = sorted(int(w) for w in fx["week"].unique())
        self.pairs: dict[int, list[tuple[int, int]]] = {}
        for w, g in fx.groupby("week"):
            seen, pairs = set(), []
            for a, b in zip(g["team_id"], g["opponent_team_id"]):
                if a in self.tix and b in self.tix and frozenset((a, b)) not in seen:
                    seen.add(frozenset((a, b)))
                    pairs.append((self.tix[a], self.tix[b]))
            self.pairs[int(w)] = pairs
        self.standings = standings
        self.current_week = weeks.week_of(as_of)
        self.notes: list[str] = []
        if standings is not None:
            games = int((standings[["wins", "losses", "ties"]].sum(axis=1)).max())
            self.done = games // 9
        else:
            self.done = 0
            self.notes.append("Sıralama verisi yok: tamamlanmış haftalar da simüle edildi (gerçek sonuçlar bilinmiyor).")
        self.playoff_weeks = [w for w in weeks.playoff_weeks if w in weeks.weeks.index]
        self.playoff_size = playoff_teams(self.league.settings)
        self.reseed = str(self.league.settings.get("Playoff Reseeding", "")).lower().startswith("y")
        self.corr = model.corr
        self._vec_cache: dict[tuple, np.ndarray] = {}

    # ------------------------------------------------------------- haftalık vektörler
    def vector(self, team: str, roster: tuple[str, ...], week: int) -> np.ndarray:
        key = (team, tuple(sorted(roster)), week)
        if key not in self._vec_cache:
            current = week == self.current_week
            il = self.league.injury_rosters.get(team, frozenset())
            ids = [p for p in roster if not (current and p in il)]
            days = self.weeks.days(week)
            tw = self.model.team_week(team, [Stint(p, slot=k) for k, p in enumerate(ids)], days, use_status=current)
            self._vec_cache[key] = tw.vector
        return self._vec_cache[key]

    def week_vectors(self, rosters: dict[str, tuple[str, ...]], week: int) -> np.ndarray:
        return np.stack([self.vector(t, rosters[t], week) for t in self.teams])

    # ------------------------------------------------------------- simülasyon
    def _wins(self, p: np.ndarray, rng: np.random.Generator, S: int) -> np.ndarray:
        """``p (M, C)`` → ``(S, M)`` A tarafının kazandığı kategori sayısı (kopula)."""
        C = p.shape[-1]
        L = np.linalg.cholesky(self.corr) if self.corr is not None else np.eye(C)
        z = rng.standard_normal((S, p.shape[0], C)) @ L.T
        thr = ndtri(np.clip(p, 1e-12, 1 - 1e-12))
        return (z < thr[None]).sum(axis=-1)

    def run(self, rosters: dict[str, tuple[str, ...]] | None = None, *, n_sims: int = 2000, seed: int = 0,
            team: str | None = None) -> SeasonResult:
        rosters = dict(rosters or self.league.rosters)
        T, S = len(self.teams), int(n_sims)
        rng = np.random.default_rng(seed)
        W = np.zeros((S, T))
        L_ = np.zeros((S, T))
        Tie = np.zeros((S, T))
        if self.standings is not None:
            st = self.standings.loc[self.teams]
            W += st["wins"].to_numpy(float)
            L_ += st["losses"].to_numpy(float)
            Tie += st["ties"].to_numpy(float)
        start = self.done + 1
        sched_rows = []
        me = self.tix.get(team) if team is not None else None
        for w in [w for w in self.regular if w >= start]:
            pairs = self.pairs.get(w, [])
            if not pairs:
                continue
            V = self.week_vectors(rosters, w)
            a = np.array([x for x, _ in pairs])
            b = np.array([y for _, y in pairs])
            p = ecw_vs(V[a], V[b][:, None, :], self.engine.config)[:, 0, :]              # (M, C)
            k = self._wins(p, rng, S)                                                     # (S, M)
            np.add.at(W, (slice(None), a), k)
            np.add.at(L_, (slice(None), a), 9 - k)
            np.add.at(W, (slice(None), b), 9 - k)
            np.add.at(L_, (slice(None), b), k)
            if me is not None:
                for j, (x, y) in enumerate(pairs):
                    if me in (x, y):
                        pm = p[j] if me == x else 1 - p[j]
                        sched_rows.append({"week": w, "start": self.weeks.weeks.loc[w, "start"] if w in
                                           self.weeks.weeks.index else None,
                                           "opponent": self.teams[y if me == x else x],
                                           "exp_cats": float(pm.sum()),
                                           "p_win": float(p_at_least(pm[None, :], 5, self.corr)[0])})
        pct = (W + 0.5 * Tie) / np.maximum(W + L_ + Tie, 1)
        order = np.argsort(-(pct + 1e-9 * rng.random((S, T))), axis=1, kind="stable")    # eşitlikte rastgele
        seeds = np.empty((S, T), dtype=int)
        np.put_along_axis(seeds, order, np.arange(1, T + 1)[None, :].repeat(S, 0), axis=1)
        champion = self._playoffs(rosters, seeds, rng, S)
        n = self.playoff_size
        rounds = len(self.playoff_weeks)
        byes = max(0, 2 ** rounds - n) if rounds else 0
        table = pd.DataFrame({
            "team": [self.league.teams[t] for t in self.teams],
            "record_now": [f"{int(r.wins)}-{int(r.losses)}-{int(r.ties)}" for r in
                           self.standings.loc[self.teams].itertuples()] if self.standings is not None else "",
            "exp_wins": W.mean(0), "exp_losses": L_.mean(0), "exp_ties": Tie.mean(0), "exp_pct": pct.mean(0),
            "mean_seed": seeds.mean(0), "p_playoff": (seeds <= n).mean(0) if n else np.nan,
            "p_bye": (seeds <= byes).mean(0) if byes else np.nan,
            "p_first": (seeds == 1).mean(0), "p_champion": champion.mean(0),
        }, index=self.teams)
        sched = pd.DataFrame(sched_rows)
        if len(sched):
            sched["opponent_name"] = [self.league.teams[t] for t in sched["opponent"]]
        return SeasonResult(table, sched, seeds, champion, start, S, n, list(self.notes))

    def _playoffs(self, rosters, seeds: np.ndarray, rng: np.random.Generator, S: int) -> np.ndarray:
        T = len(self.teams)
        champion = np.zeros((S, T), dtype=bool)
        n, rounds = self.playoff_size, len(self.playoff_weeks)
        if not n or not rounds:
            return champion
        size = 2 ** rounds
        # koltuk (seed) → takım indeksi; bay koltuğu -1
        by_seed = np.full((S, size), -1)
        order = np.argsort(seeds, axis=1)
        by_seed[:, :min(n, size)] = order[:, :min(n, size)]
        current = bracket_order(size) if not self.reseed else list(range(1, size + 1))
        cur = np.array(current)[None, :].repeat(S, 0)                                     # (S, k) seed
        for r, week in enumerate(self.playoff_weeks):
            V = self.week_vectors(rosters, week)
            P = ecw_vs(V, V[None, :, :].repeat(T, 0), self.engine.config)                 # (T, T, C)
            if self.reseed:
                cur = np.sort(cur, axis=1)
                k = cur.shape[1]
                hi, lo = cur[:, : k // 2], cur[:, ::-1][:, : k // 2]
            else:
                hi, lo = cur[:, 0::2], cur[:, 1::2]
            ta = np.take_along_axis(by_seed, hi - 1, axis=1)
            tb = np.take_along_axis(by_seed, lo - 1, axis=1)
            bye_a, bye_b = ta < 0, tb < 0
            pa = P[np.maximum(ta, 0), np.maximum(tb, 0)]                                    # (S, g, C)
            C = pa.shape[-1]
            Lc = np.linalg.cholesky(self.corr) if self.corr is not None else np.eye(C)
            z = rng.standard_normal(pa.shape) @ Lc.T
            wins = (z < ndtri(np.clip(pa, 1e-12, 1 - 1e-12))).sum(axis=-1)
            a_wins = np.where(bye_b, True, np.where(bye_a, False, wins >= 5))
            cur = np.where(a_wins, hi, lo)
        final = np.take_along_axis(by_seed, cur[:, :1] - 1, axis=1)[:, 0]
        ok = final >= 0
        champion[np.arange(S)[ok], final[ok]] = True
        return champion
