"""Rakip koltuklara profil ataması (README §6.4.3)."""

from __future__ import annotations

import numpy as np

from fdo.config import Config


def mix_list(config: Config) -> list[str]:
    out: list[str] = []
    for name, n in config.model.bots.mix.items():
        out += [name] * int(n)
    return out


def assign_profiles(config: Config, rng: np.random.Generator | None, user_seat: int | None = None) -> list[str]:
    """Koltuk sırasıyla (seat 1..T) profil adları.

    Kullanıcı koltuğu ``user_auto_profile`` alır (yalnızca "oynat" işlemlerinde kullanılır).
    ``seat_assignment = random_per_draft`` ise rakip profilleri her draft'ta karıştırılır.
    """
    teams = config.league.teams
    user_seat = config.league.my_seat if user_seat is None else user_seat
    labels = mix_list(config)
    if len(labels) != teams - 1:
        raise ValueError(f"Bot karışımı {teams - 1} olmalı, {len(labels)} verildi")
    if config.model.bots.seat_assignment == "random_per_draft":
        if rng is None:
            raise ValueError("random_per_draft için rng gerekli")
        labels = [labels[i] for i in rng.permutation(len(labels))]
    out, it = [], iter(labels)
    for seat in range(1, teams + 1):
        out.append(config.model.bots.user_auto_profile if seat == user_seat else next(it))
    return out
