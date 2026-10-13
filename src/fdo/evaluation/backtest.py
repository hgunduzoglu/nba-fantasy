"""Strateji karşılaştırması (README §13.1): aynı bot ligine karşı kullanıcı koltuğu stratejileri.

Her draft ``d`` için tüm stratejiler **aynı** bot gürültüsünü (MockDraft seed'i ``d``) ve aynı
gerçekleşen sezonu (değerlendirici ``d`` ile kurulur) görür (CRN). Sonuç: koltuğun eşleşme başına
ortalama kategori galibiyeti (all-play), lig içi sırası ve stratejiler arası CRN eşleşmeli farklar.

Stratejiler:
* ``adp``  — en düşük ADP (pozisyon kuralına uygun),
* ``z`` / ``g`` — dengeli Z / G değeri en yüksek,
* ``ecw`` — V1 advisor'ın en iyi seçimi (hızlı ayarlarla; ``advisor_overrides``).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from fdo.advisor.pairs import recommend
from fdo.advisor.simulate import prepare_context
from fdo.bots.mock import MockDraft
from fdo.bots.universe import BotUniverse
from fdo.config import Config
from fdo.evaluation.interface import SeasonEvaluator
from fdo.ingest.load import Dataset
from fdo.valuation import value_players

#: Backtest'te ECW advisor'ın hızlı ayarları (draft başına ~7 turn × birkaç saniye).
FAST_ADVISOR = {"sims_per_pair_fast": 40, "m_pairs_to_rollout": 10, "fill_sims_conditional": 30,
                "max_candidates": 14}


class RankStrategy:
    """Sabit sıraya göre (ADP ya da değer) uygun ilk oyuncu."""

    def __init__(self, order: list[str]):
        self.order = order

    def choose(self, m: MockDraft) -> list[str]:
        taken = m.log.taken
        for pid in self.order:
            if pid not in taken and m.is_allowed(pid):
                return [pid]
        raise RuntimeError("Uygun oyuncu kalmadı")


class AdvisorStrategy:
    def __init__(self, ctx):
        self.ctx = ctx
        self.fallbacks = 0

    def choose(self, m: MockDraft) -> list[str]:
        res = recommend(self.ctx, m.log, mode="fast", conditional_fill=False)
        if res.pairs:
            return list(res.pairs[0].players)
        self.fallbacks += 1                        # geçerli çift yok: ADP sırasıyla uygun ilk oyuncu
        u = self.ctx.universe
        return RankStrategy([str(u.ids[i]) for i in np.argsort(u.adp, kind="stable")]).choose(m)


def value_order(dataset: Dataset, config: Config, universe: BotUniverse, method: str) -> list[str]:
    v = value_players(dataset.projections, config, method=method).table["V"]
    ids = set(universe.ids)
    return [p for p in v.sort_values(ascending=False).index if p in ids]


def build_strategies(names, dataset: Dataset, config: Config, universe: BotUniverse, seed: int):
    out = {}
    for name in names:
        if name == "adp":
            out[name] = RankStrategy([str(universe.ids[i]) for i in np.argsort(universe.adp, kind="stable")])
        elif name in ("z", "g"):
            out[name] = RankStrategy(value_order(dataset, config, universe, name))
        elif name == "ecw":
            cfg = config.with_overrides({"model": {"advisor": FAST_ADVISOR}})
            out[name] = AdvisorStrategy(prepare_context(dataset, cfg, seed, universe=universe, fill_sims=60))
        else:
            raise ValueError(f"Bilinmeyen strateji: {name} (adp | z | g | ecw)")
    return out


def play(dataset: Dataset, config: Config, universe: BotUniverse, strategy, seed: int) -> dict[int, list[str]]:
    m = MockDraft(dataset, config, seed, universe)
    while not m.log.is_complete:
        m.play_until_user()
        if m.log.is_complete:
            break
        n = 1
        while m.log.next_pick + n <= m.log.total_picks and m.log.seat_for(m.log.next_pick + n) == m.my_seat:
            n += 1
        chosen = strategy.choose(m)
        for pid in chosen[:n]:
            m.pick(pid, "user")
        if len(chosen) < n:                       # tek seçim döndüren strateji: turn'ü tamamla
            for _ in range(n - len(chosen)):
                m.pick(strategy.choose(m)[0], "user")
    rosters: dict[int, list[str]] = {s: [] for s in range(1, config.league.teams + 1)}
    for p in m.log.picks:
        rosters[p.seat].append(p.player_id)
    return rosters


@dataclass
class BacktestResult:
    runs: pd.DataFrame                      # draft, strategy, category_wins, rank
    notes: list[str] = field(default_factory=list)
    elapsed: float = 0.0

    def summary(self) -> pd.DataFrame:
        g = self.runs.groupby("strategy")
        out = pd.DataFrame({
            "drafts": g.size(),
            "category_wins": g["category_wins"].mean(),
            "SE": g["category_wins"].std(ddof=1) / np.sqrt(g.size()),
            "rank": g["rank"].mean(),
            "top3": g["rank"].apply(lambda r: float((r <= 3).mean())),
        })
        return out.sort_values("category_wins", ascending=False)

    def paired(self, baseline: str) -> pd.DataFrame:
        """Her stratejinin ``baseline``'a göre CRN eşleşmeli farkı."""
        w = self.runs.pivot(index="draft", columns="strategy", values="category_wins")
        rows = []
        for s in w.columns:
            if s == baseline:
                continue
            d = (w[s] - w[baseline]).dropna()
            rows.append({"strategy": s, "vs": baseline, "diff": d.mean(),
                         "SE": d.std(ddof=1) / np.sqrt(len(d)) if len(d) > 1 else np.nan})
        return pd.DataFrame(rows)


def run_backtest(dataset: Dataset, config: Config, universe: BotUniverse, strategies: dict,
                 evaluator_factory: Callable[[int], SeasonEvaluator], n_drafts: int, *, seed: int = 1,
                 progress=None) -> BacktestResult:
    t0 = time.perf_counter()
    me = config.league.my_seat
    rows, notes = [], []
    total = n_drafts * len(strategies)
    done = 0
    for d in range(n_drafts):
        ev = evaluator_factory(seed + d)
        for name, strat in strategies.items():
            rosters = play(dataset, config, universe, strat, seed + d)
            res = ev.evaluate(rosters, config.league.season)
            wins = pd.Series(res.category_wins)
            rows.append({"draft": d, "strategy": name, "category_wins": wins[me],
                         "rank": int((wins > wins[me]).sum()) + 1})
            notes = res.notes
            done += 1
            if progress:
                progress(done, total)
    return BacktestResult(runs=pd.DataFrame(rows), notes=notes, elapsed=time.perf_counter() - t0)
