"""API istek gövdeleri (Pydantic)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class StrategyIn(BaseModel):
    """Hazır strateji (``preset``), özel ağırlıklar (``weights``, 9 değer 0–3), ``auto_punt`` (1 ya da 2: takımın
    kategori profilinden en zayıf kategori(ler)i punt) ya da ``auto_revive`` (1 ya da 2: en zayıf kategori(ler)
    üç kat önemli). Hiçbiri yoksa dengeli."""

    preset: str | None = None
    name: str | None = None
    weights: list[float] | None = None
    auto_punt: int | None = Field(default=None, ge=1, le=2)
    auto_revive: int | None = Field(default=None, ge=1, le=2)


class TradeIn(BaseModel):
    team_a: str
    team_b: str
    give_a: list[str] = Field(default_factory=list)
    give_b: list[str] = Field(default_factory=list)
    drop_a: list[str] = Field(default_factory=list)
    drop_b: list[str] = Field(default_factory=list)
    add_a: list[str] = Field(default_factory=list)
    add_b: list[str] = Field(default_factory=list)
    auto_balance: bool = True
    strategy_a: StrategyIn | None = None
    strategy_b: StrategyIn | None = None
    injuries: bool = True
    basis: str = Field(default="ros", pattern="^(ros|season|recent|blend|late)$")   # kalan sezon temeli (§13.28)


class OfferIn(TradeIn):
    """Teklif kaydı (``offered``) ya da bir teklifin cevabı (``accepted`` / ``rejected`` / ``countered``; ``about``:
    teklifin kayıt kimliği)."""

    outcome: str = Field(default="offered", pattern="^(offered|accepted|rejected|countered)$")
    about: str | None = None


class ReportIn(TradeIn):
    refresh: bool = False                        # kayıtlı raporu yeniden üret (ücretli)


class SeasonIn(TradeIn):
    n_sims: int = 2000
    strength_sd: float = 0.06


class SeasonManyIn(BaseModel):
    """Birden çok takasın sezon etkisi (öneri listelerini sezon simülasyonuyla sıralamak için). Her takas kendi
    takımları, oyuncuları ve stratejileriyle; ``injuries``, ``basis``, simülasyon ayarları hepsi için ortak."""

    trades: list[TradeIn] = Field(min_length=1, max_length=20)
    n_sims: int = 2000
    strength_sd: float = 0.06
    injuries: bool = True
    basis: str = Field(default="ros", pattern="^(ros|season|recent|blend|late)$")


class CompleteIn(TradeIn):
    """Takas ekranındaki seçimi tamamla/dengele: ``give_a``/``give_b`` sabit, en az biri dolu (README §13.27)."""

    min_fairness: float = Field(default=.55, ge=0, le=1)
    min_view: float = Field(default=.8, ge=0, le=3)
    require_reason: bool = True                  # rakip için gerekçesiz paketleri listeleme
    max_view: float = Field(default=1.25, ge=0, le=10)   # rakibin gözünde en çok (üstü senin fazla ödemen); 0 = kapalı
    perceived: str = Field(default="blend", pattern="^(season_total|preseason|blend)$")
    max_extra: int = Field(default=3, ge=1, le=3)
    max_evaluations: int = Field(default=4000, ge=100, le=20000)


class SuggestIn(BaseModel):
    team: str
    mode: str = "mutual"
    opponents: list[str] | None = None
    opponent_assumption: str = "balanced"           # balanced | punt1 | punt2
    perceived: str = "blend"
    min_balance: float = 0.9
    min_edge: float = 1.0
    min_view: float = 0.8                           # karşılıklı faydada rakibin gözünde en az denge
    require_reason: bool = True                     # rakip için gerekçesiz paketleri listeleme
    max_view: float = 1.25                          # rakibin gözünde en çok (üstü senin fazla ödemen); 0 = kapalı
    packages: list[str] = Field(default_factory=lambda: ["1x1", "2x1", "1x2", "2x2"])
    shortlist: int = 8
    max_evaluations: int = 4000
    min_fairness: float = 0.55
    min_gain: float = 0.005
    min_win: float = 0.0
    ecw_weight: float = 0.65
    auto_balance: bool = True
    strategy: StrategyIn | None = None
    injuries: bool = True


class MoveIn(BaseModel):
    player: str
    from_team: str
    to_team: str


class MultiTradeIn(BaseModel):
    moves: list[MoveIn]
    drops: dict[str, list[str]] = Field(default_factory=dict)        # takım → bırakılanlar
    adds: dict[str, list[str]] = Field(default_factory=dict)         # takım → boştan alınanlar
    strategies: dict[str, StrategyIn | None] = Field(default_factory=dict)
    auto_balance: bool = True
    injuries: bool = True


class MultiSeasonIn(MultiTradeIn):
    n_sims: int = 2000
    strength_sd: float = 0.06


class MultiSuggestIn(BaseModel):
    team: str
    shapes: list[str] = Field(default_factory=lambda: ["1-1-1", "2-1-1", "1-1-2", "1-1-1-1"])
    opponents: list[str] | None = None
    opponent_assumption: str = "balanced"           # balanced | punt1 | punt2
    shortlist: int = 6
    shortlist4: int = 4
    min_fairness: float = 0.5
    min_gain: float = 0.005
    min_win: float = 0.0
    ecw_weight: float = 0.65
    min_view: float = 0.8                           # diğer takımların gözünde (algılanan) en az denge
    strategy: StrategyIn | None = None
    injuries: bool = True


class WeeklyIn(BaseModel):
    team: str
    week: int | None = None
    opponent: str | None = None
    sit_out: bool = True
    questionable_out: bool = False      # senaryo: Q / GTD / DTD bu hafta oynamaz (varsayılan: oynar)
    strategy: StrategyIn | None = None
    acc_mine: dict[str, float] | None = None
    acc_opp: dict[str, float] | None = None
    injuries: bool = True


class StreamIn(WeeklyIn):
    used: int | None = None          # None: Yahoo senkronizasyonundaki bu hafta kullanılan alım
    droppable: list[str] = Field(default_factory=list)


class AddDropWeekIn(WeeklyIn):
    mode: str = Field("win", pattern="^(win|critical)$")   # win: beklenen kategori; critical: seçilen kategoriler
    categories: list[str] | None = None                     # critical: None → otomatik (en kıpırdatılabilir 2)
    droppable: list[str] | None = None                      # None → kalan sezon değeri en düşük 3 aktif oyuncu
    used: int | None = None                                 # None → Yahoo'daki bu hafta kullanılan alım
    plan: bool = True


class DropIn(WeeklyIn):
    activate: list[str] | None = None                       # IL'den aktife alınacaklar; None → dönen/dönmek üzere olanlar


class WaiverIn(BaseModel):
    team: str
    strategy: StrategyIn | None = None
    injuries: bool = True
    top: int = 80
