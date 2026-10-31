"""Trade Lab başlangıcı ve kayıtlı senaryolar."""
import json

import pandas as pd
import streamlit as st

from fdo.ui import trade_common as tc

data, eng, mine, day = tc.page("Fantasy Trade Lab")
st.markdown("Mevcut kadroları üç ayrı istatistik kaynağıyla karşılaştır; takasın iki takıma ve ligdeki rakiplere etkisini ölç.")
c = st.columns(4)
c[0].metric("Lig", len(data.leagues))
c[1].metric("Takım", sum(len(lg.teams) for lg in data.leagues.values()))
c[2].metric("Kadrolu farklı oyuncu", len({p for lg in data.leagues.values() for r in lg.rosters.values() for p in r}))
c[3].metric("Analiz tarihi", day.strftime("%d.%m.%Y"))
st.subheader("Kullanım")
st.write("Lig Sıralamaları menüsündeki üç ekran bağımsız kaynakları gösterir. Takas Analizi'nde oyuncuları seç; Takas Önerileri'nde iki tarafa da fayda sağlayan paketleri tara. Stratejileri her iki takım için ayrı belirleyebilirsin.")
st.caption("İstatistik ve kadro verileri yerel dosyalardan okunur. Senaryolar gerçek Yahoo kadrolarını değiştirmez; bu oturumda karşılaştırılır veya JSON olarak indirilir.")
st.subheader("Ligler")
st.dataframe(pd.DataFrame([{"Lig": lg.name, "Yahoo ID": lg.league_id, "Takım": len(lg.teams),
                            "Normal kadro": lg.capacity, "IL": lg.config.unverified.il_slots,
                            "Playoff": lg.settings.get("Playoffs"), "Takas son tarihi": lg.settings.get("Trade End Date")}
                           for lg in data.leagues.values()]), hide_index=True, width="stretch")
saved = [s for s in st.session_state.get("trade_saved_scenarios", []) if s["league_id"] == eng.league.league_id]
if saved:
    st.subheader("Bu ligde karşılaştırmaya eklenen senaryolar")
    st.dataframe(pd.DataFrame([{k: v for k, v in s.items() if k not in ("id", "payload")} for s in saved]), hide_index=True)
    st.download_button("Senaryoları JSON indir", json.dumps([json.loads(s["payload"]) for s in saved], ensure_ascii=False, indent=2), "trade_scenarios.json", "application/json")
