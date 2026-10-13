"""Sayfa 4 — Draft Assistant (README §6.7, §8). V1'in ana ekranı.

Öneriler yalnızca ECW (E[W]) ile sıralanır. İstatistiksel olarak ayırt edilemeyen
çiftler aynı kademede gösterilir (sahte kesinlik yok).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from fdo.advisor.deep import deep_recommend
from fdo.advisor.pairs import AdvisorError
from fdo.advisor.scenarios import run_scenarios
from fdo.types import CATEGORY_LABELS
from fdo.ui import common

common.page("4 · Draft Assistant")
cfg = common.config()
ds = common.dataset()
lg = cfg.league
adv = cfg.model.advisor
m = common.mock()
log = m.log

if log.is_complete:
    st.info("Draft tamamlandı. Yeni bir mock başlatın (Sayfa 3).")
    st.stop()
if log.next_seat != lg.my_seat:
    st.info(f"Sıra sizde değil (pick {log.next_pick}, seat {log.next_seat}).")
    if st.session_state.get("live"):
        st.caption("Canlı draft modu: rakip pick'lerini Sayfa 7'den girin.")
    elif st.button("Kullanıcıya kadar oynat", type="primary"):
        m.play_until_user()
        st.session_state.advisor_result = None
        st.rerun()
    st.stop()

timer = cfg.unverified.pick_timer_seconds
if timer is None:
    st.warning("`pick_timer_seconds` bilinmiyor: tam mod Yahoo pick süresini aşabilir; hızlı mod varsayılandır.")
else:
    st.caption(f"Bilgi: gerçek Yahoo draft'ında pick süresi {timer} s. Bu mock'ta süre yok; botlar hesap biter "
               "bitmez seçer, siz istediğiniz kadar düşünebilirsiniz.")

u = common.universe()
avail = [str(u.ids[i]) for i in np.argsort(u.adp, kind="stable")
         if str(u.ids[i]) not in log.taken and not np.isnan(common.advisor_context().vecs[i]).any()]

with st.form("advisor"):
    c = st.columns([1, 1, 3])
    mode = c[0].radio("Mod", ["fast", "full"], format_func=lambda x: {"fast": f"Hızlı (S={adv.sims_per_pair_fast})",
                                                                     "full": f"Tam (S={adv.sims_per_pair})"}[x])
    cond = c[1].checkbox("Koşullu doldurma", value=True,
                         help=f"Mevcut state'ten {adv.fill_sims_conditional} hızlı simülasyonla doldurma tablosu")
    pins = c[2].multiselect("Pinlenen oyuncular (aday kümesine eklenir)", avail, format_func=common.name_of)
    pp = st.multiselect("Pinlenen çift (2 oyuncu; rollout'a zorla girer)", avail, format_func=common.name_of,
                        max_selections=2)
    opp = st.checkbox("Rakip stratejisi tahmini", value=bool(st.session_state.get("live")),
                      help="Rakiplerin şimdiye kadarki seçimlerinden bot profili sonrası (§6.4.5); "
                           "simülasyonlarda karışım yerine kullanılır.")
    unc = st.checkbox("Sakatlık/rol belirsizliği (V2)", value=False,
                      help="Simülasyon başına oyuncu maç oranı (Beta) ve rol çarpanı (log-normal); "
                           "rookie'lerde daha geniş. Beklenti aynı kalır, P10–P90 riski yansıtır.")
    go = st.form_submit_button("Öneri hesapla", type="primary")

if go:
    common.advisor_context()
    st.button("Hesabı iptal et", help="Herhangi bir etkileşim (ya da sağ üstteki Stop) çalışan hesabı keser.")
    with st.status("Advisor çalışıyor…", expanded=True) as status:
        bar = st.progress(0.0)

        def progress(step, i, n):
            bar.progress(i / n if n else 0.0, text=f"{step} {i}/{n}" if n else step)

        try:
            res = common.advise(log, mode=mode, pins=pins, pin_pairs=[tuple(pp)] if len(pp) == 2 else (),
                                conditional=cond, uncertainty=unc, opponents=opp, progress=progress)
            st.session_state.advisor_result = res
            status.update(label=f"Tamamlandı ({res.elapsed:.1f} s)", state="complete")
        except AdvisorError as e:
            status.update(label=str(e), state="error")

res = st.session_state.advisor_result
if res is None or res.params["pick"] != log.next_pick:
    st.stop()

# ------------------------------------------------------------------- kart başlığı
nt = "/".join(map(str, res.next_turn)) if res.next_turn else "yok (son turn)"
st.markdown(
    f"**Turn {'/'.join(map(str, res.turn))} → sonraki turn {nt}** · mod {res.params['mode']} · "
    f"S = {res.params['S']} · seed {res.params['seed']} · {res.elapsed:.1f} s · "
    f"doldurma: {res.params['fill']} ({res.params['fill_sims']} sim) · "
    f"{res.params['pairs_rolled_out']}/{res.params['pairs_considered']} çift rollout"
    + (" · sakatlık/rol belirsizliği açık" if res.params.get("uncertainty") else "")
    + (" · rakip stratejisi tahmini açık" if res.params.get("opponent_model") else "")
)
st.caption("Kaynaklar: " + common.format_sources(res.sources))
if timer and res.elapsed > timer:
    st.caption(f"Not: bu hesap {res.elapsed:.0f} s sürdü; gerçek draft'taki {timer} s pick süresini aşar.")
st.markdown(" ".join([common.UNCALIBRATED] + [f"`{x}`" for x in res.uncalibrated]))
st.caption(f"Kullanıcı kadrosu: {res.real_players}/{res.roster_size} gerçek oyuncu (gerisi doldurma profili). "
           + ("Düşük gerçek oran → belirsizlik yüksek." if res.real_players < res.roster_size / 2 else ""))

# ------------------------------------------------------------------- çift tablosu
st.subheader("Aday " + ("çiftler" if len(res.turn) == 2 else "oyuncular"))
pt = res.pair_table()
show = pd.DataFrame({
    "kademe": pt["tier"],
    "seçim": pt["pair"],
    "E[W]": [f"≈{v:.3f}" for v in pt["E[W]"]],
    "SE": pt["SE"].round(4),
    "P10–P90": [f"{a:.2f} – {b:.2f}" for a, b in zip(pt["P10"], pt["P90"])],
    "regret": [f"{r:.3f} ± {s:.3f}" for r, s in zip(pt["regret"], pt["regret_SE"])],
    "Q (statik)": pt["Q_static"].round(3),
    "pin": pt["pinned"],
})
st.dataframe(show, hide_index=True, height=min(600, 36 * (len(show) + 1)))
st.caption("E[W]: sonraki turn sonrası (π + doldurma) 15 rakibe karşı beklenen kategori galibiyeti. "
           f"Kademe: en iyiye farkı < {adv.tier_se_mult}·SE_fark (CRN eşleşmeli) olan seçimler aynı kademede.")

with st.expander(f"Derin analiz — tam ufuk rollout (V2, ilk {adv.deep_pairs} seçim)"):
    st.caption("Her seçim için draft sonuna kadar simüle edilir: sonraki pick'lerinizde π her simülasyonda "
               "kalan oyuncular arasından ECW'yi en çok artıranı seçer; E[W] 13'er gerçek oyuncuyla hesaplanır "
               f"(doldurma yok). Kademeli yarılama: basamak başına {list(adv.deep_rungs)} yeni simülasyon, "
               "her basamakta en iyi yarı devam eder.")
    deep_key = f"deep:{common.state_key(log)}:{res.params['seed']}:{res.params['mode']}"
    if st.button("Tam ufuk hesapla"):
        bar = st.progress(0.0)
        st.session_state[deep_key] = deep_recommend(
            common.advisor_context(), log, res,
            opponent_probs=common.opponent_model(log).seat_probs() if res.params.get("opponent_model") else None,
            progress=lambda i, n: bar.progress(i / n, text=f"rollout {i}/{n}"))
    deep = st.session_state.get(deep_key)
    if deep is not None:
        dt_ = deep.table()
        st.dataframe(dt_.style.format({"E[W] tam ufuk": "{:.3f}", "SE": "{:.4f}", "E[W] V1": "{:.3f}"}),
                     hide_index=True)
        st.caption(f"{deep.elapsed:.1f} s. 'basamak' = ulaşılan son basamak; erken elenen seçimlerin E[W]'si "
                   "daha az simülasyona dayanır. Tam ufuk E[W], V1 E[W]'den yüksek çıkar: sonraki pick'ler "
                   "nötr doldurma yerine kadronuza göre seçilir.")

labels = [p.label for p in res.pairs]
if mine := st.selectbox("Bu turn'de uygula", ["—", *labels]):
    if mine != "—" and st.button(f"Seç: {mine}", type="primary"):
        for pid in res.by_label(mine).players:
            m.pick(pid, "user")
        st.session_state.advisor_result = None
        st.rerun()

with st.expander("Adaylar ve bekleme maliyeti"):
    cd = res.candidates.copy()
    cd["p_surv_next"] = [common.fmt_prob(p) for p in cd["p_surv_next"]]
    st.dataframe(cd.round(3), hide_index=True)
    st.caption("wait_cost = ΔECW · (1 − P_surv(sonraki turn)) — yüksekse 'şimdi al'. Yalnızca açıklama içindir; "
               "karar E[W] ile verilir. P_surv buradaki ön elemede kullanıcı pick'leri boş geçilerek hesaplanır.")


# ------------------------------------------------------------------- havuz
def pool_view(pr) -> pd.DataFrame:
    pool = pr.outcome.pool
    if pool.empty:
        return pool
    h = res.next_turn[0]
    return pd.DataFrame({
        "kademe": pool["tier"], "oyuncu": pool["name"], "poz": pool["positions"],
        "ΔECW": pool["delta_ecw"].round(3),
        f"P_surv({h})": [common.fmt_prob(p, s) for p, s in zip(pool["p_surv"], pool["se"])],
        "adp_eff": pool["adp_eff"].round(1), "adp_status": pool["adp_status"],
        "gidiş P10/P50/P90": [f"{common.fmt_pick(a, h)} / {common.fmt_pick(b, h)} / {common.fmt_pick(c, h)}"
                              for a, b, c in zip(pool["go_p10"], pool["go_p50"], pool["go_p90"])],
    })


def category_profile(pr) -> pd.DataFrame:
    cp = pr.outcome.cat_p
    return pd.DataFrame({
        "kategori": [CATEGORY_LABELS[c] for c in res.categories],
        "ortalama P(win)": cp.mean(axis=0), "P10": np.quantile(cp, 0.1, axis=0),
        "P90": np.quantile(cp, 0.9, axis=0),
    })


tab_pool, tab_cmp, tab_scen = st.tabs(["Sonraki turn havuzu", "Karşılaştırma", "Alternatif senaryolar (M6)"])

with tab_pool:
    sel = st.selectbox("Seçim", labels, key="pool_sel")
    pr = res.by_label(sel)
    if res.next_turn is None:
        st.info("Son turn: sonraki turn havuzu yok.")
    else:
        st.markdown(f"**{res.next_turn[0]}/{res.next_turn[-1]} havuzu** — `{sel}` alınırsa "
                    f"{res.next_turn[0]}. pick'te en az bir simülasyonda uygun olan, ΔECW'ye göre ilk "
                    f"{adv.pool_table_size} oyuncu " + common.UNCALIBRATED)
        st.dataframe(pool_view(pr), hide_index=True, height=420)
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Kademe görünümü**")
            tv = pr.outcome.pool_tiers.rename(columns={
                "tier": "kademe", "players": "oyuncu", "delta_ecw_max": "ΔECW max",
                "expected_available": f"beklenen uygun ({res.next_turn[0]})",
                "p_at_least_1": "P(≥1 kalır)", "p_at_least_2": "P(≥2 kalır)"})
            st.dataframe(tv.round(3), hide_index=True)
        with c2:
            st.markdown("**Sonraki seçim dağılımı (π, miyopik)**")
            nc = pr.outcome.next_choices
            if not nc.empty:
                st.dataframe(nc[["players", "probability"]].assign(
                    probability=lambda d: d["probability"].map(lambda p: common.fmt_prob(p))),
                    hide_index=True)
    st.markdown("**Kategori profili** (sonraki turn + doldurma dahil, 15 rakip ortalaması)")
    prof = category_profile(pr)
    st.bar_chart(prof.set_index("kategori")["ortalama P(win)"], color="#2a78d6")
    st.dataframe(prof.style.format({c: "{:.2f}" for c in ["ortalama P(win)", "P10", "P90"]})
                 .map(common.prob_bg, subset=["ortalama P(win)"]), hide_index=True)
    p5 = pr.outcome.p_at_least_5
    dep = (":green-badge[kategori korelasyonu kalibre]" if cfg.model.variance.category_corr
           else common.INDEPENDENCE)
    st.markdown(f"P(≥5 kategori) ≈ {p5.mean():.2f} " + dep +
                " — yalnızca ek gösterge, optimizasyonda kullanılmaz.")

with tab_cmp:
    if len(labels) < 2:
        st.info("Karşılaştırma için en az iki seçim gerekir.")
    else:
        c1, c2 = st.columns(2)
        a = c1.selectbox("A", labels, index=0, key="cmp_a")
        b = c2.selectbox("B", labels, index=1, key="cmp_b")
        pa, pb = res.by_label(a), res.by_label(b)
        d = pa.outcome.W - pb.outcome.W
        se = d.std(ddof=1) / np.sqrt(len(d))
        st.markdown(f"**E[W] farkı (A − B): {d.mean():+.3f} ± {se:.3f}** (CRN eşleşmeli SE) — "
                    + ("istatistiksel olarak ayırt edilemez" if abs(d.mean()) < adv.tier_se_mult * se else
                       ("A daha iyi" if d.mean() > 0 else "B daha iyi")))
        ca, cb = category_profile(pa), category_profile(pb)
        diff = pd.DataFrame({"kategori": ca["kategori"], "A": ca["ortalama P(win)"], "B": cb["ortalama P(win)"]})
        diff["A − B"] = diff["A"] - diff["B"]
        st.dataframe(diff.style.format({"A": "{:.2f}", "B": "{:.2f}", "A − B": "{:+.3f}"})
                     .map(lambda v: common.diverging_bg(v, 0.1), subset=["A − B"]), hide_index=True)
        if res.next_turn:
            h = res.next_turn[0]
            sa = pa.outcome.pool.set_index("player_id")[["name", "p_surv"]]
            sb = pb.outcome.pool.set_index("player_id")[["p_surv"]]
            j = sa.join(sb, how="outer", lsuffix="_A", rsuffix="_B")
            j["name"] = [common.name_of(p) for p in j.index]
            j["fark"] = j["p_surv_A"].fillna(0) - j["p_surv_B"].fillna(0)
            st.markdown(f"**P_surv({h}) farkları** (iki havuzun birleşimi)")
            st.dataframe(j.sort_values("fark", key=np.abs, ascending=False)
                         .style.format({"p_surv_A": "{:.2f}", "p_surv_B": "{:.2f}", "fark": "{:+.2f}"}, na_rep="—")
                         .map(lambda v: common.diverging_bg(v, 0.5), subset=["fark"]), height=400)

with tab_scen:
    st.markdown("Tam draft rollout'u: her turn'de miyopik π, botlar oynar. Final kadrolar kaybedilen kategori "
                "imzasına göre gruplanır. **Ulaşılabilirlik** göstergesidir, optimal plan iddiası yoktur. "
                + common.UNCALIBRATED)
    n_s = st.number_input("Simülasyon", 20, 1000, adv.scenario_full_sims, 20)
    if st.button("Senaryoları hesapla"):
        with st.spinner("Tam rollout…"):
            st.session_state.scenario_result = (log.next_pick, run_scenarios(common.advisor_context(), log,
                                                                            n_sims=int(n_s)))
    sc = st.session_state.scenario_result
    if sc and sc[0] == log.next_pick:
        r = sc[1]
        st.caption(f"{r.n_sims} sim · seed {r.seed} · {r.elapsed:.1f} s")
        tbl = r.table(cfg.categories)
        cat_cols = [CATEGORY_LABELS[c] for c in cfg.categories]
        st.dataframe(tbl.style.format({**{c: "{:.2f}" for c in cat_cols}, "frekans": "{:.0%}",
                                       "ortalama ECW": "{:.2f}"}).map(common.prob_bg, subset=cat_cols),
                     hide_index=True)
        for a in r.archetypes:
            with st.expander(f"{a.label} — tipik kadro"):
                st.write(", ".join(a.typical_roster))
