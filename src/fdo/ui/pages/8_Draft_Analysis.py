"""Draft Analizi (README §13.10) — draft sayfasının yanında ayrı sekmede açık tutulur.

Mock ya da canlı draft sayfası her pick'te durumu arka plan işçisine yayınlar; bu sayfa işçinin
sonuçlarını gösterir ve yeni sonuç geldikçe kendini yeniler. Hiçbir hesabı beklemezsin: oyuncu panosu
saniyenin altında, sıra sana gelince önce hızlı sonra tam mod öneri, boş zamanlarda punt planları.
"""

from __future__ import annotations

import streamlit as st

from fdo.types import CATEGORY_LABELS
from fdo.ui import analysis, common

common.page("Draft Analizi", header=False)
cfg = common.config()
lg = cfg.league
w = common.hub()
snap = w.snapshot()
st.session_state.analysis_rev = snap.rev


@st.fragment(run_every=1.0)
def watch() -> None:
    s = w.snapshot()
    if s.rev != st.session_state.get("analysis_rev"):
        st.rerun()
    if s.busy and s.step:
        i, n = s.progress
        st.caption(f"⏳ {s.step}" + (f" · {i}/{n}" if n else "") + " — sonuçlar geldikçe sayfa yenilenir")
    elif s.job is not None:
        t = s.timings
        done = " · ".join(f"{k} {v:.0f} s" for k, v in t.items() if v >= 1)
        st.caption("✓ Güncel" + (f" ({done})" if done else ""))


def apply_weights(weights: dict[str, float] | None) -> None:
    for c in cfg.categories:
        st.session_state[f"an_w_{c}"] = float((weights or {}).get(c, 1.0))
    w.set_weights(weights)


with st.sidebar:
    st.subheader("Strateji ağırlıkları")
    st.caption("0 = punt, 1 = normal, 2 = iki kat önem. Advisor ve pano bu ağırlıklarla hesaplar.")
    current = w.weights or {}
    new = {}
    for c in cfg.categories:
        key = f"an_w_{c}"
        if key not in st.session_state:
            st.session_state[key] = float(current.get(c, 1.0))
        new[c] = st.slider(CATEGORY_LABELS[c], 0.0, 2.0, step=0.25, key=key)
    active = {c: v for c, v in new.items()} if any(abs(v - 1.0) > 1e-9 for v in new.values()) else None
    if active != (w.weights or None):
        w.set_weights(active)
    st.button("Sıfırla (dengeli)", disabled=active is None, on_click=apply_weights, args=(None,))

job = snap.job
if job is None:
    st.title("Draft Analizi")
    st.info("Bu sayfa draft'ı takip eder. Başka bir sekmede **Mock Draft** ya da **Canlı Draft** sayfasını açıp "
            "draft'ı başlat; her pick'te analiz burada kendiliğinden güncellenir.")
    watch()
    st.stop()

log = job.log
names = dict(job.seat_names)
b = snap.board
if log.is_complete:
    head = "Draft tamamlandı"
else:
    seat = log.next_seat
    who = "SENİN SIRAN" if seat == lg.my_seat else names.get(seat, f"Takım {seat}")
    head = f"Pick {log.next_pick} · Tur {(log.next_pick - 1) // lg.teams + 1} · {who}"
until = ""
if b is not None and not b.on_clock:
    until = f" · senin pick'in **{b.pick}** ({b.pick - log.next_pick} pick sonra)"
st.markdown(f"### {head}")
st.markdown(f"{job.source} · {lg.teams} takım · koltuk {lg.my_seat}{until}"
            + (" · strateji ağırlıkları açık" if job.weight_dict else ""))
watch()
for e in snap.errors:
    st.error(e)
if log.is_complete or b is None:
    st.stop()

analysis.team_strip(b)
left, right = st.columns([3.2, 1])
with left:
    analysis.player_board(snap)
with right:
    analysis.pairs_panel(snap)
    analysis.punt_panel(snap, on_apply=lambda punt: apply_weights(
        {c: (0.0 if c in punt else 1.0) for c in cfg.categories}))
    analysis.opponents_panel(snap)
