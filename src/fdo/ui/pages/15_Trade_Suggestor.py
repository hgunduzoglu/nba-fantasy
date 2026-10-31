"""Takas önerileri: karşılıklı fayda, sat yüksek ve al düşük (ayrı öneri türleri) + playoff etkisi."""
import json
from dataclasses import asdict

import pandas as pd
import streamlit as st

from fdo.trade import Strategy
from fdo.trade.perception import PERCEPTIONS, mispricing, perceived_prices
from fdo.trade.strategy import CATEGORIES
from fdo.trade.suggest import MODES, SearchOptions, suggest_trades
from fdo.ui import season_common as sc
from fdo.ui import trade_common as tc
from fdo.ui.analysis import gain_css

data, eng, mine, day = tc.page("Takas Önerileri")
lid = eng.league.league_id
names = data.players["name"]
mode = st.radio("Öneri türü", list(MODES), format_func=MODES.get, horizontal=True, key=f"ts_mode_{lid}")
st.caption({
    "mutual": "İki takımın da kalan sezon kategori beklentisi artar; paketlerin piyasa (kalan sezon) değeri dengelidir.",
    "sell_high": "Verdiğin pakette olduğundan iyi görünen bir oyuncu var. Rakip, baktığı değere göre takası adil "
                 "ya da kârlı görür; sen kalan sezonda kazanırsın. Rakibin kalan sezonda kazanması şart değil.",
    "buy_low": "Aldığın pakette olduğundan kötü görünen bir oyuncu var. Rakip, baktığı değere göre takası adil "
               "ya da kârlı görür; sen kalan sezonda kazanırsın. Rakibin kalan sezonda kazanması şart değil.",
}[mode])
sa = tc.strategy_widget(eng, mine, f"ts_sa_{lid}_{mine}", "Takımının stratejisi")
others = [t for t in eng.team_ids if t != mine]
selected = st.multiselect("Taranacak rakipler", others, default=others, format_func=lambda t: eng.league.teams[t],
                          key=f"ts_opps_{lid}_{mine}")
assumption = st.selectbox("Rakip stratejisi varsayımı", ["Dengeli", "Zayıf kategoriyi punt", "En zayıf iki kategoriyi punt", "Rakibe özel"])
opponent_strategies = {}
if assumption == "Rakibe özel":
    for tid in selected:
        opponent_strategies[tid] = tc.strategy_widget(eng, tid, f"ts_os_{lid}_{tid}", eng.league.teams[tid])
elif assumption != "Dengeli":
    count = 1 if assumption == "Zayıf kategoriyi punt" else 2
    probs = eng.league_probabilities()
    opponent_strategies = {tid: Strategy.adaptive(probs.loc[tid, list(CATEGORIES)].to_numpy(), count) for tid in selected}
st.caption("Rakip stratejisi bir senaryodur; gerçek kabul ihtimali ölçülmez.")

perceived_basis, min_balance, min_edge = "blend", .9, 1.0
if mode != "mutual":
    with st.expander("Rakibin gözünden değer ve yanlış fiyatlama", expanded=True):
        c1, c2, c3 = st.columns(3)
        perceived_basis = c1.selectbox("Rakibin baktığı değer", list(PERCEPTIONS), index=2, format_func=PERCEPTIONS.get,
                                       key=f"ts_perc_{lid}",
                                       help="Bu sezonun rakamları erken sezonda az maça dayanır; ortalama isim değerini de katar.")
        min_balance = c2.slider("Rakibin gözünde en düşük denge", .5, 1.5, .9, .05, key=f"ts_bal_{lid}",
                                help="Rakibin aldığı / verdiği algılanan değer. 1 = rakip eşit görür, >1 = kârlı görür.")
        min_edge = c3.slider("En az yanlış fiyatlama (değer birimi)", 0.0, 5.0, 1.0, .25, key=f"ts_edge_{lid}",
                             help="Algılanan fiyat ile kalan sezon değeri arasındaki fark.")
        perceived = perceived_prices(eng, perceived_basis)
        mp = mispricing(eng, perceived)
        if len(mp):
            def show(df: pd.DataFrame):
                return pd.DataFrame({
                    "Oyuncu": df["name"], "Takım": [eng.league.teams[t] for t in df["team_id"]],
                    "Bu sezon maç": df["gp_now"], "Algılanan sıra": df["perceived_rank"],
                    "Kalan sezon sırası": df["ros_rank"], "Fark (değer)": df["edge"],
                }).style.format({"Bu sezon maç": "{:.0f}", "Algılanan sıra": "{:.0f}", "Kalan sezon sırası": "{:.0f}",
                                 "Fark (değer)": "{:+.2f}"})

            if mode == "sell_high":
                st.markdown("**Kadrondaki sat-yüksek adayları** (olduğundan iyi görünenler)")
                st.dataframe(show(mp[(mp["team_id"] == mine) & (mp["edge"] >= min_edge)].head(10)), hide_index=True,
                             width="stretch")
            else:
                st.markdown("**Rakiplerdeki al-düşük hedefleri** (olduğundan kötü görünenler)")
                tgt = mp[mp["team_id"].isin(selected) & (mp["edge"] <= -min_edge)].sort_values("edge")
                st.dataframe(show(tgt.head(15)), hide_index=True, width="stretch")
            st.caption("Algılanan sıra, seçilen kaynağın maç başı değerine göre; 3 maçtan azı sezon öncesi sırasına "
                       "düşer. Fark, o sıradaki oyuncunun kalan sezon piyasa değeri ile oyuncunun kendi değeri arasındadır.")

with st.expander("Arama ve kabul edilebilirlik ölçütleri", expanded=mode == "mutual"):
    packages = st.multiselect("Paketler (verdiğin × aldığın)", ["1x1", "2x1", "1x2", "2x2", "3x2", "2x3"], default=["1x1", "2x1", "1x2", "2x2"])
    c1, c2, c3 = st.columns(3)
    with c1:
        shortlist = st.slider("Çok oyunculu paket aday sayısı / takım", 4, 16, 8)
        budget = st.number_input("En fazla taranacak paket", 100, 100000, 8000, 100)
    with c2:
        fairness = st.slider("En düşük paket değer dengesi", 0.0, 1.0, .55, .05, disabled=mode != "mutual",
                             help="Yalnızca karşılıklı faydada; diğer türlerde rakibin gözündeki denge kullanılır.")
        min_gain = st.number_input("İki taraf için en az strateji ECW kazancı" if mode == "mutual"
                                   else "Senin için en az strateji ECW kazancı", 0.0, 2.0, .005, .005)
    with c3:
        min_win = st.slider("İki taraf için en az P(5+) değişimi (yüzde puan)" if mode == "mutual"
                            else "Senin için en az P(5+) değişimi (yüzde puan)", -5.0, 5.0, 0.0, .1)
        mix = st.slider("Sıralamada kategori beklentisinin ağırlığı", 0.0, 1.0, .65, .05)
    auto = st.checkbox("Eşit olmayan paketlerde bırakma ve boşta oyuncu eklemelerini hesaba kat", value=True)
    st.caption("Arama kısa liste ve bütçeyle sınırlıdır; bütün olası takasları tükettiği iddia edilmez. 1x1 aramasında modellenebilir kadro oyuncularının tamamı kullanılır.")
settings = [data.fingerprint, lid, mine, day.isoformat(), eng.utilization,
            asdict(sa), {t: asdict(s) for t, s in opponent_strategies.items()}, selected,
            packages, shortlist, budget, fairness, min_gain, min_win, mix, auto, mode, perceived_basis, min_balance,
            min_edge]
signature = json.dumps(settings, sort_keys=True)
button = {"mutual": "Karşılıklı faydalı takasları bul", "sell_high": "Sat-yüksek takasları bul",
          "buy_low": "Al-düşük takasları bul"}[mode]
if st.button(button, type="primary"):
    if not selected or not packages:
        st.error("En az bir rakip ve paket türü seç.")
    else:
        progress = st.progress(0, text="Takas paketleri taranıyor…")
        opts = SearchOptions(tuple(tuple(map(int, p.split("x"))) for p in packages), shortlist,
                             int(budget), 20, fairness, float(min_gain), min_win / 100, auto, mix,
                             mode, perceived_basis, float(min_balance), float(min_edge))
        found = suggest_trades(eng, mine, strategy=sa, opponent_strategies=opponent_strategies,
                               opponents=tuple(selected), options=opts, analysis_date=day,
                               progress=lambda n, total: progress.progress(min(n / total, 1.0), text=f"{n} paket tarandı"))
        progress.empty()
        st.session_state["trade_search_result"] = (signature, found, sa)
cached = st.session_state.get("trade_search_result")
if cached and cached[0] == signature:
    found = cached[1]
    st.write(f"{found.examined} paket tarandı; {found.eligible} paket eşikleri geçti. En iyi {len(found.suggestions)} sonuç gösteriliyor.")
    if found.limit_reached:
        st.caption("Arama bütçesinde durdu; tarama tamamlanmadı.")
    if found.message:
        st.info(found.message)
    if found.suggestions:
        effects_key = f"trade_search_effects:{signature}"
        n_eff = st.select_slider("Playoff etkisi için simülasyon", [500, 1000, 2000], value=1000, key="ts_eff_n")
        if st.button("Önerilerin playoff etkisini hesapla"):
            bar = st.progress(0.0, text="Sezon simülasyonu…")
            st.session_state[effects_key] = (n_eff, sc.suggestion_effects(
                eng, found.suggestions, cached[2], n_sims=n_eff,
                progress=lambda i, n: bar.progress(i / n, text=f"Öneri {i}/{n}")))
            bar.empty()
        effects = st.session_state.get(effects_key)
        eff = effects[1] if effects and effects[0] == n_eff else pd.DataFrame()
        rows = []
        for n, s in enumerate(found.suggestions, 1):
            plan, adjustments, _ = eng.resolve(s.request, {mine: sa, s.request.team_b: s.other_strategy})
            ros_after = eng.view(plan, "remaining_games_projection")
            rank_gain = eng.before["remaining_games_projection"].ranks.mean(axis=1) - ros_after.ranks.mean(axis=1)
            row = {"No": n, "Rakip": eng.league.teams[s.request.team_b],
                   "Ver": ", ".join(names[p] for p in s.request.give_a),
                   "Al": ", ".join(names[p] for p in s.request.give_b),
                   "Sen Δ strateji ECW": s.own_strategy_delta, "Rakip Δ strateji ECW": s.other_strategy_delta,
                   "Sen ΔP(5+) pp": s.own_win_delta * 100, "Rakip ΔP(5+) pp": s.other_win_delta * 100,
                   "Sen ROS sıra kazancı": rank_gain[mine], "Rakip ROS sıra kazancı": rank_gain[s.request.team_b]}
            if s.mode != "mutual":
                row["Rakibin gözünde denge"] = s.perceived_balance
                row["Yanlış fiyatlanan"] = ", ".join(names[p] for p in s.key_players)
            if len(eff):
                row["Sen ΔP(playoff)"] = eff.loc[n - 1, "me_playoff"] * 100
                row["Sen ΔP(şampiyon)"] = eff.loc[n - 1, "me_champion"] * 100
                row["Rakip ΔP(playoff)"] = eff.loc[n - 1, "opp_playoff"] * 100
            row.update({"Ek kadro işlemleri": "; ".join(f"{eng.league.teams[t]} {action}: " + ", ".join(names[p] for p in ids)
                                                        for t, adj in adjustments.items() for action, ids in adj.items() if ids),
                        "Değer dengesi": s.fairness, "Öneri puanı": s.score})
            rows.append(row)
        table = pd.DataFrame(rows)
        if len(eff):
            order = st.radio("Sıralama", ["Öneri puanı", "Sen ΔP(playoff)", "Sen ΔP(şampiyon)"], horizontal=True,
                             key="ts_sort")
            table = table.sort_values(order, ascending=False, kind="stable")
        pp_cols = [c for c in ("Sen ΔP(playoff)", "Sen ΔP(şampiyon)", "Rakip ΔP(playoff)") if c in table]
        styler = table.style.format(precision=3)
        if pp_cols:
            styler = styler.format({c: "{:+.1f}" for c in pp_cols}).map(lambda v: gain_css(v, 10), subset=pp_cols)
        st.dataframe(styler, hide_index=True, width="stretch")
        if pp_cols:
            st.caption("ΔP(playoff) ve ΔP(şampiyon) yüzde puandır: kalan normal sezon ve playoff, takassız ve takaslı "
                       "kadrolarla aynı çekilişlerle simüle edilir (kadrolar sezon boyu sabit).")
        selected_result = st.selectbox("Ayrıntılı analiz", list(range(len(found.suggestions))), format_func=lambda i: f"Öneri {i + 1}")
        suggestion = found.suggestions[selected_result]
        result = eng.analyze(suggestion.request, strategy_a=cached[2], strategy_b=suggestion.other_strategy,
                             analysis_date=day, min_fairness=fairness)
        tc.show_result(eng, result, key="suggested_trade")
    with st.expander("Arama kapsamı"):
        st.write({eng.league.teams[t]: n for t, n in found.opponent_counts.items()})
        st.caption(f"Denge nedeniyle elenen: {found.rejected_fairness}; kadro kapasitesi nedeniyle elenen: {found.rejected_roster}.")
elif cached:
    st.info("Arama ölçütleri değişti; önerileri yeniden hesapla.")
