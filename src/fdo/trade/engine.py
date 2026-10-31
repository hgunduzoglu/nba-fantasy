"""Üç kaynaklı sıralamalar, ROS matchup ve takas sonrası tüm ligin yeniden hesabı."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from fdo.matchup.ecw import ecw_matrix, p_at_least, team_ecw
from fdo.matchup.player_week import COUNT_STATS, N_COUNT, RATIO_OFFSETS, WEEK_DIM, per_game_variance
from fdo.roster.assignment import best_assignment
from fdo.trade.data import MODES, ROS, TradeData, TradeLeague
from fdo.trade.strategy import CATEGORIES, Strategy
from fdo.types import STATS
from fdo.valuation import value_players


class TradeError(ValueError):
    """Sahiplik, takım, oyuncu veya kadro kapasitesi hatası."""


@dataclass(frozen=True)
class TradeRequest:
    team_a: str
    team_b: str
    give_a: tuple[str, ...]
    give_b: tuple[str, ...]
    drop_a: tuple[str, ...] = ()
    drop_b: tuple[str, ...] = ()
    add_a: tuple[str, ...] = ()
    add_b: tuple[str, ...] = ()
    auto_drop: bool = False
    auto_fill: bool = False

    def __post_init__(self):
        object.__setattr__(self, "team_a", str(self.team_a))
        object.__setattr__(self, "team_b", str(self.team_b))
        for name in ("give_a", "give_b", "drop_a", "drop_b", "add_a", "add_b"):
            object.__setattr__(self, name, tuple(str(x) for x in getattr(self, name)))


@dataclass
class LeagueView:
    totals: pd.DataFrame
    ranks: pd.DataFrame
    coverage: pd.DataFrame


@dataclass
class TradeResult:
    request: TradeRequest
    before: dict[str, LeagueView]
    after: dict[str, LeagueView]
    probabilities_before: np.ndarray
    probabilities_after: np.ndarray
    matchup_before: np.ndarray
    matchup_after: np.ndarray
    metrics: pd.DataFrame
    rosters_after: dict[str, tuple[str, ...]]
    adjustments: dict[str, dict[str, tuple[str, ...]]]
    assessments: dict
    strategies: dict[str, Strategy]
    notes: list[str] = field(default_factory=list)


class TradeEngine:
    """Okunan veriyi değiştirmez; her senaryo orijinal kadrolara karşı hesaplanır.

    Matchup: ROS toplamı / kalan NBA takvim süresi → tipik hafta. GP/82 kullanılmaz.
    Günlük lineup için açık utilization varsayımı kullanılır; gerçek H2H fikstürü gerekmez.
    ECW kategori beklentisidir. P(5+) kategori bağımsızlığı varsayan ek göstergedir.
    """

    def __init__(self, data: TradeData, league_id: str, *, utilization: float = .987,
                 horizon_weeks: float | None = None):
        if not 0 < utilization <= 1:
            raise ValueError("Lineup kullanım oranı (0, 1] aralığında olmalı")
        self.data, self.league = data, data.leagues[str(league_id)]
        self.config = self.league.config
        self.team_ids = tuple(self.league.teams)
        self.team_index = {t: i for i, t in enumerate(self.team_ids)}
        self.ids = tuple(data.players.index)
        self.index = {p: i for i, p in enumerate(self.ids)}
        self.utilization = utilization
        if horizon_weeks is None:
            if data.schedule is None:
                raise ValueError("Haftalık modele NBA takvimi veya açık horizon_weeks gerekiyor")
            last = pd.to_datetime(data.schedule["game_date"]).max().date()
            horizon_weeks = ((last - data.as_of).days + 1) / 7
        if not np.isfinite(horizon_weeks) or horizon_weeks <= 0:
            raise ValueError("Kalan sezon süresi pozitif olmalı")
        self.horizon_weeks = float(horizon_weeks)
        self.arrays, self.complete = {}, {}
        for mode in MODES:
            frame = data.stats[mode].reindex(self.ids)
            arr = frame[list(STATS)].to_numpy(float)
            self.arrays[mode] = arr
            self.complete[mode] = np.isfinite(arr).all(axis=1) & frame["gp"].notna().to_numpy()
        self.vecs, self.modeled = self._weekly_vectors()
        self._vector_cache: dict[tuple[str, ...], np.ndarray] = {}
        self.baseline_vectors = self.vectors(self.league.rosters)
        self.baseline_p = ecw_matrix(self.baseline_vectors, self.config)
        self.baseline_matchup = p_at_least(self.baseline_p)
        np.fill_diagonal(self.baseline_matchup, np.nan)
        self.before = {m: self.view(self.league.rosters, m) for m in MODES}
        self.market, self.zscores = self._market_values()
        # Arama döngüleri için pandas'sız kopyalar (öneri taraması paket başına çok kez okur).
        self._market_arr = self.market.to_numpy(float)
        self._z_arr = self.zscores.to_numpy(float)
        self._utility_cache: dict[Strategy, np.ndarray] = {}
        self._status = dict(zip(self.ids, data.players["injury_status"].reindex(list(self.ids)).astype(str)))

    def _weekly_vectors(self) -> tuple[np.ndarray, np.ndarray]:
        f = self.data.stats[ROS].reindex(self.ids)
        gp = f["gp"].to_numpy(float)
        raw = f[list(STATS)].to_numpy(float)
        valid = (np.isfinite(raw).all(axis=1) & np.isfinite(gp) & (gp > 0)
                 & (raw >= 0).all(axis=1) & (f["fgm"] <= f["fga"]).to_numpy()
                 & (f["ftm"] <= f["fta"]).to_numpy())
        proj = f.loc[valid, list(STATS)].div(f.loc[valid, "gp"], axis=0)
        proj["player_id"] = proj.index
        var, _ = per_game_variance(proj, self.data.variance, self.config.model.variance.phi)
        mu = proj[list(STATS)]
        k = gp[valid] * self.utilization / self.horizon_weeks
        out = np.zeros((len(self.ids), WEEK_DIM))
        v = np.zeros((len(mu), WEEK_DIM))
        for j, stat in enumerate(COUNT_STATS):
            v[:, j] = k * mu[stat].to_numpy()
            v[:, N_COUNT + j] = k * var[stat].to_numpy()
        for key, (mk, at) in {"fg": ("fgm", "fga"), "ft": ("ftm", "fta")}.items():
            o = RATIO_OFFSETS[key]
            m, a, av = mu[mk].to_numpy(), mu[at].to_numpy(), var[at].to_numpy()
            pct = np.divide(m, a, out=np.zeros_like(m), where=a > 0)
            v[:, o], v[:, o + 1] = k * m, k * a
            v[:, o + 2] = k * (a * pct * (1 - pct) + pct ** 2 * av)
            v[:, o + 3], v[:, o + 4] = k * pct * av, k * av
        out[valid] = v
        return out, valid

    def _market_values(self) -> tuple[pd.Series, pd.DataFrame]:
        frame = self.data.stats[ROS].loc[np.asarray(self.ids)[self.modeled], ["gp", *STATS]].copy()
        proj = frame[list(STATS)].div(frame["gp"], axis=0)
        proj["projected_gp"], proj["player_id"] = frame["gp"], frame.index
        res = value_players(proj, self.config, basis="total", method="z")
        values = res.table["V"].sort_values(ascending=False)
        replacement = float(values.iloc[min(len(values) - 1, self.config.pool_size)]) if len(values) else 0
        market = (values - replacement + .5).clip(lower=.1).reindex(self.ids).fillna(0.0)
        return market, res.scores.reindex(self.ids).fillna(0.0)

    def roster_vector(self, roster: tuple[str, ...]) -> np.ndarray:
        key = tuple(sorted(roster))
        cached = self._vector_cache.get(key)
        if cached is None:
            # Bounded search cache; returned vectors are never edited in place.
            if len(self._vector_cache) > 20_000:
                self._vector_cache.clear()
            cached = self.vecs[[self.index[p] for p in roster]].sum(axis=0)
            self._vector_cache[key] = cached
        return cached

    def vectors(self, rosters: dict[str, tuple[str, ...]]) -> np.ndarray:
        return np.stack([self.roster_vector(rosters[t]) for t in self.team_ids])

    def view(self, rosters: dict[str, tuple[str, ...]], mode: str) -> LeagueView:
        categories, cover = [], []
        arr = self.arrays[mode]
        for tid in self.team_ids:
            ix = [self.index[p] for p in rosters[tid]]
            a = arr[ix]
            total = np.nansum(a, axis=0)
            if len(a):
                total[np.isnan(a).all(axis=0)] = np.nan
            else:
                total[:] = np.nan
            v = dict(zip(STATS, total))
            row = {}
            for cat, mk, at in (("FG_PCT", "fgm", "fga"), ("FT_PCT", "ftm", "fta")):
                m, attempts = a[:, STATS.index(mk)], a[:, STATS.index(at)]
                known = np.isfinite(m) & np.isfinite(attempts)
                denominator = attempts[known].sum()
                # Pay ve payda aynı oyunculara ait olmalı; eksik isabet '0' sayılmaz.
                row[cat] = float(m[known].sum() / denominator) if denominator > 0 else np.nan
            row.update({c: v[s] for c, s in zip(CATEGORIES[2:], COUNT_STATS)})
            categories.append(row)
            cover.append({"roster": len(ix), "complete": int(self.complete[mode][ix].sum()),
                          "modeled_ros": int(self.modeled[ix].sum())})
        totals = pd.DataFrame(categories, index=self.team_ids)
        ranks = totals.rank(ascending=False, method="average", na_option="keep")
        for c in self.config.lower_is_better:
            ranks[c] = totals[c].rank(ascending=True, method="average", na_option="keep")
        return LeagueView(totals, ranks, pd.DataFrame(cover, index=self.team_ids))

    def positions(self, ids) -> list[frozenset[str]]:
        return [frozenset(str(self.data.players.loc[p, "yahoo_positions"]).split(",")) for p in ids]

    def _utility(self, ids, strategy: Strategy) -> pd.Series:
        u = self._utility_cache.get(strategy)
        if u is None:
            if len(self._utility_cache) > 64:
                self._utility_cache.clear()
            u = self._utility_cache[strategy] = self._z_arr @ strategy.normalized
        ids = list(ids)
        return pd.Series(u[[self.index[p] for p in ids]], index=ids, dtype=float)

    def resolve(self, request: TradeRequest, strategies: dict[str, Strategy] | None = None
                ) -> tuple[dict[str, tuple[str, ...]], dict, dict[str, frozenset[str]]]:
        a, b = request.team_a, request.team_b
        if a == b or a not in self.team_index or b not in self.team_index:
            raise TradeError("Takas için ligdeki iki farklı takım seçilmeli")
        if not request.give_a or not request.give_b:
            raise TradeError("İki taraf da en az bir oyuncu vermeli")
        for field in ("give_a", "give_b", "drop_a", "drop_b", "add_a", "add_b"):
            ids = getattr(request, field)
            if len(ids) != len(set(ids)) or any(p not in self.index for p in ids):
                raise TradeError("Tekrarlanan veya bilinmeyen oyuncu")
        original = self.league.rosters
        for tid, sent, drops in ((a, request.give_a, request.drop_a), (b, request.give_b, request.drop_b)):
            if not set(sent) <= set(original[tid]) or not set(drops) <= set(original[tid]) - set(sent):
                raise TradeError("Gönderilen/bırakılan oyuncu o takımın kadrosunda değil veya iki kez seçilmiş")
        return self.resolve_moves(
            {a: request.give_a, b: request.give_b},
            {a: [(p, b) for p in request.give_b], b: [(p, a) for p in request.give_a]},
            {a: request.drop_a, b: request.drop_b}, {a: request.add_a, b: request.add_b},
            auto_drop=request.auto_drop, auto_fill=request.auto_fill, strategies=strategies)

    def resolve_moves(self, sent: dict[str, tuple[str, ...]], received: dict[str, list[tuple[str, str]]],
                      drops: dict[str, tuple[str, ...]], adds: dict[str, tuple[str, ...]], *, auto_drop: bool,
                      auto_fill: bool, strategies: dict[str, Strategy] | None = None
                      ) -> tuple[dict[str, tuple[str, ...]], dict, dict[str, frozenset[str]]]:
        """Takım sayısından bağımsız kadro çözümü (2 takımlı ve çok takımlı takas).

        ``sent[t]``: t'nin gönderdikleri; ``received[t]``: ``(oyuncu, kaynak takım)``; ``drops``/``adds``: elle
        bırak/boştan al. Takımlar ``sent`` sırasıyla işlenir (otomatik eklemeler sıralı ayrılır).
        """
        original = self.league.rosters
        owned = {p for rr in original.values() for p in rr}
        added = tuple(p for t in sent for p in adds.get(t, ()))
        if len(added) != len(set(added)) or any(p in owned for p in added):
            raise TradeError("Eklenecek oyuncu ligde boşta olmalı ve yalnızca bir takıma eklenebilir")
        rosters = dict(original)
        injuries = dict(self.league.injury_rosters)
        adjustments = {}
        strategies = strategies or {}
        for tid in sent:
            out, drp, add = tuple(sent[tid]), tuple(drops.get(tid, ())), tuple(adds.get(tid, ()))
            incoming = list(received.get(tid, []))
            inc_ids = tuple(pid for pid, _ in incoming)
            roster = [p for p in original[tid] if p not in set(out + drp)] + list(inc_ids + add)
            il = set(injuries[tid]) - set(out + drp)
            moved_il = []
            for pid, origin in incoming:
                if (pid in self.league.injury_rosters[origin] and self._status[pid] in ("O", "INJ", "INJ+")
                        and len(il) < (self.config.unverified.il_slots or 0)):
                    il.add(pid)
                    moved_il.append(pid)
            strategy = strategies.get(tid, Strategy())
            automatic_drops, automatic_adds = [], []
            over = len(roster) - len(il) - self.league.capacity
            if over > 0:
                # Boşalan IL yerine kadrodaki sakat (O/INJ) aktif oyuncu taşınır; bırakma ancak sonra gerekir.
                free_il = (self.config.unverified.il_slots or 0) - len(il)
                injured = [p for p in roster if p not in il
                           and self._status[p] in ("O", "INJ", "INJ+")]
                for pid in injured[: max(0, min(over, free_il))]:
                    il.add(pid)
                    moved_il.append(pid)
                over = len(roster) - len(il) - self.league.capacity
            if over > 0 and auto_drop:
                candidates = [p for p in roster if p not in il and p not in inc_ids + add
                              and self.modeled[self.index[p]]]
                for pid in self._utility(candidates, strategy).sort_values(kind="stable").index[:over]:
                    roster.remove(pid)
                    automatic_drops.append(pid)
            if len(roster) - len(il) > self.league.capacity:
                raise TradeError(f"{self.league.teams[tid]}: normal kadro kapasitesi aşılıyor; bırakılacak oyuncu seç")
            # Önceden var olan boşluklar takasın kazancıymış gibi otomatik doldurulmaz.
            target = min(self.league.capacity, len(original[tid]) - len(injuries[tid]))
            if auto_fill:
                count = max(0, target - (len(roster) - len(il)))
                used = owned | set(added) | {p for adj in adjustments.values() for p in adj["add"]}
                free = [p for p in self.ids if p not in used and self.modeled[self.index[p]]]
                for pid in self._utility(free, strategy).sort_values(ascending=False, kind="stable").index[:count]:
                    roster.append(pid)
                    automatic_adds.append(pid)
            rosters[tid], injuries[tid] = tuple(roster), frozenset(il)
            adjustments[tid] = {"drop": drp + tuple(automatic_drops),
                                "add": add + tuple(automatic_adds), "move_to_il": tuple(moved_il)}
        return rosters, adjustments, injuries

    def score(self, rosters: dict[str, tuple[str, ...]], team_a: str, team_b: str,
              strategy_a: Strategy, strategy_b: Strategy) -> tuple[np.ndarray, dict]:
        return self.score_many(rosters, {team_a: strategy_a, team_b: strategy_b})

    def score_many(self, rosters: dict[str, tuple[str, ...]], strategies: dict[str, Strategy]
                   ) -> tuple[np.ndarray, dict]:
        """``strategies`` içindeki takımların kadroları değişmiş kabul edilir; diğerleri temel kadroda kalır."""
        vectors = self.baseline_vectors.copy()
        for tid in strategies:
            vectors[self.team_index[tid]] = self.roster_vector(rosters[tid])
        p = ecw_matrix(vectors, self.config)
        metrics = {}
        for tid, strategy in strategies.items():
            i = self.team_index[tid]
            keep = np.arange(len(self.team_ids)) != i
            before, after = self.baseline_p[i, keep], p[i, keep]
            bp, ap = before.mean(axis=0), after.mean(axis=0)
            bw, aw = float(p_at_least(before).mean()), float(p_at_least(after).mean())
            metrics[tid] = {"ecw_before": float(bp.sum()), "ecw_after": float(ap.sum()),
                            "ecw_delta": float((ap - bp).sum()), "win_before": bw, "win_after": aw,
                            "win_delta": aw - bw,
                            "strategy_before": float(bp @ strategy.normalized * 9),
                            "strategy_after": float(ap @ strategy.normalized * 9),
                            "strategy_delta": float((ap - bp) @ strategy.normalized * 9)}
        return p, metrics

    def category_profile(self, p: np.ndarray, team_id: str) -> np.ndarray:
        """Takımın rakipler üzerinden ortalama kategori kazanma olasılığı (``p``: ``ecw_matrix`` çıktısı)."""
        i = self.team_index[team_id]
        return p[i, np.arange(len(self.team_ids)) != i].mean(axis=0)

    def deadline(self, day: dt.date | None = None) -> tuple[dt.date | None, bool]:
        """Lig takas son tarihi ve ``day`` (varsayılan veri tarihi) itibarıyla geçip geçmediği."""
        try:
            deadline = dt.datetime.strptime(self.league.settings.get("Trade End Date", ""), "%B %d, %Y").date()
        except ValueError:
            return None, False
        return deadline, (day or self.data.as_of) > deadline

    def fairness(self, request: TradeRequest) -> float:
        a = float(self._market_arr[[self.index[p] for p in request.give_a]].sum())
        b = float(self._market_arr[[self.index[p] for p in request.give_b]].sum())
        return min(a, b) / max(a, b) if max(a, b) > 0 else 0.0

    def analyze(self, request: TradeRequest, *, strategy_a: Strategy | None = None,
                strategy_b: Strategy | None = None, analysis_date: dt.date | None = None,
                min_fairness: float = .55) -> TradeResult:
        sa, sb = strategy_a or Strategy(), strategy_b or Strategy()
        strategies = {request.team_a: sa, request.team_b: sb}
        rosters, adjustments, injuries = self.resolve(request, strategies)
        p, metrics = self.score(rosters, request.team_a, request.team_b, sa, sb)
        after = {m: self.view(rosters, m) for m in MODES}
        win = p_at_least(p)
        np.fill_diagonal(win, np.nan)
        fair = self.fairness(request)
        day = analysis_date or self.data.as_of
        deadline, expired = self.deadline(day)
        gains = [metrics[t]["strategy_delta"] for t in strategies]
        wins = [metrics[t]["win_delta"] for t in strategies]
        mutual = min(gains) > 1e-8
        incomplete = {t: [pid for pid in rosters[t] if not self.modeled[self.index[pid]]] for t in strategies}
        incoming_known = all(self.modeled[self.index[pid]] for pid in request.give_a + request.give_b)
        # Bu puan insan kabul olasılığı değildir. Yalnızca karşı tarafın ölçülen faydası ve paket dengesi.
        fit = {t: float(np.clip(50 + 250 * metrics[t]["strategy_delta"] + 100 * metrics[t]["win_delta"], 0, 100))
               for t in strategies}
        risk = "Son tarih geçmiş" if expired else "Yüksek" if fair < min_fairness or not mutual else "Daha düşük"
        if not incoming_known and not expired:
            risk = "Veri yetersiz"
        assessments = {"mutual_benefit": mutual, "both_matchup_improve": min(wins) > 0,
                       "fairness_ratio": fair, "fit_scores": fit, "commissioner_risk": risk,
                       "review_type": self.league.settings.get("Trade Review", "Bilinmiyor"),
                       "review_time": self.league.settings.get("Trade Reject Time", "Bilinmiyor"),
                       "deadline": deadline.isoformat() if deadline else None, "deadline_passed": expired,
                       "analysis_date": day.isoformat(), "incomplete_players": incomplete,
                       "incoming_modeled": incoming_known, "calibrated_acceptance_probability": None}
        notes = ["Kabul puanı ve komisyon riski sezgisel değerlendirmedir; gerçek kabul/onay olasılığı değildir.",
                 "Strateji ECW, kategori tercihlerine göre 0–9 aralığına normalize edilen puandır; ağırlıksız ECW ayrıca gösterilir.",
                 "Matchup olasılıkları kalibre edilmemiş Normal yaklaşımıdır. P(5+) kategori bağımsızlığı varsayar.",
                 f"ROS toplamları {self.horizon_weeks:.2f} haftaya yayılır; lineup kullanım varsayımı %{self.utilization * 100:.1f}.",
                 "Sıralamalar mevcut kadroların oyuncu toplamlarıdır; geçmişte Yahoo'da kazanılmış takım istatistiği değildir."]
        if any(incomplete.values()):
            notes.append("Eksik ROS oyuncuları kadroda korunur. Olasılıklar yalnızca modellenebilen katkıları içerir; sonuç kısmi olabilir.")
        if any(adj["add"] for adj in adjustments.values()):
            notes.append("Boşta oyuncu eklemeleri koşulludur: waiver durumu, haftalık kalan alım hakkı ve Can't Cut listesi bu kayıtta doğrulanamaz.")
        for tid in strategies:
            active = [pid for pid in rosters[tid] if pid not in injuries[tid]]
            n = best_assignment(self.positions(active), self.config).n_open_active
            if n:
                notes.append(f"{self.league.teams[tid]}: {n} aktif pozisyon doldurulamıyor; ortalama lineup varsayımı iyimser olabilir.")
        return TradeResult(request, self.before, after, self.baseline_p, p, self.baseline_matchup, win,
                           pd.DataFrame.from_dict(metrics, orient="index"), rosters, adjustments,
                           assessments, strategies, notes)

    def league_probabilities(self) -> pd.DataFrame:
        frame = pd.DataFrame(np.nanmean(self.baseline_p, axis=1), index=self.team_ids, columns=CATEGORIES)
        frame.insert(0, "ECW", team_ecw(self.baseline_p))
        frame.insert(1, "P_5_plus", np.nanmean(self.baseline_matchup, axis=1))
        return frame
