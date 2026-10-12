"""Yahoo draft pozisyon kuralı (README §3.2, §6.3.2).

``position_limits_enforced_in_draft: true`` iken (kullanıcı doğruladı, 2026-10-12) bir
pick, takımın kalan pick'leriyle tüm aktif slotları doldurmasını imkânsız kılıyorsa
geçersizdir. Kural ``DraftLog``'un kendisinde değil (log pozisyon bilmez), log'a pick
ekleyen katmanlarda (mock, import, botlar, advisor) uygulanır.
"""

from __future__ import annotations

from collections.abc import Mapping

from fdo.config import Config
from fdo.draft.events import DraftError, DraftLog
from fdo.roster.assignment import RosterModel


def position_rule_enforced(config: Config) -> bool:
    return bool(config.unverified.position_limits_enforced_in_draft)


def roster_positions(log: DraftLog, seat: int, positions: Mapping[str, frozenset[str]]) -> list[frozenset[str]]:
    return [positions[p.player_id] for p in log.picks if p.seat == seat]


def check_pick(log: DraftLog, player_id: str, positions: Mapping[str, frozenset[str]], config: Config,
               model: RosterModel | None = None) -> None:
    """Sıradaki pick ``player_id`` olursa kural ihlal ediliyor mu? İhlalde ``DraftError``."""
    if not position_rule_enforced(config) or log.is_complete:
        return
    seat = log.next_seat
    current = roster_positions(log, seat, positions)
    remaining_after = log.rounds - len(current) - 1
    model = model or RosterModel(config)
    if not model.can_complete([*current, positions[player_id]], remaining_after):
        pos = ",".join(sorted(positions[player_id]))
        raise DraftError(f"Pozisyon kuralı: {player_id} ({pos}) alınırsa seat {seat} kalan "
                         f"{remaining_after} pick ile aktif slotları dolduramaz")


def validate_log(log: DraftLog, positions: Mapping[str, frozenset[str]], config: Config) -> None:
    """Log'daki her pick'i sırayla kurala göre denetler (import için)."""
    if not position_rule_enforced(config):
        return
    model = RosterModel(config)
    partial = DraftLog(teams=log.teams, rounds=log.rounds, third_round_reversal=log.third_round_reversal)
    for p in log.picks:
        check_pick(partial, p.player_id, positions, config, model)
        partial = partial.append(p)
