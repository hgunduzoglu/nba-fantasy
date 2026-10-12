"""Snake draft sırası (README §3.3, §6.3.1).

Pick numaraları 1-tabanlıdır. "Turn" kavramı hard-code edilmez; bir koltuğun
arada rakip seçimi olmayan ardışık pick'lerinden türetilir.
"""

from __future__ import annotations

import math


def round_for_pick(k: int, teams: int) -> int:
    if k < 1:
        raise ValueError(f"pick numarası 1-tabanlıdır: {k}")
    return math.ceil(k / teams)


def is_forward_round(r: int, third_round_reversal: bool) -> bool:
    """Tur ``r`` ileri (1→T) mi gidiyor?"""
    if not third_round_reversal:
        return r % 2 == 1
    if r == 1:
        return True
    if r == 2:
        return False
    return r % 2 == 0


def seat_for_pick(k: int, teams: int, third_round_reversal: bool = False) -> int:
    r = round_for_pick(k, teams)
    p = k - (r - 1) * teams
    return p if is_forward_round(r, third_round_reversal) else teams + 1 - p


def pick_order(teams: int, rounds: int, third_round_reversal: bool = False) -> list[int]:
    """``order[k-1]`` = k. pick'in koltuğu."""
    return [seat_for_pick(k, teams, third_round_reversal) for k in range(1, teams * rounds + 1)]


def picks_for_seat(seat: int, teams: int, rounds: int, trr: bool = False) -> list[int]:
    if not 1 <= seat <= teams:
        raise ValueError(f"seat 1..{teams} aralığında olmalı: {seat}")
    return [k for k, s in enumerate(pick_order(teams, rounds, trr), start=1) if s == seat]


def turns_for_seat(seat: int, teams: int, rounds: int, trr: bool = False) -> list[tuple[int, ...]]:
    """Koltuğun ardışık pick bloklarını döndürür: ``[(16, 17), (48, 49), ..., (208,)]``."""
    turns: list[tuple[int, ...]] = []
    current: list[int] = []
    for k in picks_for_seat(seat, teams, rounds, trr):
        if current and k != current[-1] + 1:
            turns.append(tuple(current))
            current = []
        current.append(k)
    if current:
        turns.append(tuple(current))
    return turns


def turn_containing(pick: int, seat: int, teams: int, rounds: int, trr: bool = False) -> int | None:
    """``pick``'i içeren turn'ün indeksini döndürür (yoksa ``None``)."""
    for i, turn in enumerate(turns_for_seat(seat, teams, rounds, trr)):
        if pick in turn:
            return i
    return None


def next_turn_after(pick: int, seat: int, teams: int, rounds: int,
                    trr: bool = False) -> tuple[int, ...] | None:
    """``pick``'ten sonra başlayan ilk turn (``pick``'i içeren turn hariç)."""
    for turn in turns_for_seat(seat, teams, rounds, trr):
        if turn[0] > pick:
            return turn
    return None
