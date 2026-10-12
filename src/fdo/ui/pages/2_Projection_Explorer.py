"""Sayfa 2 — Projection Explorer (README §6.2, §8).

Z ve G yalnızca burada ve bot profillerinde kullanılır; öneriler ECW ile sıralanır (İlke 2).
ADP kolonu yalnızca **gösterim** içindir (İlke 1).
"""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from fdo.types import CATEGORY_LABELS
from fdo.ui import common
from fdo.valuation import value_players
from fdo.valuation.weights import WeightError, preset, validate_weights

common.page("2 · Projection Explorer")
cfg = common.config()
ds = common.dataset()
vp = cfg.model.valuation
cats = list(cfg.categories)


@st.cache_data(show_spinner=False)
def _valuation(ds_hash: str, cfg_hash: str, weights_json: str, method: str, basis: str,
               pool: int, kappa: float):
    res = value_players(ds.projections, cfg, weights=json.loads(weights_json), method=method,
                        basis=basis, pool_size=pool, variance=ds.variance, kappa=kappa)
    return res.table, res.warnings, res.stats.n_iter, res.stats.converged


with st.sidebar:
    st.header("Değerleme")
    method = st.radio("Yöntem", ["z", "g"], format_func=lambda m: {"z": "Z-score", "g": "G-score"}[m],
                      horizontal=True)
    kappa = vp.g_kappa
    if method == "g":
        kappa = st.number_input("κ (G-score)", 0.0, 5.0, float(vp.g_kappa), 0.1)
        st.warning(f"κ = {kappa} — makaledeki kesin katsayı **doğrulanmadı** (§6.2.4).")
    basis = st.radio("Taban", ["total", "per_game"], horizontal=True,
                     format_func=lambda b: {"total": "Toplam (maç × GP)", "per_game": "Maç başına"}[b])
    pool = st.select_slider("Referans havuz N", options=list(vp.pool_size_options), value=cfg.pool_size)

    st.header("Ağırlıklar")
    preset_name = st.selectbox("Preset", list(vp.presets))
    base_w = preset(cfg, preset_name)
    weights = {}
    for c in cats:
        weights[c] = st.slider(CATEGORY_LABELS[c], vp.weight_min, vp.weight_max, float(base_w[c]),
                               vp.weight_step, key=f"w_{preset_name}_{c}")
    st.download_button("Preset'i JSON indir", json.dumps({"name": "custom", "weights": weights}, indent=2),
                       file_name="preset.json", mime="application/json")
    up = st.file_uploader("Preset JSON yükle", type=["json"])
    if up is not None:
        try:
            data = json.loads(up.getvalue())
            weights = validate_weights(cfg, data["weights"])
            st.success(f"Preset yüklendi: {data.get('name', '?')}")
        except (WeightError, KeyError, json.JSONDecodeError) as e:
            st.error(f"Preset geçersiz: {e}")
    st.session_state.weights = weights

table, warnings, n_iter, converged = _valuation(ds.content_hash, cfg.config_hash, json.dumps(weights),
                                                method, basis, int(pool), float(kappa))
for w in warnings:
    st.warning(w)
punted = [CATEGORY_LABELS[c] for c, w in weights.items() if w == 0]
st.caption(f"Havuz iterasyonu: {n_iter} adım ({'sabitlendi' if converged else 'sabitlenmedi'}) · "
           f"punt: {', '.join(punted) if punted else 'yok'} · havuz istatistikleri dengeli ağırlıklarla "
           "belirlenir, ağırlıklar yalnızca V'yi değiştirir. Matchup modeli her zaman 9 kategoriyi sayar.")

adp = ds.adp
names = ds.names()
pos = ds.positions()
df = table.copy()
df.insert(0, "name", names.reindex(df.index).to_numpy())
df.insert(1, "pos", [",".join(sorted(p)) for p in pos.reindex(df.index)])
df["adp_eff"] = adp["adp_eff"].reindex(df.index)
df["rank − ADP"] = df["rank"] - df["adp_eff"]
df["adp_status"] = adp["adp_status"].reindex(df.index)
df = df.rename(columns={c: CATEGORY_LABELS[c] for c in cats})

c1, c2, c3 = st.columns([2, 2, 2])
q = c1.text_input("Ara (ad / id)")
pos_filter = c2.multiselect("Pozisyon", ["PG", "SG", "SF", "PF", "C"])
status_filter = c3.multiselect("adp_status", ["ok", "low_confidence", "imputed", "tail"])
view = df
if q:
    view = view[view["name"].str.contains(q, case=False, na=False) | view.index.str.contains(q, case=False)]
if pos_filter:
    view = view[view["pos"].apply(lambda s: any(p in s.split(",") for p in pos_filter))]
if status_filter:
    view = view[view["adp_status"].isin(status_filter)]

st.markdown(f"**{len(view)} oyuncu** · `rank − ADP` < 0: değer sırası ADP'den iyi (\"ADP'ye göre ucuz\"). "
            "ADP yalnızca gösterim içindir.")
num_cols = ["V", *[CATEGORY_LABELS[c] for c in cats], "adp_eff", "rank − ADP"]
st.dataframe(view.style.format({c: "{:.2f}" for c in num_cols}, na_rep="—")
             .map(common.diverging_bg, subset=[CATEGORY_LABELS[c] for c in cats]),
             height=600, column_config={"in_pool": st.column_config.CheckboxColumn("havuzda")})

with st.expander("Havuz boyutu duyarlılığı (180 / 208 / 240)"):
    ranks = {}
    for n in vp.pool_size_options:
        t, *_ = _valuation(ds.content_hash, cfg.config_hash, json.dumps(weights), method, basis, int(n),
                           float(kappa))
        ranks[f"N={n}"] = t["rank"]
    sens = pd.DataFrame(ranks)
    sens.insert(0, "name", names.reindex(sens.index).to_numpy())
    sens["max fark"] = sens.drop(columns="name").max(axis=1) - sens.drop(columns="name").min(axis=1)
    st.dataframe(sens.sort_values(f"N={cfg.pool_size}").head(60), height=400)
