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
        "fill_sims_base": 20, "fill_sims_conditional": 20, "sims_per_pair_fast": 30, "sims_per_pair": 40,
        "m_pairs_to_rollout": 8, "deep_pairs": 3, "deep_rungs": [4, 4], "background_punt_sims": 4,
        "background_board_sims": 8}}})
    ds = make_synthetic(300, np.random.default_rng(1), cfg, as_of="2026-10-01", seed=1)
    mock = MockDraft(ds, cfg, 3, build_universe(ds, cfg))
    mock.play_until_user()
    return cfg, ds, mock


def compute(at):
    return next(b for b in at.button if b.label == "Yeniden hesapla")


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
    "pages/0_Home.py", "pages/1_League_and_Data.py", "pages/2_Projection_Explorer.py", "pages/3_Mock_Draft.py",
    "pages/5_Team_Dashboard.py",
])
def test_page_renders(env, page):
    at = run_page(env, page)
    assert any("SENTETİK VERİ" in e.value for e in at.error)


def test_draft_assistant_computes(env):
    at = run_page(env, "pages/4_Draft_Assistant.py", lambda at: compute(at).click())
    res = at.session_state["advisor_result"]
    assert res is not None and res.turn == (16, 17)


def test_draft_assistant_deep(env):
    def act(at):
        compute(at).click()
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



def test_live_draft_flow(env, monkeypatch, tmp_path):
    cfg, ds, _ = env
    monkeypatch.setenv("FDO_LIVE_PATH", str(tmp_path / "live.json"))
    at = AppTest.from_file(str(UI / "pages/7_Live_Draft.py"), default_timeout=300)
    at.session_state["config"] = cfg
    at.session_state["dataset"] = ds
    at.run()
    next(b for b in at.button if b.label == "Yeni canlı draft başlat").click()
    at.run()
    for _ in range(cfg.league.my_seat - 1):            # rakip pick'lerini elle gir (ilk seçenek = en düşük ADP)
        m = at.session_state["mock"]
        first = next(str(i) for i in m.universe.ids[np.argsort(m.universe.adp, kind="stable")]
                     if str(i) not in m.log.taken and m.is_allowed(str(i)))
        at.selectbox[0].set_value(first).run()
        assert not at.exception, [e.value for e in at.exception]
    m = at.session_state["mock"]
    assert len(m.log) == cfg.league.my_seat - 1 and all(p.source == "manual" for p in m.log.picks)
    assert (tmp_path / "live.json").exists()
    # sıra kullanıcıda: arka plan işçisi tam mod öneri, pano, rakip modeli ve punt planlarını hesaplar
    from fdo.ui import common

    w = common.hub()
    assert w.wait_idle(300)
    s = w.snapshot()
    assert s.job.live and s.job.log.picks == m.log.picks and not s.errors
    assert s.full is not None and s.full.params["opponent_model"] and s.punt is not None
    an = AppTest.from_file(str(UI / "pages/8_Draft_Analysis.py"), default_timeout=300)
    an.session_state["config"] = cfg
    an.session_state["dataset"] = ds
    an.run()
    assert not an.exception, [e.value for e in an.exception]
    cols = [df.value.columns for df in an.dataframe]
    assert any("Katkı" in c and "PTS" in c for c in cols)                  # oyuncu panosu
    assert any("en olası profil" in c for c in cols)                       # rakip stratejileri
    assert any("plan" in c for c in cols)                                  # punt önerisi
    assert any("Önerilen" in md.value for md in an.markdown)
    # kayıttan devam
    at2 = AppTest.from_file(str(UI / "pages/7_Live_Draft.py"), default_timeout=300)
    at2.session_state["config"] = cfg
    at2.session_state["dataset"] = ds
    at2.run()
    next(b for b in at2.button if b.label.startswith("Kayıtlı canlı draft'a devam et")).click()
    at2.run()
    assert len(at2.session_state["mock"].log) == cfg.league.my_seat - 1


def test_draft_assistant_with_strategy_weights(env):
    def act(at):
        at.slider(key="sw_FT_PCT").set_value(0.0)
        at.run()
        compute(at).click()
    at = run_page(env, "pages/4_Draft_Assistant.py", act)
    res = at.session_state["advisor_result"]
    assert res.params["category_weights"]["FT_PCT"] == 0.0
    assert all(p.ecw == p.ecw for p in res.pairs)                     # ağırlıksız ECW raporlandı


def test_auction_flow(env, monkeypatch, tmp_path):
    from fdo.calibration.bots import league_config

    cfg, ds, _ = env
    acfg = league_config(cfg, 14).with_overrides({"league": {"my_seat": 9, "draft_type": "auction"}})
    monkeypatch.setenv("FDO_AUCTION_PATH", str(tmp_path / "auction.json"))
    monkeypatch.setenv("FDO_AAV_PATH", str(tmp_path / "aav.csv"))
    at = AppTest.from_file(str(UI / "pages/9_Auction.py"), default_timeout=300)
    at.session_state["config"] = acfg
    at.session_state["dataset"] = ds
    at.run()
    next(b for b in at.button if b.label == "Yeni auction başlat").click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    log = at.session_state["auction_log"]
    first = at.selectbox(key="au_focus_0").options[0]
    pid = next(p for p in ds.players["player_id"] if first.startswith(str(ds.names()[p]) + " ·"))
    at.selectbox(key="au_focus_0").set_value(pid).run()
    assert not at.exception, [e.value for e in at.exception]
    assert any(m.label == "Teklif tavanın" for m in at.metric)
    next(b for b in at.button if b.label == "Satışı kaydet").click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    log = at.session_state["auction_log"]
    assert len(log.purchases) == 1 and log.purchases[0].seat == 9
    assert (tmp_path / "auction.json").exists()
    cols = [df.value.columns for df in at.dataframe]
    assert any("Tavan $" in c for c in cols)
