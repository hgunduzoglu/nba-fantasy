"""Oyuncu durumu (README §5.8).

Durumu ``availability.undraftable_statuses`` içinde olan oyuncu (varsayılan ``NA``: aktif
kadroda değil) draft havuzuna alınmaz; ne kullanıcıya önerilir ne de botlar seçer.
Diğer etiketler (O, Q, GTD) hiçbir hesabı değiştirmez: sakatlığın etkisi projeksiyonun
beklenen maç sayısındadır (``projected_gp``).
"""

from __future__ import annotations

import pandas as pd

from fdo.config import Config


def status_mask(status: pd.Series, statuses) -> pd.Series:
    """Durum etiketi (boşlukla ayrılmış) ``statuses`` ile kesişiyor mu?"""
    wanted = set(statuses)
    return status.fillna("").astype(str).map(lambda s: bool(wanted & set(s.split())))


def undraftable_ids(players: pd.DataFrame, config: Config) -> list[str]:
    """Durumu nedeniyle draft edilemeyen oyuncular (``injury_status`` kolonu yoksa boş)."""
    if "injury_status" not in players:
        return []
    mask = status_mask(players["injury_status"], config.model.availability.undraftable_statuses)
    return sorted(players.loc[mask, "player_id"].astype(str))
