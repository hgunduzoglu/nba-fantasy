"""Haftalık eşleşme görünümü ve streaming planı (README §13.13).

Seçilen haftanın kalan günlerinde iki takımın her günü için o gün oynayan oyuncular aktif slotlara
yerleştirilir (``daily_today`` lineup çözücüsü, öncelik = stratejiye göre maç başı değer). Oyuncu katkısı
``sayılan maç × uygunluk × maç başı ROS vektörü``; uygunluk ``min(1, ROS GP / takımının kalan maçı)``.
Haftanın şu ana kadarki skoru (elle girilir) sabit olarak eklenir. Kategori olasılıkları mevcut Normal
yaklaşımıdır (``p_win``); P(5+) kategori korelasyonu varsa kopula ile hesaplanır.

Streaming: kalan alım hakkı kadar açgözlü adım; her adım (bırak d, al f, gün t) üçlüsünden haftalık
strateji puanını en çok artıranı seçer. ``f`` t gününden itibaren ``d``'nin kalan günlerini devralır, ``d``
t'den önceki günlerde sayılır (kadro büyüklüğü her gün sabit); t yalnızca ``f``'nin maç günleridir.
Eklenen oyuncu sonraki adımda yeniden bırakılabilir (gün gün stream). Bırakılabilecek oyuncular
kullanıcının seçtiği kümedir; takasın kalıcı olsaydı kalan sezon etkisi ayrıca raporlanır.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from fdo.inseason.waiver import swap_delta
from fdo.matchup.ecw import category_corr_matrix, ecw_vs, p_at_least
from fdo.matchup.player_week import RATIO_OFFSETS, WEEK_DIM, per_game_variance, weekly_vectors
from fdo.schedule.calendar import normalize_team
from fdo.schedule.lineup import active_eligibility, day_assignment
from fdo.trade.data import ROS
from fdo.trade.engine import TradeEngine
from fdo.trade.strategy import Strategy
from fdo.types import STATS
from fdo.valuation import value_players

#: Bu durumlar haftada oynamaz sayılır (NA: takımda değil; O: out). Q (questionable) oynar.
DEFAULT_OUT = ("NA", "O", "INJ", "SUSP")
#: Elle girilen haftalık skor sütunları → vektördeki ortalama indeksleri.
ACC_FIELDS = ("fgm", "fga", "ftm", "fta", "fg3m", "pts", "reb", "ast", "stl", "blk", "tov")


def accumulated_vector(totals: dict[str, float] | None) -> np.ndarray:
    """Haftanın şu ana kadarki toplamları → yalnızca ortalama bileşenleri dolu 24'lük vektör."""
    v = np.zeros(WEEK_DIM)
    if not totals:
        return v
    for j, s in enumerate(("fg3m", "pts", "reb", "ast", "stl", "blk", "tov")):
        v[j] = float(totals.get(s, 0) or 0)
    for key, (mk, at) in {"fg": ("fgm", "fga"), "ft": ("ftm", "fta")}.items():
        o = RATIO_OFFSETS[key]
        v[o], v[o + 1] = float(totals.get(mk, 0) or 0), float(totals.get(at, 0) or 0)
    return v


@dataclass
class Stint:
    player_id: str
    first: int = 0              # kalan günler içindeki ilk gün indeksi (dahil)
    last: int = 10_000          # son gün indeksi (dahil)
    slot: int = -1              # kadro yeri: eklenen oyuncu bıraktığının yerini alır (işlem sırası için)


@dataclass
class TeamWeek:
    team_id: str
    stints: list[Stint]
    vector: np.ndarray                       # (24,) birikmiş + kalan beklenen
    grid: pd.DataFrame                       # oyuncu × gün: "▶" sayılan, "B" yedek, "✕" oynamaz, "" maç yok
    counted: pd.Series                       # oyuncu → sayılan maç
    scheduled: int
    benched: int


@dataclass
class Move:
    day: dt.date
    add: str
    drop: str
    gain: float                              # açgözlü adım kazancı (işlem listesinde NaN; toplam planda)
    ros_delta: float                         # d → f kalıcı olsaydı kalan sezon strateji ECW değişimi (+ = iyi)


@dataclass
class WeekOutlook:
    week: int
    days: list[dt.date]
    mine: TeamWeek
    opp: TeamWeek
    p: np.ndarray                            # (C,)
    expected_wins: float
    strategy_score: float
    p5: float
    moves: list[Move] = field(default_factory=list)


class WeekModel:
    """``TradeEngine``'in kalan sezon (ROS) verisiyle tek bir haftanın eşleşmesini modeller."""

    def __init__(self, engine: TradeEngine, *, strategy: Strategy | None = None, out_statuses=DEFAULT_OUT):
        self.engine = engine
        self.config = engine.config
        self.strategy = strategy or Strategy()
        self.out_statuses = tuple(out_statuses)
        data = engine.data
        f = data.stats[ROS].reindex(engine.ids)
        ok = engine.modeled
        ids = np.asarray(engine.ids)[ok]
        per_game = f.loc[ids, list(STATS)].div(f.loc[ids, "gp"], axis=0)
        cap = self.config.model.matchup.games_cap
        proj = per_game.assign(player_id=ids, projected_gp=cap).reset_index(drop=True)
        var, _ = per_game_variance(proj, data.variance, self.config.model.variance.phi)
        cfg1 = self.config.with_overrides({"model": {"matchup": {"utilization": 1.0, "games_variance": False}}})
        unit = weekly_vectors(proj, var, cfg1, games=pd.Series(1.0, index=ids))
        self.unit = unit.reindex(list(engine.ids)).fillna(0.0).to_numpy(float)          # (n, 24) maç başı
        # öncelik: stratejiye göre maç başı z (oturma/oynatma kararı)
        z = value_players(proj, self.config, basis="per_game", method="z").scores
        w = pd.Series(self.strategy.normalized, index=list(z.columns)) if len(z.columns) == 9 else 1.0
        self.priority = (z * w).sum(axis=1).reindex(list(engine.ids)).fillna(-99.0).to_numpy(float)
        sched = data.schedule.copy()
        sched["game_date"] = pd.to_datetime(sched["game_date"]).dt.date
        self.games: dict[dt.date, set[str]] = {}
        for d, g in sched.groupby("game_date"):
            self.games[d] = set(g["home_team"].map(normalize_team)) | set(g["away_team"].map(normalize_team))
        self.team = data.players["nba_team"].reindex(list(engine.ids)).map(
            lambda t: normalize_team(t) if isinstance(t, str) and t else "").to_numpy()
        future = sched[sched["game_date"] >= data.as_of]
        left = pd.concat([future["home_team"], future["away_team"]]).map(normalize_team).value_counts()
        team_left = pd.Series(self.team).map(left).fillna(0).to_numpy(float)
        gp = f["gp"].to_numpy(float)
        self.availability = np.where(ok & (team_left > 0), np.clip(np.nan_to_num(gp) / np.maximum(team_left, 1), 0, 1),
                                     0.0)
        self.corr = category_corr_matrix(self.config)
        self.positions = {p: frozenset(str(engine.data.players.loc[p, "yahoo_positions"]).split(","))
                          for p in engine.ids}

    # ------------------------------------------------------------- yardımcılar
    def playable(self, pid: str) -> bool:
        i = self.engine.index[pid]
        status = str(self.engine.data.players.loc[pid, "injury_status"] or "")
        return bool(self.engine.modeled[i]) and status not in self.out_statuses

    def has_game(self, pid: str, day: dt.date) -> bool:
        return self.team[self.engine.index[pid]] in self.games.get(day, ())

    def active_roster(self, team_id: str) -> list[str]:
        lg = self.engine.league
        return [p for p in lg.rosters[team_id] if p not in lg.injury_rosters[team_id]]

    def team_week(self, team_id: str, stints: list[Stint], days: list[dt.date],
                  acc: np.ndarray | None = None) -> TeamWeek:
        ids = [s.player_id for s in stints]
        n, D = len(ids), len(days)
        idx = [self.engine.index[p] for p in ids]
        can = np.array([self.playable(p) for p in ids], dtype=bool)
        playing = np.zeros((D, n), dtype=bool)
        for d, day in enumerate(days):
            teams = self.games.get(day, ())
            for j, s in enumerate(stints):
                playing[d, j] = can[j] and s.first <= d <= s.last and self.team[idx[j]] in teams
        elig = active_eligibility([self.positions[p] for p in ids], self.config)
        pr = self.priority[idx]
        counted_mask = np.zeros((D, n), dtype=bool)
        for d in range(D):
            counted_mask[d] = day_assignment(elig, playing[d], pr)
        counted = counted_mask.sum(axis=0)
        vec = (acc.copy() if acc is not None else np.zeros(WEEK_DIM))
        if n:
            vec += ((counted * self.availability[idx])[:, None] * self.unit[idx]).sum(axis=0)
        grid = pd.DataFrame("", index=ids, columns=[f"{day:%a %d}" for day in days])
        for d, day in enumerate(days):
            for j, s in enumerate(stints):
                if not (s.first <= d <= s.last):
                    continue
                if self.team[idx[j]] in self.games.get(day, ()):
                    grid.iat[j, d] = "▶" if counted_mask[d, j] else ("✕" if not can[j] else "B")
        return TeamWeek(team_id, list(stints), vec, grid, pd.Series(counted, index=ids),
                        int(playing.sum()), int(playing.sum() - counted.sum()))

    def _score(self, p: np.ndarray) -> float:
        return float(9 * p @ self.strategy.normalized)

    def evaluate(self, mine: TeamWeek, opp: TeamWeek) -> tuple[np.ndarray, float, float, float]:
        p = ecw_vs(mine.vector, opp.vector[None, :], self.config)[0]
        p5 = float(p_at_least(p[None, :], 5, self.corr)[0])
        return p, float(p.sum()), self._score(p), p5

    # ------------------------------------------------------------- ana giriş
    def outlook(self, team_id: str, opp_id: str, week_days: list[dt.date], *, acc_mine=None, acc_opp=None,
                week: int = 0) -> WeekOutlook:
        a_m, a_o = accumulated_vector(acc_mine), accumulated_vector(acc_opp)
        mine = self.team_week(team_id, [Stint(p, slot=k) for k, p in enumerate(self.active_roster(team_id))],
                              week_days, a_m)
        opp = self.team_week(opp_id, [Stint(p, slot=k) for k, p in enumerate(self.active_roster(opp_id))],
                             week_days, a_o)
        p, ew, sc, p5 = self.evaluate(mine, opp)
        return WeekOutlook(week, week_days, mine, opp, p, ew, sc, p5)

    def free_agents(self) -> list[str]:
        owned = {p for r in self.engine.league.rosters.values() for p in r}
        return [p for p in self.engine.ids if p not in owned and self.playable(p)]

    def stream(self, base: WeekOutlook, *, moves: int, droppable: list[str], acc_mine=None,
               shortlist: int = 30, min_gain: float = 0.01) -> WeekOutlook:
        """Açgözlü streaming planı; ``base`` aynı günler için ``outlook`` sonucudur."""
        days = base.days
        a_m = accumulated_vector(acc_mine)
        opp = base.opp
        stints = [Stint(s.player_id, s.first, s.last, s.slot) for s in base.mine.stints]
        added: set[str] = set()
        out = WeekOutlook(base.week, days, base.mine, opp, base.p, base.expected_wins, base.strategy_score, base.p5)
        fa = [p for p in self.free_agents() if any(self.has_game(p, d) for d in days)]
        if not fa or moves <= 0 or not droppable:
            return out
        # kısa liste: kadroya kısıtsız eklenince haftalık puan artışı (lineup yok, hızlı ön eleme)
        idx = np.array([self.engine.index[p] for p in fa])
        g = np.array([sum(self.has_game(p, d) for d in days) for p in fa], dtype=float)
        cand = base.mine.vector[None, :] + (g * self.availability[idx])[:, None] * self.unit[idx]
        pre = ecw_vs(cand, opp.vector[None, None, :], self.config)[:, 0, :] @ self.strategy.normalized * 9
        fa = [fa[i] for i in np.argsort(-pre, kind="stable")[:shortlist]]
        drop_pool = list(dict.fromkeys(droppable))
        current = out
        for _ in range(moves):
            best = None
            active_ids = {s.player_id for s in stints}
            for d_id in [p for p in drop_pool if p in active_ids]:
                j = next(k for k, s in enumerate(stints) if s.player_id == d_id)
                s0 = stints[j]
                end = min(s0.last, len(days) - 1)
                for f_id in fa:
                    if f_id in active_ids:
                        continue
                    # eklenen oyuncu bırakılanın kalan günlerini devralır (kadro büyüklüğü her gün sabit);
                    # başlangıç yalnızca eklenenin maç günleri (maçsız günden başlamak bırakılanın maçını boşa harcar)
                    # eklenmiş bir streamer ilk gününde bırakılmaz (alım hakkını boşa harcar)
                    first_t = max(s0.first, 0) + (1 if d_id in added else 0)
                    for t in (k for k in range(first_t, end + 1) if self.has_game(f_id, days[k])):
                        trial = [*stints[:j], Stint(d_id, s0.first, t - 1, s0.slot), *stints[j + 1:],
                                 Stint(f_id, t, s0.last, s0.slot)]
                        tw = self.team_week(base.mine.team_id, trial, days, a_m)
                        p, ew, sc, p5 = self.evaluate(tw, opp)
                        if best is None or sc > best[0]:
                            best = (sc, trial, tw, p, ew, p5, d_id, f_id, t)
            if best is None or best[0] - current.strategy_score < min_gain:
                break
            sc, trial, tw, p, ew, p5, d_id, f_id, t = best
            move = Move(days[t], f_id, d_id, sc - current.strategy_score,
                        swap_delta(self.engine, base.mine.team_id, d_id, f_id, self.strategy))
            stints = [s for s in trial if s.first <= s.last]
            drop_pool.append(f_id)
            added.add(f_id)
            fa.remove(f_id)
            current = WeekOutlook(base.week, days, tw, opp, p, ew, sc, p5, [*current.moves, move])
        current.moves = self.transactions(base.mine.team_id, base.mine.stints, current.mine.stints, days)
        return current

    def transactions(self, team_id: str, before: list[Stint], after: list[Stint], days: list[dt.date]) -> list[Move]:
        """Son plandan gün sıralı al/bırak işlemleri: her kadro yerinde ardışık oyuncular."""
        out = []
        start = {s.slot: s.player_id for s in before}
        for slot, prev in start.items():
            chain = sorted((s for s in after if s.slot == slot and s.player_id != prev), key=lambda s: s.first)
            for s in chain:
                out.append(Move(days[s.first], s.player_id, prev, float("nan"),
                                swap_delta(self.engine, team_id, prev, s.player_id, self.strategy)))
                prev = s.player_id
        return sorted(out, key=lambda m: m.day)


def vector_totals(vec: np.ndarray) -> dict[str, float]:
    """Takım haftalık vektörü → kategori beklenen toplamları (FG%/FT% isabet/deneme oranı)."""
    fg, ft = RATIO_OFFSETS["fg"], RATIO_OFFSETS["ft"]
    out = {"FG_PCT": vec[fg] / vec[fg + 1] if vec[fg + 1] > 0 else float("nan"),
           "FT_PCT": vec[ft] / vec[ft + 1] if vec[ft + 1] > 0 else float("nan")}
    for j, c in enumerate(("FG3M", "PTS", "REB", "AST", "STL", "BLK", "TOV")):
        out[c] = float(vec[j])
    return out


def acquisition_limit(settings: dict[str, str], default: int = 7) -> int:
    """Lig ayarı ``Max Acquisitions per Week`` (ör. ``"4"``); sınırsızsa ``default``."""
    m = re.match(r"\s*(\d+)", str(settings.get("Max Acquisitions per Week", "")))
    return int(m.group(1)) if m else default
