"""Sayfa 7 — Canlı draft (README §8.1).

Gerçek Yahoo draft'ı elle takip edilir: sıradaki takımın pick'i tek kutudan girilir, bot oynamaz.
Her pick arka plan analizine yayınlanır (§13.10): yan sekmedeki **Draft Analizi** sayfası tam mod
advisor'ı, rakip stratejisi tahminini (§6.4.5) ve punt önerisini beklemeden gösterir. Log her pick'te
``data/live/live_draft.json``'a yazılır (sayfa yenilense de kaybolmaz; git'e girmez).
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

from fdo.bots.mock import MockDraft
from fdo.config import REPO_ROOT
from fdo.draft.events import DraftError
from fdo.draft.io import export_json, import_log
from fdo.ui import common

common.page("Canlı Draft")
cfg = common.config()
ds = common.dataset()
u = common.universe()
lg = cfg.league
LIVE = Path(os.environ.get("FDO_LIVE_PATH", REPO_ROOT / "data" / "live" / "live_draft.json"))


def seat_names() -> dict[int, str]:
    names = st.session_state.setdefault("live_seat_names", {})
    return {s: names.get(s) or ("Siz" if s == lg.my_seat else f"Takım {s}") for s in range(1, lg.teams + 1)}


def save() -> None:
    LIVE.parent.mkdir(parents=True, exist_ok=True)
    meta = {"live": True, "seat_names": st.session_state.get("live_seat_names", {}),
            "dataset_hash": ds.content_hash, "config_hash": cfg.config_hash}
    LIVE.write_text(export_json(common.mock().log, meta), encoding="utf-8")


# ------------------------------------------------------------------- başlat / yükle
if not st.session_state.get("live"):
    st.markdown("Gerçek draft'ı burada elle takip edin: her pick'i sıradaki takım için girersiniz, botlar "
                "oynamaz. Sıra size gelince öneri kendiliğinden hesaplanır; rakiplerin seçimlerinden "
                "stratejileri (bot profili, olası punt) tahmin edilir ve simülasyonlar buna göre oynar.")
    c1, c2 = st.columns(2)
    if c1.button("Yeni canlı draft başlat", type="primary"):
        st.session_state.mock = MockDraft(ds, cfg, int(st.session_state.seed), u)
        st.session_state.live = True
        st.session_state.advisor_result = None
        save()
        st.rerun()
    if LIVE.exists():
        try:
            saved, meta = import_log(LIVE.read_text(encoding="utf-8"), cfg)
        except (DraftError, ValueError) as e:
            st.error(f"Kayıtlı canlı draft okunamadı: {e}")
        else:
            if c2.button(f"Kayıtlı canlı draft'a devam et ({len(saved)} pick)"):
                m = MockDraft(ds, cfg, int(st.session_state.seed), u)
                m.set_log(saved)
                st.session_state.mock = m
                st.session_state.live = True
                st.session_state.live_seat_names = {int(k): v for k, v in meta.get("seat_names", {}).items()}
                st.session_state.advisor_result = None
                st.rerun()
    st.stop()

m = common.mock()
log = m.log
names = seat_names()

with st.sidebar:
    st.header("Canlı draft")
    with st.expander("Takım adları"):
        current = st.session_state.setdefault("live_seat_names", {})
        edited = {}
        for s in range(1, lg.teams + 1):
            v = st.text_input(f"Seat {s}" + (" (siz)" if s == lg.my_seat else ""), current.get(s, ""),
                              key=f"seatname_{s}")
            if v:
                edited[s] = v
        if st.button("Adları kaydet"):
            st.session_state.live_seat_names = edited
            save()
            st.rerun()
    if st.button("Canlı moddan çık"):
        st.session_state.live = False
        st.rerun()
    st.caption(f"Log: `{LIVE.name}` (her pick'te kaydedilir)")

if log.is_complete:
    st.success("Draft tamamlandı. Takım Panosu'ndan kadroları inceleyebilirsiniz.")
else:
    k, seat = log.next_pick, log.next_seat
    mine = seat == lg.my_seat
    st.subheader(f"Pick {k} · Tur {(k - 1) // lg.teams + 1} · {names[seat]}" + (" — SİZİN SIRANIZ" if mine else ""))
    upcoming = [f"{n}: {names[log.seat_for(n)]}" + (" ★" if log.seat_for(n) == lg.my_seat else "")
                for n in range(k + 1, min(lg.total_picks, k + 6) + 1)]
    st.caption("Sıradakiler: " + " · ".join(upcoming))

    taken = log.taken
    pos = ds.positions()
    team = ds.players.set_index("player_id")["nba_team"]
    options = [str(u.ids[i]) for i in np.argsort(u.adp, kind="stable")
               if str(u.ids[i]) not in taken and m.is_allowed(str(u.ids[i]))]
    labels = {p: f"{common.name_of(p)} · {','.join(sorted(pos[p]))} · "
                 f"{team.get(p, '')} · ADP {u.adp[u.index[p]]:.0f}"
              for p in options}
    key = f"live_pick_{len(log)}"

    def enter() -> None:
        pid = st.session_state.get(key)
        if not pid:
            return
        try:
            m.pick(pid, "user" if m.log.next_seat == lg.my_seat else "manual")
            st.session_state.advisor_result = None
            save()
        except DraftError as e:
            st.session_state.live_error = str(e)

    c1, c2 = st.columns([5, 1])
    c1.selectbox(f"{names[seat]} kimi seçti?", options, index=None, key=key, format_func=labels.get,
                 placeholder="Oyuncu adı yazın, Enter ile kaydedilir…", on_change=enter)
    if c2.button("Undo", disabled=not len(log)):
        m.undo()
        st.session_state.advisor_result = None
        save()
        st.rerun()
    if err := st.session_state.pop("live_error", None):
        st.error(err)
    st.caption("Yahoo pozisyon kuralına aykırı oyuncular listede yok.")
common.advisor_line(log)


# ------------------------------------------------------------------- son pick'ler
if len(log):
    st.subheader("Son pick'ler")
    st.dataframe(pd.DataFrame([{"pick": p.overall_pick, "tur": p.round, "takım": names[p.seat],
                                "oyuncu": common.name_of(p.player_id), "kaynak": p.source}
                               for p in reversed(log.picks[-16:])]), hide_index=True)

common.publish_draft(seat_names=names)
