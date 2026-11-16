"""Sakatlık analizi uç noktaları (``fdo.inseason.injury_intel``): takımın sakat ya da belirsiz oyuncuları ve arka
planda Claude'un web aramasıyla yenileme.

Ücretli çağrı: yerelde ``.env``'deki anahtarla açıktır; salt okunur sunucuda takas raporuyla aynı erişim koduyla
(``FDO_REPORT_CODE``, ``X-Report-Code`` başlığı) çalışır. Günlük harcama ``FDO_INJURY_DAILY_CAP`` dolarla sınırlı
(varsayılan 3); dolunca yenileme reddedilir.
"""

from __future__ import annotations

import datetime as dt
import os

from fastapi import FastAPI, Header, HTTPException

from fdo.api.app import REPORT_CODE_ENV
from fdo.api.jobs import Job
from fdo.api.schemas import InjuryIntelIn
from fdo.api.serialize import clean
from fdo.api.state import AppState
from fdo.inseason import injury_intel as intel
from fdo.inseason.news import load_env_key

DAILY_CAP_ENV = "FDO_INJURY_DAILY_CAP"
DEFAULT_CAP = 3.0


def daily_cap() -> float:
    try:
        return max(0.0, float(os.environ.get(DAILY_CAP_ENV, DEFAULT_CAP)))
    except ValueError:
        return DEFAULT_CAP


def spent_today(store: dict, today: dt.date | None = None) -> float:
    day = (today or dt.datetime.now(dt.timezone.utc).date()).isoformat()
    return intel.cost([u for u in store["usage"] if str(u.get("at", "")).startswith(day)])


def register(app: FastAPI, state: AppState, *, read_only: bool = False) -> Job:
    job = Job()

    def access(code: str | None) -> None:
        if not load_env_key():
            raise HTTPException(503, "ANTHROPIC_API_KEY yok: sakatlık analizi kapalı.")
        if read_only:
            expected = os.environ.get(REPORT_CODE_ENV, "").strip()
            if not expected:
                raise HTTPException(403, "Bu sunucuda sakatlık analizi kapalı.")
            if (code or "").strip() != expected:
                raise HTTPException(401, "Sakatlık analizi için erişim kodu gerekli.")

    def engine(lid: str, team: str, injuries: bool = True):
        try:
            eng = state.engine(lid, injuries)
        except KeyError as e:
            raise HTTPException(404, str(e)) from e
        if team not in eng.league.rosters:
            raise HTTPException(404, f"Takım yok: {team}")
        return eng

    @app.get("/api/leagues/{lid}/injury-intel")
    def injury_intel(lid: str, team: str, injuries: bool = True):
        eng = engine(lid, team, injuries)
        store = intel.load_store(state.data_dir)
        now = dt.datetime.now(dt.timezone.utc)
        rows = []
        for r in intel.candidates(eng, [team]):
            item = store["items"].get(r["id"]) or {}
            rows.append({**r, "analysis": item.get("analysis"), "analyzed_at": item.get("analyzed_at"),
                         "model": item.get("model"), "stale": intel.stale(store, r, now)})
        code = bool(os.environ.get(REPORT_CODE_ENV, "").strip())
        return clean({"players": rows, "job": job.status(), "model": intel.model_name(),
                      "available": load_env_key() and (not read_only or code), "needs_code": read_only and code,
                      "spent_today": round(spent_today(store), 4), "daily_cap": daily_cap()})

    @app.post("/api/leagues/{lid}/injury-intel/refresh")
    def injury_intel_refresh(lid: str, body: InjuryIntelIn,
                             x_report_code: str | None = Header(default=None, alias="X-Report-Code")):
        access(x_report_code)
        eng = engine(lid, body.team, body.injuries)
        store = intel.load_store(state.data_dir)
        if spent_today(store) >= daily_cap():
            raise HTTPException(429, f"Günlük sakatlık analizi bütçesi (${daily_cap():.2f}) doldu.")
        rows = intel.candidates(eng, [body.team])
        if not job.start(lambda log: intel.refresh(state.data_dir, rows, max_players=body.max_players,
                                                   force=body.force, log=log)):
            raise HTTPException(409, "Sakatlık analizi zaten sürüyor")
        return job.status()

    @app.get("/api/injury-intel/status")
    def injury_intel_status():
        return clean(job.status())

    return job
