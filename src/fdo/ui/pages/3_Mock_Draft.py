"""Sayfa 3 — Mock Draft (README §6.3, §6.4, §7 görünürlük, §8)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from fdo.bots.mock import MockDraft
from fdo.draft.events import DraftError
from fdo.draft.io import export_csv, export_json, import_log
from fdo.realism.metrics import reach_class
from fdo.ui import common

common.page("3 · Mock Draft")
cfg = common.config()
ds = common.dataset()
u = common.universe()
rp = cfg.model.realism
lg = cfg.league

with st.sidebar:
    st.header("Mock")
    new_seed = st.number_input("Mock seed", 0, 2**31 - 1, int(st.session_state.seed))
    if st.button("Yeni mock başlat", type="primary"):
        st.session_state.seed = int(new_seed)
        st.session_state.mock = MockDraft(ds, cfg, int(new_seed), u)
        st.session_state.advisor_result = None
        st.rerun()

m = common.mock()
log = m.log

with st.sidebar:
    st.caption(f"Bot karışımı ({cfg.model.bots.seat_assignment}) — koltuk {lg.my_seat} sizsiniz; "
               f"'oynat' işlemlerinde {cfg.model.bots.user_auto_profile} olarak seçer.")
    st.dataframe(pd.DataFrame({"seat": range(1, lg.teams + 1), "profil": m.profiles}),
                 hide_index=True, height=300)
    st.markdown(common.UNCALIBRATED + " bot parametreleri gerçek draft verisiyle ayarlanmadı.")


def reach_info(pid: str, k: int) -> tuple[float, str]:
    i = u.index[pid]
    z = (u.adp[i] - k) / u.sigma[i]
    return float(z), reach_class(z, rp)


# ------------------------------------------------------------------- kontroller
status = "tamamlandı" if log.is_complete else f"sıradaki pick **{log.next_pick}** · seat **{log.next_seat}**" + \
    (" (siz)" if log.next_seat == lg.my_seat else "")
st.markdown(f"Draft durumu: {status}")


def act(fn, *args):
    try:
        fn(*args)
        st.session_state.advisor_result = None
    except DraftError as e:
        st.error(str(e))


c = st.columns(6)
if c[0].button("Sıradaki pick'i oynat", disabled=log.is_complete):
    act(m.play_next)
    st.rerun()
if c[1].button("Kullanıcıya kadar oynat", disabled=log.is_complete):
    act(m.play_until_user)
    st.rerun()
if c[2].button("Sona kadar oynat", disabled=log.is_complete):
    act(m.play_to_end)
    st.rerun()
if c[3].button("Undo", disabled=not len(log)):
    act(m.undo)
    st.rerun()
back_to = c[4].number_input("Pick k'ye dön", 1, max(1, len(log)), max(1, len(log)), label_visibility="collapsed")
if c[5].button(f"Pick {back_to}'e dön", disabled=not len(log)):
    act(m.truncate, int(back_to))
    st.rerun()

if not log.is_complete:
    taken = log.taken
    avail = [str(u.ids[i]) for i in np.argsort(u.adp, kind="stable") if str(u.ids[i]) not in taken]
    labels = {p: f"{common.name_of(p)} · {','.join(sorted(ds.positions()[p]))} · ADP {u.adp[u.index[p]]:.1f} "
                 f"({u.status[u.index[p]]})" for p in avail}
    cc = st.columns([4, 1])
    choice = cc[0].selectbox("Manuel seçim (arama)", avail, format_func=labels.get)
    if cc[1].button("Seç", type="primary"):
        src = "user" if log.next_seat == lg.my_seat else "manual"
        z, cls = reach_info(choice, log.next_pick)
        act(m.pick, choice, src)
        if src == "user" and cls in ("warn", "bad"):
            st.toast(f"Bu pick ADP'ye göre {z:.1f}σ erken.")
        st.rerun()

# ------------------------------------------------------------------- board
st.subheader(f"Board ({lg.teams}×{lg.rounds})")
st.caption("Renk: ▲▲ kırmızı = uygunsuz reach (z > 2.5σ) · ▲ sarı = 1.5–2.5σ erken · ▼ mavi = slide (2.5σ geç). "
           "z = (A − pick)/σ.")
board = pd.DataFrame("", index=pd.Index(range(1, lg.rounds + 1), name="tur"),
                     columns=[f"S{s}" + ("★" if s == lg.my_seat else "") for s in range(1, lg.teams + 1)])
cls_df = pd.DataFrame("neutral", index=board.index, columns=board.columns)
for p in log.picks:
    z, cls = reach_info(p.player_id, p.overall_pick)
    col = board.columns[p.seat - 1]
    badge = common.REACH_STYLE[cls][1]
    board.loc[p.round, col] = f"{p.overall_pick}. {common.name_of(p.player_id)} {badge}".strip()
    cls_df.loc[p.round, col] = cls
st.dataframe(common.style_reach(board, cls_df), height=35 * (lg.rounds + 1) + 5)

# ------------------------------------------------------------------- log
if len(log):
    st.subheader("Seçim logu")
    rows = []
    for p in reversed(log.picks):
        z, cls = reach_info(p.player_id, p.overall_pick)
        i = u.index[p.player_id]
        tag = {"bad": f"reach {z:.1f}σ", "warn": f"erken {z:.1f}σ", "slide": f"slide {-z:.1f}σ"}.get(cls, "")
        rows.append({"pick": p.overall_pick, "tur": p.round, "seat": p.seat,
                     "oyuncu": common.name_of(p.player_id), "kaynak": p.source,
                     "A": round(float(u.adp[i]), 1), "σ": round(float(u.sigma[i]), 1),
                     "z_reach": round(z, 2), "rozet": tag, "adp_status": u.status[i]})
    st.dataframe(pd.DataFrame(rows), hide_index=True, height=300)
    mine = [r for r in rows if r["kaynak"] == "user"]
    for r in mine:
        if r["z_reach"] > rp.reach_z_warn:
            st.info(f"Pick {r['pick']} ({r['oyuncu']}): ADP'ye göre {r['z_reach']:.1f}σ erken.")

# ------------------------------------------------------------------- export / import
st.subheader("Export / import")
meta = {"seed": m.seed, "dataset_hash": ds.content_hash, "config_hash": cfg.config_hash,
        "sources": ds.sources(), "profiles": m.profiles}
c = st.columns(3)
c[0].download_button("CSV indir", export_csv(log, meta), file_name=f"draft_log_seed{m.seed}.csv", mime="text/csv")
c[1].download_button("JSON indir", export_json(log, meta), file_name=f"draft_log_seed{m.seed}.json",
                     mime="application/json")
up = c[2].file_uploader("Draft log yükle (CSV/JSON)", type=["csv", "json"])
if up is not None and st.button("Log'u uygula (replay)"):
    try:
        new_log, imeta = import_log(up.getvalue().decode("utf-8"), cfg)
        missing = [p.player_id for p in new_log.picks if p.player_id not in u.index]
        if missing:
            raise DraftError(f"Draft havuzunda olmayan oyuncu(lar): {missing[:5]}")
        m.set_log(new_log)
        st.session_state.advisor_result = None
        st.success(f"{len(new_log)} pick yüklendi (seed {imeta.get('seed', '?')}).")
        st.rerun()
    except (DraftError, ValueError) as e:
        st.error(f"Import hatası: {e}")
