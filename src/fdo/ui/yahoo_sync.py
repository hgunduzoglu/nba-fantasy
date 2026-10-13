"""Draft Assistant için Yahoo canlı draft senkronizasyon paneli (README §13.7, V2)."""

from __future__ import annotations

import streamlit as st

from fdo.ui import common
from fdo.yahoo_api import (
    ATTRIBUTION,
    AppCredentials,
    TokenProvider,
    TokenStore,
    YahooApiError,
    YahooAuthError,
    YahooClient,
    merge,
)
from fdo.yahoo_api.client import urllib_post
from fdo.yahoo_api.oauth import authorize_url, exchange_code


def _client() -> YahooClient:
    creds = AppCredentials.load()
    return YahooClient(TokenProvider(creds, TokenStore(), urllib_post))


def sync_once(league_key: str) -> None:
    m = common.mock()
    try:
        meta, results = _client().draft_results(league_key)
    except (YahooAuthError, YahooApiError) as e:
        st.session_state.yahoo_last = f"Hata: {e}"
        return
    new_log, rep = merge(m.log, results, set(common.dataset().draft_ids))
    st.session_state.yahoo_last = (f"{meta.get('name', league_key)} · draft_status={meta.get('draft_status')} · "
                                   + rep.summary())
    st.session_state.yahoo_report = rep
    if rep.added or rep.replaced_from:
        m.set_log(new_log)
        st.session_state.advisor_result = None
        st.rerun()


def panel() -> None:
    with st.expander("Yahoo canlı draft senkronizasyonu (V2)"):
        st.caption("Gerçek draft'ta pick'leri Yahoo Fantasy API'den okur (yalnızca okuma). Elle girilen pick "
                   "API ile çakışırsa elle girilen korunur. Uygulama bilgisi: `YAHOO_CLIENT_ID` / "
                   "`YAHOO_CLIENT_SECRET` ya da `~/.fdo/yahoo_app.json`; token `~/.fdo/yahoo_token.json`. "
                   + ATTRIBUTION)
        league = st.text_input("League key (örn. 466.l.12345)", st.session_state.get("yahoo_league", ""))
        st.session_state.yahoo_league = league
        try:
            creds = AppCredentials.load()
        except YahooAuthError as e:
            st.info(str(e))
            return
        if TokenStore().load() is None:
            st.markdown(f"1. [Yahoo'da yetkilendir]({authorize_url(creds)}) · 2. verilen kodu girin:")
            code = st.text_input("Yetkilendirme kodu", type="password")
            if code and st.button("Kodu kaydet"):
                try:
                    TokenStore().save(exchange_code(creds, code, urllib_post))
                    st.success("Bağlandı.")
                except (YahooAuthError, YahooApiError) as e:
                    st.error(str(e))
            return
        c1, c2 = st.columns(2)
        if c1.button("Şimdi çek", disabled=not league):
            sync_once(league)
        auto = c2.toggle("Otomatik (10 s)", value=False, disabled=not league)
        if auto and league:
            _auto(league)
        if st.session_state.get("yahoo_last"):
            st.caption(st.session_state.yahoo_last)
        rep = st.session_state.get("yahoo_report")
        if rep is not None:
            for e in rep.errors:
                st.error(e)
            for k, mine, api in rep.conflicts:
                st.warning(f"Pick {k}: elle girilen {common.name_of(mine)} ≠ Yahoo {common.name_of(api)} "
                           "(elle girilen korundu; düzeltmek için Mock Draft sayfasında geri alın)")


@st.fragment(run_every=10)
def _auto(league: str) -> None:
    sync_once(league)
