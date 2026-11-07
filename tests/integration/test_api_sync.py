"""Uygulamadan Yahoo senkronizasyonu: arka plan işi, durum ve tek seferde tek iş (sahte site, ağ yok)."""
import json
import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from fdo.api import sync as sync_api  # noqa: E402
from fdo.api.app import create_app  # noqa: E402
from unit.test_yahoo_sync import _site, real_dir  # noqa: E402,F401


def _wait(c, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        s = c.get("/api/sync").json()
        if not s["running"]:
            return s
        time.sleep(0.05)
    raise AssertionError("senkronizasyon bitmedi")


def test_sync_runs_in_background_and_reports(real_dir, monkeypatch):  # noqa: F811
    monkeypatch.setattr(sync_api, "refresh_cbs", lambda d: "CBS atlandı")
    app = create_app(data_dir=real_dir, frontend_dir=real_dir / "yok")
    fetch, _ = _site()
    app.state.sync.make_fetch = lambda: fetch
    c = TestClient(app)
    assert c.get("/api/sync").json()["last_sync"] is None
    assert c.post("/api/sync", json={"players": False}).status_code == 200
    s = _wait(c)
    assert s["error"] is None and s["result"]["written"][0] == "rosters.json" and "CBS atlandı" in s["log"]
    assert s["last_sync"] is not None
    assert json.loads((real_dir / "yahoo_live.json").read_text(encoding="utf-8"))["leagues"]["500"]["week"] == 3


def test_sync_error_leaves_files_and_second_start_is_refused(real_dir, monkeypatch):  # noqa: F811
    monkeypatch.setattr(sync_api, "refresh_cbs", lambda d: "")
    app = create_app(data_dir=real_dir, frontend_dir=real_dir / "yok")
    gate = {"open": False}

    def slow(path):
        while not gate["open"]:
            time.sleep(0.01)
        return "<html>bakım</html>"
    app.state.sync.make_fetch = lambda: slow
    c = TestClient(app)
    assert c.post("/api/sync", json={}).status_code == 200
    assert c.post("/api/sync", json={}).status_code == 409                     # zaten sürüyor
    gate["open"] = True
    s = _wait(c)
    assert "dokunulmadı" in s["error"] and s["result"] is None
    assert not (real_dir / "yahoo_live.json").exists()
