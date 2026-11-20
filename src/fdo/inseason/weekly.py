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

from fdo.inseason.injuries import b2b_play, presence, questionable_play
from fdo.inseason.live import stat
from fdo.inseason.waiver import swap_delta
from fdo.matchup.ecw import category_corr_matrix, ecw_vs, p_at_least, p_win
from fdo.matchup.player_week import RATIO_OFFSETS, WEEK_DIM, attendance_vectors, per_game_variance, weekly_vectors
from fdo.schedule.calendar import normalize_team
from fdo.schedule.lineup import active_eligibility, slot_assignment
from fdo.trade.data import ROS
from fdo.trade.engine import TradeEngine
from fdo.trade.strategy import Strategy
from fdo.types import STATS

#: Bu durumlar haftada oynamaz sayılır (NA: takımda değil; O: out). Q (questionable) oynar.
DEFAULT_OUT = ("NA", "O", "INJ", "SUSP")
#: Belirsiz durumlar: varsayılan olarak oynar; "Q oynamaz" senaryosunda ``out_statuses``a eklenir (kalibre değil).
QUESTIONABLE = ("Q", "GTD", "DTD")
#: Yeni dönmüş oyuncu (maç kayıtlarından, ``sources["recent_returns"]``): dönüşten sonraki ilk ``RETURN_OTHER_GAMES``
#: takım maçında B2B dışı maçlarda da oynama oranı (geçmiş iki sezon: sağlıklıya göre %91–94 toplam; README §13.59).
RETURN_OTHER_PLAY = .95
RETURN_OTHER_GAMES = 20
#: Yakın vade: bu kadar gün son maçların dakikası ve maça çıkması kullanılır (``durability._near_term``; README §13.61).
NEAR_DAYS = 7
#: Elle girilen haftalık skor sütunları → vektördeki ortalama indeksleri.
ACC_FIELDS = ("fgm", "fga", "ftm", "fta", "fg3m", "pts", "reb", "ast", "stl", "blk", "tov")


def accumulated_vector(totals: dict[str, float] | None) -> np.ndarray:
    """Haftanın şu ana kadarki toplamları → yalnızca ortalama bileşenleri dolu 24'lük vektör (\"-\"/eksik = 0)."""
    v = np.zeros(WEEK_DIM)
    if not totals:
        return v
    for j, s in enumerate(("fg3m", "pts", "reb", "ast", "stl", "blk", "tov")):
        v[j] = stat(totals.get(s))
    for key, (mk, at) in {"fg": ("fgm", "fga"), "ft": ("ftm", "fta")}.items():
        o = RATIO_OFFSETS[key]
        v[o], v[o + 1] = stat(totals.get(mk)), stat(totals.get(at))
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
    slots: np.ndarray | None = None          # (gün, oyuncu) aktif slot satırı, -1 sayılmadı (``slot_assignment``)
    playing: np.ndarray | None = None        # (gün, oyuncu) maçı var ve oynayabilir


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

    def __init__(self, engine: TradeEngine, *, strategy: Strategy | None = None, out_statuses=DEFAULT_OUT,
                 roles: dict | None = None, questionable: float | None = None, b2b: dict | None = None):
        """``roles``: oyuncu → ``fdo.inseason.roles.RoleBoost`` (takım arkadaşı yokken maç başı; ``until``'e kadar).
        ``questionable``: belirsiz (Q/GTD/DTD) oyuncunun takımının bir sonraki maçında oynama olasılığı (``None``:
        ``config/returns.yaml``'deki ölçülmüş değer, yoksa 1). ``b2b``: arka arkaya maçın ikinci gününde oynama oranları
        (``None``: veri kaynağındaki ya da ``config/returns.yaml``'deki ölçüm; ``{}``: kapalı)."""
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
        # yakın vade (ilk NEAR_DAYS gün): son maçların dakikası ve maça çıkması (README §13.61)
        self.near_until = data.as_of + dt.timedelta(days=NEAR_DAYS)
        dur = getattr(data, "durability", None)
        near = dur["near_minutes"].reindex(ids).fillna(1.0) if dur is not None and "near_minutes" in dur else None
        self.near_unit = self.unit
        self.near_role = np.zeros(len(engine.ids), dtype=bool)        # yalnız bunlarda yakın vade vektörü
        if near is not None and (near.to_numpy() != 1.0).any():
            self.near_role[[engine.index[p] for p in ids[near.to_numpy() != 1.0]]] = True
            nproj = (per_game.mul(near.to_numpy(), axis=0)).assign(player_id=ids, projected_gp=cap).reset_index(drop=True)
            nvar, _ = per_game_variance(nproj, data.variance, self.config.model.variance.phi)
            nunit = weekly_vectors(nproj, nvar, cfg1, games=pd.Series(1.0, index=ids))
            self.near_unit = nunit.reindex(list(engine.ids)).fillna(0.0).to_numpy(float)
        # rol değişimi: dönüşe kadar (hariç) maç başı vektörü yerine bu kullanılır (README §13.24)
        self.roles = {p: r for p, r in (roles or {}).items() if p in engine.index and ok[engine.index[p]]}
        self.boost_unit = self.unit.copy()
        self.boost_until = np.full(len(engine.ids), dt.date.min, dtype=object)
        if self.roles:
            rp = list(self.roles)
            bproj = pd.DataFrame([self.roles[p].per_game for p in rp])[list(STATS)].assign(
                player_id=rp, projected_gp=cap)
            bvar, _ = per_game_variance(bproj, data.variance, self.config.model.variance.phi)
            bunit = weekly_vectors(bproj, bvar, cfg1, games=pd.Series(1.0, index=rp))
            for p in rp:
                self.boost_unit[engine.index[p]] = bunit.loc[p].to_numpy(float)
                self.boost_until[engine.index[p]] = self.roles[p].until
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
        # Sakatlık dönüş tarihi (CBS): o güne kadar oynamaz; kalan maçları dönüş sonrasına yayılır.
        self.return_date: dict[str, dt.date] = {}
        self.injury_known: set[str] = set()
        inj = getattr(data, "injuries", None)
        if inj is not None and len(inj):
            for pid, r in inj.iterrows():
                if pid not in engine.index:
                    continue
                self.injury_known.add(pid)
                if r["kind"] == "season":
                    self.return_date[pid] = dt.date.max
                elif r["kind"] == "out_until" and r["return_date"] is not None and not pd.isna(r["return_date"]):
                    self.return_date[pid] = max(data.as_of, pd.Timestamp(r["return_date"]).date())
        games_by_team: dict[str, list[dt.date]] = {}
        for d_, teams_ in self.games.items():
            for t_ in teams_:
                games_by_team.setdefault(t_, []).append(d_)
        for pid, ret in self.return_date.items():
            i = engine.index[pid]
            team_left[i] = sum(d_ >= ret for d_ in games_by_team.get(self.team[i], []))
        # Maç başına oynama ağırlığı (1 değilse): dönüşü bekleyen oyuncuda ölçülmüş gecikme dağılımıyla o maçta dönmüş
        # olma olasılığı; belirsiz (Q) oyuncuda takımının bir sonraki maçında oynama olasılığı. Beklenen maç
        # (``availability`` paydası) ağırlıkların toplamıdır: ROS'taki beklenen kayıp iki kez düşülmez.
        self.play_weight: dict[str, dict[dt.date, float]] = {}
        pmf = (data.sources.get("injuries") or {}).get("delay_pmf")
        if pmf:
            pmf = {int(k): float(v) for k, v in pmf.items()}
            for pid, ret in self.return_date.items():
                if ret == dt.date.max or ret <= data.as_of:
                    continue
                i = engine.index[pid]
                g = sorted(d_ for d_ in games_by_team.get(self.team[i], []) if d_ >= ret)
                pres = presence(len(g), pmf)
                self.play_weight[pid] = dict(zip(g, pres))
                team_left[i] = float(pres.sum())
        configured_q = (data.sources.get("attendance") or {}).get("questionable_play")
        if questionable is None:
            questionable = questionable_play() if configured_q is None else configured_q
        self.questionable = min(1.0, max(0.0, float(questionable)))
        if self.questionable < 1:
            status = data.players["injury_status"].reindex(list(engine.ids)).astype(str)
            for pid in [p for p, st in status.items() if st in QUESTIONABLE and ok[engine.index[p]]]:
                nxt = min((d_ for d_ in games_by_team.get(self.team[engine.index[pid]], []) if d_ >= data.as_of),
                          default=None)
                if nxt is not None:
                    w_ = self.play_weight.setdefault(pid, {})
                    w_[nxt] = w_.get(nxt, 1.0) * self.questionable
        if b2b is None:
            attendance = data.sources.get("attendance") or {}
            b2b = attendance["b2b"] if "b2b" in attendance else b2b_play()
        if b2b:
            self._apply_b2b(b2b, games_by_team, data.as_of, ids)
        self.availability = np.where(ok & (team_left > 0), np.clip(np.nan_to_num(gp) / np.maximum(team_left, 1), 0, 1),
                                     0.0)
        # yakın vadede maça çıkma: sezon öncesi önselli ROS oranı yerine son takım maçları (dönüş tarihi bilinen hariç)
        self.near_availability = self.availability.copy()
        self.near_present = np.zeros(len(engine.ids), dtype=bool)     # yalnız bunlarda yakın vade maça çıkma
        if dur is not None and "near_attendance" in dur:
            att = dur["near_attendance"].reindex(list(engine.ids)).to_numpy(float)
            known = np.array([p in self.return_date for p in engine.ids], dtype=bool)
            self.near_present = ok & np.isfinite(att) & ~known & (self.availability > 0)
            self.near_availability[self.near_present] = np.clip(att[self.near_present], 0.0, 1.0)
        self.corr = category_corr_matrix(self.config)
        self.positions = {p: frozenset(str(engine.data.players.loc[p, "yahoo_positions"]).split(","))
                          for p in engine.ids}
        self.lineup_reference = engine.baseline_vectors.mean(axis=0) / 7

    def _apply_b2b(self, b2b: dict, games_by_team: dict[str, list[dt.date]], as_of: dt.date, ids) -> None:
        """Arka arkaya maçın ikinci gününde daha düşük oynama (``config/returns.yaml`` → ``b2b_play``, maç kayıtlarından
        ölçülmüş oran): sağlıklı oyuncuda ``healthy``; dönüş tarihi bilinen sakatta dönüşten sonraki gün aralıklarında
        ``after_return`` (ör. ilk 14 gün). Sağlıklı orana kadar olan kayıp beklenen toplamı değiştirmez (ROS maç sayısı
        olağan dinlenmeyi zaten içerir): diğer maçların ağırlığı aynı oranda artar, yalnız günlere ve haftalara dağılım
        değişir. Dönüş penceresinde sağlıklı oranın altında kalan kısım ise net kayıptır: dönüşten sonra oyuncu o maçı
        gerçekten kaçırır, diğer maçlarda daha fazla oynamaz (maç kayıtlarında dönüş sonrası diğer maçlarda oynama
        sağlıklı tabanla aynı: %87,4'e %86,6; README §13.55).

        CBS listesinden çıkmış, son günlerde dönmüş oyuncu (``sources["recent_returns"]``, maç kayıtlarından) için de
        dönüş pencereleri uygulanır; ayrıca dönüşten sonraki ilk ``RETURN_OTHER_GAMES`` takım maçında B2B dışı
        maçlarda ``RETURN_OTHER_PLAY`` oranında oynar (net kayıp; README §13.59)."""
        healthy = min(1.0, max(0.0, float(b2b.get("healthy", 1.0))))
        after = sorted((int(k), min(1.0, max(0.0, float(v)))) for k, v in (b2b.get("after_return") or {}).items())
        second: dict[str, tuple[list[dt.date], set[dt.date]]] = {}
        for team, days in games_by_team.items():
            all_days = set(days)
            future = sorted(d for d in days if d >= as_of)
            second[team] = (future, {d for d in future if d - dt.timedelta(days=1) in all_days})
        recent = {str(k): v if isinstance(v, dt.date) else dt.date.fromisoformat(str(v))
                  for k, v in ((self.engine.data.sources or {}).get("recent_returns") or {}).items()}
        for pid in ids:
            team = self.team[self.engine.index[pid]]
            future, b2 = second.get(team, ([], set()))
            current = self.play_weight.get(pid, {})
            ret = self.return_date.get(pid)
            ret = ret if ret is not None and ret != dt.date.max and ret > as_of else None
            back = recent.get(pid) if ret is None else None          # CBS'ten çıkmış, yeni dönmüş
            start = ret or back
            if not b2 and back is None:
                continue
            domain = sorted(current) if ret is not None and current else [d for d in future if ret is None or d >= ret]
            if not domain:
                continue
            team_days = sorted(games_by_team.get(team, []))

            def factor(d: dt.date) -> float:
                if start is not None:
                    since = (d - start).days
                    for window, rate in after:
                        if 0 < since <= window:
                            return rate
                return healthy

            def other_play(d: dt.date) -> float:
                if back is None:
                    return 1.0
                since = sum(back < x <= d for x in team_days)
                return RETURN_OTHER_PLAY if since <= RETURN_OTHER_GAMES else 1.0

            w = {d: current.get(d, 1.0) for d in domain}
            hit = {d: factor(d) for d in domain if d in b2}
            miss = {d: other_play(d) for d in domain if d not in hit}
            other = sum(w[d] * f for d, f in miss.items())
            # dönüş sonrası fazladan kaçan maç: B2B'de sağlıklı oranın altı, diğer maçlarda eksik oynama
            net = sum(w[d] * max(0.0, healthy - f) for d, f in hit.items()) + sum(w[d] * (1 - f) for d, f in miss.items())
            if other <= 0 or ((not hit or all(f >= 1.0 for f in hit.values())) and net <= 0):
                continue
            total = sum(w.values())
            scale = max(0.0, total - net - sum(w[d] * f for d, f in hit.items())) / other
            self.play_weight[pid] = {**current, **{d: w[d] * (hit[d] if d in hit else miss[d] * scale) for d in domain}}

    # ------------------------------------------------------------- yardımcılar
    def playable(self, pid: str, use_status: bool = True) -> bool:
        """``use_status=False``: güncel sakatlık durumu yok sayılır (gelecek haftalar; kayıp maçlar ROS GP'de).
        Dönüş tarihi bilinen oyuncuda Yahoo durumu yerine tarih kullanılır (``team_week`` gün maskesi)."""
        i = self.engine.index[pid]
        status = str(self.engine.data.players.loc[pid, "injury_status"] or "")
        if pid in self.injury_known:              # CBS tarihi bilinen: Yahoo durumu yalnız NA ya da seçilen Q senaryosunda
            use_status = (status == "NA" or (status in QUESTIONABLE and status in self.out_statuses)) and use_status
        return bool(self.engine.modeled[i]) and (not use_status or status not in self.out_statuses)

    def game_unit(self, idx: np.ndarray, days: list[dt.date]) -> np.ndarray:
        """``(n, 24)`` maç başı vektör, ``days`` içindeki maçları üzerinden ortalama (rol değişimi süresince rollü)."""
        out = self.unit[idx].copy()
        for j, i in enumerate(idx if days else ()):
            until = self.boost_until[i]
            if until > days[0]:
                plays = [d for d in days if self.team[i] in self.games.get(d, ())] or days
                share = sum(d < until for d in plays) / len(plays)
                out[j] = share * self.boost_unit[i] + (1 - share) * self.unit[i]
        return out

    def has_game(self, pid: str, day: dt.date) -> bool:
        return self.team[self.engine.index[pid]] in self.games.get(day, ())

    def games_in(self, pid: str, days) -> int:
        """NBA takımının ``days`` içindeki maçları; bilinen sakatlık dönüşünden önceki günler sayılmaz."""
        team, ret = self.team[self.engine.index[pid]], self.return_date.get(pid)
        return sum(1 for d in days if team in self.games.get(d, ()) and (ret is None or d >= ret))

    def active_roster(self, team_id: str) -> list[str]:
        lg = self.engine.league
        return [p for p in lg.rosters[team_id] if p not in lg.injury_rosters[team_id]]

    def team_week(self, team_id: str, stints: list[Stint], days: list[dt.date],
                  acc: np.ndarray | None = None, *, use_status: bool = True, priority: np.ndarray | None = None,
                  sit: np.ndarray | None = None, strategy: Strategy | None = None,
                  reference: np.ndarray | None = None) -> TeamWeek:
        """``priority``: stint veya gün/stint başına öncelik (varsayılan beklenen kategori katkısı); ``sit``: (gün, stint) maçı olsa da
        oturtulan (sit/start önerisi). ``reference``: rakibin birikmiş + kalan haftalık vektörü; slot adayları,
        diğer günlerin seçilmiş katkıları ve ``acc`` ile birlikte bu aynı haftalık hedefe göre karşılaştırılır."""
        ids = [s.player_id for s in stints]
        n, D = len(ids), len(days)
        idx = [self.engine.index[p] for p in ids]
        can = np.array([self.playable(p, use_status) for p in ids], dtype=bool)
        playing = np.zeros((D, n), dtype=bool)
        for d, day in enumerate(days):
            teams = self.games.get(day, ())
            for j, s in enumerate(stints):
                playing[d, j] = (can[j] and s.first <= d <= s.last and self.team[idx[j]] in teams
                                 and day >= self.return_date.get(s.player_id, day))
        elig = active_eligibility([self.positions[p] for p in ids], self.config)
        allowed = playing & ~sit if sit is not None else playing
        # A role boost is conditional production, and availability/return/Q
        # probabilities describe the same attendance event. Form its moments
        # once, before either selecting a lineup or aggregating production.
        expected = self.daily_vectors(np.asarray(idx, int), days)
        policy = strategy or self.strategy
        slots = np.full((D, n), -1)
        for d in range(D):
            if priority is not None:
                pr = np.asarray(priority, float)
                pr = pr[d] if pr.ndim == 2 else pr
                slots[d] = slot_assignment(elig, allowed[d], pr)
            else:
                # Bootstrap on a daily horizon without accumulated weekly scores.
                pr = p_win(expected[d], self.lineup_reference, self.config) @ policy.normalized
                slots[d] = slot_assignment(elig, allowed[d], pr)
        competing_days = np.flatnonzero((allowed & (slots < 0)).any(axis=1))
        if priority is None and len(competing_days):
            total = (acc.copy() if acc is not None else np.zeros(WEEK_DIM)) + expected[slots >= 0].sum(axis=0)
            # A known opponent supplies its accumulated + remaining weekly total.
            # Otherwise the league reference spans the same forecast window (a
            # whole week when past production is included), never just one day.
            if reference is None:
                horizon = max(7, D) if acc is not None and np.any(acc) else D
                reference = self.lineup_reference * horizon
            score = float(p_win(total, reference, self.config) @ policy.normalized)
            for _ in range(2):
                changed = False
                for d in competing_days:
                    context = total - expected[d, slots[d] >= 0].sum(axis=0)
                    candidate = self._expected_assignment(elig, allowed[d], expected[d], policy, context, reference)
                    trial = context + expected[d, candidate >= 0].sum(axis=0)
                    trial_score = float(p_win(trial, reference, self.config) @ policy.normalized)
                    if trial_score > score + 1e-12:
                        slots[d], total, score, changed = candidate, trial, trial_score, True
                if not changed:
                    break
        counted_mask = slots >= 0
        counted = counted_mask.sum(axis=0)
        vec = (acc.copy() if acc is not None else np.zeros(WEEK_DIM))
        if n:
            vec += expected[counted_mask].sum(axis=0)
        grid = pd.DataFrame("", index=ids, columns=[f"{day:%a %d}" for day in days])
        for d, day in enumerate(days):
            for j, s in enumerate(stints):
                if not (s.first <= d <= s.last):
                    continue
                if self.team[idx[j]] in self.games.get(day, ()):
                    out_today = not can[j] or day < self.return_date.get(s.player_id, day)
                    grid.iat[j, d] = "▶" if counted_mask[d, j] else ("✕" if out_today else "B")
        return TeamWeek(team_id, list(stints), vec, grid, pd.Series(counted, index=ids),
                        int(playing.sum()), int(playing.sum() - counted.sum()), slots, playing)

    def _expected_assignment(self, elig: np.ndarray, allowed: np.ndarray, units: np.ndarray,
                             strategy: Strategy, acc: np.ndarray | None,
                             reference: np.ndarray | None = None) -> np.ndarray:
        """Choose expected category contribution, then compare feasible lineup swaps.

        Ratios and turnovers are scored jointly on team totals rather than
        multiplying possibly negative z-scores by attendance probabilities.
        This is a bounded local search, not an exhaustive lineup optimizer.
        """
        if not allowed.any():
            return np.full(len(allowed), -1)
        reference = self.lineup_reference if reference is None else reference
        context = np.zeros(WEEK_DIM) if acc is None else acc
        w = strategy.normalized
        priority = p_win(context + units, reference, self.config) @ w
        slots = slot_assignment(elig, allowed, priority)
        # Full lineups that fit have no competing alternatives.
        for _ in range(2):
            selected = slots >= 0
            benched = np.flatnonzero(allowed & ~selected)
            if not len(benched):
                break
            total = context + units[selected].sum(axis=0)
            choices, vectors = [], []
            for incoming in benched:
                for outgoing in np.flatnonzero(selected):
                    pick = selected.copy()
                    pick[outgoing], pick[incoming] = False, True
                    assignment = slot_assignment(elig, pick)
                    if np.count_nonzero(assignment >= 0) == np.count_nonzero(selected):
                        choices.append(assignment)
                        vectors.append(total + units[incoming] - units[outgoing])
            if not vectors:
                break
            scores = p_win(np.stack([total, *vectors]), reference, self.config) @ w
            best = int(np.argmax(scores))
            if best == 0 or scores[best] <= scores[0] + 1e-12:
                break
            slots = choices[best - 1]
        return slots

    def daily_vectors(self, idx: np.ndarray, days: list[dt.date]) -> np.ndarray:
        """(Day, player, moment) including attendance and temporary role production."""
        idx = np.asarray(idx, int)
        units = np.broadcast_to(self.unit[idx], (len(days), len(idx), WEEK_DIM)).copy()
        weight = np.ones((len(days), len(idx)))
        avail = np.broadcast_to(self.availability[idx], (len(days), len(idx))).copy()
        for j, i in enumerate(idx):
            pw = self.play_weight.get(self.engine.ids[i], {})
            weight[:, j] = [pw.get(day, 1.0) for day in days]
        role, present = self.near_role[idx], self.near_present[idx]
        for d, day in enumerate(days):
            if day < self.near_until:
                units[d, role] = self.near_unit[idx[role]]
                avail[d, present] = self.near_availability[idx[present]]
            boosted = day < self.boost_until[idx]
            units[d, boosted] = self.boost_unit[idx[boosted]]
        return attendance_vectors(units, np.minimum(weight * avail, 1.0))

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
                             week_days, a_o, reference=mine.vector)
        mine = self.team_week(team_id, mine.stints, week_days, a_m, reference=opp.vector)
        p, ew, sc, p5 = self.evaluate(mine, opp)
        return WeekOutlook(week, week_days, mine, opp, p, ew, sc, p5)

    def free_agents(self) -> list[str]:
        owned = {p for r in self.engine.league.rosters.values() for p in r}
        return [p for p in self.engine.ids if p not in owned and self.playable(p)]

    def _can_start(self, pid: str, day: dt.date, available_from: dict[str, dt.date]) -> bool:
        """Eklenen oyuncu o gün oynayabilir mi: maçı var ve (waiver'daysa) serbest kalmış."""
        return self.has_game(pid, day) and day >= available_from.get(pid, day)

    def shortlist(self, base: WeekOutlook, available_from: dict[str, dt.date] | None = None,
                  size: int = 30) -> tuple[list[str], np.ndarray]:
        """Boştakiler, kadroya kısıtsız eklenince (lineup yok, hızlı ön eleme) haftalık puan artışına göre; ikinci
        çıktı her birinin kategori olasılığı artışı ``(F, C)``."""
        avail = available_from or {}
        fa = [p for p in self.free_agents() if any(self._can_start(p, d, avail) for d in base.days)]
        if not fa:
            return [], np.zeros((0, len(base.p)))
        idx = np.array([self.engine.index[p] for p in fa])
        playing = np.array([[self._can_start(p, d, avail) and d >= self.return_date.get(p, d)
                             for p in fa] for d in base.days], dtype=bool).reshape(len(base.days), len(fa))
        contribution = (self.daily_vectors(idx, base.days) * playing[..., None]).sum(axis=0)
        cand = base.mine.vector[None, :] + contribution
        dp = ecw_vs(cand, base.opp.vector[None, None, :], self.config)[:, 0, :] - base.p[None, :]
        order = np.argsort(-(dp @ self.strategy.normalized), kind="stable")[:size]
        return [fa[i] for i in order], dp[order]

    def _moves(self, team_id: str, stints: list[Stint], drop_pool: list[str], fa: list[str], added: set[str],
               days: list[dt.date], acc: np.ndarray, opp: TeamWeek, available_from: dict[str, dt.date]):
        """Tek bir al/bırak adımının bütün adayları: ``(puan, deneme, tw, p, ew, p5, bırak, al, gün)``."""
        active_ids = {s.player_id for s in stints}
        for d_id in [p for p in drop_pool if p in active_ids]:
            j = next(k for k, s in enumerate(stints) if s.player_id == d_id)
            s0 = stints[j]
            end = min(s0.last, len(days) - 1)
            for f_id in fa:
                if f_id in active_ids:
                    continue
                # eklenen oyuncu bırakılanın kalan günlerini devralır (kadro büyüklüğü her gün sabit);
                # başlangıç yalnızca eklenenin oynayabildiği günler (maçsız günden başlamak bırakılanın maçını boşa
                # harcar; waiver'daki oyuncu serbest kalmadan alınamaz); eklenmiş bir streamer ilk gününde bırakılmaz
                first_t = max(s0.first, 0) + (1 if d_id in added else 0)
                for t in (k for k in range(first_t, end + 1) if self._can_start(f_id, days[k], available_from)):
                    trial = [*stints[:j], Stint(d_id, s0.first, t - 1, s0.slot), *stints[j + 1:],
                             Stint(f_id, t, s0.last, s0.slot)]
                    tw = self.team_week(team_id, trial, days, acc, reference=opp.vector)
                    p, ew, sc, p5 = self.evaluate(tw, opp)
                    yield sc, trial, tw, p, ew, p5, d_id, f_id, t

    def single_moves(self, base: WeekOutlook, *, droppable: list[str], acc_mine=None,
                     available_from: dict[str, dt.date] | None = None, shortlist: int = 30) -> pd.DataFrame:
        """Kısa listedeki her boştaki oyuncu için en iyi tek hamle (bırakılacak oyuncu ve gün) ve etkisi."""
        avail = available_from or {}
        fa, _ = self.shortlist(base, avail, shortlist)
        stints = [Stint(s.player_id, s.first, s.last, s.slot) for s in base.mine.stints]
        best: dict[str, tuple] = {}
        for c in self._moves(base.mine.team_id, stints, list(dict.fromkeys(droppable)), fa, set(), base.days,
                             accumulated_vector(acc_mine), base.opp, avail):
            if c[7] not in best or c[0] > best[c[7]][0]:
                best[c[7]] = c
        rows = []
        for f_id, (sc, trial, tw, p, ew, p5, d_id, _, t) in best.items():
            rows.append({"add": f_id, "drop": d_id, "day": base.days[t], "games": int(tw.counted.get(f_id, 0)),
                         "gain": sc - base.strategy_score, "d_expected_wins": ew - base.expected_wins,
                         "d_p5": p5 - base.p5, "dp": p - base.p, "available_from": avail.get(f_id),
                         "ros_delta": swap_delta(self.engine, base.mine.team_id, d_id, f_id, self.strategy)})
        return pd.DataFrame(rows).sort_values("gain", ascending=False, kind="stable").reset_index(drop=True)             if rows else pd.DataFrame(rows)

    def stream(self, base: WeekOutlook, *, moves: int, droppable: list[str], acc_mine=None,
               shortlist: int = 30, min_gain: float = 0.01,
               available_from: dict[str, dt.date] | None = None, beam: int = 1) -> WeekOutlook:
        """Streaming planı; ``base`` aynı günler için ``outlook`` sonucudur. ``available_from``: waiver'daki oyuncunun
        serbest kaldığı gün (öncesinde alınamaz). ``beam``: her adımda tutulan kısmi plan sayısı (1 = açgözlü; daha
        büyüğü birbirini etkileyen hamleleri, ör. hafta başı alıp aynı yerde sonra değiştirmeyi, birlikte arar)."""
        days = base.days
        avail = available_from or {}
        a_m = accumulated_vector(acc_mine)
        opp = base.opp
        out = WeekOutlook(base.week, days, base.mine, opp, base.p, base.expected_wins, base.strategy_score, base.p5)
        fa0, _ = self.shortlist(base, avail, shortlist)
        if not fa0 or moves <= 0 or not droppable:
            return out
        start = {"outlook": out, "stints": [Stint(s.player_id, s.first, s.last, s.slot) for s in base.mine.stints],
                 "drop_pool": list(dict.fromkeys(droppable)), "added": set(), "fa": list(fa0)}
        frontier, best = [start], start
        width = max(1, int(beam))
        for _ in range(moves):
            children = []
            for plan in frontier:
                cands = sorted(self._moves(base.mine.team_id, plan["stints"], plan["drop_pool"], plan["fa"],
                                           plan["added"], days, a_m, opp, avail), key=lambda c: -c[0])
                current = plan["outlook"]
                for sc, trial, tw, p, ew, p5, d_id, f_id, t in cands[:width]:
                    if sc - current.strategy_score < min_gain:
                        break
                    move = Move(days[t], f_id, d_id, sc - current.strategy_score,
                                swap_delta(self.engine, base.mine.team_id, d_id, f_id, self.strategy))
                    children.append({"outlook": WeekOutlook(base.week, days, tw, opp, p, ew, sc, p5,
                                                            [*current.moves, move]),
                                     "stints": [s for s in trial if s.first <= s.last],
                                     "drop_pool": [*plan["drop_pool"], f_id], "added": plan["added"] | {f_id},
                                     "fa": [x for x in plan["fa"] if x != f_id]})
            if not children:
                break
            seen, frontier = set(), []
            for c in sorted(children, key=lambda c: -c["outlook"].strategy_score):
                key = frozenset((s.player_id, s.first, s.last, s.slot) for s in c["stints"])
                if key not in seen:
                    seen.add(key)
                    frontier.append(c)
                if len(frontier) >= width:
                    break
            if frontier[0]["outlook"].strategy_score > best["outlook"].strategy_score:
                best = frontier[0]
        current = best["outlook"]
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
