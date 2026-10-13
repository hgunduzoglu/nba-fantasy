"""YAML konfigürasyonu yükleme ve doğrulama (README §3, §6).

``config/league.yaml`` kesinleşmiş lig ayarlarını ve doğrulanmamış ayarları,
``config/model.yaml`` kalibre edilmemiş model parametrelerini içerir.
Her ikisi de değişmez (frozen) dataclass'lara yüklenir.
"""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from fdo.types import COUNTING_CATEGORY_STAT, POSITIONS

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_DIR = REPO_ROOT / "config"

BOT_PROFILES: tuple[str, ...] = (
    "MarketFollower", "ValueHunter", "PositionAware", "PuntBuilder", "AutoDrafter", "RandomHuman",
)


class ConfigError(ValueError):
    """Konfigürasyon tutarsız."""


@dataclass(frozen=True)
class LeagueSettings:
    platform: str
    season: str
    teams: int
    my_seat: int
    rounds: int
    draft_type: str
    third_round_reversal: bool

    @property
    def total_picks(self) -> int:
        return self.teams * self.rounds


@dataclass(frozen=True)
class ScoringSettings:
    format: str
    categories: tuple[str, ...]
    lower_is_better: frozenset[str]
    ratio_categories: dict[str, dict[str, str]]

    def is_ratio(self, cat: str) -> bool:
        return cat in self.ratio_categories

    @property
    def counting_categories(self) -> tuple[str, ...]:
        return tuple(c for c in self.categories if c not in self.ratio_categories)


@dataclass(frozen=True)
class RosterSettings:
    slots: dict[str, int]
    active_slots: tuple[str, ...]
    slot_eligibility: dict[str, frozenset[str]]

    @property
    def size(self) -> int:
        return sum(self.slots.values())

    @property
    def n_active(self) -> int:
        return sum(n for s, n in self.slots.items() if s in self.active_slots)


@dataclass(frozen=True)
class UnverifiedSettings:
    tie_value: float | None
    pick_timer_seconds: float | None
    lineup_lock: str | None
    il_slots: int | None
    keepers: bool | None
    position_limits_enforced_in_draft: bool | None
    il_plus_slots: int | None = None
    playoff_weeks: int | None = None     # fantasy playoff'u olan son hafta sayısı (V2 takvim)

    def null_fields(self) -> list[str]:
        return [f.name for f in dataclasses.fields(self) if getattr(self, f.name) is None]


@dataclass(frozen=True)
class ScheduleSettings:
    """Fantasy haftaları (README §13.4). Hafta ``week_start`` gününde başlar; ``merge_with_next``
    içindeki hafta numaraları sonraki haftayla tek eşleşme sayılır (örn. All-Star arası)."""
    week_start: str = "monday"
    merge_with_next: tuple[int, ...] = ()


@dataclass(frozen=True)
class ValuationParams:
    basis: str = "total"
    method: str = "z"
    pool_size: int | None = None
    pool_size_options: tuple[int, ...] = (180, 208, 240)
    max_pool_iterations: int = 10
    g_kappa: float = 1.0
    weight_min: float = 0.0
    weight_max: float = 3.0
    weight_step: float = 0.05
    presets: dict[str, dict[str, float]] = field(default_factory=lambda: {"balanced": {}})


@dataclass(frozen=True)
class AdpFallbackParams:
    pct_drafted_threshold: float = 50.0
    coverage_limit: float = 150.0
    sigma_mult: dict[str, float] = field(
        default_factory=lambda: {"ok": 1.0, "low_confidence": 1.5, "imputed": 2.0, "tail": 2.0}
    )
    low_confidence_default_w: float = 0.5
    extrapolation_tail_fraction: float = 0.2
    missing_adp_policy: str = "after_coverage"


@dataclass(frozen=True)
class BotParams:
    mix: dict[str, int] = field(default_factory=dict)
    seat_assignment: str = "random_per_draft"
    user_auto_profile: str = "MarketFollower"
    sigma0: float = 1.5
    sigma1: float = 0.12
    sigma_floor: float = 1.0
    sigma_cap: float = 25.0
    t_df: float = 5.0
    t_df_random_human: float = 3.0
    jitter_rho: float = 0.15
    value_lambda: float = 0.3
    punt_lambda: float = 0.4
    punt_after_round: int = 3
    beta_need: float = 4.0
    position_aware_need_mult: float = 3.0
    beta_stack: float = 3.0
    enforce_completion_feasibility: bool = True
    profile_sigma_mult: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class VarianceParams:
    phi: dict[str, float] = field(default_factory=dict)
    #: kategori × kategori korelasyonu (V2, scripts/calibrate_variance.py); None → bağımsızlık
    category_corr: dict[str, dict[str, float]] | None = None


@dataclass(frozen=True)
class MatchupParams:
    games_per_week: float = 3.5
    utilization: float = 0.92
    games_cap: float = 82.0
    playoff_weight: float = 1.0      # takvimde playoff haftalarının ağırlığı (V2)
    games_variance: bool = False     # haftadan haftaya maç sayısı varyansı (V2, bağımsızlık varsayar)
    winnable_threshold: float = 0.6
    lost_threshold: float = 0.4


@dataclass(frozen=True)
class AvailabilityParams:
    """Oyuncu durumu (README §5.8): bu etiketlerdeki oyuncu draft havuzuna alınmaz."""
    undraftable_statuses: tuple[str, ...] = ("NA",)


@dataclass(frozen=True)
class AdvisorParams:
    k1_top_ecw: int = 20
    k2_urgency_pool: int = 35
    urgency_survival_threshold: float = 0.5
    max_candidates: int = 25
    m_pairs_to_rollout: int = 30
    sims_per_pair: int = 500
    sims_per_pair_fast: int = 200
    next_policy_top_l: int = 12
    policy_shortlist_k: int = 60
    fill_sims_base: int = 200
    fill_sims_conditional: int = 100
    fill_smoothing_window: int = 5
    scenario_full_sims: int = 200
    pool_table_size: int = 30
    pool_tiers: int = 5
    tier_se_mult: float = 2.0


@dataclass(frozen=True)
class RealismParams:
    reach_z_warn: float = 1.5
    reach_z_bad: float = 2.5
    slide_z: float = 2.5
    extreme_adp_center: float = 90.0
    extreme_adp_halfwidth: float = 5.0
    diversity_top_n: int = 32


@dataclass(frozen=True)
class ModelSettings:
    valuation: ValuationParams
    adp_fallback: AdpFallbackParams
    bots: BotParams
    variance: VarianceParams
    matchup: MatchupParams
    advisor: AdvisorParams
    realism: RealismParams
    availability: AvailabilityParams = field(default_factory=AvailabilityParams)


@dataclass(frozen=True)
class Config:
    league: LeagueSettings
    scoring: ScoringSettings
    roster: RosterSettings
    unverified: UnverifiedSettings
    model: ModelSettings
    schedule: ScheduleSettings = field(default_factory=ScheduleSettings)
    raw: dict[str, Any] = field(repr=False, compare=False, default_factory=dict)

    # --- kısayollar ---------------------------------------------------------
    @property
    def categories(self) -> tuple[str, ...]:
        return self.scoring.categories

    @property
    def lower_is_better(self) -> frozenset[str]:
        """İlke 5: "düşük iyi" kategorileri tek kaynaktan okunur."""
        return self.scoring.lower_is_better

    @property
    def opponents(self) -> int:
        return self.league.teams - 1

    @property
    def pool_size(self) -> int:
        n = self.model.valuation.pool_size
        return int(n) if n else self.league.teams * self.league.rounds

    @property
    def config_hash(self) -> str:
        blob = json.dumps(self.raw, sort_keys=True, default=str).encode()
        return hashlib.sha256(blob).hexdigest()[:16]

    def with_overrides(self, overrides: dict[str, Any]) -> "Config":
        """``{"league": {"third_round_reversal": True}}`` gibi derin birleştirme ile yeni config."""
        merged = _deep_merge(copy.deepcopy(self.raw), overrides)
        return config_from_dict(merged)


# --------------------------------------------------------------------------
# yükleme
# --------------------------------------------------------------------------

def _deep_merge(base: dict, extra: dict) -> dict:
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            base[k] = _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def _build(cls, data: dict | None):
    data = dict(data or {})
    names = {f.name: f for f in dataclasses.fields(cls)}
    unknown = set(data) - set(names)
    if unknown:
        raise ConfigError(f"{cls.__name__}: bilinmeyen alan(lar) {sorted(unknown)}")
    for k, v in list(data.items()):
        if isinstance(v, list):
            data[k] = tuple(v)
    return cls(**data)


def config_from_dict(raw: dict[str, Any]) -> Config:
    try:
        lg = raw["league"]
        sc = raw["scoring"]
        ro = raw["roster"]
    except KeyError as e:
        raise ConfigError(f"league config'te zorunlu bölüm eksik: {e}") from e

    league = LeagueSettings(
        platform=str(lg["platform"]),
        season=str(lg["season"]),
        teams=int(lg["teams"]),
        my_seat=int(lg["my_seat"]),
        rounds=int(lg["rounds"]),
        draft_type=str(lg["draft_type"]),
        third_round_reversal=bool(lg.get("third_round_reversal", False)),
    )
    scoring = ScoringSettings(
        format=str(sc["format"]),
        categories=tuple(sc["categories"]),
        lower_is_better=frozenset(sc.get("lower_is_better", [])),
        ratio_categories={k: dict(v) for k, v in sc.get("ratio_categories", {}).items()},
    )
    roster = RosterSettings(
        slots={str(k): int(v) for k, v in ro["slots"].items()},
        active_slots=tuple(ro["active_slots"]),
        slot_eligibility={str(k): frozenset(v) for k, v in ro["slot_eligibility"].items()},
    )
    unverified = _build(UnverifiedSettings, raw.get("unverified", {}))

    m = raw.get("model", {})
    model = ModelSettings(
        valuation=_build(ValuationParams, m.get("valuation")),
        adp_fallback=_build(AdpFallbackParams, m.get("adp_fallback")),
        bots=_build(BotParams, m.get("bots")),
        variance=_build(VarianceParams, m.get("variance")),
        matchup=_build(MatchupParams, m.get("matchup")),
        advisor=_build(AdvisorParams, m.get("advisor")),
        realism=_build(RealismParams, m.get("realism")),
        availability=_build(AvailabilityParams, m.get("availability")),
    )
    cfg = Config(league=league, scoring=scoring, roster=roster, unverified=unverified,
                 model=model, schedule=_build(ScheduleSettings, raw.get("schedule")), raw=raw)
    validate_config(cfg)
    return cfg


def load_config(league_path: str | Path | None = None,
                model_path: str | Path | None = None) -> Config:
    league_path = Path(league_path) if league_path else DEFAULT_CONFIG_DIR / "league.yaml"
    model_path = Path(model_path) if model_path else DEFAULT_CONFIG_DIR / "model.yaml"
    with open(league_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    with open(model_path, encoding="utf-8") as f:
        raw["model"] = yaml.safe_load(f) or {}
    return config_from_dict(raw)


def validate_config(cfg: Config) -> None:
    lg, sc, ro = cfg.league, cfg.scoring, cfg.roster
    if lg.draft_type != "snake":
        raise ConfigError(f"Yalnızca snake draft destekleniyor (draft_type={lg.draft_type!r})")
    if lg.teams < 2:
        raise ConfigError("teams ≥ 2 olmalı")
    if not 1 <= lg.my_seat <= lg.teams:
        raise ConfigError(f"my_seat 1..{lg.teams} aralığında olmalı")
    if ro.size != lg.rounds:
        raise ConfigError(f"sum(slots) == rounds olmalı ({ro.size} ≠ {lg.rounds})")

    known = set(COUNTING_CATEGORY_STAT) | set(sc.ratio_categories)
    bad = [c for c in sc.categories if c not in known]
    if bad:
        raise ConfigError(f"Tanınmayan kategori(ler): {bad}")
    if not sc.lower_is_better <= set(sc.categories):
        raise ConfigError("lower_is_better kategorileri categories içinde olmalı")
    for cat, spec in sc.ratio_categories.items():
        if set(spec) != {"makes", "attempts"}:
            raise ConfigError(f"{cat}: ratio tanımı makes/attempts içermeli")

    for slot in ro.slots:
        if slot not in ro.slot_eligibility:
            raise ConfigError(f"{slot} slotu için slot_eligibility tanımı yok")
    for slot, positions in ro.slot_eligibility.items():
        if not positions <= set(POSITIONS):
            raise ConfigError(f"{slot}: izinsiz pozisyon {sorted(positions - set(POSITIONS))}")
    for slot in ro.active_slots:
        if slot not in ro.slots:
            raise ConfigError(f"Aktif slot {slot} slots içinde yok")

    bots = cfg.model.bots
    unknown_profiles = set(bots.mix) - set(BOT_PROFILES)
    if unknown_profiles:
        raise ConfigError(f"Bilinmeyen bot profili: {sorted(unknown_profiles)}")
    if bots.mix and sum(bots.mix.values()) != lg.teams - 1:
        raise ConfigError(f"Bot karışımı {lg.teams - 1} rakibe eşit olmalı (şu an {sum(bots.mix.values())})")
    if bots.user_auto_profile not in BOT_PROFILES:
        raise ConfigError(f"user_auto_profile bilinmiyor: {bots.user_auto_profile}")
    if bots.seat_assignment not in ("random_per_draft", "fixed"):
        raise ConfigError("seat_assignment: random_per_draft | fixed")

    if cfg.model.adp_fallback.missing_adp_policy not in ("after_coverage", "isotonic"):
        raise ConfigError("adp_fallback.missing_adp_policy: after_coverage | isotonic")
    days = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
    if cfg.schedule.week_start not in days:
        raise ConfigError(f"schedule.week_start: {' | '.join(days)}")
    if cfg.model.matchup.playoff_weight < 0:
        raise ConfigError("matchup.playoff_weight ≥ 0 olmalı")
    if cfg.unverified.lineup_lock not in (None, "daily_today", "daily_tomorrow", "weekly"):
        raise ConfigError("lineup_lock: daily_today | daily_tomorrow | weekly")

    corr = cfg.model.variance.category_corr
    if corr:
        bad = (set(corr) | {b for row in corr.values() for b in row}) - set(sc.categories)
        if bad:
            raise ConfigError(f"variance.category_corr: bilinmeyen kategori {sorted(bad)}")
        if any(abs(float(v)) > 1 for row in corr.values() for v in row.values()):
            raise ConfigError("variance.category_corr değerleri [-1, 1] aralığında olmalı")

    val = cfg.model.valuation
    if val.basis not in ("total", "per_game"):
        raise ConfigError("valuation.basis: total | per_game")
    if val.method not in ("z", "g"):
        raise ConfigError("valuation.method: z | g")
    for name, preset in val.presets.items():
        bad = set(preset or {}) - set(sc.categories)
        if bad:
            raise ConfigError(f"Preset {name}: bilinmeyen kategori {sorted(bad)}")
