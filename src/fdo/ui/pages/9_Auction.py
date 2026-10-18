"""Auction draft (README §13.12): canlı takip, takımına göre teklif tavanı, aday gösterme önerisi.

Aday gösterilen oyuncuyu kutuya yazınca kartı (beklenen fiyat, senin için değeri, teklif tavanın,
kategori etkisi) anında görünür; satış bitince alan takımı ve fiyatı girip kaydedersin. Log her
satışta ``data/live/auction.json``'a yazılır.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

from fdo.auction.advice import evaluate, prepare_auction
from fdo.auction.state import AuctionLog
from fdo.config import DEFAULT_CONFIG_DIR, REPO_ROOT, load_config
from fdo.ingest.auction import parse_costs
from fdo.types import CATEGORY_LABELS
from fdo.ui import analysis, common

common.page("Auction Draft")
cfg = common.config()
ds = common.dataset()
lg = cfg.league
LIVE = Path(os.environ.get("FDO_AUCTION_PATH", REPO_ROOT / "data" / "live" / "auction.json"))
AAV_FILE = Path(os.environ.get("FDO_AAV_PATH", REPO_ROOT / "data" / "real" / "auction_aav_yahoo.csv"))
AUCTION_LEAGUE = DEFAULT_CONFIG_DIR / "league_14_auction.yaml"

if lg.draft_type != "auction":
    st.info(f"Seçili lig snake ({lg.name}). Auction için auction ligini yükle.")
    if AUCTION_LEAGUE.exists() and st.button("14 takımlı auction ligini yükle", type="primary"):
        common.set_config(load_config(AUCTION_LEAGUE))
        common.set_dataset(None, None)
        st.rerun()
    st.stop()


# ------------------------------------------------------------------- durum
def save() -> None:
    LIVE.parent.mkdir(parents=True, exist_ok=True)
    LIVE.write_text(st.session_state.auction_log.to_json({"names": st.session_state.get("auction_names", {})}),
                    encoding="utf-8")


def load_aav() -> pd.Series | None:
    if "auction_aav" not in st.session_state:
        aav = None
        if AAV_FILE.exists():
            df = pd.read_csv(AAV_FILE, dtype={"player_id": str})
            aav = df.set_index("player_id")["avg_cost"].astype(float)
        st.session_state.auction_aav = aav
    return st.session_state.auction_aav


def actx():
    log = st.session_state.auction_log
    aav = load_aav()
    key = (ds.content_hash, cfg.config_hash, log.budget, log.min_bid,
           None if aav is None else hash(tuple(aav.round(2).items())))
    if st.session_state.get("auction_ctx_key") != key:
        st.session_state.auction_ctx = prepare_auction(ds, cfg, aav, budget=log.budget, min_bid=log.min_bid,
                                                       universe=common.universe())
        st.session_state.auction_ctx_key = key
    return st.session_state.auction_ctx


if "auction_log" not in st.session_state:
    c1, c2, c3 = st.columns(3)
    budget = c1.number_input("Bütçe ($)", 50, 1000, int(cfg.auction.budget), 5)
    min_bid = c2.number_input("En düşük teklif ($)", 1, 10, int(cfg.auction.min_bid))
    c3.metric("Kadro", f"{lg.rounds} oyuncu · {lg.teams} takım · koltuk {lg.my_seat}")
    b1, b2 = st.columns(2)
    if b1.button("Yeni auction başlat", type="primary"):
        st.session_state.auction_log = AuctionLog.new(cfg, budget, min_bid)
        save()
        st.rerun()
    if LIVE.exists():
        saved, meta = AuctionLog.from_json(LIVE.read_text(encoding="utf-8"))
        if b2.button(f"Kayıtlı auction'a devam et ({len(saved.purchases)} satış)"):
            st.session_state.auction_log = saved
            st.session_state.auction_names = {int(k): v for k, v in meta.get("names", {}).items()}
            st.rerun()
    st.stop()

log: AuctionLog = st.session_state.auction_log
names = {s: st.session_state.get("auction_names", {}).get(s) or ("Sen" if s == lg.my_seat else f"Takım {s}")
         for s in range(1, lg.teams + 1)}

# ------------------------------------------------------------------- kenar çubuğu
with st.sidebar:
    st.subheader("Auction")
    st.caption(f"Bütçe ${log.budget} · en düşük ${log.min_bid} · {lg.teams} takım × {lg.rounds} · koltuk {lg.my_seat}")
    with st.expander("Yahoo ortalama fiyatları (AAV)", expanded=load_aav() is None):
        aav = load_aav()
        st.caption(f"{0 if aav is None else len(aav)} oyuncunun fiyatı yüklü. Yapıştır (CSV, JSON ya da "
                   "'Oyuncu ... $23' satırları) ya da dosya seç; yoksa projeksiyondan model değeri kullanılır.")
        text = st.text_area("Fiyat verisi", height=120, key="aav_text")
        up = st.file_uploader("ya da dosya", type=["csv", "json", "txt", "tsv"], key="aav_file")
        if st.button("Fiyatları içe aktar", disabled=not text and up is None):
            raw = up.getvalue().decode("utf-8") if up is not None else text
            s, miss = parse_costs(raw, ds.players)
            if len(s):
                AAV_FILE.parent.mkdir(parents=True, exist_ok=True)
                s.rename_axis("player_id").reset_index().to_csv(AAV_FILE, index=False)
                st.session_state.auction_aav = s
                st.success(f"{len(s)} fiyat yüklendi" + (f"; eşleşmeyen {len(miss)}: {', '.join(miss[:8])}"
                                                          if miss else ""))
            else:
                st.error("Fiyat bulunamadı; biçimi kontrol et.")
    with st.expander("Takım adları"):
        cur = st.session_state.setdefault("auction_names", {})
        for s in range(1, lg.teams + 1):
            v = st.text_input(f"Seat {s}" + (" (sen)" if s == lg.my_seat else ""), cur.get(s, ""), key=f"an_name_{s}")
            if v:
                cur[s] = v
        if st.button("Adları kaydet"):
            save()
            st.rerun()
    st.subheader("Strateji ağırlıkları")
    weights = {}
    for c in cfg.categories:
        weights[c] = st.slider(CATEGORY_LABELS[c], 0.0, 2.0, 1.0, 0.25, key=f"au_w_{c}")
    if st.button("Auction'dan çık (kayıt kalır)"):
        del st.session_state["auction_log"]
        st.rerun()

w_active = weights if any(abs(v - 1.0) > 1e-9 for v in weights.values()) else None
ctx = actx()
board = evaluate(ctx, log, lg.my_seat, w_active)
t = board.table
uses_market = bool(np.isfinite(ctx.market).any())

# ------------------------------------------------------------------- üst bilgi
if log.is_complete:
    st.success("Auction tamamlandı.")
nom = board.nominator
c = st.columns(6)
c[0].metric("Kalan bütçen", f"${log.budget_left(lg.my_seat)}")
c[1].metric("Boş slot", board.my_open)
c[2].metric("Max teklifin", f"${board.my_max_bid}")
c[3].metric("Enflasyon", f"{board.inflation:.2f}×", help="Kalan para / kalan oyuncuların taban değeri. >1: "
            "kalanlar taban fiyatından pahalıya gider.")
c[4].metric("Rakip max teklif", f"${board.rival_max}",
            help=f"En çok verebilen rakip: {names.get(board.rival_max_seat, '—')}")
c[5].metric("Sıradaki aday gösteren", names.get(nom, "—") if nom else "—", help="Tahmini (koltuk sırası döngüsü)")
analysis.team_strip(board)

# ------------------------------------------------------------------- aday kartı + satış girişi
labels = {p: f"{n} · {pos} · ${pr:.0f}" for p, n, pos, pr in zip(t["player_id"], t["name"], t["positions"], t["price"])}
focus = st.selectbox("Aday gösterilen oyuncu", list(t["player_id"]), index=None, format_func=labels.get,
                     placeholder="Oyuncu adını yaz…", key=f"au_focus_{len(log.purchases)}")
if focus:
    r = t.set_index("player_id").loc[focus]
    with st.container(border=True):
        st.markdown(f"### {r['name']} · {r['positions']} · {r['nba_team']}" + (f" ({r['injury']})" if r["injury"] else ""))
        k = st.columns(6)
        verdict = ("AL" if r["gap"] >= 1 else ("sınırda" if r["gap"] > -2 else "pahalı")) if r["allowed"] else "alamazsın"
        k[0].metric("Teklif tavanın", f"${r['ceiling']:.0f}" if r["allowed"] else "—", help="min(senin için değeri, max teklifin)")
        k[1].metric("Beklenen fiyat", f"${r['price']:.0f}", help="Taban fiyat × enflasyon")
        k[2].metric("Senin için değeri", f"${r['my_value']:.0f}", delta=f"{r['gap']:+.0f}")
        k[3].metric("Yahoo AAV", "—" if np.isnan(r["aav"]) else f"${r['aav']:.1f}")
        k[4].metric("Model değeri", f"${r['model']:.0f}")
        k[5].metric("Karar", verdict)
        cats = list(board.categories)
        eff = pd.DataFrame([[100 * r[f"d_{c_}"] for c_ in cats]], columns=[CATEGORY_LABELS[c_] for c_ in cats],
                           index=["kategori etkisi (puan)"])
        vmax = max(float(np.abs(eff.to_numpy()).max()), 1e-9)
        st.dataframe(eff.style.format("{:+.1f}").map(lambda v: analysis.gain_css(v, vmax)), width="stretch")
        st.caption(f"Rakiplerden en fazla {names.get(board.rival_max_seat, '—')} ${board.rival_max} verebilir. "
                   f"Etkisi: {analysis.effect_text(r, cats) or '—'}")

    with st.form("sale", clear_on_submit=True):
        f = st.columns([2, 1, 1])
        seat = f[0].selectbox("Alan takım", list(range(1, lg.teams + 1)), format_func=lambda s: names[s],
                              index=lg.my_seat - 1)
        price = f[1].number_input("Fiyat ($)", log.min_bid, log.budget, max(log.min_bid, int(round(r["price"]))))
        if f[2].form_submit_button("Satışı kaydet", type="primary"):
            try:
                log.add(focus, int(seat), int(price))
                save()
                st.rerun()
            except ValueError as e:
                st.error(str(e))

if st.button("Son satışı geri al", disabled=not log.purchases):
    log.undo()
    save()
    st.rerun()

# ------------------------------------------------------------------- sekmeler
tab_p, tab_nom, tab_teams, tab_me = st.tabs(["Oyuncular", "Aday göster", "Takımlar", "Kadron"])

with tab_p:
    cc = st.columns([2, 2, 2])
    pos = cc[0].selectbox("Pozisyon", analysis.POSITION_FILTERS, key="au_pos")
    sort = cc[1].selectbox("Sırala", ["Fark (değer − fiyat)", "Senin için değeri", "Beklenen fiyat"], key="au_sort")
    n_show = cc[2].selectbox("Göster", [30, 60, 120, 250], index=1, key="au_n")
    v = t[t["allowed"]] if board.my_open else t
    if pos != "Hepsi":
        v = v[v["positions"].str.split(",").map(lambda ps: pos in ps)]
    col = {"Fark (değer − fiyat)": "gap", "Senin için değeri": "my_value", "Beklenen fiyat": "price"}[sort]
    if col == "gap":
        v = v[v["in_pool"]]
    v = v.sort_values(col, ascending=False).head(int(n_show)).reset_index(drop=True)
    cats = list(board.categories)
    labs = [CATEGORY_LABELS[c_] for c_ in cats]
    shown = pd.DataFrame({
        "Oyuncu": [n + (f" ({s})" if s else "") for n, s in zip(v["name"], v["injury"])],
        "Poz": v["positions"], "Takım": v["nba_team"], "GP": v["gp"],
        "Tavan $": v["ceiling"], "Değer $": v["my_value"], "Fiyat $": v["price"], "Fark": v["gap"],
        "AAV": v["aav"], "Model $": v["model"],
    })
    for c_, lab in zip(cats, labs):
        if c_ in ("FG_PCT", "FT_PCT"):
            mk, at = ("fgm", "fga") if c_ == "FG_PCT" else ("ftm", "fta")
            shown[lab] = [f"{x:.3f} ({a:.1f}/{b:.1f})" for x, a, b in zip(v[f"s_{c_}"], v[mk], v[at])]
        else:
            shown[lab] = v[f"s_{c_}"]
    shown["Etkisi"] = [analysis.effect_text(r_, cats) for _, r_ in v.iterrows()]
    gmax = float(np.nanquantile(np.abs(v["gap"]), 0.95)) if len(v) else 1.0

    def style(_):
        out = pd.DataFrame("", index=shown.index, columns=shown.columns)
        for c_, lab in zip(cats, labs):
            out[lab] = [analysis.perf_css(analysis.perf_level(z)) for z in v[f"z_{c_}"]]
        out["Fark"] = [analysis.gain_css(x, gmax) for x in shown["Fark"]]
        out["Tavan $"] = "font-weight: 700"
        return out

    fmt = {"GP": "{:.0f}", "Tavan $": "${:.0f}", "Değer $": "${:.0f}", "Fiyat $": "${:.0f}", "Fark": "{:+.0f}",
           "AAV": "${:.1f}", "Model $": "${:.0f}",
           **{lab: "{:.1f}" for c_, lab in zip(cats, labs) if c_ not in ("FG_PCT", "FT_PCT")}}
    st.dataframe(shown.style.apply(style, axis=None).format(fmt, na_rep="—"), hide_index=True, width="stretch",
                 height=min(35 * (len(shown) + 1) + 3, 900))
    st.caption("**Fiyat**: beklenen satış fiyatı (" + ("Yahoo AAV lige ölçekli" if uses_market else
               "AAV yok — projeksiyondan model değeri") + " × enflasyon). **Değer**: senin kadrona göre değeri "
               "(kategori katkısı dolara çevrildi; ağırlıklarınla). **Tavan**: verebileceğin en yüksek teklif = "
               "min(değer, max teklifin). **Fark** yeşilse fiyatından değerli. İstatistik renkleri z kademesi. "
               + common.UNCALIBRATED)

with tab_nom:
    a, b_ = st.columns(2)
    with a:
        st.markdown("**Aday göster — rakipler harcasın**")
        st.caption("Pahalı gidecek ama senin kadron için fiyatını hak etmeyen oyuncular: erken aday göster, "
                   "rakiplerin bütçesi erisin.")
        nm = board.nominate(10)
        st.dataframe(pd.DataFrame({"oyuncu": nm["name"], "fiyat": nm["price"], "senin için": nm["my_value"]})
                     .style.format({"fiyat": "${:.0f}", "senin için": "${:.0f}"}), hide_index=True, width="stretch")
    with b_:
        st.markdown("**Hedeflerin — değeri fiyatından yüksek**")
        st.caption("Bunları rakiplerin bütçesi azaldığında (geç) aday göstermek genelde daha ucuza getirir.")
        tg = board.targets(10)
        st.dataframe(pd.DataFrame({"oyuncu": tg["name"], "fiyat": tg["price"], "senin için": tg["my_value"],
                                   "tavan": tg["ceiling"]})
                     .style.format({"fiyat": "${:.0f}", "senin için": "${:.0f}", "tavan": "${:.0f}"}),
                     hide_index=True, width="stretch")

with tab_teams:
    st.dataframe(log.team_table(names, lg.my_seat), hide_index=True, width="stretch")
    if log.purchases:
        st.markdown("**Satışlar**")
        st.dataframe(pd.DataFrame([{"#": i + 1, "oyuncu": common.name_of(p.player_id), "takım": names[p.seat],
                                    "$": p.price} for i, p in enumerate(log.purchases)][::-1]),
                     hide_index=True, width="stretch", height=300)

with tab_me:
    mine = [p for p in log.purchases if p.seat == lg.my_seat]
    if not mine:
        st.info("Henüz oyuncu almadın.")
    else:
        st.dataframe(pd.DataFrame([{"oyuncu": common.name_of(p.player_id),
                                    "poz": ",".join(sorted(ds.positions()[p.player_id])), "$": p.price}
                                   for p in mine]), hide_index=True, width="stretch")
