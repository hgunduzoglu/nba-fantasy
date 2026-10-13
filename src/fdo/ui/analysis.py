"""Draft Analizi görünümü (README §13.10): arka plan işçisinin sonuçlarını hashtagbasketball tarzında gösterir.

* Oyuncu panosu: maç başı istatistikler z kademesine göre (Elite … Poor) yeşilden kırmızıya; "Takımına
  katkı" görünümünde aynı hücreler oyuncunun kadrona kategori bazında etkisi (ΔP, puan). Advisor'ın
  önerdiği oyuncular üstte.
* Yan panel: önerilen çiftler (ör. 16/17), punt önerisi, rakip stratejileri.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import streamlit as st

from fdo.advisor.background import Snapshot
from fdo.advisor.board import CategoryBoard, perf_level, scarcity
from fdo.types import CATEGORY_LABELS
from fdo.ui import common

#: Kademe → (arka plan, yazı rengi). Yeşil = iyi, kırmızı = kötü (TO dahil: z zaten ters çevrili).
PERF_STYLE = {
    "Elite": ("rgba(0, 135, 45, 0.92)", "#ffffff"),
    "Great": ("rgba(46, 170, 80, 0.62)", None),
    "Good": ("rgba(100, 195, 115, 0.30)", None),
    "Avg": ("", None),
    "Below": ("rgba(225, 85, 85, 0.30)", None),
    "Poor": ("rgba(205, 30, 30, 0.88)", "#ffffff"),
}
POSITION_FILTERS = ("Hepsi", "PG", "SG", "G", "SF", "PF", "F", "C")
GONE = 0.10          # bekleme modunda bu olasılığın altında kalacaklar listenin sonuna


def perf_css(level: str) -> str:
    bg, fg = PERF_STYLE.get(level, ("", None))
    if not bg:
        return ""
    return f"background-color: {bg}" + (f"; color: {fg}" if fg else "")


def gain_css(v, vmax: float) -> str:
    """Diverjan yeşil (katkı) / kırmızı (zarar); 0 renksiz."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return ""
    if math.isnan(x) or vmax <= 0 or abs(x) < 1e-12:
        return ""
    a = min(abs(x) / vmax, 1.0)
    rgb = "0, 150, 60" if x > 0 else "215, 40, 40"
    return f"background-color: rgba({rgb}, {0.12 + 0.75 * a:.2f})" + ("; color: #ffffff" if a > 0.7 else "")


def avail_css(p) -> str:
    try:
        x = float(p)
    except (TypeError, ValueError):
        return ""
    if math.isnan(x):
        return ""
    if x < 0.3:
        return "background-color: rgba(215, 40, 40, 0.25)"
    if x > 0.8:
        return "background-color: rgba(0, 150, 60, 0.18)"
    return ""


def effect_text(row: pd.Series, cats, threshold: float = 0.005) -> str:
    """Oyuncunun kadrona en çok katkı yaptığı iki ve en çok zarar verdiği kategori: ``↑3PM ↑PTS ↓FG%``."""
    d = {c: row[f"d_{c}"] for c in cats}
    up = [c for c, v in sorted(d.items(), key=lambda kv: -kv[1]) if v > threshold][:2]
    down = [c for c, v in sorted(d.items(), key=lambda kv: kv[1]) if v < -threshold][:1]
    return " ".join([*(f"↑{CATEGORY_LABELS[c]}" for c in up), *(f"↓{CATEGORY_LABELS[c]}" for c in down)])


def recommendation_rank(snap: Snapshot) -> dict[str, int]:
    """Oyuncu → içinde geçtiği en iyi önerinin sırası (1 tabanlı)."""
    out: dict[str, int] = {}
    if snap.advice is not None:
        for j, pr in enumerate(snap.advice.pairs):
            for pid in pr.players:
                out.setdefault(pid, j + 1)
    return out


def ordered(t: pd.DataFrame, rank: dict[str, int], on_clock: bool) -> pd.DataFrame:
    """Öneri sırası: advisor'ın önerdikleri (sırasıyla), sonra katkıya göre; beklerken gidecek olanlar sonda."""
    r = t["player_id"].map(rank).fillna(10_000)
    gone = (t["p_avail"].fillna(1.0) < GONE) & (not on_clock)
    return t.assign(_r=r, _g=gone).sort_values(["_g", "_r", "score"], ascending=[True, True, False],
                                               kind="stable").drop(columns=["_r", "_g"])


def team_strip(b: CategoryBoard) -> None:
    cats = [CATEGORY_LABELS[c] for c in b.categories]
    df = pd.DataFrame([b.team_p], columns=cats, index=["Takımın P(kazan)"])
    st.dataframe(df.style.format("{:.0%}").map(lambda v: gain_css(v - 0.5, 0.15)), width="stretch")
    st.caption("Mevcut kadron + kalan pick'lerin için ortalama oyuncu varsayımıyla, her kategoride rakiplere "
               "karşı ortalama kazanma olasılığı. Kırmızı = zayıf, yeşil = güçlü.")


def player_board(snap: Snapshot, *, key: str = "an") -> None:
    b = snap.board
    rank = recommendation_rank(snap)
    c = st.columns([3, 2, 2, 2])
    view = c[0].radio("Görünüm", ["İstatistik", "Takımına katkı"], horizontal=True, key=f"{key}_view",
                      help="İstatistik: maç başı projeksiyon, renk = oyuncunun o kategorideki z kademesi. "
                           "Takımına katkı: oyuncu bu pick'te alınırsa o kategoride kazanma olasılığın kaç "
                           "puan değişir (aynı pick'teki ortalama oyuncuya göre).")
    pos = c[1].selectbox("Pozisyon", POSITION_FILTERS, key=f"{key}_pos")
    sort = c[2].selectbox("Sırala", ["Öneri", "Takımına katkı", "Z toplam", "ADP"], key=f"{key}_sort")
    n_show = c[3].selectbox("Göster", [25, 50, 100, 200], index=1, key=f"{key}_n")

    t = b.table[b.table["allowed"]]
    if pos != "Hepsi":
        t = t[t["positions"].str.split(",").map(lambda ps: pos in ps)]
    if sort == "Öneri":
        t = ordered(t, rank, b.on_clock)
    else:
        col = {"Takımına katkı": "score", "Z toplam": "z_total", "ADP": "adp"}[sort]
        t = t.sort_values(col, ascending=sort == "ADP", kind="stable")
    t = t.head(int(n_show)).reset_index(drop=True)

    cats = list(b.categories)
    labels = [CATEGORY_LABELS[c] for c in cats]
    avail_label = f"Kalır ({b.avail_pick})" if b.avail_pick else "Kalır"
    shown = pd.DataFrame({
        "Öneri": [(f"★{rank[p]}" if rank[p] == 1 else f"{rank[p]}") if p in rank else "" for p in t["player_id"]],
        "Oyuncu": [n + (f" ({s})" if s else "") for n, s in zip(t["name"], t["injury"])],
        "Poz": t["positions"], "Takım": t["nba_team"], "ADP": t["adp"], "GP": t["gp"],
    })
    if view == "İstatistik":
        for c_, lab in zip(cats, labels):
            if c_ in ("FG_PCT", "FT_PCT"):
                mk, at = ("fgm", "fga") if c_ == "FG_PCT" else ("ftm", "fta")
                shown[lab] = [f"{v:.3f} ({a:.1f}/{b_:.1f})" for v, a, b_ in zip(t[f"s_{c_}"], t[mk], t[at])]
            else:
                shown[lab] = t[f"s_{c_}"]
        cell_css = {lab: [perf_css(perf_level(z)) for z in t[f"z_{c_}"]] for c_, lab in zip(cats, labels)}
        cat_fmt = {lab: "{:.1f}" for c_, lab in zip(cats, labels) if c_ not in ("FG_PCT", "FT_PCT")}
    else:
        for c_, lab in zip(cats, labels):
            shown[lab] = 100 * t[f"d_{c_}"]
        vals = np.abs(shown[labels].to_numpy(float))
        vmax = float(np.nanquantile(vals, 0.95)) if vals.size else 1.0
        cell_css = {lab: [gain_css(v, vmax) for v in shown[lab]] for lab in labels}
        cat_fmt = {lab: "{:+.1f}" for lab in labels}
    shown["Z"] = t["z_total"]
    shown["Katkı"] = t["score"]
    shown["Etkisi"] = [effect_text(r, cats) for _, r in t.iterrows()]
    shown[avail_label] = t["p_avail"]
    kmax = float(np.nanquantile(np.abs(t["score"]), 0.95)) if len(t) else 1.0

    def style(_):
        out = pd.DataFrame("", index=shown.index, columns=shown.columns)
        for lab in labels:
            out[lab] = cell_css[lab]
        out["Katkı"] = [gain_css(v, kmax) for v in shown["Katkı"]]
        out[avail_label] = [avail_css(p) for p in shown[avail_label]]
        out["Öneri"] = ["font-weight: 700; color: #b8860b" if v else "" for v in shown["Öneri"]]
        return out

    styler = shown.style.apply(style, axis=None).format(
        {"ADP": "{:.1f}", "GP": "{:.0f}", "Z": "{:+.1f}", "Katkı": "{:+.3f}",
         avail_label: lambda p: "—" if p != p else f"{p:.0%}", **cat_fmt}, na_rep="—")
    st.dataframe(styler, hide_index=True, height=min(35 * (len(shown) + 1) + 3, 900), width="stretch")
    st.caption(
        "Renk (İstatistik): z kademesi Elite ≥1.5 · Great ≥1.0 · Good ≥0.5 · Avg · Below ≤−0.5 · Poor ≤−1.0 "
        "(TO'da az olan iyi). **Katkı**: oyuncunun kadrona getirdiği beklenen kategori galibiyeti (ΔECW, strateji "
        "ağırlıklarınla); **Etkisi**: en çok yükselttiği ve düşürdüğü kategoriler. "
        f"**{avail_label}**: o pick'e kadar kalma olasılığı (bot simülasyonu). **Öneri**: advisor'ın önerdiği "
        "seçimlerdeki sırası (★ = en iyi). Yahoo pozisyon kuralı yüzünden alamayacağın oyuncular gizli.")
    with st.expander("Kategori kıtlığı (kalan oyuncularda Elite / Great / Good sayısı)"):
        sc = scarcity(b.table, b.categories).rename(columns=CATEGORY_LABELS)
        st.dataframe(sc.style.apply(lambda col: [perf_css(lv) for lv in sc.index], axis=0))


def pairs_panel(snap: Snapshot) -> None:
    res = snap.advice
    b = snap.board
    turn = "/".join(map(str, res.turn)) if res else (str(b.pick) if b else "?")
    st.markdown(f"##### Önerilen {'çiftler' if res is None or len(res.turn) > 1 else 'seçimler'} · {turn}")
    if b is not None and not b.on_clock:
        st.caption("Sıra sana gelince hesaplanır. Bu arada pano, pick'ine kadar kimin kalacağını gösteriyor.")
        return
    if res is None:
        st.caption("Hesaplanıyor…")
        return
    mode = "tam mod" if snap.full is not None else "hızlı mod — tam mod hesaplanıyor"
    weighted = bool(res.params.get("category_weights"))
    for j, pr in enumerate(res.pairs[:6]):
        with st.container(border=True):
            st.markdown(f"**{'★ ' if j == 0 else ''}{j + 1}. {pr.label}**")
            st.caption(f"E[W] {pr.mean:.3f} · kademe {pr.tier}" + (" · en iyi" if j == 0 else f" · −{pr.regret:.3f}")
                       + (f" · ağırlıksız ECW {pr.ecw:.2f}" if weighted else ""))
    st.caption(f"{mode} · S = {res.params['S']} · {res.elapsed:.0f} s"
               + (" · rakip stratejileri dahil" if res.params.get("opponent_model") else "")
               + ". E[W]: sonraki turn sonrası rakip başına beklenen kategori galibiyeti; aynı kademe = "
                 "istatistiksel olarak ayırt edilemez.")


def punt_panel(snap: Snapshot, on_apply=None) -> None:
    st.markdown("##### Punt önerisi")
    pr = snap.punt
    if pr is None:
        st.caption("Hesaplanıyor (boş zamanlarda, ~30 s)…" if snap.busy else "Henüz hesaplanmadı.")
        return
    best = pr.best
    if best["plan"] == "dengeli":
        st.success("Punt gerekmiyor: **dengeli** plan en iyi.")
    else:
        st.success(f"**{best['plan']}** · dengeliye göre {best['fark']:+.2f} ± {best['fark_SE']:.2f} E[W]")
    top = pr.table.head(5)
    st.dataframe(pd.DataFrame({"plan": top["plan"], "E[W]": top["E[W]"], "fark": top["fark"]})
                 .style.format({"E[W]": "{:.2f}", "fark": "{:+.2f}"})
                 .map(lambda v: gain_css(v, 0.3), subset=["fark"]), hide_index=True, width="stretch")
    if on_apply and best["plan"] not in ("dengeli", "benim stratejim") and best["punt"]:
        st.button(f"Ağırlıklara uygula: {best['plan']}", key="apply_punt", on_click=on_apply,
                  args=(tuple(best["punt"]),))
    st.caption(f"Pick {snap.punt_pick} durumundan {pr.n_sims} simülasyonla draft sonuna kadar; her plan aynı "
               "senaryolarda. Kadron değiştikçe yenilenir. " + common.UNCALIBRATED)


def opponents_panel(snap: Snapshot) -> None:
    model = snap.opponents
    if model is None:
        return
    st.markdown("##### Rakip stratejileri")
    names = dict(snap.job.seat_names) if snap.job else {}
    tab = model.table(names)
    if tab.empty or tab["pick"].sum() == 0:
        st.caption("Rakip pick'i girildikçe oluşur.")
        return
    st.dataframe(tab[["takım", "en olası profil", "olasılık", "olası punt"]].style.format({"olasılık": "{:.0%}"}),
                 hide_index=True, width="stretch", height=36 * (len(tab) + 1) + 3)
    st.caption("Simülasyonlar rakipleri bu tahminlere göre oynatır. " + common.UNCALIBRATED)
