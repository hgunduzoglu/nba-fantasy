"""Sayfa 3 — Mock Draft (README §6.3, §6.4, §7 görünürlük, §8, §13.10).

Sade draft ekranı: botlar sıra size gelene kadar otomatik oynar, siz isimle arayıp seçersiniz. Analiz
(öneri, oyuncu panosu, punt) yan sekmedeki **Draft Analizi** sayfasında arka planda hesaplanır.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from fdo.bots.mock import MockDraft
from fdo.config import BOT_PROFILES
from fdo.draft.events import DraftError
from fdo.draft.io import export_csv, export_json, import_log
from fdo.realism.metrics import reach_class
from fdo.ui import common

common.page("Mock Draft")
cfg = common.config()
ds = common.dataset()
u = common.universe()
rp = cfg.model.realism
lg = cfg.league

with st.sidebar:
    st.header("Mock")
    new_seed = st.number_input("Mock seed", 0, 2**31 - 1, int(st.session_state.seed))
    bp = cfg.model.bots
    with st.expander(f"Bot karışımı ({lg.teams - 1} rakip)"):
        mix = {name: st.number_input(name, 0, lg.teams - 1, int(bp.mix.get(name, 0)), key=f"mix_{name}")
               for name in BOT_PROFILES}
        assignment = st.selectbox("Koltuk ataması", ["random_per_draft", "fixed"],
                                  index=0 if bp.seat_assignment == "random_per_draft" else 1)
        total = sum(mix.values())
        if total != lg.teams - 1:
            st.warning(f"Toplam {total}; {lg.teams - 1} olmalı.")
        st.caption("Değişiklik 'Yeni mock başlat' ile uygulanır. " + common.UNCALIBRATED)
    if st.button("Yeni mock başlat", type="primary", disabled=total != lg.teams - 1):
        st.session_state.live = False
        st.session_state.seed = int(new_seed)
        if mix != dict(bp.mix) or assignment != bp.seat_assignment:
            common.set_config(cfg.with_overrides({"model": {"bots": {"mix": mix, "seat_assignment": assignment}}}))
            cfg = common.config()
            u = common.universe()
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
live = bool(st.session_state.get("live"))
if live:
    st.warning("Canlı draft modu açık (Canlı Draft sayfası): bot oynatma kapalı.")


def act(fn, *args):
    try:
        fn(*args)
        st.session_state.advisor_result = None
    except DraftError as e:
        st.error(str(e))


auto = st.session_state.setdefault("mock_auto", True)
if auto and not live and not log.is_complete and log.next_seat != lg.my_seat:
    act(m.play_until_user)
    st.rerun()

status = "tamamlandı" if log.is_complete else f"pick **{log.next_pick}** · seat **{log.next_seat}**" +     (" — **SİZİN SIRANIZ**" if log.next_seat == lg.my_seat else "")
st.markdown(f"Draft durumu: {status}")
common.advisor_line(log)


def undo() -> None:
    """Otomatik modda son kendi pick'inizin öncesine döner (botlar yeniden oynamasın diye)."""
    mine = [p.overall_pick for p in log.picks if p.seat == lg.my_seat]
    if auto and not live and mine:
        m.truncate(mine[-1])
    else:
        m.undo()


if not log.is_complete:
    taken = log.taken
    avail = [str(u.ids[i]) for i in np.argsort(u.adp, kind="stable")
             if str(u.ids[i]) not in taken and m.is_allowed(str(u.ids[i]))]
    pos = ds.positions()
    labels = {p: f"{common.name_of(p)} · {','.join(sorted(pos[p]))} · ADP {u.adp[u.index[p]]:.1f}" for p in avail}
    key = f"mock_pick_{len(log)}"

    def enter() -> None:
        pid = st.session_state.get(key)
        if not pid:
            return
        src = "user" if m.log.next_seat == lg.my_seat else "manual"
        z, cls = reach_info(pid, m.log.next_pick)
        try:
            m.pick(pid, src)
            st.session_state.advisor_result = None
        except DraftError as e:
            st.session_state.mock_error = str(e)
            return
        if src == "user" and cls in ("warn", "bad"):
            st.session_state.mock_toast = f"Bu pick ADP'ye göre {z:.1f}σ erkendi."

    st.selectbox("Seçiminiz" if log.next_seat == lg.my_seat else f"Seat {log.next_seat} için manuel seçim",
                 avail, index=None, key=key, format_func=labels.get, on_change=enter,
                 placeholder="Oyuncu adı yazın, Enter ile seçilir…")
    if err := st.session_state.pop("mock_error", None):
        st.error(err)
    if msg := st.session_state.pop("mock_toast", None):
        st.toast(msg)

c = st.columns([1.3, 1, 1, 1, 0.8, 1])
c[0].toggle("Botlar otomatik oynasın", key="mock_auto", disabled=live,
            help="Açıkken siz seçtikten sonra botlar sıra size gelene kadar kendiliğinden oynar.")
if c[1].button("Sıradaki pick'i oynat", disabled=log.is_complete or live or auto):
    act(m.play_next)
    st.rerun()
if c[2].button("Sona kadar oynat", disabled=log.is_complete or live):
    act(m.play_to_end)
    st.rerun()
if c[3].button("Undo", disabled=not len(log), help="Otomatik modda son kendi pick'inizin öncesine döner."):
    act(undo)
    st.rerun()
back_to = c[4].number_input("Pick k'ye dön", 1, max(1, len(log)), max(1, len(log)), label_visibility="collapsed")
if c[5].button(f"Pick {back_to}'e dön", disabled=not len(log)):
    act(m.truncate, int(back_to))
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
    with st.expander("Seçim logu"):
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
        for r in [r for r in rows if r["kaynak"] == "user"]:
            if r["z_reach"] > rp.reach_z_warn:
                st.info(f"Pick {r['pick']} ({r['oyuncu']}): ADP'ye göre {r['z_reach']:.1f}σ erken.")

# ------------------------------------------------------------------- export / import
with st.expander("Export / import"):
    meta = {"seed": m.seed, "dataset_hash": ds.content_hash, "config_hash": cfg.config_hash,
            "sources": ds.sources(), "profiles": m.profiles}
    c = st.columns(3)
    c[0].download_button("CSV indir", export_csv(log, meta), file_name=f"draft_log_seed{m.seed}.csv",
                         mime="text/csv")
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

if not live:
    common.publish_draft()
