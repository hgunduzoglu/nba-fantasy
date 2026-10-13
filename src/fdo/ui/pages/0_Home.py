"""Ana sayfa: lig özeti ve hızlı başlangıç."""

from __future__ import annotations

import streamlit as st
from streamlit.errors import StreamlitPageNotFoundError

from fdo.ui import common

common.page("Fantasy Draft Optimizer", needs_data=False)
cfg = common.config()
lg = cfg.league
ds = st.session_state.dataset

st.markdown(f"**{lg.name or 'Lig'}** · Yahoo {lg.season} · {lg.teams} takım · H2H 9-Cat · {lg.rounds} tur snake · "
            f"koltuğun **{lg.my_seat}**")
c1, c2, c3 = st.columns(3)
c1.metric("Veri", "yüklü" if ds is not None else "yok", help=None if ds is None else common.sources_caption(ds))
m = st.session_state.mock
c2.metric("Draft", f"pick {m.log.next_pick}/{lg.total_picks}" if m else "başlamadı")
c3.metric("Mod", "canlı" if st.session_state.get("live") else "mock")

st.subheader("Hızlı başlangıç")
st.markdown(
    "1. **Draft sayfasını aç:** prova için *Mock Draft*, gerçek draft için *Canlı Draft*. Draft sayfası sade: "
    "pick'leri isimle arayıp Enter'la girersin.\n"
    "2. **Draft Analizi'ni yan sekmede aç** (sağ tık → yeni sekmede aç, ya da draft sayfasındaki düğme). "
    "Draft'ı kendiliğinden takip eder: sıra sana gelince tam mod öneri ve önerilen çiftler (16/17 gibi), "
    "hashtagbasketball tarzı renkli oyuncu panosu, punt önerisi ve rakip stratejileri. Hesaplar arka "
    "planda yapılır, beklemezsin.\n"
    "3. Kendi punt stratejini Draft Analizi'nin kenar çubuğundaki ağırlıklarla kur.\n"
    "4. Derin inceleme (havuz, karşılaştırma, tam ufuk) için *Detaylı Advisor*; lig ve veri ayarları için "
    "*Lig ve Veri*."
)
c = st.columns(3)
try:
    c[0].page_link("pages/3_Mock_Draft.py", label="Mock Draft", icon=":material/sports_basketball:")
    c[1].page_link("pages/7_Live_Draft.py", label="Canlı Draft", icon=":material/edit_note:")
except StreamlitPageNotFoundError:          # sayfa menüsüz (tek başına) çalıştırıldı
    pass
c[2].link_button("Draft Analizi (yeni sekme) ↗", f"/{common.ANALYSIS_URL}")

with st.expander("Değişmez ilkeler"):
    st.markdown(
        "- ADP yalnızca rakip davranışı ve kalma olasılığı içindir; oyuncu değeri projeksiyondan gelir.\n"
        "- Öneriler ECW (rakip başına beklenen kategori galibiyeti) ile sıralanır; strateji ağırlıkları "
        "verirsen ağırlıklı ECW.\n"
        "- Matchup modeli her zaman 9 kategoriyi sayar.\n"
        "- Kalibre edilmemiş parametrelere dayanan olasılıklar " + common.UNCALIBRATED + " ile gösterilir."
    )
