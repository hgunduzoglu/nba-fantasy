"""Dosya şemaları (README §5.3).

Projeksiyon ve ADP ayrı dosyalardır ve ``player_id`` üzerinden birleşir.
"""

from __future__ import annotations

from dataclasses import dataclass

from fdo.types import STATS


@dataclass(frozen=True)
class Column:
    name: str
    dtype: str  # str | float | int | bool | date | datetime
    required: bool = False
    description: str = ""


PLAYERS: tuple[Column, ...] = (
    Column("player_id", "str", True, "Provider'dan bağımsız iç ID"),
    Column("name", "str", True, "Görünen ad"),
    Column("nba_team", "str"),
    Column("yahoo_positions", "str", True, "Virgülle ayrılmış: PG,SG / SF,PF / C"),
    Column("yahoo_player_id", "str"),
    Column("nba_person_id", "str"),
    Column("aliases", "str", False, "; ile ayrılmış alternatif yazımlar"),
    Column("is_synthetic", "bool", True),
    Column("injury_status", "str", False, "Kaynağın durum etiketi (O, Q, NA…); NA draft edilmez (§5.8)"),
    Column("is_rookie", "bool", False, "V2 senaryoları: rookie belirsizliği daha geniş (§13.5)"),
)

PROJECTIONS: tuple[Column, ...] = (
    Column("player_id", "str", True),
    Column("projected_gp", "float", True, "Beklenen NBA maç sayısı (0–82)"),
    Column("minutes", "float"),
    *(Column(s, "float", True, "/ maç") for s in STATS),
    Column("projection_source", "str", True),
    Column("as_of", "date", True),
    Column("is_synthetic", "bool", True),
    Column("notes", "str"),
)

ADP: tuple[Column, ...] = (
    Column("player_id", "str", True),
    Column("adp", "float"),
    Column("adp_std", "float"),
    Column("adp_min", "float"),
    Column("adp_max", "float"),
    Column("pct_drafted", "float"),
    Column("default_rank", "float"),
    Column("adp_source", "str", True),
    Column("adp_window", "str"),
    Column("as_of", "date", True),
    Column("is_synthetic", "bool", True),
)

VARIANCE: tuple[Column, ...] = (
    Column("player_id", "str", True),
    Column("stat", "str", True),
    Column("per_game_var", "float", True),
    Column("n_games", "int"),
    Column("seasons", "str"),
)

DRAFT_LOG: tuple[Column, ...] = (
    Column("overall_pick", "int", True),
    Column("round", "int", True),
    Column("seat", "int", True),
    Column("player_id", "str", True),
    Column("source", "str", True),
    Column("observed_at", "datetime"),
)

#: V2: NBA maç takvimi (§13.4). Takım kodları ``players.nba_team`` ile aynı olmalı
#: (yaygın alternatif kodlar ``fdo.schedule.calendar.TEAM_ALIASES`` ile çevrilir).
SCHEDULE: tuple[Column, ...] = (
    Column("game_date", "date", True, "Yerel (ET) maç tarihi"),
    Column("home_team", "str", True),
    Column("away_team", "str", True),
    Column("game_id", "str"),
)

#: V2: oyuncu maç kayıtları (§13.2 varyans kalibrasyonu, §13.1 backtest).
GAMELOGS: tuple[Column, ...] = (
    Column("player_id", "str", True),
    Column("game_date", "date", True),
    Column("season", "str", True, "Örn. 2025-26"),
    Column("nba_team", "str"),
    Column("minutes", "float"),
    *(Column(s, "float", True, "maçtaki değer") for s in STATS),
)

SCHEMAS: dict[str, tuple[Column, ...]] = {
    "players": PLAYERS,
    "projections": PROJECTIONS,
    "adp": ADP,
    "variance": VARIANCE,
    "draft_log": DRAFT_LOG,
    "schedule": SCHEDULE,
    "gamelogs": GAMELOGS,
}

#: Projeksiyonda zorunlu sayısal stat kolonları (eksikse oyuncu havuz dışında kalır).
REQUIRED_PROJECTION_STATS: tuple[str, ...] = ("projected_gp", *STATS)

MANIFEST_KINDS: tuple[str, ...] = ("projections", "adp", "players", "variance", "draft_log", "schedule",
                                   "gamelogs")
LICENSE_STATUSES: tuple[str, ...] = ("personal_use_confirmed", "assumed", "unknown")
MANIFEST_REQUIRED: tuple[str, ...] = (
    "kind", "source_name", "retrieved_at", "license_status", "is_synthetic",
)


def required_columns(kind: str) -> list[str]:
    return [c.name for c in SCHEMAS[kind] if c.required]


def column_names(kind: str) -> list[str]:
    return [c.name for c in SCHEMAS[kind]]
