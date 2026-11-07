"""Uygulamadan Yahoo senkronizasyonu (README §13.20): arka plan iş parçacığında ``fdo.ingest.yahoo_sync.sync``
ve ardından CBS sakatlık raporu. Aynı anda tek senkronizasyon çalışır; durum ``GET /api/sync`` ile izlenir.
Dosyalar değişince ``AppState`` her şeyi yeniden kurar (``file_signature``)."""

from __future__ import annotations

import datetime as dt
import threading
from typing import Callable

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from fdo.api.state import AppState
from fdo.inseason.injuries import refresh_cbs
from fdo.inseason.live import load_live


class SyncIn(BaseModel):
    players: bool = True


class SyncJob:
    def __init__(self, state: AppState, make_fetch: Callable[[], Callable[[str], str]] | None = None):
        self.state = state
        self.make_fetch = make_fetch
        self.lock = threading.Lock()
        self.running = False
        self.log: list[str] = []
        self.started_at: str | None = None
        self.finished_at: str | None = None
        self.error: str | None = None
        self.result: dict | None = None

    def start(self, players: bool) -> bool:
        with self.lock:
            if self.running:
                return False
            self.running, self.log, self.error, self.result = True, [], None, None
            self.started_at, self.finished_at = _now(), None
        threading.Thread(target=self._run, args=(players,), daemon=True).start()
        return True

    def _run(self, players: bool) -> None:
        from fdo.ingest.yahoo_sync import Fetcher, NotLoggedIn, sync

        try:
            self.log.append("Chrome profilinden Yahoo oturumu alınıyor")
            fetch = self.make_fetch() if self.make_fetch else Fetcher()
            res = sync(self.state.data_dir, fetch, players=players, log=self.log.append)
            self.log.append(refresh_cbs(self.state.data_dir))
            self.result = {"as_of": res.as_of.isoformat(), "pages": res.pages, "written": res.written,
                           "notes": res.notes, "live": res.live}
        except NotLoggedIn as e:
            self.error = f"{e}"
        except Exception as e:  # noqa: BLE001 — kullanıcıya gösterilir; dosyalar yazılmadan durur
            self.error = f"Senkronizasyon durdu, dosyalara dokunulmadı: {e}"
        finally:
            self.finished_at = _now()
            self.running = False

    def status(self) -> dict:
        live = load_live(self.state.data_dir)
        last = max((lv.captured_at for lv in live.values()), default=None)
        return {"running": self.running, "log": self.log[-12:], "started_at": self.started_at,
                "finished_at": self.finished_at, "error": self.error, "result": self.result, "last_sync": last}


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def register(app: FastAPI, state: AppState, job: SyncJob | None = None) -> SyncJob:
    job = job or SyncJob(state)

    @app.get("/api/sync")
    def sync_status():
        return job.status()

    @app.post("/api/sync")
    def sync_start(body: SyncIn):
        if not job.start(body.players):
            raise HTTPException(409, "Senkronizasyon zaten sürüyor")
        return job.status()

    return job
