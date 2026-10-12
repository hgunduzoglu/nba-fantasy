"""Validasyon kuralları (README §5.5).

``ValidationReport.errors`` boş değilse veri seti kullanılamaz. Eksik değer
**asla** 0 ile doldurulmaz: eksik zorunlu stat → oyuncu havuz dışında kalır.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from fdo.types import POSITIONS, STATS

PTS_TOLERANCE = 0.5
STALE_DAYS = 60


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    #: Ad eşleme sorunları (UI düzeltme tablosu): file, row, name, problem, suggestions.
    name_issues: list[dict] = field(default_factory=list)
    #: Havuzdan çıkarılan oyuncular ve nedenleri.
    excluded: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def note(self, msg: str) -> None:
        self.notes.append(msg)

    def exclude(self, player_id: str, reason: str) -> None:
        self.excluded.setdefault(str(player_id), reason)

    def extend(self, other: "ValidationReport") -> None:
        self.errors += other.errors
        self.warnings += other.warnings
        self.notes += other.notes
        self.name_issues += other.name_issues
        for k, v in other.excluded.items():
            self.exclude(k, v)

    def summary(self) -> str:
        return (f"{len(self.errors)} hata, {len(self.warnings)} uyarı, {len(self.notes)} not, "
                f"{len(self.excluded)} oyuncu havuz dışı")


def _ids(df: pd.DataFrame, mask) -> list[str]:
    return df.loc[mask, "player_id"].astype(str).tolist()


def _fmt_ids(ids: list[str], limit: int = 8) -> str:
    more = f" (+{len(ids) - limit})" if len(ids) > limit else ""
    return ", ".join(ids[:limit]) + more


def check_duplicate_ids(df: pd.DataFrame, label: str, report: ValidationReport) -> None:
    dup = df["player_id"][df["player_id"].duplicated(keep=False)]
    if len(dup):
        report.error(f"{label}: tekrarlanan player_id: {_fmt_ids(sorted(set(dup.astype(str))))}")


def parse_position_string(value) -> tuple[frozenset[str] | None, str | None]:
    """``"PG,SG"`` → frozenset; hata durumunda ``(None, mesaj)``."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None, "boş"
    parts = [p.strip().upper() for p in str(value).replace("/", ",").split(",") if p.strip()]
    if not parts:
        return None, "boş"
    bad = [p for p in parts if p not in POSITIONS]
    if bad:
        return None, f"izinsiz değer {bad}"
    return frozenset(parts), None


def validate_players(players: pd.DataFrame, report: ValidationReport) -> None:
    check_duplicate_ids(players, "players", report)
    for pid, val in zip(players["player_id"], players["yahoo_positions"]):
        _, problem = parse_position_string(val)
        if problem:
            report.error(f"players: {pid} yahoo_positions {problem}")
    missing_name = players["name"].isna() | (players["name"].astype(str).str.strip() == "")
    if missing_name.any():
        report.error(f"players: adı boş oyuncular: {_fmt_ids(_ids(players, missing_name))}")


def validate_projections(proj: pd.DataFrame, report: ValidationReport, *,
                         season: str, reference_date: dt.date | None = None) -> None:
    check_duplicate_ids(proj, "projections", report)

    missing = proj[list(("projected_gp", *STATS))].isna().any(axis=1)
    for pid in _ids(proj, missing):
        report.exclude(pid, "projeksiyonda eksik zorunlu stat")
    if missing.any():
        report.warn(f"projections: eksik zorunlu stat nedeniyle havuz dışı: {_fmt_ids(_ids(proj, missing))}")

    p = proj[~missing]
    rules = [
        (p["fgm"] > p["fga"], "fgm > fga"),
        (p["ftm"] > p["fta"], "ftm > fta"),
        (p["fg3m"] > p["fgm"], "fg3m > fgm"),
        ((p[list(STATS)] < 0).any(axis=1), "negatif istatistik"),
        ((p["projected_gp"] < 0) | (p["projected_gp"] > 82), "projected_gp ∉ [0, 82]"),
    ]
    for mask, label in rules:
        if mask.any():
            report.error(f"projections: {label}: {_fmt_ids(_ids(p, mask))}")

    zero_att = (p["fga"] == 0) | (p["fta"] == 0)
    if zero_att.any():
        report.note(f"projections: fga=0 veya fta=0 (oran katkısı 0): {_fmt_ids(_ids(p, zero_att))}")

    pts_gap = (p["pts"] - (2 * p["fgm"] + p["fg3m"] + p["ftm"])).abs() > PTS_TOLERANCE
    if pts_gap.any():
        report.warn(f"projections: pts ≠ 2·fgm + fg3m + ftm (±{PTS_TOLERANCE}): {_fmt_ids(_ids(p, pts_gap))}")

    check_as_of(proj, "projections", report, season=season, reference_date=reference_date)


def validate_adp(adp: pd.DataFrame, report: ValidationReport, *,
                 season: str, reference_date: dt.date | None = None) -> None:
    check_duplicate_ids(adp, "adp", report)
    for col in ("adp", "adp_std", "adp_min", "adp_max", "default_rank"):
        if col in adp and (adp[col] < 0).any():
            report.error(f"adp: negatif {col}: {_fmt_ids(_ids(adp, adp[col] < 0))}")
    if "pct_drafted" in adp:
        bad = (adp["pct_drafted"] < 0) | (adp["pct_drafted"] > 100)
        if bad.any():
            report.error(f"adp: pct_drafted ∉ [0, 100]: {_fmt_ids(_ids(adp, bad))}")
    check_as_of(adp, "adp", report, season=season, reference_date=reference_date)


def season_start(season: str) -> dt.date:
    """``"2026-27"`` → sezon öncesi dönemin başlangıcı (1 Temmuz 2026)."""
    return dt.date(int(str(season)[:4]), 7, 1)


def check_as_of(df: pd.DataFrame, label: str, report: ValidationReport, *,
                season: str, reference_date: dt.date | None) -> None:
    if "as_of" not in df or df["as_of"].isna().all():
        return
    ref = reference_date or dt.date.today()
    dates = pd.to_datetime(df["as_of"]).dt.date
    oldest = min(dates.dropna())
    if oldest < season_start(season):
        report.warn(f"{label}: as_of ({oldest}) {season} sezonundan önce")
    elif (ref - oldest).days > STALE_DAYS:
        report.warn(f"{label}: as_of ({oldest}) {STALE_DAYS} günden eski")


def validate_cross(players: pd.DataFrame, proj: pd.DataFrame, adp: pd.DataFrame,
                   report: ValidationReport) -> None:
    pl_ids = set(players["player_id"])
    pr_ids = set(proj["player_id"])
    ad_ids = set(adp["player_id"])

    no_proj = sorted(pl_ids - pr_ids)
    if no_proj:
        report.warn(f"Projeksiyonu olmayan oyuncu(lar) havuz dışı: {_fmt_ids(no_proj)}")
        for pid in no_proj:
            if pid not in ad_ids:
                report.exclude(pid, "projeksiyon ve ADP yok")

    adp_no_proj = sorted((ad_ids & pl_ids) - pr_ids)
    if adp_no_proj:
        report.warn("ADP'si olan ama projeksiyonu olmayan oyuncu(lar) bot havuzunda kalır, "
                    f"kullanıcıya önerilmez: {_fmt_ids(adp_no_proj)}")

    for label, ids in (("projections", pr_ids), ("adp", ad_ids)):
        unknown = sorted(ids - pl_ids)
        if unknown:
            report.error(f"{label}: players.csv'de olmayan player_id: {_fmt_ids(unknown)}")


def validate_synthetic_mix(flags: dict[str, set[bool]], report: ValidationReport) -> bool | None:
    """Dosya başına ``is_synthetic`` değer kümelerinden karışımı denetler (§5.7)."""
    values = set().union(*flags.values()) if flags else set()
    if len(values) > 1:
        detail = ", ".join(f"{k}={sorted(v)}" for k, v in flags.items())
        report.error(f"Sentetik ve gerçek veri aynı oturumda karıştırılamaz ({detail})")
        return None
    return next(iter(values)) if values else None
