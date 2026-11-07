"""Uygulamadan Yahoo senkronizasyonu (README §13.20): arka plan iş parçacığında ``fdo.ingest.yahoo_sync.sync``,
ardından CBS sakatlık raporu, bu sezonun NBA maç kayıtları (rol değişimi, §13.24) ve haberler (§13.25). Aynı anda tek
senkronizasyon çalışır; durum ``GET /api/sync`` ile izlenir. Dosyalar değişince ``AppState`` her şeyi yeniden kurar
(``file_signature``)."""

from __future__ import annotations

from typing import Callable

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from fdo.api.jobs import Job
from fdo.api.state import AppState
from fdo.inseason.injuries import refresh_cbs
from fdo.inseason.live import load_live


class SyncIn(BaseModel):
    players: bool = True


class SyncJob(Job):
    def __init__(self, state: AppState, make_fetch: Callable[[], Callable[[str], str]] | None = None,
                 after: list[Callable[[Callable[[str], None]], str]] | None = None):
        """``after``: Yahoo'dan sonra sırayla çalışan adımlar (her biri günlüğe tek satır özet döner)."""
        super().__init__()
        self.state = state
        self.make_fetch = make_fetch
        self.after = after if after is not None else []

    def begin(self, players: bool) -> bool:
        return self.start(lambda log: self._work(players, log))

    def _work(self, players: bool, log) -> dict:
        from fdo.ingest.yahoo_sync import Fetcher, sync

        log("Chrome profilinden Yahoo oturumu alınıyor")
        fetch = self.make_fetch() if self.make_fetch else Fetcher()
        res = sync(self.state.data_dir, fetch, players=players, log=log)
        log(refresh_cbs(self.state.data_dir))
        for step in self.after:
            log(step(log))
        return {"as_of": res.as_of.isoformat(), "pages": res.pages, "written": res.written, "notes": res.notes,
                "live": res.live}

    def describe(self, e: Exception) -> str:
        from fdo.ingest.yahoo_sync import NotLoggedIn

        return str(e) if isinstance(e, NotLoggedIn) else f"Senkronizasyon durdu, dosyalara dokunulmadı: {e}"

    def status(self) -> dict:
        live = load_live(self.state.data_dir)
        return {**super().status(), "last_sync": max((lv.captured_at for lv in live.values()), default=None)}


def register(app: FastAPI, state: AppState, job: SyncJob | None = None) -> SyncJob:
    job = job or SyncJob(state)

    @app.get("/api/sync")
    def sync_status():
        return job.status()

    @app.post("/api/sync")
    def sync_start(body: SyncIn):
        if not job.begin(body.players):
            raise HTTPException(409, "Senkronizasyon zaten sürüyor")
        return job.status()

    return job
