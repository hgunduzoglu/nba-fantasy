"""Arka plan işleri: aynı anda tek çalışma, günlük satırları ve sonuç (``GET`` ile izlenir)."""

from __future__ import annotations

import datetime as dt
import threading
from typing import Callable


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


class Job:
    """``start(work)``: ``work(log) → sonuç sözlüğü`` iş parçacığında çalışır; hata metni ``error``'a yazılır."""

    def __init__(self):
        self.lock = threading.Lock()
        self.running = False
        self.log: list[str] = []
        self.started_at: str | None = None
        self.finished_at: str | None = None
        self.error: str | None = None
        self.result: dict | None = None

    def start(self, work: Callable[[Callable[[str], None]], dict]) -> bool:
        with self.lock:
            if self.running:
                return False
            self.running, self.log, self.error, self.result = True, [], None, None
            self.started_at, self.finished_at = now_iso(), None
        threading.Thread(target=self._run, args=(work,), daemon=True).start()
        return True

    def _run(self, work) -> None:
        try:
            self.result = work(self.log.append)
        except Exception as e:  # noqa: BLE001 — kullanıcıya gösterilir
            self.error = self.describe(e)
        finally:
            self.finished_at = now_iso()
            self.running = False

    def describe(self, e: Exception) -> str:
        return str(e)

    def status(self) -> dict:
        return {"running": self.running, "log": self.log[-12:], "started_at": self.started_at,
                "finished_at": self.finished_at, "error": self.error, "result": self.result}
