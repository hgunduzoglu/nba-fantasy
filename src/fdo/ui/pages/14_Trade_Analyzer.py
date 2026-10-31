"""İsteğe bağlı kadro dengelemesiyle manuel takas analizi."""
import streamlit as st

from fdo.trade import TradeError, TradeRequest
from fdo.ui import season_common as sc
from fdo.ui import trade_common as tc

data, eng, mine, day = tc.page("Takas Analizi")
tids = list(eng.team_ids)
a = st.selectbox("Birinci takım", tids, index=tids.index(mine), format_func=lambda t: eng.league.teams[t], key=f"ta_a_{eng.league.league_id}")
b = st.selectbox("Karşı taraf", [t for t in tids if t != a], format_func=lambda t: eng.league.teams[t], key=f"ta_b_{eng.league.league_id}_{a}")
ca, cb = st.columns(2)
with ca:
    sa = tc.strategy_widget(eng, a, f"ta_sa_{eng.league.league_id}_{a}", "Birinci takımın stratejisi")
with cb:
    sb = tc.strategy_widget(eng, b, f"ta_sb_{eng.league.league_id}_{b}", "Karşı tarafın stratejisi")
owned = {p for r in eng.league.rosters.values() for p in r}
free = [p for p in eng.ids if p not in owned and eng.modeled[eng.index[p]]]
free.sort(key=lambda p: -float(eng.market[p]))
with st.container(border=True):
    c1, c2 = st.columns(2)
    with c1:
        give_a = st.multiselect("Birinci takımın verecekleri", eng.league.rosters[a], format_func=lambda p: tc.label(eng, p))
        drop_a = st.multiselect("Birinci takımın ayrıca bırakacakları", eng.league.rosters[a], format_func=lambda p: tc.label(eng, p))
        add_a = st.multiselect("Birinci takımın boşta havuzundan alacakları", free, format_func=lambda p: tc.label(eng, p))
    with c2:
        give_b = st.multiselect("Karşı tarafın verecekleri", eng.league.rosters[b], format_func=lambda p: tc.label(eng, p))
        drop_b = st.multiselect("Karşı tarafın ayrıca bırakacakları", eng.league.rosters[b], format_func=lambda p: tc.label(eng, p))
        add_b = st.multiselect("Karşı tarafın boşta havuzundan alacakları", free, format_func=lambda p: tc.label(eng, p))
    auto_drop = st.checkbox("Kapasite aşılırsa düşük strateji değerli oyuncuyu otomatik bırak", value=False)
    auto_fill = st.checkbox("Takasın açtığı boşluğu boşta havuzundan tamamla", value=False)
    st.caption("Otomatik işlemler sonuçta isimleriyle gösterilir. Kaynakta eksik verisi olan oyuncular değiştirilmez; onların bulunduğu analiz kısmi olabilir.")
    submitted = st.button("Takası analiz et", type="primary")
req = TradeRequest(a, b, tuple(give_a), tuple(give_b), tuple(drop_a), tuple(drop_b), tuple(add_a), tuple(add_b), auto_drop, auto_fill)
fingerprint = tc.request_fingerprint(eng, req, sa, sb, day)
if submitted:
    try:
        result = eng.analyze(req, strategy_a=sa, strategy_b=sb, analysis_date=day)
        st.session_state["trade_analysis_result"] = (fingerprint, result)
    except TradeError as exc:
        st.error(str(exc))
cached = st.session_state.get("trade_analysis_result")
if cached and cached[0] == fingerprint:
    tc.show_result(eng, cached[1], key="manual_trade")
    sc.show_trade_effect(eng, cached[1], key="manual_trade_season")
elif cached:
    st.info("Seçimler değişti. Güncel karşılaştırma için takası yeniden analiz et.")
