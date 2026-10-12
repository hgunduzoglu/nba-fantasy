"""Bot profilleri (README §6.4.2).

| Profil          | q̃                          | Ek davranış                         | σ çarpanı |
|-----------------|-----------------------------|-------------------------------------|-----------|
| MarketFollower  | q                           | —                                   | 0.8       |
| ValueHunter     | (1−λ)·q + λ·R               | R: dengeli Z-değer sırası           | 1.0       |
| PositionAware   | q                           | güçlü need_bonus                    | 1.0       |
| PuntBuilder     | (1−λ)·q + λ·R^punt          | r_punt turundan sonra en zayıf kat. | 1.0       |
| AutoDrafter     | default_rank (yoksa A)      | ortada olmayan menajer              | 0.3       |
| RandomHuman     | q                           | daha kalın kuyruk (ν küçük)         | 1.5       |

ValueHunter ve PuntBuilder projeksiyon kullanır; bu İlke 1'e aykırı değildir:
bot *davranışı* modelleniyor, kullanıcıya değer önerilmiyor.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from fdo.config import BOT_PROFILES, BotParams


@dataclass(frozen=True)
class ProfileTable:
    """Profil indeksine göre vektörleştirilmiş parametreler."""

    names: tuple[str, ...]
    sigma_mult: np.ndarray
    t_df: np.ndarray
    lam: np.ndarray            # q ile R harmanlama ağırlığı
    need_mult: np.ndarray
    is_punt: np.ndarray
    uses_default_rank: np.ndarray

    def index(self, name: str) -> int:
        return self.names.index(name)


def profile_table(params: BotParams) -> ProfileTable:
    names = BOT_PROFILES
    defaults = {"MarketFollower": 0.8, "ValueHunter": 1.0, "PositionAware": 1.0,
                "PuntBuilder": 1.0, "AutoDrafter": 0.3, "RandomHuman": 1.5}
    sm = {**defaults, **(params.profile_sigma_mult or {})}
    return ProfileTable(
        names=names,
        sigma_mult=np.array([float(sm[n]) for n in names]),
        t_df=np.array([params.t_df_random_human if n == "RandomHuman" else params.t_df for n in names],
                      dtype=float),
        lam=np.array([params.value_lambda if n == "ValueHunter" else
                      params.punt_lambda if n == "PuntBuilder" else 0.0 for n in names]),
        need_mult=np.array([params.position_aware_need_mult if n == "PositionAware" else 1.0
                            for n in names]),
        is_punt=np.array([n == "PuntBuilder" for n in names]),
        uses_default_rank=np.array([n == "AutoDrafter" for n in names]),
    )
