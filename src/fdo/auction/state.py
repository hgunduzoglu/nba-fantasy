"""Canlı auction durumu: satın alımlar, takım bütçeleri ve aday gösterme sırası (README §13.12)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import pandas as pd

from fdo.config import Config


@dataclass(frozen=True)
class Purchase:
    player_id: str
    seat: int
    price: int


@dataclass
class AuctionLog:
    teams: int
    rounds: int
    budget: int
    min_bid: int
    purchases: list[Purchase] = field(default_factory=list)

    @classmethod
    def new(cls, config: Config, budget: int | None = None, min_bid: int | None = None) -> "AuctionLog":
        au = config.auction
        return cls(config.league.teams, config.league.rounds, int(budget or au.budget), int(min_bid or au.min_bid))

    # ------------------------------------------------------------- sorgular
    @property
    def taken(self) -> set[str]:
        return {p.player_id for p in self.purchases}

    def roster(self, seat: int) -> list[str]:
        return [p.player_id for p in self.purchases if p.seat == seat]

    def spent(self, seat: int) -> int:
        return sum(p.price for p in self.purchases if p.seat == seat)

    def open_slots(self, seat: int) -> int:
        return self.rounds - len(self.roster(seat))

    def budget_left(self, seat: int) -> int:
        return self.budget - self.spent(seat)

    def max_bid(self, seat: int) -> int:
        """Her boş slot için ``min_bid`` ayırmak zorunlu: ``kalan − min_bid·(boş − 1)``; dolu takım 0."""
        m = self.open_slots(seat)
        return 0 if m <= 0 else self.budget_left(seat) - self.min_bid * (m - 1)

    @property
    def is_complete(self) -> bool:
        return all(self.open_slots(s) <= 0 for s in range(1, self.teams + 1))

    def nominator(self) -> int | None:
        """Sıradaki aday gösteren (tahmini): koltuk 1..T döngüsü, kadrosu dolu takımlar atlanır."""
        counts = {s: 0 for s in range(1, self.teams + 1)}
        ptr = 1

        def advance(start: int) -> int | None:
            for k in range(self.teams):
                s = (start - 1 + k) % self.teams + 1
                if counts[s] < self.rounds:
                    return s
            return None

        cur = advance(ptr)
        for p in self.purchases:
            counts[p.seat] += 1
            if cur is None:
                return None
            cur = advance(cur % self.teams + 1)
        return cur

    # ------------------------------------------------------------- değişiklik
    def add(self, player_id: str, seat: int, price: int) -> None:
        if player_id in self.taken:
            raise ValueError(f"{player_id} zaten alındı")
        if not 1 <= seat <= self.teams:
            raise ValueError(f"seat 1..{self.teams}")
        if self.open_slots(seat) <= 0:
            raise ValueError(f"Takım {seat} kadrosu dolu")
        if price < self.min_bid:
            raise ValueError(f"En düşük teklif ${self.min_bid}")
        if price > self.max_bid(seat):
            raise ValueError(f"Takım {seat} en fazla ${self.max_bid(seat)} verebilir (boş slotlar için "
                             f"${self.min_bid} ayırmak zorunlu)")
        self.purchases.append(Purchase(player_id, int(seat), int(price)))

    def undo(self) -> None:
        if self.purchases:
            self.purchases.pop()

    def team_table(self, names: dict[int, str] | None = None, my_seat: int | None = None) -> pd.DataFrame:
        rows = []
        for s in range(1, self.teams + 1):
            m = self.open_slots(s)
            rows.append({"seat": s, "takım": (names or {}).get(s, f"Takım {s}") + (" ★" if s == my_seat else ""),
                         "harcanan": self.spent(s), "kalan $": self.budget_left(s), "boş slot": m,
                         "max teklif": self.max_bid(s),
                         "$/slot": round(self.budget_left(s) / m, 1) if m else 0.0})
        return pd.DataFrame(rows)

    # ------------------------------------------------------------- kalıcılık
    def to_json(self, meta: dict | None = None) -> str:
        return json.dumps({"teams": self.teams, "rounds": self.rounds, "budget": self.budget,
                           "min_bid": self.min_bid, "meta": meta or {},
                           "purchases": [p.__dict__ for p in self.purchases]}, ensure_ascii=False, indent=1)

    @classmethod
    def from_json(cls, text: str) -> tuple["AuctionLog", dict]:
        d = json.loads(text)
        log = cls(int(d["teams"]), int(d["rounds"]), int(d["budget"]), int(d["min_bid"]),
                  [Purchase(str(p["player_id"]), int(p["seat"]), int(p["price"])) for p in d["purchases"]])
        return log, d.get("meta", {})
