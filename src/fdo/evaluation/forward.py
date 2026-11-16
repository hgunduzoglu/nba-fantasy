"""İleriye dönük test: geçmiş bir günün verisiyle modelin tahmini, sonra gerçekleşenle karşılaştırılır.

Arşivdeki günlük kopya (``snapshots/<gün>/``: kadrolar, kalan sezon projeksiyonu) ve o günün CBS raporu o gün bilineni
verir (``snapshot_dir``); NBA maç kayıtları o günden sonra olanı. İki düzey ölçülür:

* **Oyuncu** (``forecast`` ↔ ``realized``): pencerede (gün → son maç günü) beklenen maç ve kategori toplamı ile
  gerçekleşen. Dönüş bekleyen sakatlar ayrıca raporlanır: dönüş varsayımı (CBS tarihi kesin mi, ölçülmüş gecikme
  dağılımı mı) burada sınanır.
* **Takas** (``pair_test``): takımın o gün yapabileceği bütün 1'e 1 takaslar; modelin takas puanı (strateji farkı) ve
  oyuncu tahmininden gelen değer farkı ile pencerede gerçekleşen değer farkının işaret uyumu ve sıra korelasyonu.

Değer, dokuz kategorinin gerçekleşen lig dağılımına göre ölçeklenmiş toplamıdır (yüzdeler isabet katkısıyla, top kaybı
eksi). Pencere kısa olduğu için gürültü büyüktür; sonuç örnek boyutuyla okunmalı. Karar günlüğü
(``fdo.evaluation.decisions``) biriktikçe aynı ölçüm gerçekten verilmiş önerilere uygulanır.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

from fdo.inseason.identity import Resolver
from fdo.schedule.calendar import normalize_team
from fdo.trade.data import ROS

COUNTS = ("fg3m", "pts", "reb", "ast", "stl", "blk", "tov")
STATS_USED = ("fgm", "fga", "ftm", "fta", *COUNTS)
POLICY_VERSION = "dated-roster-v4"
# Undated mutable inputs (settings, live scores, overrides, standings, logs,
# variance, etc.) must come from the archive, never today's directory.
DATED_INPUTS = ("players_yahoo_", "projections_yahoo_", "adp_yahoo_", "injuries_cbs_")


def snapshot_dir(data_dir: str | Path, day: dt.date, work: str | Path) -> Path:
    """Archive inputs plus explicitly dated pre-decision exports. No current
    settings/live/log/variance fallback. Missing historical inputs stay missing.
    ``work`` must be empty, so a mistaken path cannot delete existing data.
    """
    data_dir, work = Path(data_dir), Path(work)
    snap = data_dir / "snapshots" / day.isoformat()
    if not (snap / "rosters.json").exists():
        raise FileNotFoundError(f"Kopya yok: {snap}")
    roster = json.loads((snap / "rosters.json").read_text(encoding="utf-8-sig"))
    if roster.get("roster_date") != day.isoformat():
        raise ValueError("Arşiv kadrosunun tarihi decision_time ile eşleşmiyor")
    if work.exists() and any(work.iterdir()):
        raise ValueError(f"Replay çalışma dizini boş olmalı: {work}")
    work.mkdir(parents=True, exist_ok=True)
    for p in snap.iterdir():
        if p.is_file() and not p.name.startswith("yahoo_live"):
            dates = re.findall(r"\d{4}-\d{2}-\d{2}", p.name)
            if not dates or max(dates) <= day.isoformat():
                shutil.copy2(p, work / p.name)
    for p in data_dir.iterdir():
        if not p.is_file() or (work / p.name).exists() or not p.name.startswith(DATED_INPUTS):
            continue
        dates = re.findall(r"\d{4}-\d{2}-\d{2}", p.name)
        if dates and max(dates) <= day.isoformat():
            shutil.copy2(p, work / p.name)
    return work


def snapshot_id(directory: str | Path) -> str:
    root = Path(directory)
    digest = hashlib.sha256()
    for p in sorted(root.iterdir()):
        if p.is_file():
            digest.update(p.name.encode())
            digest.update(hashlib.sha256(p.read_bytes()).digest())
    return digest.hexdigest()


def freeze_model(config_dir: str | Path, destination: str | Path, trained_through: dt.date, *,
                 returns_path: str | Path | None = None) -> Path:
    """Freeze all YAML model inputs; content-addressed, with training/policy provenance."""
    config_dir, destination = Path(config_dir), Path(destination)
    files = {name: (config_dir / name).read_bytes() for name in ("league.yaml", "model.yaml", "returns.yaml")}
    if returns_path is not None:
        files["returns.yaml"] = Path(returns_path).read_bytes()
    hashes = {name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()}
    provenance = {"files": hashes, "trained_through": str(trained_through), "policy_version": POLICY_VERSION}
    version = hashlib.sha256(json.dumps(provenance, sort_keys=True).encode()).hexdigest()
    root = destination / version
    manifest = {"model_version": version, **provenance}
    if root.exists():
        if (json.loads((root / "manifest.json").read_text(encoding="utf-8")) != manifest
                or any((root / n).read_bytes() != raw for n, raw in files.items())):
            raise ValueError("Mevcut dondurulmuş model değişmiş; üzerine yazılamaz")
        return root
    root.mkdir(parents=True, exist_ok=True)
    for name, raw in files.items():
        (root / name).write_bytes(raw)
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return root


def replay_model(directory: str | Path, decision_day: dt.date) -> dict:
    """Reject missing provenance, changed parameters, future training and foreign policies."""
    root = Path(directory)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    trained = dt.date.fromisoformat(manifest["trained_through"])
    if trained >= decision_day:
        raise ValueError("Dış örneklem replay için trained_through < decision_time olmalı")
    if manifest["policy_version"] != POLICY_VERSION:
        raise ValueError("Replay policy_version bu kod sürümüyle eşleşmiyor")
    expected = manifest["files"]
    hashes = {n: hashlib.sha256((root / n).read_bytes()).hexdigest()
              for n in ("league.yaml", "model.yaml", "returns.yaml")}
    provenance = {"files": hashes, "trained_through": str(trained), "policy_version": POLICY_VERSION}
    if hashes != expected or hashlib.sha256(json.dumps(provenance, sort_keys=True).encode()).hexdigest() != manifest["model_version"]:
        raise ValueError("Dondurulmuş model dosyaları model_version ile eşleşmiyor")
    return manifest


def realized(logs: pd.DataFrame, players: pd.DataFrame, start: dt.date, end: dt.date,
             overrides: pd.DataFrame | None = None) -> tuple[pd.DataFrame, int]:
    """Oyuncu kimliği → pencerede oynadığı maç (dakika > 0) ve kategori toplamları; ikinci çıktı kimliği
    bulunamayan maç kaydı adı (bu oyuncular 0 sayılmaz, dışarıda kalır)."""
    w = logs[(logs["game_date"] >= start) & (logs["game_date"] <= end)].copy()
    one = Resolver(players, overrides)
    keys = w[["name", "nba_team"]].drop_duplicates()
    ids = {(r.name, r.nba_team): one(r.name, r.nba_team).player_id for r in keys.itertuples()}
    w["player_id"] = [ids[(n, t)] for n, t in zip(w["name"], w["nba_team"])]
    missing = int(w.loc[w["player_id"].isna(), "name"].nunique())
    w = w[w["player_id"].notna()]
    w["games"] = (w["minutes"].fillna(0) > 0).astype(float)
    return w.groupby("player_id")[["games", *STATS_USED]].sum(), missing


def forecast(engine, start: dt.date, end: dt.date) -> pd.DataFrame:
    """Modelin ``start`` günü beklediği: pencerede oynanacak maç ve kategori toplamı (kalan sezon projeksiyonu, dönüş
    tarihi ve varsa ölçülmüş gecikme dağılımı ile; takas puanıyla aynı dağıtım)."""
    ros = engine.data.stats[ROS].reindex(list(engine.ids))
    teams = engine.data.players["nba_team"].reindex(list(engine.ids))
    rows = {}
    for i, pid in enumerate(engine.ids):
        if not engine.modeled[i]:
            continue
        gp = float(ros.loc[pid, "gp"])
        team = normalize_team(teams.loc[pid]) if isinstance(teams.loc[pid], str) and teams.loc[pid] else ""
        if not np.isfinite(gp) or gp <= 0 or team not in engine._team_games:
            continue
        ret = max(engine.return_day(pid) or engine.data.as_of, engine.data.as_of)
        games = [d for d in engine._team_games[team] if d >= ret]
        pres = engine._presence(len(games)) if ret > engine.data.as_of else np.ones(len(games))
        if not games or pres.sum() <= 0:
            continue
        inside = float(sum(p for d, p in zip(games, pres) if start <= d <= end))
        g = gp * inside / float(pres.sum())
        rows[pid] = {"games": g, **{s: float(ros.loc[pid, s]) / gp * g for s in STATS_USED},
                     "returning": ret > engine.data.as_of}
    return pd.DataFrame.from_dict(rows, orient="index")


def value_scales(real: pd.DataFrame) -> dict:
    """Değer ölçeği gerçekleşen dağılımdan: yüzdelerde lig ortalaması, her kategoride oynayanlar arasında standart
    sapma."""
    played = real[real["games"] > 0]
    fg, ft = played["fgm"].sum() / max(played["fga"].sum(), 1), played["ftm"].sum() / max(played["fta"].sum(), 1)
    impact = pd.DataFrame({"fg": played["fgm"] - fg * played["fga"], "ft": played["ftm"] - ft * played["fta"],
                           **{c: played[c] for c in COUNTS}})
    return {"fg_avg": fg, "ft_avg": ft, "sd": impact.std().replace(0, 1).to_dict()}


def value(totals: pd.DataFrame, scales: dict) -> pd.Series:
    """Dokuz kategorinin ölçeklenmiş toplamı (top kaybı eksi)."""
    sd = scales["sd"]
    v = (totals["fgm"] - scales["fg_avg"] * totals["fga"]) / sd["fg"] \
        + (totals["ftm"] - scales["ft_avg"] * totals["fta"]) / sd["ft"]
    for c in COUNTS:
        v = v + (-1 if c == "tov" else 1) * totals[c] / sd[c]
    return v


def _spearman(a, b) -> float:
    a, b = pd.Series(a).rank(), pd.Series(b).rank()
    return float(np.corrcoef(a, b)[0, 1]) if len(a) > 2 and a.std() > 0 and b.std() > 0 else float("nan")


def pair_test(engine, team: str, fc: pd.Series, real: pd.Series, strategy=None) -> pd.DataFrame:
    """Takımın bütün 1'e 1 takasları (iki tarafta da tahmin ve gerçekleşen değeri olan oyuncular): modelin takas
    puanı (``strategy_delta``, kadro çözümü ve bedava hamleler dahil), oyuncu tahmininden değer farkı ve pencerede
    gerçekleşen değer farkı (alınan − verilen)."""
    from fdo.trade import TradeError, TradeRequest
    from fdo.trade.strategy import Strategy
    s = strategy or Strategy()
    ok = set(fc.index) & set(real.index)
    mine = [p for p in engine.league.rosters[team] if p in ok]
    rows = []
    for other in engine.team_ids:
        if other == team:
            continue
        for give in mine:
            for get in [p for p in engine.league.rosters[other] if p in ok]:
                req = TradeRequest(team, other, (give,), (get,), auto_drop=True, auto_fill=True)
                try:
                    rosters, _, il = engine.resolve(req, {team: s, other: Strategy()})
                    _, m = engine.score(rosters, team, other, s, Strategy(), il)
                except TradeError:
                    continue
                rows.append({"team_b": other, "give": give, "get": get, "model": m[team]["strategy_delta"],
                             "forecast": float(fc[get] - fc[give]), "realized": float(real[get] - real[give])})
    return pd.DataFrame(rows)


def summary(pairs: pd.DataFrame) -> dict:
    """Takas düzeyi: modelin ve oyuncu tahmininin işaret uyumu ve sıra korelasyonu (gerçekleşen değer farkıyla)."""
    if pairs.empty:
        return {"n": 0}
    sign = lambda col: float((np.sign(pairs[col]) == np.sign(pairs["realized"])).mean())
    return {"n": len(pairs), "model_sign": sign("model"), "forecast_sign": sign("forecast"),
            "model_spearman": _spearman(pairs["model"], pairs["realized"]),
            "forecast_spearman": _spearman(pairs["forecast"], pairs["realized"])}
