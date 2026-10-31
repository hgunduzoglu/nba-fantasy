"""Çok takımlı (3–4 takım) takas: elle analiz ve döngü önerileri.

Takas ``(oyuncu, veren takım, alan takım)`` hareketlerinden oluşur; takasa giren her takım en az bir oyuncu
verir ve en az bir oyuncu alır. Kadro dengesi iki takımlı takasla aynı kuralla çözülür
(``TradeEngine.resolve_moves``: IL, otomatik bırak/boştan al) ve değişen tüm kadrolarla lig olasılıkları
yeniden hesaplanır.

Öneriler (``suggest_multi``) döngüdür: sen → T1 → T2 (→ T3) → sen; her ok bir ya da iki oyuncudur
(``SHAPES``). İki takımlı takasta karşılığı bulunmayan durumları yakalar: T1 senin oyuncunu ister ama sana
uygun oyuncusu yoktur; T2 ise T1'in oyuncusunu ister ve sana uygun oyuncu verir.

1. Yerel tarama: her takımın kazancı yalnızca kendi kadro değişikliğiyle, ligin geri kalanı değişmemiş kabul
   edilerek vektörel hesaplanır (aynı takastaki diğer takımların da değişmesi ihmal edilir).
2. Kesin değerlendirme: yerel puanı en yüksek adaylar tam modelle yeniden puanlanır; eşikler burada uygulanır.

Bu bir kabul olasılığı değildir: her takımın verilen stratejiye göre ölçülen kalan sezon kazancıdır.
"""

from __future__ import annotations

import datetime as dt
import itertools
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

from fdo.matchup.ecw import p_at_least, p_win
from fdo.matchup.player_week import WEEK_DIM
from fdo.roster.assignment import best_assignment
from fdo.trade.data import MODES
from fdo.trade.engine import LeagueView, TradeEngine, TradeError
from fdo.trade.strategy import Strategy
from fdo.trade.suggest import _shortlist

MAX_TEAMS = 4
OUT_STATUSES = ("O", "INJ", "INJ+")
# Döngüdeki ok başına oyuncu sayısı: sen → T1, T1 → T2, ..., son takım → sen.
SHAPES = {(1, 1, 1): "3 takım · herkes 1 verir", (2, 1, 1): "3 takım · sen 2 verirsin",
          (1, 2, 1): "3 takım · ortadaki takım 2 verir", (1, 1, 2): "3 takım · sen 2 alırsın",
          (1, 1, 1, 1): "4 takım · herkes 1 verir"}


@dataclass(frozen=True)
class MultiTradeRequest:
    moves: tuple[tuple[str, str, str], ...]              # (oyuncu, veren, alan)
    drops: tuple[tuple[str, str], ...] = ()               # (takım, bırakılan oyuncu)
    adds: tuple[tuple[str, str], ...] = ()                # (takım, boştan alınan oyuncu)
    auto_balance: bool = True

    def __post_init__(self):
        object.__setattr__(self, "moves", tuple((str(p), str(s), str(r)) for p, s, r in self.moves))
        for name in ("drops", "adds"):
            object.__setattr__(self, name, tuple((str(t), str(p)) for t, p in getattr(self, name)))

    @property
    def teams(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(t for _, s, r in self.moves for t in (s, r)))

    def sent(self, tid: str) -> tuple[str, ...]:
        return tuple(p for p, s, _ in self.moves if s == tid)

    def received(self, tid: str) -> list[tuple[str, str]]:
        return [(p, s) for p, s, r in self.moves if r == tid]

    def dropped(self, tid: str) -> tuple[str, ...]:
        return tuple(p for t, p in self.drops if t == tid)

    def added(self, tid: str) -> tuple[str, ...]:
        return tuple(p for t, p in self.adds if t == tid)


@dataclass
class MultiTradeResult:
    request: MultiTradeRequest
    teams: tuple[str, ...]
    strategies: dict[str, Strategy]
    metrics: pd.DataFrame                  # takım × ölçüt (ECW, P(5+), strateji, değer akışı)
    categories: pd.DataFrame               # takım × kategori: rakiplere karşı ortalama P değişimi
    profiles: dict[str, tuple[np.ndarray, np.ndarray]]   # takım → (önce, sonra) kategori olasılıkları
    before: dict[str, LeagueView]
    after: dict[str, LeagueView]
    rosters_after: dict[str, tuple[str, ...]]
    adjustments: dict[str, dict[str, tuple[str, ...]]]
    fairness: float
    mutual: bool
    assessments: dict
    notes: list[str] = field(default_factory=list)


def validate(engine: TradeEngine, request: MultiTradeRequest) -> None:
    names, teams = engine.data.players["name"], engine.league.teams
    if not request.moves:
        raise TradeError("Takasa en az bir oyuncu hareketi girmeli")
    if not 2 <= len(request.teams) <= MAX_TEAMS:
        raise TradeError(f"Çok takımlı takas 2–{MAX_TEAMS} takım arasında olmalı")
    if any(t not in engine.team_index for t in request.teams):
        raise TradeError("Ligde olmayan takım")
    players = [p for p, _, _ in request.moves]
    if len(players) != len(set(players)) or any(p not in engine.index for p in players):
        raise TradeError("Tekrarlanan veya bilinmeyen oyuncu")
    for p, s, r in request.moves:
        if s == r:
            raise TradeError(f"{names[p]}: veren ve alan takım aynı")
        if p not in engine.league.rosters[s]:
            raise TradeError(f"{names[p]} {teams[s]} kadrosunda değil")
    for t in request.teams:
        if not request.sent(t) or not request.received(t):
            raise TradeError(f"{teams[t]}: takasa giren her takım en az bir oyuncu vermeli ve almalı")
    dropped = [p for _, p in request.drops]
    if len(dropped) != len(set(dropped)) or any(p not in engine.index for p in dropped):
        raise TradeError("Tekrarlanan veya bilinmeyen bırakılan oyuncu")
    for t, p in request.drops:
        if t not in request.teams or p not in engine.league.rosters[t] or p in request.sent(t):
            raise TradeError("Bırakılan oyuncu, takastaki takımın kadrosunda olmalı ve takasa girmemeli")
    for t, p in request.adds:
        if t not in request.teams:
            raise TradeError("Boştan ekleme yalnızca takastaki takımlara yapılabilir")
        if p not in engine.index:
            raise TradeError("Bilinmeyen oyuncu")


def resolve_multi(engine: TradeEngine, request: MultiTradeRequest, strategies: dict[str, Strategy]):
    validate(engine, request)
    teams = request.teams
    return engine.resolve_moves({t: request.sent(t) for t in teams}, {t: request.received(t) for t in teams},
                                {t: request.dropped(t) for t in teams}, {t: request.added(t) for t in teams},
                                auto_drop=request.auto_balance, auto_fill=request.auto_balance,
                                strategies=strategies)


def value_flow(engine: TradeEngine, request: MultiTradeRequest, prices: pd.Series | None = None
               ) -> dict[str, tuple[float, float]]:
    """Takım → (aldığı, verdiği) toplam değer; varsayılan ROS piyasa değeri."""
    prices = engine.market if prices is None else prices
    return {t: (float(prices.reindex([p for p, _ in request.received(t)]).fillna(0).sum()),
                float(prices.reindex(list(request.sent(t))).fillna(0).sum())) for t in request.teams}


def _fairness(flow: dict[str, tuple[float, float]]) -> float:
    """En dengesiz takımın aldığı/verdiği oranı (iki takımda ``TradeEngine.fairness`` ile aynı)."""
    ratios = [min(i, o) / max(i, o) if max(i, o) > 0 else 0.0 for i, o in flow.values()]
    return min(ratios) if ratios else 0.0


def analyze_multi(engine: TradeEngine, request: MultiTradeRequest, strategies: dict[str, Strategy] | None = None,
                  *, analysis_date: dt.date | None = None, min_fairness: float = .55) -> MultiTradeResult:
    teams = request.teams
    strategies = {t: (strategies or {}).get(t) or Strategy() for t in teams}
    rosters, adjustments, injuries = resolve_multi(engine, request, strategies)
    p, metrics = engine.score_many(rosters, strategies)
    flow = value_flow(engine, request)
    fair = _fairness(flow)
    profiles = {t: (engine.category_profile(engine.baseline_p, t), engine.category_profile(p, t)) for t in teams}
    for t in teams:
        metrics[t]["value_in"], metrics[t]["value_out"] = flow[t]
    frame = pd.DataFrame.from_dict(metrics, orient="index")
    cats = pd.DataFrame({t: profiles[t][1] - profiles[t][0] for t in teams}, index=engine.config.categories).T
    deadline, expired = engine.deadline(analysis_date)
    mutual = bool(min(m["strategy_delta"] for m in metrics.values()) > 1e-8)
    incomplete = {t: [pid for pid in rosters[t] if not engine.modeled[engine.index[pid]]] for t in teams}
    incoming_known = all(engine.modeled[engine.index[p]] for p, _, _ in request.moves)
    risk = "Son tarih geçmiş" if expired else "Yüksek" if fair < min_fairness or not mutual else "Daha düşük"
    if not incoming_known and not expired:
        risk = "Veri yetersiz"
    assessments = {"mutual_benefit": mutual, "all_matchup_improve": min(m["win_delta"] for m in metrics.values()) > 0,
                   "fairness_ratio": fair, "commissioner_risk": risk,
                   "review_type": engine.league.settings.get("Trade Review", "Bilinmiyor"),
                   "deadline": deadline.isoformat() if deadline else None, "deadline_passed": expired,
                   "analysis_date": (analysis_date or engine.data.as_of).isoformat(),
                   "incomplete_players": incomplete, "incoming_modeled": incoming_known}
    notes = ["Yahoo çok takımlı takası tek işlemde desteklemez; bu analiz aynı anda yapılan ikili takasların "
             "toplamıdır. Sırayla yapılırsa ara adımlarda bir takım kabul etmeyebilir.",
             "Denge oranı, takastaki en dengesiz takımın aldığı/verdiği ROS piyasa değeridir.",
             "Strateji ECW, kategori tercihlerine göre 0–9 aralığına normalize edilen puandır; P(5+) kategori "
             "bağımsızlığı varsayar."]
    if any(adj["add"] for adj in adjustments.values()):
        notes.append("Boştan eklemeler koşulludur: waiver durumu ve haftalık alım hakkı doğrulanamaz.")
    if any(incomplete.values()):
        notes.append("Eksik ROS oyuncuları kadroda korunur; olasılıklar yalnızca modellenebilen katkıları içerir.")
    for t in teams:
        active = [pid for pid in rosters[t] if pid not in injuries[t]]
        n = best_assignment(engine.positions(active), engine.config).n_open_active
        if n:
            notes.append(f"{engine.league.teams[t]}: {n} aktif pozisyon doldurulamıyor; ortalama lineup varsayımı "
                         "iyimser olabilir.")
    after = {m: engine.view(rosters, m) for m in MODES}
    return MultiTradeResult(request, teams, strategies, frame, cats, profiles, engine.before, after, rosters,
                            adjustments, fair, mutual, assessments, notes)


# --------------------------------------------------------------------------- öneriler
@dataclass(frozen=True)
class MultiSearchOptions:
    shapes: tuple[tuple[int, ...], ...] = ((1, 1, 1), (2, 1, 1), (1, 1, 2), (1, 1, 1, 1))
    shortlist: int = 6
    shortlist4: int = 4                  # 4 takımlı döngüde takım başına aday (arama hacmi k⁴)
    candidates: int = 200                # yerel taramadan kesin değerlendirmeye geçen aday
    max_results: int = 20
    per_group: int = 3                   # aynı takım grubundan en fazla öneri (çeşitlilik)
    per_package: int = 3                 # senin aynı verdiğin paketle en fazla öneri
    min_fairness: float = .5
    min_strategy_gain: float = .005
    min_win_gain: float = 0.0
    ecw_weight: float = .65

    def __post_init__(self):
        if (not self.shapes or any(tuple(s) not in SHAPES for s in self.shapes) or not 2 <= self.shortlist <= 10
                or not 2 <= self.shortlist4 <= self.shortlist or self.candidates < 1 or self.max_results < 1
                or self.per_group < 1 or self.per_package < 1 or not 0 <= self.min_fairness <= 1 or not 0 <= self.ecw_weight <= 1
                or self.min_strategy_gain < 0 or not -1 <= self.min_win_gain <= 1):
            raise ValueError("Geçersiz çok takımlı öneri ayarları")


@dataclass
class MultiSuggestion:
    request: MultiTradeRequest
    shape: tuple[int, ...]
    score: float
    metrics: dict[str, dict]
    fairness: float
    strategies: dict[str, Strategy]


@dataclass
class MultiSearchResult:
    suggestions: list[MultiSuggestion] = field(default_factory=list)
    scanned: int = 0                     # yerel olarak puanlanan döngü
    candidates: int = 0                  # yerel eşikleri geçen
    evaluated: int = 0                   # tam modelle değerlendirilen
    eligible: int = 0                    # tüm eşikleri geçen
    rejected_roster: int = 0
    message: str = ""


@dataclass
class _Table:
    outs: list[tuple[str, ...]]
    ins: list[tuple[str, ...]]
    strategy: np.ndarray                 # (len(outs), len(ins)) strateji ECW değişimi
    win: np.ndarray                      # P(5+) değişimi
    gain: np.ndarray                     # birleşik kazanç
    ok: np.ndarray                       # kadro çözülebilir mi
    value_out: np.ndarray                # verilen paketin ROS piyasa değeri (len(outs))


class _Local:
    """Takımın kendi kadro değişikliğinin kazancı (lig geri kalanı sabit); ``resolve_moves`` kurallarının
    hızlı kopyası. Tablolar ``(takım, kaynak, verilen sayı, alınan sayı)`` başına önbelleklenir."""

    def __init__(self, engine: TradeEngine, strategies: dict[str, Strategy], short: dict[str, list[str]],
                 ecw_weight: float):
        self.e, self.s, self.short, self.w = engine, strategies, short, ecw_weight
        lg = engine.league
        self.cap, self.il_slots = lg.capacity, engine.config.unverified.il_slots or 0
        status = engine.data.players["injury_status"].astype(str)
        self.hurt = {p for p in engine.ids if status.get(p, "") in OUT_STATUSES}
        owned = {p for r in lg.rosters.values() for p in r}
        free = [p for p in engine.ids if p not in owned and engine.modeled[engine.index[p]]]
        self.drop_order, self.fill = {}, {}
        for t in engine.team_ids:
            mine = [p for p in lg.rosters[t] if engine.modeled[engine.index[p]]]
            self.drop_order[t] = list(engine._utility(mine, strategies[t]).sort_values(kind="stable").index)
            self.fill[t] = list(engine._utility(free, strategies[t]).sort_values(ascending=False, kind="stable")
                                .index[:4])
        self.tables: dict[tuple, _Table] = {}

    def _balance(self, t: str, out: tuple[str, ...], inc: tuple[str, ...], origin: str):
        lg, e = self.e.league, self.e
        roster = [p for p in lg.rosters[t] if p not in out] + list(inc)
        il = set(lg.injury_rosters[t]) - set(out)
        for p in inc:
            if p in lg.injury_rosters[origin] and p in self.hurt and len(il) < self.il_slots:
                il.add(p)
        over = len(roster) - len(il) - self.cap
        if over > 0:
            injured = [p for p in roster if p not in il and p in self.hurt]
            il.update(injured[: max(0, min(over, self.il_slots - len(il)))])
            over = len(roster) - len(il) - self.cap
        drops = []
        if over > 0:
            drops = [p for p in self.drop_order[t] if p in roster and p not in il and p not in inc][:over]
            if len(drops) < over:
                return None
        target = min(self.cap, len(lg.rosters[t]) - len(lg.injury_rosters[t]))
        count = max(0, target - (len(roster) - len(drops) - len(il)))
        return drops, self.fill[t][:count]

    def table(self, t: str, origin: str, n_out: int, n_in: int) -> _Table:
        key = (t, origin, n_out, n_in)
        if key in self.tables:
            return self.tables[key]
        e = self.e
        outs = list(itertools.combinations(self.short[t], n_out))
        ins = list(itertools.combinations(self.short[origin], n_in))
        i = e.team_index[t]
        base = e.baseline_vectors[i]
        vecs = np.repeat(base[None, :], len(outs) * len(ins), axis=0).reshape(len(outs), len(ins), WEEK_DIM)
        ok = np.ones((len(outs), len(ins)), dtype=bool)
        V = e.vecs
        for a, out in enumerate(outs):
            v_out = V[[e.index[p] for p in out]].sum(axis=0)
            for b, inc in enumerate(ins):
                res = self._balance(t, out, inc, origin)
                if res is None:
                    ok[a, b] = False
                    continue
                drops, adds = res
                v = base - v_out + V[[e.index[p] for p in inc]].sum(axis=0)
                if drops:
                    v = v - V[[e.index[p] for p in drops]].sum(axis=0)
                if adds:
                    v = v + V[[e.index[p] for p in adds]].sum(axis=0)
                vecs[a, b] = v
        keep = np.arange(len(e.team_ids)) != i
        flat = vecs.reshape(-1, WEEK_DIM)
        p = p_win(flat[:, None, :], e.baseline_vectors[keep][None, :, :], e.config)        # (n, K, 9)
        bp = e.baseline_p[i, keep]
        dp = p.mean(axis=1) - bp.mean(axis=0)
        sd = (dp @ self.s[t].normalized * 9).reshape(ok.shape)
        wd = (p_at_least(p).mean(axis=1) - float(p_at_least(bp).mean())).reshape(ok.shape)
        market = e.market.to_numpy(float)
        value = np.array([market[[e.index[p] for p in o]].sum() for o in outs])
        out = _Table(outs, ins, sd, wd, self.w * sd / 9 + (1 - self.w) * wd, ok, value)
        self.tables[key] = out
        return out


def _place(arr: np.ndarray, ax_a: int, ax_b: int, k: int) -> np.ndarray:
    """``arr[x_a, x_b]`` → k boyutlu yayınlanabilir dizi."""
    if ax_a > ax_b:
        arr, ax_a, ax_b = arr.T, ax_b, ax_a
    shape = [1] * k
    shape[ax_a], shape[ax_b] = arr.shape
    return arr.reshape(shape)


def _pick(items: list, limit: int, shape: Callable, caps: list[tuple[Callable, int]]) -> list:
    """Puana göre sıralı ``items``'tan çeşitli seçim. Önce her şekle eşit pay verilir, kalan yer en iyilerle
    dolar; ``caps`` (anahtar, sınır) çiftleri her iki turda da geçerlidir (takım grubu, senin paketin)."""
    quota = -(-limit // max(1, len({shape(x) for x in items})))
    counts: list[dict] = [{} for _ in caps]
    per_shape: dict = {}
    out, taken = [], set()
    for first in (True, False):
        for i, x in enumerate(items):
            if len(out) >= limit:
                return out
            if i in taken or (first and per_shape.get(shape(x), 0) >= quota):
                continue
            keys = [key(x) for key, _ in caps]
            if any(c.get(k, 0) >= cap for c, k, (_, cap) in zip(counts, keys, caps)):
                continue
            for c, k in zip(counts, keys):
                c[k] = c.get(k, 0) + 1
            per_shape[shape(x)] = per_shape.get(shape(x), 0) + 1
            taken.add(i)
            out.append(x)
    return out


def suggest_multi(engine: TradeEngine, team_id: str, *, strategy: Strategy | None = None,
                  opponent_strategies: dict[str, Strategy] | None = None,
                  opponents: tuple[str, ...] | None = None, options: MultiSearchOptions | None = None,
                  analysis_date: dt.date | None = None,
                  progress: Callable[[int, int], None] | None = None) -> MultiSearchResult:
    options, strategy = options or MultiSearchOptions(), strategy or Strategy()
    if team_id not in engine.team_index:
        raise TradeError("Takım bu ligde yok")
    others = tuple(t for t in (opponents or engine.team_ids) if t != team_id)
    if any(t not in engine.team_index for t in others):
        raise TradeError("Rakip bu ligde yok")
    result = MultiSearchResult()
    if engine.deadline(analysis_date)[1]:
        result.message = "Lig takas son tarihi geçmiş; yeni takas önerisi üretilmedi."
        return result
    strategies = {t: (opponent_strategies or {}).get(t) or Strategy() for t in engine.team_ids}
    strategies[team_id] = strategy
    short = {t: _shortlist(engine, t, strategies[t], options.shortlist) for t in (team_id, *others)}
    local = _Local(engine, strategies, short, options.ecw_weight)
    slack_s, slack_w = .02, .01                      # yerel yaklaşım payı; kesin eşikler sonra
    pool: list[tuple[float, tuple[int, ...], tuple[str, ...], tuple[int, ...]]] = []
    jobs = []
    for shape in options.shapes:
        k = len(shape)
        jobs += [(tuple(shape), (team_id, *combo)) for combo in itertools.permutations(others, k - 1)]
    for n_job, (shape, teams) in enumerate(jobs):
        k = len(teams)
        tabs = []
        for i, t in enumerate(teams):
            prev = (i - 1) % k
            tab = local.table(t, teams[prev], shape[i], shape[prev])
            # 4 takımlı döngüde oklar tekli: ilk ``shortlist4`` aday, tablonun sol üst alt tablosudur.
            n = options.shortlist4 if k == 4 else max(len(tab.outs), len(tab.ins))
            tabs.append((i, prev, tab, (slice(0, n), slice(0, n))))
        mask = np.ones((1,) * k, dtype=bool)
        gains, fair = [], np.ones((1,) * k)
        for i, prev, tab, sub in tabs:
            mask = (mask & _place(tab.ok[sub], i, prev, k)
                    & _place(tab.strategy[sub] >= options.min_strategy_gain - slack_s, i, prev, k)
                    & _place(tab.win[sub] >= options.min_win_gain - slack_w, i, prev, k))
            gains.append(_place(tab.gain[sub], i, prev, k))
            v_out = tab.value_out[sub[0]].reshape([-1 if a == i else 1 for a in range(k)])
            v_in = tabs[prev][2].value_out[tabs[prev][3][0]].reshape([-1 if a == prev else 1 for a in range(k)])
            ratio = np.minimum(v_in, v_out) / np.maximum(np.maximum(v_in, v_out), 1e-9)
            fair = np.minimum(fair, ratio)
        g = np.broadcast_arrays(*gains)
        stacked = np.stack(g)
        mask = mask & (fair >= options.min_fairness)
        result.scanned += int(np.prod(stacked.shape[1:]))
        if not mask.any():
            continue
        score = (stacked.min(axis=0) + stacked.mean(axis=0)) * (.5 + .5 * np.broadcast_to(fair, stacked.shape[1:]))
        score = np.where(mask, score, -np.inf)
        flat = score.ravel()
        top = np.argpartition(-flat, min(len(flat) - 1, 11))[:12]
        for ix in top:
            if np.isfinite(flat[ix]):
                pool.append((float(flat[ix]), shape, teams, np.unravel_index(ix, score.shape)))
        if progress:
            progress(n_job + 1, len(jobs))
    result.candidates = len(pool)
    pool.sort(key=lambda x: -x[0])
    # Kesin değerlendirmeye çeşitli adaylar geçer: her şekle pay, aynı takım grubu ve senin aynı paketin sınırlı.
    def my_package(item):
        _, shape, teams, idx = item
        return frozenset(local.tables[(teams[1], teams[0], shape[1], shape[0])].ins[idx[0]])
    chosen = _pick(pool, options.candidates, lambda x: x[1],
                   [(lambda x: frozenset(x[2]), 15), (my_package, 5 * options.per_package)])
    found = []
    for _, shape, teams, idx in chosen:
        k = len(teams)
        moves = []
        for i, t in enumerate(teams):
            tab = local.tables[(teams[(i + 1) % k], t, shape[(i + 1) % k], shape[i])]
            moves += [(p, t, teams[(i + 1) % k]) for p in tab.ins[idx[i]]]
        req = MultiTradeRequest(tuple(moves))
        result.evaluated += 1
        try:
            rosters, _, _ = resolve_multi(engine, req, {t: strategies[t] for t in teams})
        except TradeError:
            result.rejected_roster += 1
            continue
        _, metrics = engine.score_many(rosters, {t: strategies[t] for t in teams})
        fair = _fairness(value_flow(engine, req))
        if (fair < options.min_fairness
                or min(m["strategy_delta"] for m in metrics.values()) < options.min_strategy_gain
                or min(m["win_delta"] for m in metrics.values()) < options.min_win_gain):
            continue
        w = options.ecw_weight
        g = np.array([w * m["strategy_delta"] / 9 + (1 - w) * m["win_delta"] for m in metrics.values()])
        if g.min() <= 0:
            continue
        result.eligible += 1
        value = (g.min() + float(np.exp(np.log(g).mean()))) * (.5 + .5 * fair)
        found.append(MultiSuggestion(req, shape, float(value), metrics, fair, {t: strategies[t] for t in teams}))
    found.sort(key=lambda s: -s.score)
    result.suggestions = sorted(_pick(found, options.max_results, lambda s: s.shape,
                                      [(lambda s: frozenset(s.request.teams), options.per_group),
                                       (lambda s: frozenset(s.request.sent(team_id)), options.per_package)]),
                                key=lambda s: -s.score)
    if not result.suggestions:
        result.message = ("Bu aralıkta takastaki her takıma fayda sağlayan çok takımlı döngü bulunamadı. Eşikleri "
                          "gevşetmeyi, kısa listeyi büyütmeyi ya da rakip strateji varsayımını değiştirmeyi dene.")
    return result
