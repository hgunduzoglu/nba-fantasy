"""Fantasy Draft Optimizer — Streamlit girişi (gruplu menü).

    streamlit run src/fdo/ui/app.py
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from fdo.ui.common import ANALYSIS_URL

P = Path(__file__).resolve().parent / "pages"

nav = st.navigation({
    "Başlangıç": [
        st.Page(P / "0_Home.py", title="Ana sayfa", icon=":material/home:", url_path="home", default=True),
    ],
    "Draft": [
        st.Page(P / "3_Mock_Draft.py", title="Mock Draft", icon=":material/sports_basketball:", url_path="mock"),
        st.Page(P / "7_Live_Draft.py", title="Canlı Draft", icon=":material/edit_note:", url_path="canli"),
        st.Page(P / "8_Draft_Analysis.py", title="Draft Analizi", icon=":material/insights:",
                url_path=ANALYSIS_URL),
    ],
    "İnceleme": [
        st.Page(P / "4_Draft_Assistant.py", title="Detaylı Advisor", icon=":material/psychology:",
                url_path="advisor"),
        st.Page(P / "5_Team_Dashboard.py", title="Takım Panosu", icon=":material/groups:", url_path="takimlar"),
        st.Page(P / "2_Projection_Explorer.py", title="Projeksiyonlar", icon=":material/query_stats:",
                url_path="projeksiyonlar"),
    ],
    "Ayarlar": [
        st.Page(P / "1_League_and_Data.py", title="Lig ve Veri", icon=":material/settings:", url_path="lig"),
        st.Page(P / "6_Realism_Report.py", title="Bot Gerçekçiliği", icon=":material/fact_check:",
                url_path="gercekcilik"),
    ],
})
nav.run()
