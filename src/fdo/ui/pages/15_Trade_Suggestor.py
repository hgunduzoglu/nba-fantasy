"""Karşılıklı fayda, matchup ve paket dengesiyle takas arama."""
import json
from dataclasses import asdict

import numpy as np
import pandas as pd
import streamlit as st

from fdo.trade import Strategy
from fdo.trade.strategy import CATEGORIES
from fdo.trade.suggest import SearchOptions, suggest_trades
from fdo.ui import trade_common as tc

data, eng, mine, day = tc.page("Takas Önerileri")
sa = tc.strategy_widget(eng, mine, f"ts_sa_{eng.league.league_id}_{mine}", "Takımının stratejisi")
others = [t for t in eng.team_ids if t != mine]
selected = st.multiselect("Taranacak rakipler", others, default=others, format_func=lambda t: eng.league.teams[t], key=f"ts_opps_{eng.league.league_id}_{mine}")
assumption = st.selectbox("Rakip stratejisi varsayımı", ["Dengeli", "Zayıf kategoriyi punt", "En zayıf iki kategoriyi punt", "Rakibe özel"])
opponent_strategies = {}
if assumption == "Rakibe özel":
    for tid in selected:
        opponent_strategies[tid] = tc.strategy_widget(eng, tid, f"ts_os_{eng.league.league_id}_{tid}", eng.league.teams[tid])
elif assumption != "Dengeli":
    count = 1 if assumption == "Zayıf kategoriyi punt" else 2
    probs = eng.league_probabilities()
    opponent_strategies = {tid: Strategy.adaptive(probs.loc[tid, list(CATEGORIES)].to_numpy(), count) for tid in selected}
st.caption("Rakip stratejisi bir senaryodur. Öneriler senin ve rakibin ayrı fayda eşiklerini geçmek zorundadır; gerçek kabul ihtimali ölçülmez.")
with st.expander("Arama ve kabul edilebilirlik ölçütleri", expanded=True):
    packages = st.multiselect("Paketler (verdiğin × aldığın)", ["1x1", "2x1", "1x2", "2x2", "3x2", "2x3"], default=["1x1", "2x1", "1x2", "2x2"])
    c1, c2, c3 = st.columns(3)
    with c1:
        shortlist = st.slider("Çok oyunculu paket aday sayısı / takım", 4, 16, 8)
        budget = st.number_input("En fazla taranacak paket", 100, 100000, 8000, 100)
    with c2:
        fairness = st.slider("En düşük paket değer dengesi", 0.0, 1.0, .55, .05)
        min_gain = st.number_input("İki taraf için en az strateji ECW kazancı", 0.0, 2.0, .005, .005)
    with c3:
        min_win = st.slider("İki taraf için en az P(5+) değişimi (yüzde puan)", -5.0, 5.0, 0.0, .1)
        mix = st.slider("Sıralamada kategori beklentisinin ağırlığı", 0.0, 1.0, .65, .05)
    auto = st.checkbox("Eşit olmayan paketlerde bırakma ve boşta oyuncu eklemelerini hesaba kat", value=True)
    st.caption("Arama kısa liste ve bütçeyle sınırlıdır; bütün olası takasları tükettiği iddia edilmez. 1x1 aramasında modellenebilir kadro oyuncularının tamamı kullanılır.")
settings = [data.fingerprint, eng.league.league_id, mine, day.isoformat(), eng.utilization,
            asdict(sa), {t: asdict(s) for t, s in opponent_strategies.items()}, selected,
            packages, shortlist, budget, fairness, min_gain, min_win, mix, auto]
signature = json.dumps(settings, sort_keys=True)
if st.button("Karşılıklı faydalı takasları bul", type="primary"):
    if not selected or not packages:
        st.error("En az bir rakip ve paket türü seç.")
    else:
        progress = st.progress(0, text="Takas paketleri taranıyor…")
        opts = SearchOptions(tuple(tuple(map(int, p.split("x"))) for p in packages), shortlist,
                             int(budget), 20, fairness, float(min_gain), min_win / 100, auto, mix)
        found = suggest_trades(eng, mine, strategy=sa, opponent_strategies=opponent_strategies,
                               opponents=tuple(selected), options=opts, analysis_date=day,
                               progress=lambda n, total: progress.progress(min(n / total, 1.0), text=f"{n} paket tarandı"))
        progress.empty()
        st.session_state["trade_search_result"] = (signature, found, sa)
cached = st.session_state.get("trade_search_result")
if cached and cached[0] == signature:
    found = cached[1]
    st.write(f"{found.examined} paket tarandı; {found.eligible} paket iki tarafın eşiklerini geçti. En iyi {len(found.suggestions)} sonuç gösteriliyor.")
    if found.limit_reached:
        st.caption("Arama bütçesinde durdu; tarama tamamlanmadı.")
    if found.message:
        st.info(found.message)
    if found.suggestions:
        rows = []
        for n, s in enumerate(found.suggestions, 1):
            plan, adjustments, _ = eng.resolve(s.request, {mine: sa, s.request.team_b: s.other_strategy})
            ros_after = eng.view(plan, "remaining_games_projection")
            rank_gain = eng.before["remaining_games_projection"].ranks.mean(axis=1) - ros_after.ranks.mean(axis=1)
            rows.append({"No": n, "Rakip": eng.league.teams[s.request.team_b],
                         "Ver": ", ".join(data.players.loc[p, "name"] for p in s.request.give_a),
                         "Al": ", ".join(data.players.loc[p, "name"] for p in s.request.give_b),
                         "Sen Δ strateji ECW": s.own_strategy_delta, "Rakip Δ strateji ECW": s.other_strategy_delta,
                         "Sen ΔP(5+) pp": s.own_win_delta * 100, "Rakip ΔP(5+) pp": s.other_win_delta * 100,
                         "Sen ROS sıra kazancı": rank_gain[mine], "Rakip ROS sıra kazancı": rank_gain[s.request.team_b],
                         "Ek kadro işlemleri": "; ".join(f"{eng.league.teams[t]} {action}: " + ", ".join(data.players.loc[p, "name"] for p in ids)
                                                        for t, adj in adjustments.items() for action, ids in adj.items() if ids),
                         "Değer dengesi": s.fairness, "Ortak fayda": s.score})
        st.dataframe(pd.DataFrame(rows).style.format(precision=3), hide_index=True, width="stretch")
        selected_result = st.selectbox("Ayrıntılı analiz", list(range(len(found.suggestions))), format_func=lambda i: f"Öneri {i + 1}")
        suggestion = found.suggestions[selected_result]
        result = eng.analyze(suggestion.request, strategy_a=cached[2], strategy_b=suggestion.other_strategy,
                             analysis_date=day, min_fairness=fairness)
        tc.show_result(eng, result, key="suggested_trade")
    with st.expander("Arama kapsamı"):
        st.write({eng.league.teams[t]: n for t, n in found.opponent_counts.items()})
        st.caption(f"Değer dengesi nedeniyle elenen: {found.rejected_fairness}; kadro kapasitesi nedeniyle elenen: {found.rejected_roster}.")
elif cached:
    st.info("Arama ölçütleri değişti; önerileri yeniden hesapla.")
