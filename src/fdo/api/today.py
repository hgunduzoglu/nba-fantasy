"""Bugün: her ligde kullanıcının takımı için tek ekranlık özet (bu haftanın planı, sezon, waiver, kadro uyarıları).

Hesap uzun (lig başına haftalık plan ve sezon simülasyonu); veri imzası başına bir kez arka planda yapılır ve veri
dizininde ``today.json``'a yazılır. Uç nokta önbelleği döner; imza değiştiyse yeniden hesaplamayı başlatır. Salt okunur
sunucuda ``FDO_PRECOMPUTE`` kapalı değilse arka plan iş parçacığı veri gönderiminden sonra kendiliğinden hesaplar.
Hesap mevcut uç noktaları uygulama içinden çağırır (aynı mantık iki yerde yazılmaz).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import threading
import time
from pathlib import Path

from fastapi import FastAPI

from fdo.api.jobs import Job
from fdo.api.serialize import clean
from fdo.api.state import AppState

FILE = "today.json"
PRECOMPUTE_ENV = "FDO_PRECOMPUTE"
#: Yahoo IL slotuna yalnız bu durumlar uygun; başka durumda IL'deki oyuncu kadro işlemlerini engeller.
IL_OK = frozenset({"O", "INJ", "IL", "IL+", "NA", "OUT", "D"})


def _load(directory: Path) -> dict | None:
    path = directory / FILE
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _save(directory: Path, payload: dict) -> None:
    tmp = directory / (FILE + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")
    tmp.replace(directory / FILE)


def alerts(roster: dict) -> list[dict]:
    """Kadro uyarıları: IL'de uygun olmayan oyuncu (kadro işlemlerini engeller), aktifte oynamayacak (O) oyuncu."""
    out = []
    for p in roster.get("players", []):
        status = (p.get("status") or "").upper()
        if p.get("il") and status not in IL_OK:
            out.append({"kind": "il_ineligible", "player": p["name"],
                        "text": f"{p['name']} IL slotunda ama durumu '{status or 'sağlıklı'}': Yahoo IL'de uygun olmayan "
                                f"oyuncu varken ekleme, bırakma ve takas yapılamaz."})
    return out


def summarize(call, lid: str, team: str) -> dict:
    """Bir lig için özet; ``call(method, path, body)`` uygulama içi istek (``TestClient``)."""
    row: dict = {"league_id": lid, "team_id": team}
    roster = call("GET", f"/api/leagues/{lid}/roster/{team}", None)
    row["team"] = roster.get("team")
    row["alerts"] = alerts(roster)
    week = call("POST", f"/api/leagues/{lid}/adddrop/week", {"team": team})
    if "base" in week:
        plan = week.get("plan") or {}
        after = plan.get("after") or {}
        row["week"] = {"week": week.get("week"), "opponent": week.get("opponent_name"),
                       "expected_wins": week["base"]["expected_wins"], "p_win": week["base"]["p5"],
                       "adds_left": week.get("adds_left"), "adds_limit": week.get("adds_limit"),
                       "plan_expected_wins": after.get("expected_wins"), "plan_p_win": after.get("p5"),
                       "moves": [{"day": m["day"], "add": m["add"]["name"], "drop": m["drop"]["name"]}
                                 for m in plan.get("moves", [])]}
    season = call("GET", f"/api/leagues/{lid}/season?team={team}&n=1000", None)
    me = next((r for r in season.get("table", []) if r["team_id"] == team), None)
    if me:
        row["season"] = {"record": me.get("record_now"), "p_playoff": me.get("p_playoff"),
                         "p_champion": me.get("p_champion"), "mean_seed": me.get("mean_seed"),
                         "playoff_size": season.get("playoff_size")}
    waiver = call("POST", f"/api/leagues/{lid}/waiver", {"team": team})
    top = (waiver.get("rows") or [None])[0]
    if top:
        row["waiver"] = {"add": top["add"]["name"], "drop": top["drop"]["name"], "delta_ecw": top.get("delta_ecw")}
    intel = call("GET", f"/api/leagues/{lid}/injury-intel?team={team}", None)
    if "players" in intel:
        row["injuries"] = {"players": len(intel["players"]), "stale": sum(1 for p in intel["players"] if p["stale"])}
    return row


def compute(app: FastAPI, state: AppState, log=lambda s: None) -> dict:
    from fastapi.testclient import TestClient
    client = TestClient(app)

    def call(method: str, path: str, body: dict | None) -> dict:
        r = client.request(method, path, json=body) if body is not None else client.request(method, path)
        return r.json() if r.status_code == 200 else {"error": r.status_code}

    sig = state.signature()
    data = state.data(True)
    leagues = []
    for lid, lg in data.leagues.items():
        log(f"Bugün: {lid}")
        try:
            leagues.append({"league": getattr(lg, "name", "") or lid, **summarize(call, lid, lg.default_team_id)})
        except Exception as e:  # noqa: BLE001 — bir lig hatası diğerlerini durdurmaz
            leagues.append({"league_id": lid, "team_id": lg.default_team_id, "error": str(e)})
    payload = {"signature": sig, "computed_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
               "as_of": str(data.as_of), "leagues": leagues}
    _save(state.data_dir, clean(payload))
    return {"leagues": len(leagues)}


def register(app: FastAPI, state: AppState, *, read_only: bool = False) -> Job:
    job = Job()

    def start() -> bool:
        return job.start(lambda log: compute(app, state, log))

    @app.get("/api/today")
    def today():
        cached = _load(state.data_dir)
        fresh = cached is not None and cached.get("signature") == state.signature()
        if not fresh and not job.running:
            start()
        return clean({"fresh": fresh, "job": job.status(), **(cached or {"leagues": []})})

    @app.post("/api/today/refresh")
    def today_refresh():
        start()
        return job.status()

    enabled = os.environ.get(PRECOMPUTE_ENV, "1" if read_only else "0").strip().lower() in ("1", "true", "yes", "on")
    if enabled:
        def loop():
            time.sleep(30)
            while True:
                try:
                    cached = _load(state.data_dir)
                    if (cached is None or cached.get("signature") != state.signature()) and not job.running:
                        start()
                except Exception:  # noqa: BLE001 — arka plan; bir sonraki turda yeniden denenir
                    pass
                time.sleep(600)
        threading.Thread(target=loop, daemon=True, name="today-precompute").start()
    return job
