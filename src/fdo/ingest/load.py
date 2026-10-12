"""CSV okuma, kolon eşleme, manifest zorunluluğu, ad eşleme ve ``Dataset`` (README §5, §6.1).

Bu repo hiçbir web sitesinden veri çekmez. Bütün veri kullanıcının sağladığı
CSV dosyalarından gelir ve her dosyanın bir manifest'i olmalıdır.
"""

from __future__ import annotations

import datetime as dt
import difflib
import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from fdo.config import Config, load_config
from fdo.ingest import schema
from fdo.ingest.adp_fallback import apply_adp_fallback
from fdo.ingest.validate import (
    ValidationReport,
    parse_position_string,
    validate_adp,
    validate_cross,
    validate_players,
    validate_projections,
    validate_synthetic_mix,
)
from fdo.types import STATS

#: Sık görülen kaynak kolon adları → şema kolonu (kullanıcı ``column_map``'i önceliklidir).
DEFAULT_SYNONYMS: dict[str, str] = {
    "3pm": "fg3m", "3ptm": "fg3m", "fg3": "fg3m", "threes": "fg3m",
    "to": "tov", "turnovers": "tov",
    "gp": "projected_gp", "g": "projected_gp", "games": "projected_gp",
    "fg%": "fg_pct", "fgpct": "fg_pct", "ft%": "ft_pct", "ftpct": "ft_pct",
    "pos": "yahoo_positions", "position": "yahoo_positions", "positions": "yahoo_positions",
    "player": "name", "player_name": "name",
    "min": "minutes", "mpg": "minutes",
    "team": "nba_team",
}

_SUFFIX_RE = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b")
_PUNCT_RE = re.compile(r"[^a-z0-9 ]+")


class ManifestError(ValueError):
    pass


@dataclass
class Dataset:
    players: pd.DataFrame
    projections: pd.DataFrame
    adp: pd.DataFrame                  # draft havuzu: adp_eff, adp_status, sigma_mult eklenmiş
    manifests: dict[str, dict]
    is_synthetic: bool
    content_hash: str
    variance: pd.DataFrame | None = None
    excluded: dict[str, str] = field(default_factory=dict)

    @property
    def draft_ids(self) -> list[str]:
        """Draft havuzu (bot havuzu): ADP tablosundaki tüm oyuncular."""
        return list(self.adp.index)

    @property
    def projected_ids(self) -> list[str]:
        return list(self.projections["player_id"])

    def names(self) -> pd.Series:
        return self.players.set_index("player_id")["name"]

    def positions(self) -> pd.Series:
        return self.players.set_index("player_id")["positions"]

    def sources(self) -> list[dict]:
        """Her öneri/export'un taşıdığı kaynak kaydı (§5.2)."""
        return [{"kind": k, "source_name": m.get("source_name"), "retrieved_at": m.get("retrieved_at"),
                 "license_status": m.get("license_status")} for k, m in sorted(self.manifests.items())]


# --------------------------------------------------------------------------
# ad normalizasyonu
# --------------------------------------------------------------------------

def normalize_name(name) -> str:
    """Küçük harf, aksan kaldırma, noktalama ve Jr./Sr./II/III temizliği."""
    if name is None or (isinstance(name, float) and np.isnan(name)):
        return ""
    s = unicodedata.normalize("NFKD", str(name))
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    s = _PUNCT_RE.sub(" ", s.replace(".", ""))
    s = _SUFFIX_RE.sub(" ", s)
    return " ".join(s.split())


def resolve_player_ids(df: pd.DataFrame, players: pd.DataFrame, label: str,
                       report: ValidationReport) -> pd.DataFrame:
    """``player_id`` → ad → alias sırasıyla eşler. Belirsiz/eşleşmeyen satır hatadır."""
    known = set(players["player_id"])
    if "player_id" not in df:
        df = df.assign(player_id=pd.Series([np.nan] * len(df), index=df.index, dtype=object))
    if "name" not in df:
        return df

    by_name: dict[str, set[str]] = {}
    by_alias: dict[str, set[str]] = {}
    for pid, nm, al in zip(players["player_id"], players["name"],
                           players.get("aliases", pd.Series([None] * len(players)))):
        by_name.setdefault(normalize_name(nm), set()).add(pid)
        if isinstance(al, str):
            for a in al.split(";"):
                if a.strip():
                    by_alias.setdefault(normalize_name(a), set()).add(pid)
    all_names = list(by_name)

    ids = df["player_id"].astype(object).tolist()
    for row, (pid, nm) in enumerate(zip(ids, df["name"])):
        if isinstance(pid, str) and pid in known:
            continue
        key = normalize_name(nm)
        for index, how in ((by_name, "ad"), (by_alias, "alias")):
            cands = index.get(key, set())
            if len(cands) == 1:
                ids[row] = next(iter(cands))
                break
            if len(cands) > 1:
                report.error(f"{label}: '{nm}' birden fazla oyuncuya eşleşiyor ({how}): {sorted(cands)}")
                report.name_issues.append(dict(file=label, row=row, name=nm, problem="belirsiz",
                                               suggestions=sorted(cands)))
                break
        else:
            sugg = difflib.get_close_matches(key, all_names, n=3, cutoff=0.75)
            sugg_ids = sorted({p for s in sugg for p in by_name[s]})
            report.error(f"{label}: '{nm}' eşleşmedi" + (f" (öneri: {sugg_ids})" if sugg_ids else ""))
            report.name_issues.append(dict(file=label, row=row, name=nm, problem="eşleşmedi",
                                           suggestions=sugg_ids))
    return df.assign(player_id=ids)


# --------------------------------------------------------------------------
# CSV okuma ve tip dönüşümü
# --------------------------------------------------------------------------

def read_csv_raw(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str, keep_default_na=True, skipinitialspace=True)
    df.columns = [str(c).strip() for c in df.columns]
    return df


def apply_column_map(df: pd.DataFrame, column_map: dict[str, str] | None,
                     report: ValidationReport, label: str) -> pd.DataFrame:
    user = {str(k).strip().lower(): v for k, v in (column_map or {}).items()}
    rename = {}
    for col in df.columns:
        key = col.strip().lower()
        if key in user:
            rename[col] = user[key]
        elif key in DEFAULT_SYNONYMS and DEFAULT_SYNONYMS[key] not in df.columns:
            rename[col] = DEFAULT_SYNONYMS[key]
        else:
            rename[col] = key
    df = df.rename(columns=rename)
    return _derive_makes(df, report, label)


def _derive_makes(df: pd.DataFrame, report: ValidationReport, label: str) -> pd.DataFrame:
    """Yalnızca yüzde + deneme varsa ``fgm = fg_pct × fga`` dönüşümü (not olarak kaydedilir)."""
    for makes, att, pct in (("fgm", "fga", "fg_pct"), ("ftm", "fta", "ft_pct")):
        if makes not in df and pct in df and att in df:
            p = pd.to_numeric(df[pct], errors="coerce")
            if p.max(skipna=True) > 1.0:
                p = p / 100.0
            df[makes] = p * pd.to_numeric(df[att], errors="coerce")
            report.note(f"{label}: {makes} = {pct} × {att} dönüşümü uygulandı")
    return df


_TRUE = {"true", "1", "yes", "y", "t", "evet"}
_FALSE = {"false", "0", "no", "n", "f", "hayır", "hayir"}


def coerce_types(df: pd.DataFrame, kind: str, report: ValidationReport, label: str) -> pd.DataFrame:
    """Şemaya göre tip dönüşümü. Dönüştürülemeyen dolu hücre → error."""
    df = df.copy()
    missing = [c for c in schema.required_columns(kind) if c not in df.columns]
    if missing:
        report.error(f"{label}: zorunlu kolon eksik: {missing}")
    for col in schema.SCHEMAS[kind]:
        if col.name not in df.columns:
            continue
        s = df[col.name]
        blank = s.isna() | (s.astype(str).str.strip() == "")
        if col.dtype in ("float", "int"):
            num = pd.to_numeric(s.where(~blank), errors="coerce")
            bad = num.isna() & ~blank
            if bad.any():
                report.error(f"{label}: '{col.name}' sayıya dönüştürülemiyor: "
                             f"{s[bad].astype(str).head(5).tolist()}")
            df[col.name] = num.astype(float)
        elif col.dtype == "bool":
            low = s.astype(str).str.strip().str.lower()
            val = pd.Series(np.nan, index=df.index, dtype=object)
            val[low.isin(_TRUE)] = True
            val[low.isin(_FALSE)] = False
            bad = val.isna() & ~blank
            if bad.any():
                report.error(f"{label}: '{col.name}' bool değil: {s[bad].astype(str).head(5).tolist()}")
            df[col.name] = val
        elif col.dtype in ("date", "datetime"):
            ts = pd.to_datetime(s.where(~blank), errors="coerce")
            bad = ts.isna() & ~blank
            if bad.any():
                report.error(f"{label}: '{col.name}' tarih değil: {s[bad].astype(str).head(5).tolist()}")
            df[col.name] = ts.dt.strftime("%Y-%m-%d") if col.dtype == "date" else ts
        else:
            df[col.name] = s.where(~blank).map(lambda v: v.strip() if isinstance(v, str) else v)
    return df


# --------------------------------------------------------------------------
# manifest
# --------------------------------------------------------------------------

def manifest_candidates(csv_path: Path, manifest_dir: Path | None) -> list[Path]:
    dirs = [manifest_dir] if manifest_dir else [csv_path.parent / "manifests",
                                                csv_path.parent.parent / "manifests"]
    out = []
    for d in dirs:
        out += [d / f"{csv_path.name}.yaml", d / f"{csv_path.stem}.yaml"]
    return out


def read_manifest(csv_path: str | Path, kind: str, report: ValidationReport,
                  manifest_dir: str | Path | None = None) -> dict | None:
    csv_path = Path(csv_path)
    for cand in manifest_candidates(csv_path, Path(manifest_dir) if manifest_dir else None):
        if cand.exists():
            with open(cand, encoding="utf-8") as f:
                m = yaml.safe_load(f) or {}
            check_manifest(m, kind, report, str(cand))
            m["_path"] = str(cand)
            return m
    report.error(f"{csv_path.name}: manifest yok — dosya yüklenmedi (§5.2)")
    return None


def check_manifest(m: dict, kind: str, report: ValidationReport, label: str) -> None:
    missing = [k for k in schema.MANIFEST_REQUIRED if k not in m]
    if missing:
        report.error(f"{label}: manifest alanı eksik: {missing}")
    if m.get("kind") and m["kind"] != kind:
        report.error(f"{label}: manifest kind={m['kind']!r}, beklenen {kind!r}")
    ls = m.get("license_status")
    if ls is not None and ls not in schema.LICENSE_STATUSES:
        report.error(f"{label}: geçersiz license_status {ls!r}")
    if ls == "unknown":
        report.warn(f"{label}: license_status = unknown — kaynağın kullanım şartlarını doğrulayın")


# --------------------------------------------------------------------------
# Dataset kurulumu
# --------------------------------------------------------------------------

def content_hash(*frames: pd.DataFrame | None) -> str:
    h = hashlib.sha256()
    for df in frames:
        if df is None:
            h.update(b"<none>")
            continue
        cols = sorted(c for c in df.columns if c != "positions")
        d = df[cols]
        if "player_id" in d:
            d = d.sort_values([c for c in ("player_id", "stat") if c in d.columns], kind="mergesort")
        h.update(d.to_csv(index=False).encode())
    return h.hexdigest()[:16]


def _flags(df: pd.DataFrame) -> set[bool]:
    if "is_synthetic" not in df:
        return set()
    return {bool(v) for v in df["is_synthetic"].dropna()}


def build_dataset(players: pd.DataFrame, projections: pd.DataFrame, adp: pd.DataFrame,
                  config: Config, *, variance: pd.DataFrame | None = None,
                  manifests: dict[str, dict] | None = None,
                  report: ValidationReport | None = None,
                  reference_date: dt.date | None = None) -> tuple[Dataset | None, ValidationReport]:
    """Tiplenmiş tablolardan ``Dataset`` kurar; ADP fallback'i bir kez uygular.

    ``errors`` doluysa ``(None, report)`` döner: veri seti kullanılamaz.
    """
    from fdo.valuation import balanced_value_rank  # ingest → valuation (tek yönlü)

    report = report or ValidationReport()
    manifests = manifests or {}
    season = config.league.season

    validate_players(players, report)
    validate_projections(projections, report, season=season, reference_date=reference_date)
    validate_adp(adp, report, season=season, reference_date=reference_date)
    validate_cross(players, projections, adp, report)

    flags = {"players": _flags(players), "projections": _flags(projections), "adp": _flags(adp)}
    for kind, m in manifests.items():
        if "is_synthetic" in m:
            flags[f"manifest:{kind}"] = {bool(m["is_synthetic"])}
    is_synth = validate_synthetic_mix(flags, report)
    if is_synth:
        bad = players.loc[~players["name"].astype(str).str.startswith("SYN_"), "player_id"].tolist()
        if bad:
            report.error(f"Sentetik oyuncu adları SYN_ önekli olmalı: {bad[:5]}")

    if not report.ok:
        return None, report

    players = players.copy()
    players["positions"] = [parse_position_string(v)[0] for v in players["yahoo_positions"]]

    excluded = set(report.excluded)
    proj = projections[~projections["player_id"].isin(excluded)].reset_index(drop=True)
    vrank = balanced_value_rank(proj, config) if len(proj) else pd.Series(dtype=float)

    known = set(players["player_id"])
    draft_ids = sorted((set(proj["player_id"]) | set(adp["player_id"])) & known)
    adp_tab, notes = apply_adp_fallback(draft_ids, adp, vrank, config.model.adp_fallback,
                                        config.pool_size)
    for n in notes:
        report.note(n)
    for pid in sorted(set(draft_ids) - set(adp_tab.index)):
        report.exclude(pid, "ADP ve değer yok")

    n_slots = config.league.total_picks
    if len(adp_tab) < n_slots:
        report.warn(f"Draft havuzu ({len(adp_tab)}) toplam pick sayısından ({n_slots}) küçük")

    adp_tab = adp_tab.join(adp.set_index("player_id")[
        [c for c in ("adp_source", "adp_window", "as_of") if c in adp.columns]], how="left")
    ds = Dataset(players=players.reset_index(drop=True), projections=proj, adp=adp_tab,
                 manifests=manifests, is_synthetic=bool(is_synth), variance=variance,
                 content_hash=content_hash(players, projections, adp, variance),
                 excluded=dict(report.excluded))
    return ds, report


def _load_table(path: str | Path, kind: str, column_map: dict | None, report: ValidationReport,
                manifest_dir: str | Path | None) -> tuple[pd.DataFrame | None, dict | None]:
    path = Path(path)
    label = path.name
    manifest = read_manifest(path, kind, report, manifest_dir)
    if manifest is None:
        return None, None
    if not path.exists():
        report.error(f"{label}: dosya bulunamadı")
        return None, manifest
    df = apply_column_map(read_csv_raw(path), column_map, report, label)
    return df, manifest


def load_dataset(players_csv: str | Path, projections_csv: str | Path, adp_csv: str | Path,
                 variance_csv: str | Path | None = None, column_map: dict | None = None, *,
                 config: Config | None = None, manifest_dir: str | Path | None = None,
                 reference_date: dt.date | None = None) -> tuple[Dataset | None, ValidationReport]:
    """CSV'lerden doğrulanmış ``Dataset``. Hata varsa ``(None, report)``."""
    config = config or load_config()
    report = ValidationReport()
    manifests: dict[str, dict] = {}

    raw: dict[str, pd.DataFrame | None] = {}
    for kind, path in (("players", players_csv), ("projections", projections_csv), ("adp", adp_csv),
                       ("variance", variance_csv)):
        if path is None:
            raw[kind] = None
            continue
        df, m = _load_table(path, kind, column_map, report, manifest_dir)
        raw[kind] = df
        if m is not None:
            manifests[kind] = m
    if any(raw[k] is None for k in ("players", "projections", "adp")):
        return None, report

    players = coerce_types(raw["players"], "players", report, Path(players_csv).name)
    if not report.ok:
        return None, report
    proj = resolve_player_ids(raw["projections"], players, Path(projections_csv).name, report)
    adp = resolve_player_ids(raw["adp"], players, Path(adp_csv).name, report)
    proj = coerce_types(proj, "projections", report, Path(projections_csv).name)
    adp = coerce_types(adp, "adp", report, Path(adp_csv).name)
    variance = None
    if raw.get("variance") is not None:
        variance = coerce_types(raw["variance"], "variance", report, Path(variance_csv).name)
        bad = sorted(set(variance["stat"].dropna()) - set(STATS))
        if bad:
            report.error(f"variance: bilinmeyen stat {bad}")
    if not report.ok:
        return None, report

    keep = {k: [c for c in schema.column_names(k)] for k in ("players", "projections", "adp")}
    players = players[[c for c in keep["players"] if c in players.columns]]
    proj = proj[[c for c in keep["projections"] if c in proj.columns]]
    adp = adp[[c for c in keep["adp"] if c in adp.columns]]
    return build_dataset(players, proj, adp, config, variance=variance, manifests=manifests,
                         report=report, reference_date=reference_date)
