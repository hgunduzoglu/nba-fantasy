"""Pozisyon ayrıştırma ve slot uygunluğu (README §6.5)."""

from __future__ import annotations

from fdo.config import Config
from fdo.ingest.validate import parse_position_string
from fdo.types import POSITIONS


def parse_positions(value: str) -> frozenset[str]:
    """``"PG,SG"`` → ``frozenset({"PG", "SG"})``. Geçersiz değer ``ValueError``."""
    pos, problem = parse_position_string(value)
    if problem:
        raise ValueError(f"Geçersiz pozisyon {value!r}: {problem}")
    return pos


def eligible_slots(positions: frozenset[str], slot_eligibility: dict[str, frozenset[str]]) -> set[str]:
    return {slot for slot, allowed in slot_eligibility.items() if positions & allowed}


def slot_instances(config: Config) -> list[str]:
    """Slot örnekleri: ``[PG, SG, G, SF, PF, F, C, C, UTIL, UTIL, BN, BN, BN]``."""
    out: list[str] = []
    for slot, n in config.roster.slots.items():
        out += [slot] * n
    return out


def slot_tier(slot: str, config: Config) -> str:
    """``specific`` < ``flex`` < ``util`` < ``bench`` (atama maliyet sırası)."""
    if slot not in config.roster.active_slots:
        return "bench"
    allowed = config.roster.slot_eligibility[slot]
    if len(allowed) == 1:
        return "specific"
    if allowed >= set(POSITIONS):
        return "util"
    return "flex"


def position_key(positions: frozenset[str]) -> str:
    """Kararlı, okunabilir anahtar: ``"PG,SG"``."""
    return ",".join(p for p in POSITIONS if p in positions)
