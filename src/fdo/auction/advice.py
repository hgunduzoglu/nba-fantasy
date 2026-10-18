"""Auction teklif ve aday gösterme önerisi (README §13.12).

Her uygun oyuncu için:

* **taban fiyat**: piyasa fiyatı (Yahoo AAV, lige ölçekli) varsa o, yoksa model değeri;
* **beklenen fiyat**: taban × enflasyon (kalan para / kalan değer), draft edilebilir havuzdaki (kalan
  slot sayısı kadar en iyi) oyuncular için; diğerleri ``min_bid``;
* **senin için değeri**: oyuncunun kadrona katkısı ``Δ = ECW(R ∪ {i} ∪ (m−1)·f) − ECW(R ∪ {yedek} ∪ (m−1)·f)``
  (strateji ağırlıklarıyla) dolara çevrilir. Kur, havuzun beklenen fiyatları toplamının Δ⁺ toplamına
  oranıdır; ortalama bir takım için değer ≈ beklenen fiyat, kadrona uyan oyuncuda daha yüksek.
  ``f``: kalan draft edilebilir havuzun ortalama oyuncusu (boş slotlar), ``yedek``: havuzun hemen
  altındaki oyuncuların ortalaması. Rakipler: kendi kadroları + boş slotları için ``f``.
* **teklif tavanı**: ``min(senin için değeri, max teklifin)``.

Aday gösterme: senin için değeri beklenen fiyatın altında kalan pahalı oyuncular (rakipler harcasın) ve
değeri fiyatından yüksek hedefler.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from fdo.advisor.board import STAT_FORMULAS
from fdo.advisor.simulate import player_vectors
from fdo.auction.state import AuctionLog
from fdo.auction.values import inflation, market_prices, model_dollars
from fdo.bots.universe import BotUniverse, build_universe
from fdo.config import Config
from fdo.ingest.load import Dataset
from fdo.matchup.ecw import ecw_vs
from fdo.roster.assignment import RosterModel

REPLACEMENT_BAND = 14          # yedek seviyesi: havuzun hemen altındaki bu kadar oyuncunun ortalaması


@dataclass
class AuctionContext:
    dataset: Dataset
    config: Config
    universe: BotUniverse
    vecs: np.ndarray               # (n, 24), NaN = projeksiyon yok
    model_dollars: np.ndarray      # (n,)
    market: np.ndarray             # (n,) lige ölçekli AAV; NaN = veri yok
    aav: np.ndarray                # (n,) ham AAV
    budget: int
    min_bid: int

    @property
    def has_vec(self) -> np.ndarray:
        return ~np.isnan(self.vecs).any(axis=1)

    @property
    def base_price(self) -> np.ndarray:
        return np.where(np.isnan(self.market), self.model_dollars, self.market)


def prepare_auction(dataset: Dataset, config: Config, aav: pd.Series | None = None, *,
                    budget: int | None = None, min_bid: int | None = None,
                    universe: BotUniverse | None = None) -> AuctionContext:
    from fdo.valuation import value_players

    lg = config.league
    budget = int(budget or config.auction.budget)
    min_bid = int(min_bid or config.auction.min_bid)
    u = universe or build_universe(dataset, config)
    vecs, _ = player_vectors(dataset, config, u)
    V = value_players(dataset.projections, config, method="z").table["V"]
    ids = pd.Index([str(i) for i in u.ids])
    md = model_dollars(V, teams=lg.teams, budget=budget, rounds=lg.rounds, min_bid=min_bid)
    md = md.reindex(ids).fillna(float(min_bid)).to_numpy(float)
    raw = (aav.reindex(ids) if aav is not None else pd.Series(np.nan, index=ids)).astype(float)
    mk = market_prices(raw, teams=lg.teams, budget=budget, rounds=lg.rounds, min_bid=min_bid) \
        if raw.notna().any() else raw
    return AuctionContext(dataset=dataset, config=config, universe=u, vecs=vecs, model_dollars=md,
                          market=mk.to_numpy(float), aav=raw.to_numpy(float), budget=budget, min_bid=min_bid)


@dataclass
class AuctionBoard:
    table: pd.DataFrame            # uygun oyuncular, beklenen fiyata göre azalan
    team_p: np.ndarray             # (C,) kadron + boş slotlar (f) ile kategori P'leri
    categories: tuple[str, ...]
    inflation: float
    money_left: int
    slots_left: int
    my_max_bid: int
    my_open: int
    rival_max: int
    rival_max_seat: int | None
    nominator: int | None

    def nominate(self, n: int = 8) -> pd.DataFrame:
        """Rakipleri harcatmak için: pahalı ama senin için fiyatının altında değerli oyuncular."""
        t = self.table[self.table["in_pool"] & (self.table["price"] >= 8)]
        return t.assign(_k=t["price"] - t["my_value"]).sort_values("_k", ascending=False).head(n).drop(columns="_k")

    def targets(self, n: int = 8) -> pd.DataFrame:
        """Değeri beklenen fiyatından yüksek, alabileceğin oyuncular."""
        t = self.table[self.table["allowed"] & (self.table["gap"] > 0)]
        return t.sort_values("gap", ascending=False).head(n)


def evaluate(actx: AuctionContext, log: AuctionLog, my_seat: int,
             weights: dict[str, float] | None = None) -> AuctionBoard:
    cfg = actx.config
    u, vecs, mb = actx.universe, actx.vecs, actx.min_bid
    cats = tuple(cfg.categories)
    T = log.teams
    w = np.array([float((weights or {}).get(c, 1.0)) for c in cats])

    taken = np.zeros(u.n, dtype=bool)
    rosters: dict[int, list[int]] = {s: [] for s in range(1, T + 1)}
    for p in log.purchases:
        if p.player_id in u.index:
            i = u.index[p.player_id]
            taken[i] = True
            rosters[p.seat].append(i)
    avail = ~taken & actx.has_vec
    idx = np.flatnonzero(avail)
    base = actx.base_price
    # taban fiyata göre; eşitlikte (havuz altı $min_bid oyuncular) dengeli değere göre — yedek seviyesi doğru olsun
    order = idx[np.lexsort((-u.zcat[idx].sum(axis=1), -base[idx]))]

    open_ = {s: log.open_slots(s) for s in rosters}
    slots_left = int(sum(max(m, 0) for m in open_.values()))
    money_left = int(sum(log.budget_left(s) for s in rosters if open_[s] > 0))
    pool = order[:slots_left]
    infl = inflation(money_left, slots_left, base[pool], mb) if len(pool) else 1.0
    price = np.full(u.n, float(mb))
    price[pool] = mb + (base[pool] - mb) * infl

    nan_vec = np.zeros(vecs.shape[1])
    f = vecs[pool].mean(axis=0) if len(pool) else nan_vec
    band = order[slots_left: slots_left + REPLACEMENT_BAND]
    repl = vecs[band].mean(axis=0) if len(band) else (vecs[order[-REPLACEMENT_BAND:]].mean(axis=0) if len(order)
                                                      else nan_vec)

    def roster_vec(seat: int) -> np.ndarray:
        ids = [i for i in rosters[seat] if actx.has_vec[i]]
        return vecs[ids].sum(axis=0) if ids else np.zeros(vecs.shape[1])

    opps = np.stack([roster_vec(s) + max(open_[s], 0) * f for s in rosters if s != my_seat])
    m = max(open_[my_seat], 0)
    mine = roster_vec(my_seat)
    team_p = ecw_vs(mine + m * f, opps, cfg).mean(axis=-2)
    if m > 0:
        b = mine + (m - 1) * f
        p_ref = ecw_vs(b + repl, opps, cfg).mean(axis=-2)
        d = ecw_vs(b[None, :] + vecs[order], opps, cfg).mean(axis=-2) - p_ref          # (k, C)
    else:
        d = np.zeros((len(order), len(cats)))
    delta = d @ w
    in_pool = np.isin(order, pool)
    pos_d = np.clip(delta, 0, None)
    denom = float(pos_d[in_pool].sum())
    rate = float((price[pool] - mb).sum()) / denom if denom > 0 else 0.0
    my_value = mb + pos_d * rate if m > 0 else np.zeros(len(order))
    my_max = log.max_bid(my_seat)

    model = RosterModel(cfg)
    mine_pos = [u.groups[u.group[i]] for i in rosters[my_seat]]
    allowed = np.array([m > 0 and model.can_complete([*mine_pos, u.groups[u.group[i]]], m - 1) for i in order])

    rivals = {s: log.max_bid(s) for s in rosters if s != my_seat}
    rival_seat = max(rivals, key=rivals.get) if rivals else None

    ids = [str(u.ids[i]) for i in order]
    ds = actx.dataset
    names = ds.names()
    players = ds.players.set_index("player_id")
    proj = ds.projections.set_index("player_id").reindex(ids)
    table = pd.DataFrame({
        "player_id": ids,
        "name": [str(names.get(p, p)) for p in ids],
        "positions": [",".join(sorted(players.at[p, "positions"])) for p in ids],
        "nba_team": [players.at[p, "nba_team"] for p in ids],
        "injury": proj["injury_status"].fillna("").to_numpy() if "injury_status" in proj else "",
        "gp": proj["projected_gp"].to_numpy(float),
        "aav": actx.aav[order], "market": actx.market[order], "model": actx.model_dollars[order],
        "price": price[order], "my_value": my_value, "gap": my_value - price[order],
        "ceiling": np.floor(np.minimum(my_value, my_max)) if m > 0 else 0.0,
        "delta": delta, "delta_ecw": d.sum(axis=1), "z_total": u.zcat[order].sum(axis=1),
        "in_pool": in_pool, "allowed": allowed,
    })
    for j, c in enumerate(cats):
        table[f"d_{c}"] = d[:, j]
    for j, c in enumerate(cats):
        table[f"z_{c}"] = u.zcat[order, j]
    with np.errstate(divide="ignore", invalid="ignore"):
        for c in cats:
            table[f"s_{c}"] = STAT_FORMULAS[c](proj).to_numpy(float) if c in STAT_FORMULAS else np.nan
    for col in ("fgm", "fga", "ftm", "fta"):
        table[col] = proj[col].to_numpy(float)
    return AuctionBoard(table=table, team_p=team_p, categories=cats, inflation=infl, money_left=money_left,
                        slots_left=slots_left, my_max_bid=my_max, my_open=m, rival_max=rivals.get(rival_seat, 0),
                        rival_max_seat=rival_seat, nominator=log.nominator())
