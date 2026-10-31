"""Kaynak tarihleri, eksik alanlar ve ham lig ayarları."""
import pandas as pd
import streamlit as st

from fdo.trade import MODES
from fdo.trade.data import ROS
from fdo.types import STATS
from fdo.ui import trade_common as tc

data, eng, mine, day = tc.page("Trade Verileri ve Lig Kuralları")
st.caption("Ham dosyalar otomatik düzeltilmez veya üzerine yazılmaz. Değişiklikler dosya imzası değişince yeniden okunur.")
st.subheader("Kaynaklar")
st.json(data.sources)
st.subheader("Lig kuralları")
st.dataframe(pd.DataFrame(eng.league.settings.items(), columns=["Ayar", "Değer"]), hide_index=True, width="stretch")
st.subheader("Kadrolu oyuncularda veri kapsamı")
owned = sorted({p for roster in eng.league.rosters.values() for p in roster})
table = data.players.loc[owned, ["name", "nba_team", "yahoo_positions", "injury_status"]].copy()
for mode, title in MODES.items():
    frame = data.stats[mode]
    table[title + " GP"] = frame.loc[owned, "gp"]
    table[title + " tam"] = frame.loc[owned, ["gp", *STATS]].notna().all(axis=1)
table["ROS modellenebilir"] = [bool(eng.modeled[eng.index[p]]) for p in owned]
st.dataframe(table, width="stretch")
with st.expander("Kaynak notları"):
    for issue in data.issues:
        st.write(issue)
    st.caption("Ham tablolarda '-' eksiktir; sayısal 0 sıfırdır. Yüzdeler kaynaktaki yüzde sütunları yerine şut isabet/denemelerinden üretilir.")
    st.caption("İstatistik ekranındaki Roster Status yalnızca çekildiği lig içindir. Sahiplik her ligin kendi güncel kadrosundan belirlenir.")
