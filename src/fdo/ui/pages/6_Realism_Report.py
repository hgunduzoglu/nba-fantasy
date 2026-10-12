"""Sayfa 6 — Realism Report (README §7, §8).

Bot parametreleri yalnızca bu ölçümler üzerinden ayarlanır. Hedefler varsayımdır;
gerçek draft log'u olmadan botların gerçek insanlar gibi seçtiği iddia edilmez.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from fdo.realism.metrics import compute_metrics, pick_table, reach_class, run_mock_batch
from fdo.realism.report import build_report
from fdo.ui import common

common.page("6 · Realism Report")
cfg = common.config()
ds = common.dataset()
u = common.universe()
rp = cfg.model.realism
lg = cfg.league

st.markdown(common.UNCALIBRATED + " Hedef değerler gerçek veriyle doğrulanmamıştır.")

# ------------------------------------------------------------------- son mock
st.header("Son mock")
m = st.session_state.mock
if m is None or not len(m.log):
    st.info("Henüz mock yok (Sayfa 3).")
else:
    rows = []
    for p in m.log.picks:
        i = u.index[p.player_id]
        z = (u.adp[i] - p.overall_pick) / u.sigma[i]
        rows.append({"pick": p.overall_pick, "tur": p.round, "seat": p.seat, "oyuncu": common.name_of(p.player_id),
                     "kaynak": p.source, "pick − A": p.overall_pick - u.adp[i], "z_reach": z,
                     "sınıf": reach_class(z, rp)})
    last = pd.DataFrame(rows)
    by_round = last.groupby("tur").agg(medyan=("pick − A", "median"),
                                       uygunsuz_reach=("sınıf", lambda s: float(np.mean(s == "bad"))),
                                       slide=("sınıf", lambda s: float(np.mean(s == "slide"))))
    st.dataframe(by_round.style.format({"medyan": "{:.1f}", "uygunsuz_reach": "{:.0%}", "slide": "{:.0%}"}))
    bad = last[last["sınıf"].isin(["bad", "warn"])].sort_values("z_reach", ascending=False)
    if len(bad):
        st.markdown("**Reach'ler (son mock)**")
        st.dataframe(bad.round(2), hide_index=True)

# ------------------------------------------------------------------- batch
st.header("Mock batch")
c = st.columns(3)
n = c[0].number_input("Mock sayısı", 20, 2000, 200, 20)
seed = c[1].number_input("Seed", 0, 2**31 - 1, 1)
ext = c[2].file_uploader("Gerçek draft log (opsiyonel, KS testi)", type=["csv"])
if st.button("Batch çalıştır", type="primary"):
    bar = st.progress(0.0)
    batch = run_mock_batch(u, cfg, int(n), int(seed), progress=lambda i, k: bar.progress(i / k, f"{i}/{k} mock"))
    external = pd.read_csv(ext) if ext is not None else None
    met = compute_metrics(batch, u, cfg, external)
    st.session_state.realism = (met, pick_table(batch, u, lg.teams))

if st.session_state.realism is None:
    st.stop()
met, pt = st.session_state.realism
st.caption(f"{met.n_mocks} mock · seed {met.seed}")

st.subheader("Tur bazında `pick − A`")
st.line_chart(met.rounds[["p10", "median", "p90"]].rename(columns={"p10": "P10", "median": "medyan", "p90": "P90"}),
              color=["#2a78d6", "#eb6834", "#1baf7a"], x_label="tur", y_label="pick − A")
st.dataframe(met.rounds.style.format({"median": "{:.1f}", "p10": "{:.1f}", "p90": "{:.1f}",
                                      "bad_reach_rate": "{:.1%}", "warn_reach_rate": "{:.1%}",
                                      "slide_rate": "{:.1%}"}))
st.caption(f"Hedef (varsayım): medyan ≈ 0; erken turlarda uygunsuz reach (z > {rp.reach_z_bad}) < %2 ama sıfır değil.")

st.subheader("`z_reach` dağılımı")
edges = np.arange(-6, 6.5, 0.5)
hist, _ = np.histogram(np.clip(pt["z_reach"], -6, 6), bins=edges)
st.bar_chart(pd.Series(hist, index=[f"{a:+.1f}" for a in edges[:-1]], name="pick"), color="#2a78d6",
             x_label="z_reach (alt sınır)", y_label="pick")

c1, c2, c3 = st.columns(3)
c1.metric(f"ADP≈{rp.extreme_adp_center:.0f} ilk {lg.teams} pick'te", f"{met.extreme['rate_per_player_mock']:.4%}",
          help=f"{met.extreme['hits']} olay; hedef ≈ 0 ama > 0")
c2.metric("Kendall τ (ilk 32)", f"{met.diversity['kendall_tau_mean']:.3f}", help="hedef varsayımı < 0.98")
c3.metric("Tamamlanamayan kadro", met.incomplete)
st.caption(f"Jaccard (ilk {rp.diversity_top_n}): {met.diversity['jaccard_mean']:.3f} · "
           f"bot tutarlılığı (kalıcı sıradaki 1. oyuncuyu seçme oranı): {met.consistency['top1_agreement']:.2f}")

st.subheader("Pozisyon dağılımı (tur bazında)")
st.dataframe(met.positions.style.format("{:.0%}"))
st.subheader("Profil bazında")
st.dataframe(met.profiles.style.format({"median_pick_minus_A": "{:.1f}", "bad_reach_rate": "{:.1%}"}))
st.subheader("En uç reach'ler")
wr = met.worst_reaches.copy()
wr.insert(4, "oyuncu", [common.name_of(p) for p in wr["player_id"]])
st.dataframe(wr.round(2), hide_index=True)
if met.external:
    st.subheader("Dış karşılaştırma (KS)")
    st.json(met.external)

st.download_button("Markdown raporu indir",
                   build_report(met, cfg, data_label=f"hash {ds.content_hash}", is_synthetic=ds.is_synthetic),
                   file_name=f"realism_n{met.n_mocks}_seed{met.seed}.md", mime="text/markdown")
