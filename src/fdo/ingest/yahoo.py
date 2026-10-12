"""Yahoo JSON dışa aktarımlarının şemaya dönüştürülmesi (README §5.3–§5.4).

Girdiler kullanıcının kendi aldığı dosyalardır; bu modül hiçbir yerden veri çekmez.

* ``players.json`` — "Yahoo Fantasy Basketball", ``season_totals``: sezon boyu projeksiyon toplamları
* ``adp.json``     — "Yahoo Draft Analysis", ``players``: xrank, % drafted, ADP

Eşleştirme sırası: (1) ``player_id``, (2) ID'si boş satırlar için takım + pozisyon + sıra
(``preseason_rank == xrank``; iki dosyada da benzersiz ve eşleşen tüm oyuncularda birebir aynı),
(3) normalize ad + takım (``S. Gilgeous-Alexander`` gibi baş harfli kısaltmalar dahil).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from fdo.config import REPO_ROOT
from fdo.ingest.load import normalize_name

STAT_MAP = {"fgm": "fgm", "fga": "fga", "ftm": "ftm", "fta": "fta", "three_pm": "fg3m", "pts": "pts",
            "reb": "reb", "ast": "ast", "stl": "stl", "blk": "blk", "tov": "tov"}
STATUS_FLAGS = ("Q", "O", "NA", "GTD", "INJ", "SUSP", "DTD", "IL", "IL+")


def internal_id(yahoo_id) -> str:
    return f"y_{yahoo_id}"


def name_key(name: str, team: str) -> str:
    return f"{normalize_name(name)}|{team}"


def initial_key(name: str, team: str) -> str:
    """``Shai Gilgeous-Alexander`` ve ``S. Gilgeous-Alexander`` → ``s gilgeous alexander|OKC``."""
    parts = normalize_name(name).split()
    if not parts:
        return ""
    return f"{parts[0][0]} {' '.join(parts[1:])}|{team}"


def parse_position_text(text: str) -> tuple[str, str]:
    """``"DET - PG,SG Q"`` → ``("PG,SG", "Q")``."""
    rest = str(text).split(" - ", 1)[-1].split()
    pos = rest[0] if rest else ""
    flags = " ".join(t for t in rest[1:] if t in STATUS_FLAGS or t.isupper())
    return pos, flags


def match(proj: pd.DataFrame, adp: pd.DataFrame) -> tuple[pd.Series, list[str]]:
    """``proj`` satırı → ``adp`` satır indeksi. Dönüş: eşleşme serisi ve log satırları."""
    log: list[str] = []
    out = pd.Series(pd.NA, index=proj.index, dtype="object")
    by_id = {str(v): i for i, v in adp["player_id"].items()}
    by_rank = {(r.team, r.pos, int(r.xrank)): i for i, r in adp.iterrows()}
    by_name: dict[str, list[int]] = {}
    by_init: dict[str, list[int]] = {}
    for i, r in adp.iterrows():
        by_name.setdefault(name_key(r["name"], r["team"]), []).append(i)
        by_init.setdefault(initial_key(r["name"], r["team"]), []).append(i)

    used: set[int] = set()
    counts = {"player_id": 0, "takım+pozisyon+sıra": 0, "ad+takım": 0, "baş harf+takım": 0}
    for i, r in proj.iterrows():
        cand, how = None, None
        pid = r["player_id"]
        if isinstance(pid, str) and pid in by_id:
            cand, how = by_id[pid], "player_id"
        if cand is None and pd.notna(r.get("preseason_rank")):
            cand = by_rank.get((r["team"], ",".join(r["positions"]), int(r["preseason_rank"])))
            how = "takım+pozisyon+sıra"
        if cand is None and r.get("name"):
            for index, key_fn, label in ((by_name, name_key, "ad+takım"),
                                         (by_init, initial_key, "baş harf+takım")):
                hits = [h for h in index.get(key_fn(r["name"], r["team"]), []) if h not in used]
                if len(hits) == 1:
                    cand, how = hits[0], label
                    break
        if cand is None or cand in used:
            log.append(f"EŞLEŞMEDİ: {r.get('name')!r} {r['team']} rank={r.get('preseason_rank')}")
            continue
        used.add(cand)
        out[i] = cand
        counts[how] += 1
    log.insert(0, "Eşleşme yöntemleri: " + ", ".join(f"{k}={v}" for k, v in counts.items()))
    unused = sorted(set(adp.index) - used)
    if unused:
        log.append(f"ADP dosyasında projeksiyon dosyasıyla eşleşmeyen {len(unused)} oyuncu: "
                   + ", ".join(adp.loc[unused[:8], "name"]))
    return out, log


def manifest(kind: str, file: Path, source: str, extracted: str, notes: str, season: str) -> dict:
    return {
        "file": file.relative_to(REPO_ROOT).as_posix(),
        "kind": kind,
        "source_name": source,
        "source_url": None,
        "retrieved_at": extracted[:10],
        "retrieved_by": "manual export (JSON) + scripts/import_yahoo_json.py",
        "license_status": "unknown",
        "license_notes": "Kullanım şartları doğrulanmadı — kullanıcı okuyup güncellemeli (README §5.1). " + notes,
        "season": season,
        "basis": "per_game",
        "is_synthetic": False,
    }


def convert(players_json: dict, adp_json: dict, adp_field: str = "adp_preseason"
            ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[str]]:
    """İki JSON'u ``(players, projections, adp)`` şema tablolarına çevirir.

    Projeksiyonlar sezon toplamıdır; ``gp``'ye bölünerek maç başına yazılır. Projeksiyonu
    eksik (``projection_complete = false``) oyuncunun projeksiyon satırı yazılmaz (eksik
    değer 0 ile doldurulmaz). ``default_rank = xrank`` (AutoDrafter botu için).
    """
    adp = pd.DataFrame(adp_json["players"])
    adp["player_id"] = adp["player_id"].astype(str)
    adp[["pos", "flags"]] = [parse_position_text(t) for t in adp["position_text"]]
    proj = pd.DataFrame(players_json["season_totals"])
    proj["player_id"] = proj["player_id"].where(proj["player_id"].notna(), None)

    idx, log = match(proj, adp)
    proj = proj[idx.notna()].reset_index(drop=True)
    a = adp.loc[idx[idx.notna()].astype(int)].reset_index(drop=True)
    yid = a["player_id"]

    players = pd.DataFrame({
        "player_id": yid.map(internal_id),
        "name": a["name"],
        "nba_team": a["team"],
        "yahoo_positions": a["pos"],
        "yahoo_player_id": yid,
        "nba_person_id": "",
        "aliases": [n if n and n != full else "" for n, full in zip(proj["name"], a["name"])],
        "is_synthetic": False,
    })

    complete = proj["projection_complete"].astype(bool) & proj["gp"].fillna(0).gt(0)
    pr = proj[complete]
    gp = pr["gp"].astype(float)
    projections = pd.DataFrame({"player_id": yid[complete].map(internal_id), "projected_gp": gp})
    projections["minutes"] = np.nan
    for src, dst in STAT_MAP.items():
        projections[dst] = (pr[src].astype(float) / gp).round(4)
    projections["projection_source"] = f"yahoo_{players_json.get('stats_mode', 'proj')}"
    projections["as_of"] = players_json["extracted_at"][:10]
    projections["is_synthetic"] = False
    projections["notes"] = [f"Yahoo durum: {f}" if f else "" for f in a.loc[complete, "flags"]]

    adp_out = pd.DataFrame({
        "player_id": yid.map(internal_id),
        "adp": a[adp_field],
        "adp_std": np.nan,
        "adp_min": np.nan,
        "adp_max": np.nan,
        "pct_drafted": a["drafted_pct"],
        "default_rank": a["xrank"],
        "adp_source": "yahoo_draft_analysis",
        "adp_window": adp_field.removeprefix("adp_"),
        "as_of": adp_json["extracted_at"][:10],
        "is_synthetic": False,
    })
    return players, projections.reset_index(drop=True), adp_out, log
