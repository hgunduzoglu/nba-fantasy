"""Event sourcing: ``DraftPick`` ve değişmez ``DraftLog`` (README §6.3.2).

Kurallar: bir oyuncu yalnızca bir kez seçilir; ``seat`` değeri
``seat_for_pick(overall_pick)`` ile tutarlı olmalıdır. Pozisyon kısıtı draft
motorunda **uygulanmaz** (§3.2: Yahoo'nun draft sırasında uygulayıp uygulamadığı
doğrulanmadı).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field, replace

from fdo.config import Config
from fdo.draft.order import round_for_pick, seat_for_pick

SOURCES_PREFIXES = ("user", "bot:", "import", "manual")


class DraftError(ValueError):
    pass


@dataclass(frozen=True)
class DraftPick:
    overall_pick: int
    round: int
    seat: int
    player_id: str
    source: str              # user | bot:<profil> | import | manual
    observed_at: dt.datetime

    def to_dict(self) -> dict:
        return {
            "overall_pick": self.overall_pick, "round": self.round, "seat": self.seat,
            "player_id": self.player_id, "source": self.source,
            "observed_at": self.observed_at.isoformat(timespec="seconds"),
        }


@dataclass(frozen=True)
class DraftLog:
    teams: int
    rounds: int
    third_round_reversal: bool = False
    picks: tuple[DraftPick, ...] = field(default=())

    @classmethod
    def new(cls, config: Config) -> "DraftLog":
        lg = config.league
        return cls(teams=lg.teams, rounds=lg.rounds, third_round_reversal=lg.third_round_reversal)

    # --- sorgular ------------------------------------------------------------
    @property
    def total_picks(self) -> int:
        return self.teams * self.rounds

    @property
    def next_pick(self) -> int:
        return len(self.picks) + 1

    @property
    def is_complete(self) -> bool:
        return len(self.picks) >= self.total_picks

    @property
    def next_seat(self) -> int | None:
        if self.is_complete:
            return None
        return seat_for_pick(self.next_pick, self.teams, self.third_round_reversal)

    def seat_for(self, k: int) -> int:
        return seat_for_pick(k, self.teams, self.third_round_reversal)

    @property
    def taken(self) -> frozenset[str]:
        return frozenset(p.player_id for p in self.picks)

    def __len__(self) -> int:
        return len(self.picks)

    # --- değişiklikler (yeni log döndürür) -----------------------------------
    def append(self, pick: DraftPick) -> "DraftLog":
        if self.is_complete:
            raise DraftError("Draft tamamlandı")
        if pick.overall_pick != self.next_pick:
            raise DraftError(f"Beklenen pick {self.next_pick}, gelen {pick.overall_pick}")
        expected_seat = self.seat_for(pick.overall_pick)
        if pick.seat != expected_seat:
            raise DraftError(f"Pick {pick.overall_pick}: seat {pick.seat} tutarsız (beklenen {expected_seat})")
        expected_round = round_for_pick(pick.overall_pick, self.teams)
        if pick.round != expected_round:
            raise DraftError(f"Pick {pick.overall_pick}: round {pick.round} tutarsız (beklenen {expected_round})")
        if pick.player_id in self.taken:
            raise DraftError(f"{pick.player_id} zaten seçildi")
        if not pick.source.startswith(SOURCES_PREFIXES):
            raise DraftError(f"Geçersiz source: {pick.source!r}")
        return replace(self, picks=self.picks + (pick,))

    def make_pick(self, player_id: str, source: str = "manual",
                  observed_at: dt.datetime | None = None) -> "DraftLog":
        k = self.next_pick
        return self.append(DraftPick(
            overall_pick=k, round=round_for_pick(k, self.teams), seat=self.seat_for(k),
            player_id=str(player_id), source=source,
            observed_at=observed_at or dt.datetime.now().replace(microsecond=0),
        ))

    def undo(self) -> "DraftLog":
        if not self.picks:
            return self
        return replace(self, picks=self.picks[:-1])

    def truncate(self, overall_pick: int) -> "DraftLog":
        """"Pick k'ye dön": k ve sonrası silinir, sıradaki pick k olur."""
        return replace(self, picks=self.picks[: max(0, overall_pick - 1)])

    @classmethod
    def replay(cls, teams: int, rounds: int, trr: bool, picks) -> "DraftLog":
        log = cls(teams=teams, rounds=rounds, third_round_reversal=trr)
        for p in picks:
            log = log.append(p)
        return log
