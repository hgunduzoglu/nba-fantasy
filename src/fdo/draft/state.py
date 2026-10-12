"""``DraftLog``'dan türetilen ``DraftState`` (README §6.3.2).

State her zaman log'dan **türetilir**; doğrudan değiştirilmez.
"""

from __future__ import annotations

from dataclasses import dataclass

from fdo.config import Config
from fdo.draft.events import DraftError, DraftLog
from fdo.draft.order import picks_for_seat


@dataclass(frozen=True)
class DraftState:
    current_pick: int                         # sıradaki pick (tamamlandıysa total + 1)
    next_seat: int | None
    available: tuple[str, ...]                # draft havuzu sırasıyla uygun oyuncular
    rosters: dict[int, tuple[str, ...]]       # seat → seçilen oyuncular (pick sırasıyla)
    remaining_picks: dict[int, tuple[int, ...]]
    pick_owner: dict[str, tuple[int, int]]    # player_id → (seat, overall_pick)
    is_complete: bool

    @property
    def taken(self) -> frozenset[str]:
        return frozenset(self.pick_owner)


def state_from_log(log: DraftLog, config: Config, draft_ids: list[str]) -> DraftState:
    """``draft_ids``: draft havuzu (genelde ``Dataset.draft_ids``)."""
    pool = set(draft_ids)
    rosters: dict[int, list[str]] = {s: [] for s in range(1, log.teams + 1)}
    owner: dict[str, tuple[int, int]] = {}
    for p in log.picks:
        if p.player_id not in pool:
            raise DraftError(f"{p.player_id} draft havuzunda yok")
        rosters[p.seat].append(p.player_id)
        owner[p.player_id] = (p.seat, p.overall_pick)
    k = log.next_pick
    remaining = {
        s: tuple(n for n in picks_for_seat(s, log.teams, log.rounds, log.third_round_reversal) if n >= k)
        for s in rosters
    }
    return DraftState(
        current_pick=k,
        next_seat=log.next_seat,
        available=tuple(pid for pid in draft_ids if pid not in owner),
        rosters={s: tuple(r) for s, r in rosters.items()},
        remaining_picks=remaining,
        pick_owner=owner,
        is_complete=log.is_complete,
    )
