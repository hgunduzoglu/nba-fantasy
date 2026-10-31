"""Trade ekranları: draft oturumundan bağımsız veri ve lig seçimi."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
import hashlib
import json
from dataclasses import asdict

import numpy as np
import pandas as pd
import streamlit as st

from fdo.config import REPO_ROOT
from fdo.trade import MODES, Strategy, TradeData, TradeEngine, load_trade_data
from fdo.trade.data import ROS, file_signature
from fdo.trade.engine import TradeResult
from fdo.trade.report import category_changes, export_result, opponent_changes
from fdo.trade.strategy import CATEGORIES, PRESETS
from fdo.types import CATEGORY_LABELS

DATA_DIR = REPO_ROOT / "data" / "real"


@st.cache_resource(show_spinner="Ligler ve üç istatistik kaynağı okunuyor…")
def _data(directory: str, signature: str) -> TradeData:
    return load_trade_data(directory)


@st.cache_resource(show_spinner="Sakatlık dönüş tarihleri uygulanıyor…")
def _injured(_data: TradeData, fingerprint: str, path: str) -> TradeData:
    from fdo.inseason.injuries import with_injuries

    return with_injuries(_data, Path(path).parent)


@st.cache_resource(show_spinner="Kategori ve matchup modeli hazırlanıyor…")
def _engine(_data: TradeData, fingerprint: str, league_id: str, utilization: float) -> TradeEngine:
    return TradeEngine(_data, league_id, utilization=utilization)


def page(title: str) -> tuple[TradeData, TradeEngine, str, dt.date]:
    st.set_page_config(page_title=f"Fantasy Trade Lab · {title}", layout="wide")
    st.title(title)
    try:
        data = _data(str(DATA_DIR), file_signature(DATA_DIR))
    except (ValueError, OSError, KeyError, IndexError) as exc:
        st.error(f"Trade verisi yüklenemedi: {exc}")
        st.info("data/real altında rosters.json, league_info.json, player_stat_pages.json ve sezon öncesi CSV'leri bulunmalı.")
        st.stop()
    ss = st.session_state
    current = ss.get("trade_active_league", next(iter(data.leagues)))
    if current not in data.leagues:
        current = next(iter(data.leagues))
    ids = list(data.leagues)
    with st.sidebar:
        st.subheader("Trade Lab")
        lid = st.selectbox("Lig", ids, index=ids.index(current),
                           format_func=lambda x: f"{data.leagues[x].name} · {x}", key="_trade_league_widget")
        ss.trade_active_league = lid
        league = data.leagues[lid]
        tids = list(league.teams)
        default = ss.get(f"trade_team_{lid}", league.default_team_id)
        mine = st.selectbox("Analiz edeceğin takım", tids, index=tids.index(default) if default in tids else 0,
                            format_func=lambda t: league.teams[t], key=f"_trade_team_widget_{lid}")
        ss[f"trade_team_{lid}"] = mine
        day = st.date_input("Takas değerlendirme tarihi", value=data.as_of, key="trade_analysis_date")
        from fdo.inseason.injuries import latest_file

        inj_file = latest_file(DATA_DIR)
        use_inj = st.checkbox("Sakatlık dönüş tarihlerini uygula", value=True, key="trade_use_injuries",
                              disabled=inj_file is None,
                              help="CBS Sports sakatlık raporu (scripts/fetch_injuries.py): oyuncu tahmini dönüş "
                                   "gününe kadar oynamaz, kalan maçları dönüş sonrasına yayılır."
                                   + ("" if inj_file else " Dosya yok."))
        if inj_file is not None:
            st.caption(f"Sakatlık raporu: {inj_file.name}")
        with st.expander("Matchup varsayımları"):
            utilization = st.slider("Maçların aktif kadroda kullanılan oranı", .50, 1.0, .987, .001,
                                    key="trade_utilization", help="Tüm takımlara uygulanan ortalama lineup varsayımı.")
            st.caption("Kazanma ihtimali: kalan sezon projeksiyonu → tipik hafta. Normal yaklaşım; kalibre edilmemiş. P(5+) kategori bağımsızlığı varsayar.")
        st.caption(f"Kadro/veri tarihi: {data.as_of:%d.%m.%Y}. Değerlendirme tarihi yalnızca takas son tarihi kontrolünü değiştirir.")
    if inj_file is not None and use_inj:
        data = _injured(data, data.fingerprint, str(inj_file))
    engine = _engine(data, data.fingerprint, lid, utilization)
    st.caption(f"{league.name} · {len(league.teams)} takım · normal kadro {league.capacity} · "
               f"{league.config.unverified.il_slots} IL · {engine.horizon_weeks:.2f} haftalık kalan NBA dönemi")
    return data, engine, mine, day


def label(engine: TradeEngine, pid: str) -> str:
    row = engine.data.players.loc[pid]
    flag = " · ROS eksik" if not engine.modeled[engine.index[pid]] else ""
    return f"{row['name']} · {row['nba_team']} · {row['yahoo_positions']}{flag}"


def strategy_widget(engine: TradeEngine, tid: str, key: str, title: str) -> Strategy:
    with st.expander(title):
        choice = st.selectbox("Strateji", [*PRESETS, "Otomatik: zayıf kategoriyi punt", "Özel ağırlıklar"], key=f"{key}_preset")
        if choice == "Otomatik: zayıf kategoriyi punt":
            count = st.radio("Punt kategori sayısı", [1, 2], horizontal=True, key=f"{key}_auto_count")
            probs = engine.league_probabilities().loc[tid, list(CATEGORIES)].to_numpy()
            s = Strategy.adaptive(probs, count)
            st.caption("Rakibin gerçek tercihi bilinmiyor; bu bir strateji senaryosudur.")
        elif choice == "Özel ağırlıklar":
            weights = tuple(st.slider(CATEGORY_LABELS[c], 0.0, 3.0, 1.0, .1, key=f"{key}_{c}") for c in CATEGORIES)
            if sum(weights) == 0:
                st.error("En az bir kategori ağırlığı pozitif olmalı.")
                st.stop()
            s = Strategy("Özel", weights)
        else:
            s = Strategy.preset(choice)
        st.caption(" · ".join(f"{CATEGORY_LABELS[c]}: {w:g}" for c, w in zip(CATEGORIES, s.weights)))
        st.caption("Ağırlıklar tercih/fayda puanını değiştirir. Gerçek 9 kategori ve kazanma olasılıkları aynı kalır.")
        return s


def rank_table(engine: TradeEngine, view, *, changes_from=None) -> pd.DataFrame:
    df = view.ranks.rename(columns=CATEGORY_LABELS).copy()
    df.insert(0, "Takım", [engine.league.teams[t] for t in df.index])
    df["Ortalama sıra"] = view.ranks.mean(axis=1)
    df["Tam verili oyuncu"] = [f"{int(r.complete)}/{int(r.roster)}" for r in view.coverage.itertuples()]
    if changes_from is not None:
        df["Ortalama sıra kazancı"] = changes_from.ranks.mean(axis=1) - view.ranks.mean(axis=1)
    return df.sort_values("Ortalama sıra", kind="stable")


def render_rankings(mode: str) -> None:
    _, eng, _, _ = page(MODES[mode])
    view = eng.before[mode]
    source = eng.data.sources[mode]
    st.caption(f"Kaynak: {source.get('file', source.get('source_url'))} · tarih: {source.get('as_of', source.get('captured_at'))}")
    st.info("Her kategori için 1 en iyi sıradır; TO'da düşük değer iyidir. Eşitlikler ortalama sıra alır. FG% = toplam FGM / toplam FGA; FT% = toplam FTM / toplam FTA.")
    st.subheader("Tüm takımların kategori sıraları")
    st.dataframe(rank_table(eng, view).style.format(precision=2), hide_index=True, width="stretch")
    st.subheader("Aynı kadroların dönem toplamları")
    vals = view.totals.rename(columns=CATEGORY_LABELS)
    vals.index = [eng.league.teams[t] for t in vals.index]
    st.dataframe(vals.style.format({c: "{:.3f}" if c in ("FG%", "FT%") else "{:.1f}" for c in vals}), width="stretch")
    st.caption("Geçmiş ve sezon öncesi ekranları mevcut kadrolara uygulanır. Bench ve IL oyuncularının kaynakta bulunan dönem katkıları dahildir. Bu, geçmişte Yahoo'da aktif kadrodan kazanılmış takım istatistiği değildir.")
    missing = int((view.coverage.roster - view.coverage.complete).sum())
    if missing:
        st.caption(f"{missing} kadro kaydında eksik kaynak alanı var. Tablolar mevcut sayısal katkıları toplar; eksik katkılar tahmin edilmez. Karşılaştırma kısmi olabilir.")
    if mode == ROS:
        st.subheader("Rakiplere karşı kalan sezon gücü")
        probs = eng.league_probabilities().rename(columns={**CATEGORY_LABELS, "P_5_plus": "P(5+)"})
        probs.insert(0, "Takım", [eng.league.teams[t] for t in probs.index])
        st.dataframe(probs.style.format({"ECW": "{:.3f}", **{c: "{:.1%}" for c in ["P(5+)", *CATEGORY_LABELS.values()]}}), hide_index=True, width="stretch")
        st.caption("ECW = rakip başına beklenen kategori galibiyeti (0–9). P(5+) = tipik haftada en az 5 kategori kazanma ihtimali; lig puanı veya playoff'a kalma ihtimali değildir.")
    st.download_button("Kategori sıralarını CSV indir", rank_table(eng, view).to_csv(index=False),
                       file_name=f"ranks_{eng.league.league_id}_{mode}.csv", mime="text/csv")


def show_result(eng: TradeEngine, result: TradeResult, *, key: str) -> None:
    a, b = result.request.team_a, result.request.team_b
    st.subheader("Takas paketi")
    cols = st.columns(2)
    for col, tid, give in zip(cols, (a, b), (result.request.give_a, result.request.give_b)):
        with col:
            st.markdown(f"**{eng.league.teams[tid]} veriyor**")
            st.write(", ".join(eng.data.players.loc[p, "name"] for p in give))
            adj = result.adjustments[tid]
            for field, text in (("drop", "Kadrosundan bırakıyor"), ("add", "Boşta havuzundan ekliyor"), ("move_to_il", "IL'e yerleşiyor")):
                if adj[field]:
                    st.write(f"{text}: " + ", ".join(eng.data.players.loc[p, "name"] for p in adj[field]))
    assessment = result.assessments
    if assessment["mutual_benefit"]:
        st.success("Seçilen stratejilerle iki takımın da kalan sezon kategori beklentisi artıyor.")
    else:
        st.warning("Seçilen stratejilerle iki tarafın birden fayda sağladığı koşul karşılanmıyor.")
    st.subheader("Kalan sezon kazanma ihtimali ve iki tarafın faydası")
    for col, tid in zip(st.columns(2), (a, b)):
        with col:
            m = result.metrics.loc[tid]
            st.markdown(f"**{eng.league.teams[tid]}** · {result.strategies[tid].name}")
            st.metric("Rakip başına beklenen kategori galibiyeti", f"{m.ecw_after:.3f}", f"{m.ecw_delta:+.3f}")
            st.metric("Tipik haftada P(5+)", f"{m.win_after:.1%}", f"{m.win_delta * 100:+.2f} yüzde puan")
            st.metric("Stratejiye göre kategori beklentisi", f"{m.strategy_after:.3f}", f"{m.strategy_delta:+.3f}")
            st.caption(f"Önce: ECW {m.ecw_before:.3f}, P(5+) {m.win_before:.1%}")
    st.subheader("Kabul ve komisyon değerlendirmesi")
    st.write(f"Paket değer dengesi: **{assessment['fairness_ratio']:.0%}** · Komisyon değerlendirme riski: **{assessment['commissioner_risk']}**")
    st.caption(f"İnceleme: {assessment['review_type']} · bekleme: {assessment['review_time']} · son tarih: {assessment['deadline']} · değerlendirme tarihi: {assessment['analysis_date']}")
    for tid in (a, b):
        st.write(f"{eng.league.teams[tid]} için fayda/uyum puanı: {assessment['fit_scores'][tid]:.0f}/100")
    st.caption("Bu puanlar insan kabul olasılığı veya komisyon onay garantisi değildir. Piyasa dengesi kalan sezonun dengeli kategori değerinden, fayda iki tarafın ayrı stratejisinden hesaplanır.")
    tabs = st.tabs(list(MODES.values()))
    for tab, mode in zip(tabs, MODES):
        with tab:
            for tid in (a, b):
                st.markdown(f"**{eng.league.teams[tid]} — kategori değeri ve sıra değişimi**")
                frame = category_changes(result, mode, tid).rename(index=CATEGORY_LABELS)
                st.dataframe(frame.style.format(precision=3), width="stretch")
            with st.expander("Tüm ligin takas sonrası kategori sıralaması"):
                st.dataframe(rank_table(eng, result.after[mode], changes_from=result.before[mode]), hide_index=True, width="stretch")
            st.caption("Sıra kazancı pozitifse iyileşme vardır. Bu sekme yalnızca belirtilen kaynağı kullanır; olasılık paneli her zaman kalan sezon projeksiyonundandır.")
    st.subheader("Her rakibe karşı değişim")
    for tid in (a, b):
        with st.expander(eng.league.teams[tid]):
            st.dataframe(opponent_changes(eng, result, tid).rename(columns=CATEGORY_LABELS).style.format(precision=2), width="stretch")
            st.caption("Kategori sütunları kazanma ihtimalindeki yüzde puan değişimidir. P(5+) sütunları yüzde cinsindedir. Takas yapılan rakibin yeni kadrosu da hesaba katılır.")
    for note in result.notes:
        st.caption(note)
    payload = export_result(eng, result)
    st.download_button("Analizi JSON indir", payload, file_name=f"trade_{eng.league.league_id}.json", mime="application/json", key=f"{key}_download")
    if st.button("Senaryoyu karşılaştırmaya ekle", key=f"{key}_save"):
        saved = st.session_state.setdefault("trade_saved_scenarios", [])
        digest = hashlib.sha256(payload.encode()).hexdigest()
        if all(s["id"] != digest for s in saved):
            saved.append({"id": digest, "league_id": eng.league.league_id, "a": eng.league.teams[a],
                          "b": eng.league.teams[b], "a_ecw": float(result.metrics.loc[a, "ecw_delta"]),
                          "b_ecw": float(result.metrics.loc[b, "ecw_delta"]), "a_win": float(result.metrics.loc[a, "win_delta"]),
                          "b_win": float(result.metrics.loc[b, "win_delta"]), "payload": payload})
        st.success("Bu oturumdaki senaryo karşılaştırmasına eklendi.")


def request_fingerprint(engine: TradeEngine, req, sa: Strategy, sb: Strategy, day: dt.date) -> str:
    return json.dumps([engine.data.fingerprint, engine.league.league_id, engine.utilization,
                       asdict(req), asdict(sa), asdict(sb), day.isoformat()], sort_keys=True)
