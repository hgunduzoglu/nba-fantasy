"""Referans vakalar: API'ye sabit istekler gönderir, cevapları ve beklenti kontrollerini kayda geçirir.

Amaç davranışı sürümler arasında karşılaştırmak (aynı veriyle eski ve yeni kod ne öneriyor) ve kullanıcının hatalı
bulduğu önerileri tekrar üretilebilir tutmak. Vaka dosyası kişisel lig kimlikleri içerdiği için yerelde durur
(``data/real/cases.json``, git dışı). Biçim (JSON listesi)::

    {"id": "banchero-to-6", "path": "/api/leagues/<lig>/trade/complete",
     "body": {"team_a": "7", "team_b": "6", "give_a": ["6691"], "give_b": []},
     "note": "neden önemli",
     "expect": [{"absent": {"give_a": ["6691"], "give_b": ["5185"]}, "reason": "rakip için gerekçesiz"}]}

Beklentiler cevabın ``suggestions`` listesine bakar: ``absent`` verilen/alınan oyuncu kümeleri tam bu olan paketin
listede olmamasını, ``present`` olmasını ister. Kontrol sonucu bir beklentidir, model başarısının kanıtı değildir.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from pathlib import Path

import numpy as np

from fdo.config import REPO_ROOT

#: Kayıtta tutulan öneri alanları (varsa).
FIELDS = ("tier", "mode", "own_delta", "other_delta", "own_win", "other_win", "fairness", "perceived_view",
          "perceived_balance", "score")


def _ids(side) -> frozenset[str]:
    return frozenset(str(x["id"]) if isinstance(x, dict) else str(x) for x in side or ())


def package(row: dict) -> tuple[frozenset[str], frozenset[str]]:
    """Öneri satırının paketi: (verilen, alınan) oyuncu kimlikleri."""
    return _ids(row.get("give_a")), _ids(row.get("give_b"))


def check(expect: dict, response: dict) -> bool:
    found = {package(r) for r in response.get("suggestions") or ()}
    for kind in ("absent", "present"):
        if kind in expect:
            target = (_ids(expect[kind].get("give_a")), _ids(expect[kind].get("give_b")))
            return (target in found) == (kind == "present")
    raise ValueError(f"Bilinmeyen beklenti: {expect}")


def summarize(response: dict, top: int = 15) -> dict:
    """Cevabın karşılaştırmaya yeten özeti: ilk ``top`` öneri (kimlik, ad, metrikler) ve sayaçlar."""
    rows = []
    for r in (response.get("suggestions") or [])[:top]:
        rows.append({"give_a": sorted(_ids(r.get("give_a"))), "give_b": sorted(_ids(r.get("give_b"))),
                     "names": [x.get("name") for x in (*r.get("give_a", ()), *r.get("give_b", ()))
                               if isinstance(x, dict)],
                     **{k: r[k] for k in FIELDS if k in r}})
    meta = {k: v for k, v in response.items() if k != "suggestions" and not isinstance(v, (dict, list))}
    return {"n_suggestions": len(response.get("suggestions") or []), "suggestions": rows, **meta}


def season_trades(path: str, body: dict, rows: list[dict]) -> list[dict]:
    """Tamamlama (``/trade/complete``) ya da öneri (``/trade/suggest``) cevabındaki paketleri ``/trade/season/many``
    istek gövdesine çevirir (aynı takımlar ve stratejilerle)."""
    ids = lambda side: [str(x["id"]) if isinstance(x, dict) else str(x) for x in side or ()]
    out = []
    for r in rows:
        if path.endswith("/trade/complete"):
            t = {"team_a": body["team_a"], "team_b": body["team_b"], "strategy_a": body.get("strategy_a"),
                 "strategy_b": body.get("strategy_b")}
        else:
            t = {"team_a": body["team"], "team_b": r["team_b"], "strategy_a": body.get("strategy"),
                 "strategy_b": {"name": r.get("other_strategy"), "weights": r.get("other_weights")}}
        out.append({**t, "give_a": ids(r.get("give_a")), "give_b": ids(r.get("give_b")),
                    "auto_balance": body.get("auto_balance", True), "injuries": body.get("injuries", True)})
    return out


def _ranks(x) -> np.ndarray:
    return np.argsort(np.argsort(np.asarray(x, dtype=float), kind="stable"), kind="stable").astype(float)


def shadow(deltas: list[float | None]) -> dict:
    """Model sırası (listedeki sıra) ile sezon simülasyonu sırasının uyumu (gölge karşılaştırma): Spearman sıra
    korelasyonu ve modelin ilk önerisinin sezon sıralamasındaki yeri. Sezon farkı hesaplanamayan satırlar dışarıda."""
    pts = [(i, d) for i, d in enumerate(deltas) if d is not None]
    if len(pts) < 2:
        return {"n": len(pts), "spearman": None, "model_top_season_rank": None}
    pos, d = zip(*pts)
    a, b = _ranks([-p for p in pos]), _ranks(d)
    rho = float(np.corrcoef(a, b)[0, 1]) if a.std() > 0 and b.std() > 0 else None
    order = sorted(range(len(d)), key=lambda k: -d[k])
    return {"n": len(pts), "spearman": rho, "model_top_season_rank": order.index(0) + 1 if pos[0] == 0 else None}


def run(client, cases: list[dict], *, season_sims: int = 0) -> list[dict]:
    """``client``: FastAPI ``TestClient`` (ya da ``post``/``get`` sağlayan nesne). ``season_sims`` > 0: öneri listesi
    sezon simülasyonuyla da değerlendirilir (her öneriye ``season``, vakaya ``shadow`` eklenir); sıra değişmez."""
    out = []
    for case in cases:
        method = case.get("method", "POST").upper()
        res = client.post(case["path"], json=case.get("body", {})) if method == "POST" else client.get(case["path"])
        entry = {"id": case["id"], "path": case["path"], "body": case.get("body", {}), "status": res.status_code,
                 "note": case.get("note", "")}
        if res.status_code != 200:
            entry["error"] = res.text[:500]
            entry["checks"] = [{**e, "ok": None} for e in case.get("expect", [])]
        else:
            body = res.json()
            entry["result"] = summarize(body)
            entry["checks"] = [{**e, "ok": check(e, body)} for e in case.get("expect", [])]
            rows = entry["result"]["suggestions"]
            if season_sims and rows and method == "POST":
                _season(client, case, body, rows, entry, season_sims)
        out.append(entry)
    return out


def _season(client, case: dict, body: dict, rows: list[dict], entry: dict, n_sims: int) -> None:
    lid = case["path"].split("/leagues/")[1].split("/")[0]
    trades = season_trades(case["path"], case.get("body", {}), (body.get("suggestions") or [])[:len(rows)])
    res = client.post(f"/api/leagues/{lid}/trade/season/many", json={
        "trades": trades, "n_sims": n_sims, "injuries": case.get("body", {}).get("injuries", True)})
    if res.status_code != 200:
        entry["season_error"] = res.text[:300]
        return
    by = {t["index"]: t for t in res.json()["trades"]}
    for i, r in enumerate(rows):
        t = by.get(i, {})
        r["season"] = ({k: {f: v[f] for f in ("delta", "se", "clear")} for k, v in t["teams"]["a"].items()
                        if isinstance(v, dict)} if "teams" in t else {"error": t.get("error")})
    entry["shadow"] = {k: shadow([r["season"].get(k, {}).get("delta") for r in rows]) for k in ("playoff", "champion")}


def code_version(root: Path = REPO_ROOT) -> dict:
    """Çalışan kodun git commit'i ve çalışma ağacında commit'lenmemiş değişiklik olup olmadığı."""
    def git(*args):
        try:
            return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=10).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""
    return {"commit": git("rev-parse", "--short", "HEAD") or None,
            "dirty": bool(git("status", "--porcelain", "--untracked-files=no"))}


def record(results: list[dict], *, data_signature: str, as_of: str) -> dict:
    return {"created_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "code": code_version(),
            "data_signature": data_signature, "data_as_of": as_of, "cases": results}


def compare(old: dict, new: dict) -> list[str]:
    """İki kaydın vaka vaka farkı: beklenti sonucu değişimi, listeye giren ve çıkan paketler."""
    lines = [f"eski: kod {old['code'].get('commit')} veri {old['data_as_of']} · "
             f"yeni: kod {new['code'].get('commit')} veri {new['data_as_of']}"]
    if old["data_signature"] != new["data_signature"]:
        lines.append("Uyarı: veri farklı; fark yalnız koddan gelmiyor olabilir.")
    before = {c["id"]: c for c in old["cases"]}
    for c in new["cases"]:
        o = before.get(c["id"])
        if o is None:
            lines.append(f"[{c['id']}] yeni vaka")
            continue
        for e_old, e_new in zip(o.get("checks", []), c.get("checks", [])):
            if e_old.get("ok") != e_new.get("ok"):
                lines.append(f"[{c['id']}] beklenti {e_new.get('reason', '')}: {e_old.get('ok')} → {e_new.get('ok')}")
        pk = lambda case: {(tuple(r["give_a"]), tuple(r["give_b"])) for r in case.get("result", {}).get("suggestions", [])}
        for p in sorted(pk(c) - pk(o)):
            lines.append(f"[{c['id']}] + {p[0]} → {p[1]}")
        for p in sorted(pk(o) - pk(c)):
            lines.append(f"[{c['id']}] − {p[0]} → {p[1]}")
    return lines


def load_cases(path: str | Path) -> list[dict]:
    cases = json.loads(Path(path).read_text(encoding="utf-8"))
    ids = [c["id"] for c in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("Vaka kimlikleri benzersiz olmalı")
    return cases
