import pytest

from fdo.draft.order import (
    next_turn_after,
    pick_order,
    picks_for_seat,
    seat_for_pick,
    turns_for_seat,
)

SEAT16_NO_3RR = [16, 17, 48, 49, 80, 81, 112, 113, 144, 145, 176, 177, 208]
SEAT16_3RR = [16, 17, 33, 64, 65, 96, 97, 128, 129, 160, 161, 192, 193]


@pytest.mark.parametrize("trr", [False, True])
def test_208_unique_picks(trr):
    order = pick_order(16, 13, trr)
    assert len(order) == 208
    for seat in range(1, 17):
        assert order.count(seat) == 13
    all_picks = sorted(k for s in range(1, 17) for k in picks_for_seat(s, 16, 13, trr))
    assert all_picks == list(range(1, 209))


def test_seat16_picks_without_3rr():
    assert picks_for_seat(16, 16, 13, False) == SEAT16_NO_3RR


def test_seat16_picks_with_3rr():
    assert picks_for_seat(16, 16, 13, True) == SEAT16_3RR


def test_turns_without_3rr():
    assert turns_for_seat(16, 16, 13, False) == [
        (16, 17), (48, 49), (80, 81), (112, 113), (144, 145), (176, 177), (208,),
    ]


def test_turns_with_3rr():
    assert turns_for_seat(16, 16, 13, True) == [
        (16, 17), (33,), (64, 65), (96, 97), (128, 129), (160, 161), (192, 193),
    ]


def test_snake_direction():
    assert [seat_for_pick(k, 16) for k in (1, 16, 17, 32, 33)] == [1, 16, 16, 1, 1]
    # 3RR: 3. tur da geri gider
    assert [seat_for_pick(k, 16, True) for k in (33, 48, 49, 64)] == [16, 1, 1, 16]


def test_next_turn_after():
    assert next_turn_after(17, 16, 16, 13) == (48, 49)
    assert next_turn_after(15, 16, 16, 13) == (16, 17)
    assert next_turn_after(208, 16, 16, 13) is None
