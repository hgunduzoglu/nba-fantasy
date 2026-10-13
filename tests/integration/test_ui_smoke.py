"""Streamlit sayfalarının tarayıcısız duman testi (``streamlit.testing.v1.AppTest``)."""

from pathlib import Path

import numpy as np
import pytest

from fdo.bots.mock import MockDraft
from fdo.bots.universe import build_universe
from fdo.ingest import make_synthetic

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
UI = Path(__file__).resolve().parents[2] / "src" / "fdo" / "ui"


@pytest.fixture(scope="module")
def env(config):
    cfg = config.with_overrides({"model": {"advisor": {
        "fill_sims_base": 20, "fill_sims_conditional": 20, "sims_per_pair_fast": 30,
        "m_pairs_to_rollout": 8, "deep_pairs": 3, "deep_rungs": [4, 4]}}})
    ds = make_synthetic(300, np.random.default_rng(1), cfg, as_of="2026-10-01", seed=1)
    mock = MockDraft(ds, cfg, 3, build_universe(ds, cfg))
    mock.play_until_user()
    return cfg, ds, mock


def run_page(env, page, action=None):
    cfg, ds, mock = env
    at = AppTest.from_file(str(UI / page), default_timeout=300)
    at.session_state["config"] = cfg
    at.session_state["dataset"] = ds
    at.session_state["mock"] = mock
    at.run()
    if action:
        action(at)
        at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


@pytest.mark.parametrize("page", [
    "app.py", "pages/1_League_and_Data.py", "pages/2_Projection_Explorer.py", "pages/3_Mock_Draft.py",
    "pages/5_Team_Dashboard.py",
])
def test_page_renders(env, page):
    at = run_page(env, page)
    assert any("SENTETİK VERİ" in e.value for e in at.error)


def test_draft_assistant_computes(env):
    at = run_page(env, "pages/4_Draft_Assistant.py", lambda at: at.button[0].click())
    res = at.session_state["advisor_result"]
    assert res is not None and res.turn == (16, 17)


def test_draft_assistant_deep(env):
    def act(at):
        at.button[0].click()
        at.run()
        next(b for b in at.button if b.label == "Tam ufuk hesapla").click()
    at = run_page(env, "pages/4_Draft_Assistant.py", act)
    deep = [df.value for df in at.dataframe if "E[W] tam ufuk" in df.value.columns]
    assert deep and len(deep[0]) == 3


def test_realism_batch(env):
    def act(at):
        at.number_input[0].set_value(20)
        at.button[0].click()
    at = run_page(env, "pages/6_Realism_Report.py", act)
    assert at.session_state["realism"] is not None


@pytest.mark.parametrize("page", ["pages/1_League_and_Data.py", "pages/5_Team_Dashboard.py"])
def test_pages_with_schedule(env, page):
    import datetime as dt

    from fdo.schedule import synthetic_schedule

    cfg, ds, mock = env
    sched = synthetic_schedule(["SYN", *[f"T{i:02d}" for i in range(29)]], dt.date(2026, 10, 20),
                               np.random.default_rng(0))
    at = run_page((cfg, ds.with_schedule(sched), mock), page)
    assert at.dataframe


def test_yahoo_sync_panel_merges_picks(env, monkeypatch, tmp_path):
    import copy
    import time

    from fdo.ui import yahoo_sync
    from fdo.yahoo_api.client import DraftResult
    from fdo.yahoo_api.oauth import Token

    cfg, ds, mock = env
    mock = copy.deepcopy(mock)
    taken = set(mock.log.taken)
    free = [p for p in ds.draft_ids if p not in taken and mock.is_allowed(p)][:2]
    picks = [p.player_id for p in mock.log.picks] + free
    results = [DraftResult(k, (k - 1) // 16 + 1, f"t.{mock.log.seat_for(k)}", f"466.p.{pid.removeprefix('y_')}")
               for k, pid in enumerate(picks, start=1)]

    class FakeClient:
        def draft_results(self, league_key):
            return {"name": "Test", "draft_status": "drafting"}, results

    class FakeStore:
        def load(self):
            return Token("a", "r", time.time() + 3600)

    monkeypatch.setenv("YAHOO_CLIENT_ID", "x")
    monkeypatch.setenv("YAHOO_CLIENT_SECRET", "y")
    monkeypatch.setattr(yahoo_sync, "TokenStore", FakeStore)
    monkeypatch.setattr(yahoo_sync, "_client", lambda: FakeClient())
    monkeypatch.setattr("fdo.yahoo_api.sync.player_id_from_key", lambda k: k.split(".p.")[-1])

    def act(at):
        at.text_input[0].set_value("466.l.1")
        at.run()
        next(b for b in at.button if b.label == "Şimdi çek").click()
    at = run_page((cfg, ds, mock), "pages/4_Draft_Assistant.py", act)
    assert len(at.session_state["mock"].log) == len(picks)
