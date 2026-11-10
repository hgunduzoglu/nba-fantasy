"""Sezon simülasyonu: normal sezon kalan fikstür + playoff braketi (README §13.14).

* **Başlangıç**: tam sıralama varsa tamamlanan hafta ``(W+L+T)/9`` kabul edilir ve gerçek W-L-T'den
  başlanır; yoksa 1. haftadan itibaren her hafta simüle edilir.
* **Haftalık güç**: her takımın o haftaki vektörü ``WeekModel.team_week`` ile (gerçek NBA takvimi, günlük
  lineup, uygunluk). İçinde bulunulan hafta güncel sakatlık durumu ve IL ile; gelecek haftalarda bütün
  kadro (IL dahil) durumdan bağımsız (kaçırılacak maçlar ROS GP'de). Kadrolar sezon boyu sabit; tek istisna
  IL dönüşü: boş aktif yer yoksa dönüş gününden itibaren en düşük değerli aktif oyuncu (dengeli değer) kadrodan
  çıkar, dönen oyuncu daha zayıfsa kendisi hiç aktifleşmez (``drop_schedule``). Dönüş tarihi bilinmeyen IL
  oyuncusu gelecek hafta döner sayılır.
* **İçinde bulunulan hafta**: yalnız veri tarihinden itibaren kalan günler senaryonun (takas sonrası) kadrosuyla
  oynanır. Geçmiş günler Yahoo senkronizasyonunun gerçek hafta toplamıdır (``realized``, §13.20); yoksa takas öncesi
  gerçek kadronun beklenen katkısı. İkisi de her senaryoda aynıdır (``_past``); takas geçmiş günleri değiştirmez.
* **Eşleşme**: kategori olasılıkları ``p_win``; birlikte çekiliş Gauss kopulası (``category_corr``).
  Kategori beraberliği yok sayılır (9 tek sayı → eşleşmede beraberlik yok).
* **Sıralama**: (W + T/2) / (W+L+T), eşitlikte rastgele. **Playoff**: ilk ``n`` takım; braket ``2^tur``
  boyutunda, boş koltuklar bay. ``Playoff Reseeding: Yes`` ise her turda en yüksek – en düşük eşleşir,
  değilse standart sabit braket. Playoff haftaları kendi takvimiyle (son tur iki takvim haftası olabilir).
* **Güç belirsizliği**: kalan sezon projeksiyonunun hatası için her simülasyonda her takımın haftalık
  vektörü (ortalama ve varyans) sezon boyu sabit bir ``λ ~ lognormal(0, strength_sd)`` ile ölçeklenir
  (oranlar değişmez). Olmadan takım güçleri kesin bilinir sayılır ve olasılıklar aşırı kesinleşir.
  ``strength_sd`` kalibre edilmedi (varsayılan 0.06).
* Aynı ``seed`` ile iki senaryo aynı çekilişleri kullanır (CRN): takas etkisi eşleşmeli farktır.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.special import ndtri

from fdo.inseason.weekly import Stint, WeekModel, accumulated_vector
from fdo.inseason.weeks import LeagueWeeks
from fdo.matchup.ecw import ecw_vs, p_at_least, p_win
from fdo.matchup.player_week import WEEK_DIM
from fdo.trade.strategy import Strategy


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


@dataclass(frozen=True)
class PairedDelta:
    """İki senaryonun aynı çekilişlerle (aynı ``seed`` ve simülasyon sayısı) farkı. ``se``: farkın Monte Carlo standart
    hatası (simülasyon başına fark dizisinden); kalan sezon modelinin kendi hatasını içermez."""

    before: float
    after: float
    delta: float
    se: float

    @property
    def clear(self) -> bool:
        """Fark simülasyon gürültüsünden ayrılıyor mu (|Δ| ≥ 2·SE). Ayrılmıyorsa sıralamada eşit sayılmalı."""
        return bool(self.se == self.se and abs(self.delta) >= 2 * self.se and self.delta != 0)


def paired(before: np.ndarray, after: np.ndarray) -> PairedDelta:
    b, a = np.asarray(before, dtype=float), np.asarray(after, dtype=float)
    d = a - b
    se = float(d.std(ddof=1) / np.sqrt(len(d))) if len(d) > 1 else float("nan")
    return PairedDelta(float(b.mean()), float(a.mean()), float(d.mean()), se)


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
                 standings: pd.DataFrame | None, as_of: dt.date,
                 realized: dict[str, dict[str, float]] | None = None):
        """``realized``: içinde bulunulan haftanın takım → şu ana kadarki toplamları (``accumulated_vector`` alanları)."""
        self.model = model
        self.realized = realized or {}
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
        self._past_cache: dict[tuple[str, int], np.ndarray] = {}
        self._drop_cache: dict[tuple, dict[str, dt.date]] = {}
        if self.current_week is not None and any(d < as_of for d in weeks.days(self.current_week)):
            if set(self.teams) <= set(self.realized):
                self.notes.append(f"{self.current_week}. hafta sürüyor: geçmiş günler Yahoo'daki gerçek skordur; takas "
                                  "yalnız kalan günleri etkiler.")
            else:
                self.realized = {}
                self.notes.append(f"{self.current_week}. hafta sürüyor: geçmiş günlerin gerçek skoru bilinmediği için bu "
                                  "günler takas öncesi kadroyla beklenen değerdir; takas yalnız kalan günleri etkiler.")

    # ------------------------------------------------------------- haftalık vektörler
    def il_map(self, rosters: dict[str, tuple[str, ...]],
               injuries: dict[str, frozenset[str]] | None = None) -> dict[str, frozenset[str]]:
        return {t: self.engine._il(t, rosters[t], injuries) for t in self.teams}

    def drop_schedule(self, roster: tuple[str, ...], il: frozenset[str]) -> dict[str, dt.date]:
        """IL dönüşünde kadrodan çıkan oyuncu → çıktığı gün (``TradeEngine.crunch_vector`` ile aynı kural,
        dengeli değerle). Dönen oyuncu bırakılırsa kendisi listededir (hiç aktifleşmez)."""
        key = (tuple(sorted(roster)), tuple(sorted(il)))
        if key in self._drop_cache:
            return self._drop_cache[key]
        eng = self.engine
        back = [p for p in il if p in set(roster) and eng.modeled[eng.index[p]] and eng.return_share(p) > 0]
        gone: dict[str, dt.date] = {}
        if back:
            u = eng._utility_array(Strategy())
            ret = {p: self.model.return_date.get(p) or self.as_of + dt.timedelta(days=7) for p in back}
            active = [p for p in roster if p not in il]
            free = self.league.capacity - len(active)
            pool = sorted((p for p in active if eng.modeled[eng.index[p]]), key=lambda p: u[eng.index[p]])
            for r in sorted(back, key=lambda p: ret[p]):
                if free > 0:
                    free -= 1
                elif not pool or u[eng.index[r]] <= u[eng.index[pool[0]]]:
                    gone[r] = ret[r]
                    continue
                else:
                    gone[pool.pop(0)] = ret[r]
                pool.append(r)
                pool.sort(key=lambda p: u[eng.index[p]])
        self._drop_cache[key] = gone
        return gone

    def _past(self, team: str, week: int) -> np.ndarray:
        """İçinde bulunulan haftanın veri tarihinden önceki günleri: Yahoo'daki gerçek toplam, yoksa takas öncesi gerçek
        kadronun (IL hariç, güncel durumla) beklenen katkısı. Senaryodan bağımsız."""
        key = (team, week)
        if key not in self._past_cache and week == self.current_week and team in self.realized:
            self._past_cache[key] = accumulated_vector(self.realized[team])
        if key not in self._past_cache:
            days = [d for d in self.weeks.days(week) if d < self.as_of]
            roster = self.league.rosters[team]
            il = self.engine._il(team, roster)
            stints = [Stint(p, slot=i) for i, p in enumerate(p for p in roster if p not in il)]
            self._past_cache[key] = self.model.team_week(team, stints, days).vector if days else np.zeros(WEEK_DIM)
        return self._past_cache[key]

    def vector(self, team: str, roster: tuple[str, ...], week: int, il: frozenset[str] | None = None) -> np.ndarray:
        il = self.engine._il(team, roster) if il is None else frozenset(il)
        key = (team, tuple(sorted(roster)), tuple(sorted(il)), week)
        if key not in self._vec_cache:
            if len(self._vec_cache) > 50_000:
                self._vec_cache.clear()
            current = week == self.current_week
            days = self.weeks.days(week)
            if current:
                days = [d for d in days if d >= self.as_of]
            gone = self.drop_schedule(roster, il)
            stints = []
            for p in roster:
                if current and p in il:
                    continue
                last = 10_000
                if p in gone:
                    last = sum(d < gone[p] for d in days) - 1                  # çıktığı günden önceki son gün
                    if last < 0:
                        continue
                stints.append(Stint(p, last=last, slot=len(stints)))
            tw = self.model.team_week(team, stints, days, use_status=current)
            self._vec_cache[key] = tw.vector + self._past(team, week) if current else tw.vector
        return self._vec_cache[key]

    def week_vectors(self, rosters: dict[str, tuple[str, ...]], week: int,
                     il: dict[str, frozenset[str]] | None = None) -> np.ndarray:
        il = il or self.il_map(rosters)
        return np.stack([self.vector(t, rosters[t], week, il[t]) for t in self.teams])

    def fixture_outlook(self, team: str, rosters: dict[str, tuple[str, ...]] | None = None,
                        injuries: dict[str, frozenset[str]] | None = None) -> pd.DataFrame:
        """Takımın kalan normal sezon haftaları: rakip, beklenen kategori ve haftayı kazanma olasılığı (nokta
        tahmini, güç belirsizliği yok). Takas sonrası kadrolarla çağrılırsa iki tarafın değişimi de yansır."""
        rosters = dict(rosters or self.league.rosters)
        il = self.il_map(rosters, injuries)
        me = self.tix[team]
        rows = []
        for w in [w for w in self.regular if w >= self.done + 1]:
            for x, y in self.pairs.get(w, []):
                if me not in (x, y):
                    continue
                o = self.teams[y if me == x else x]
                vm = self.vector(team, rosters[team], w, il[team])
                vo = self.vector(o, rosters[o], w, il[o])
                pm = ecw_vs(vm, vo[None, :], self.engine.config)[0]
                rows.append({"week": w, "start": self.weeks.weeks.loc[w, "start"] if w in self.weeks.weeks.index else None,
                             "opponent": o, "exp_cats": float(pm.sum()),
                             "p_win": float(p_at_least(pm[None, :], 5, self.corr)[0])})
        out = pd.DataFrame(rows, columns=["week", "start", "opponent", "exp_cats", "p_win"])
        out["opponent_name"] = [self.league.teams[t] for t in out["opponent"]]
        return out

    # ------------------------------------------------------------- simülasyon
    def _wins(self, p: np.ndarray, rng: np.random.Generator) -> np.ndarray:
        """``p (S, M, C)`` → ``(S, M)`` A tarafının kazandığı kategori sayısı (kopula)."""
        C = p.shape[-1]
        L = np.linalg.cholesky(self.corr) if self.corr is not None else np.eye(C)
        z = rng.standard_normal(p.shape) @ L.T
        return (z < ndtri(np.clip(p, 1e-12, 1 - 1e-12))).sum(axis=-1)

    def run(self, rosters: dict[str, tuple[str, ...]] | None = None, *, n_sims: int = 2000, seed: int = 0,
            team: str | None = None, strength_sd: float = 0.06,
            injuries: dict[str, frozenset[str]] | None = None) -> SeasonResult:
        """``injuries``: takas sonrası IL kümeleri (``TradeEngine.resolve``); yoksa lig IL'i ∩ kadro."""
        rosters = dict(rosters or self.league.rosters)
        il = self.il_map(rosters, injuries)
        T, S = len(self.teams), int(n_sims)
        rng = np.random.default_rng(seed)
        lam = np.exp(strength_sd * rng.standard_normal((S, T)))                         # (S, T) sezonluk güç çarpanı
        W = np.zeros((S, T))
        L_ = np.zeros((S, T))
        Tie = np.zeros((S, T))
        if self.standings is not None:
            st = self.standings.loc[self.teams]
            W += st["wins"].to_numpy(float)
            L_ += st["losses"].to_numpy(float)
            Tie += st["ties"].to_numpy(float)
        start = self.done + 1
        for w in [w for w in self.regular if w >= start]:
            pairs = self.pairs.get(w, [])
            if not pairs:
                continue
            V = self.week_vectors(rosters, w, il)
            a = np.array([x for x, _ in pairs])
            b = np.array([y for _, y in pairs])
            ps = p_win(lam[:, a, None] * V[a][None], lam[:, b, None] * V[b][None], self.engine.config)  # (S, M, C)
            k = self._wins(ps, rng)                                                       # (S, M)
            np.add.at(W, (slice(None), a), k)
            np.add.at(L_, (slice(None), a), 9 - k)
            np.add.at(W, (slice(None), b), 9 - k)
            np.add.at(L_, (slice(None), b), k)
        pct = (W + 0.5 * Tie) / np.maximum(W + L_ + Tie, 1)
        order = np.argsort(-(pct + 1e-9 * rng.random((S, T))), axis=1, kind="stable")    # eşitlikte rastgele
        seeds = np.empty((S, T), dtype=int)
        np.put_along_axis(seeds, order, np.arange(1, T + 1)[None, :].repeat(S, 0), axis=1)
        champion = self._playoffs(rosters, seeds, rng, S, lam, il)
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
        sched = self.fixture_outlook(team, rosters, injuries) if team is not None else pd.DataFrame()
        notes = list(self.notes) + [f"Takım gücü belirsizliği: sezonluk ±%{100 * strength_sd:.0f} (kalibre edilmedi)."]
        return SeasonResult(table, sched, seeds, champion, start, S, n, notes)

    def effect(self, base: SeasonResult, after: SeasonResult, team: str) -> dict[str, PairedDelta]:
        """Bir senaryonun takıma etkisi: ``playoff`` (playoff varsa), ``champion``, ``seed`` (ortalama sıra). İki koşu
        aynı ``seed`` ve simülasyon sayısıyla yapılmış olmalı; fark simülasyon simülasyon eşleşir."""
        if base.n_sims != after.n_sims or base.seeds.shape != after.seeds.shape:
            raise ValueError("Eşleşmeli fark için iki koşu aynı simülasyon sayısıyla yapılmalı")
        i = self.tix[team]
        out = {"champion": paired(base.champion[:, i], after.champion[:, i]),
               "seed": paired(base.seeds[:, i], after.seeds[:, i])}
        if base.playoff_size:
            n = base.playoff_size
            out["playoff"] = paired(base.seeds[:, i] <= n, after.seeds[:, i] <= n)
        return out

    def _playoffs(self, rosters, seeds: np.ndarray, rng: np.random.Generator, S: int, lam: np.ndarray,
                  il: dict[str, frozenset[str]]) -> np.ndarray:
        T = len(self.teams)
        champion = np.zeros((S, T), dtype=bool)
        n, rounds = self.playoff_size, len(self.playoff_weeks)
        if not n or not rounds:
            return champion
        size = 2 ** rounds
        # koltuk (seed) → takım indeksi; bay koltuğu -1
        by_seed = np.full((S, size), -1)
        order = np.argsort(seeds, axis=1)
        k = min(n, size, T)
        by_seed[:, :k] = order[:, :k]
        current = bracket_order(size) if not self.reseed else list(range(1, size + 1))
        cur = np.array(current)[None, :].repeat(S, 0)                                     # (S, k) seed
        for r, week in enumerate(self.playoff_weeks):
            V = self.week_vectors(rosters, week, il)
            if self.reseed:
                cur = np.sort(cur, axis=1)
                k = cur.shape[1]
                hi, lo = cur[:, : k // 2], cur[:, ::-1][:, : k // 2]
            else:
                hi, lo = cur[:, 0::2], cur[:, 1::2]
            ta = np.take_along_axis(by_seed, hi - 1, axis=1)
            tb = np.take_along_axis(by_seed, lo - 1, axis=1)
            bye_a, bye_b = ta < 0, tb < 0
            ia, ib = np.maximum(ta, 0), np.maximum(tb, 0)
            sims = np.arange(S)[:, None]
            pa = p_win(lam[sims, ia][..., None] * V[ia], lam[sims, ib][..., None] * V[ib], self.engine.config)  # (S, g, C)
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
