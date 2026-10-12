"""Ortak tipler ve sabitler.

Kategori sırası, istatistik adları ve pozisyonlar burada tek yerde tanımlanır.
Hangi kategorinin "düşük iyi" olduğu ise config'ten (``scoring.lower_is_better``)
okunur (İlke 5).
"""

from __future__ import annotations

from typing import NewType

PlayerId = NewType("PlayerId", str)
Category = str
Slot = str
Position = str

#: Yahoo pozisyonları (``yahoo_positions`` kolonunda izinli değerler).
POSITIONS: tuple[Position, ...] = ("PG", "SG", "SF", "PF", "C")

#: Maç başına projeksiyon istatistikleri (küçük harf, CSV kolon adlarıyla aynı).
STATS: tuple[str, ...] = (
    "fgm", "fga", "ftm", "fta", "fg3m", "pts", "reb", "ast", "stl", "blk", "tov",
)

#: Sayma kategorisi → projeksiyon kolonu.
COUNTING_CATEGORY_STAT: dict[Category, str] = {
    "FG3M": "fg3m",
    "PTS": "pts",
    "REB": "reb",
    "AST": "ast",
    "STL": "stl",
    "BLK": "blk",
    "TOV": "tov",
}

#: Kategori görünen adları.
CATEGORY_LABELS: dict[Category, str] = {
    "FG_PCT": "FG%",
    "FT_PCT": "FT%",
    "FG3M": "3PM",
    "PTS": "PTS",
    "REB": "REB",
    "AST": "AST",
    "STL": "STL",
    "BLK": "BLK",
    "TOV": "TO",
}

ADP_STATUSES: tuple[str, ...] = ("ok", "low_confidence", "imputed", "tail")
