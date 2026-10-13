"""Streamlit sayfalarının ortak durumu ve yardımcıları (README §8).

``ui/`` dışında hiçbir modül Streamlit import etmez (İlke 11).
Durum ``st.session_state`` içinde: ``config``, ``dataset``, ``report``, ``mock``,
``seed``, ``weights``, ``advisor_result``.
"""

from __future__ import annotations

import math

import pandas as pd
import streamlit as st

from fdo.advisor.simulate import AdvisorContext, prepare_context
from fdo.bots.mock import MockDraft
from fdo.bots.universe import BotUniverse, build_universe
from fdo.config import Config, load_config
from fdo.ingest.load import Dataset

#: Reach sınıfı → (arka plan, rozet). Durum paleti: critical/warning; slide: mavi ton.
REACH_STYLE = {
    "bad": ("rgba(208, 59, 59, 0.35)", "▲▲"),
    "warn": ("rgba(250, 178, 25, 0.35)", "▲"),
    "slide": ("rgba(42, 120, 214, 0.25)", "▼"),
    "neutral": ("", ""),
}

UNCALIBRATED = ":orange-badge[uncalibrated]"
INDEPENDENCE = ":violet-badge[assumes_independence]"


def init_state() -> None:
    ss = st.session_state
    if "config" not in ss:
        ss.config = load_config()
    ss.setdefault("dataset", None)
    ss.setdefault("report", None)
    ss.setdefault("mock", None)
    ss.setdefault("seed", 7)
    ss.setdefault("weights", None)
    ss.setdefault("advisor_result", None)
    ss.setdefault("scenario_result", None)
    ss.setdefault("realism", None)


def page(title: str, *, needs_data: bool = True) -> None:
    st.set_page_config(page_title=f"FDO · {title}", layout="wide")
    init_state()
    st.title(title)
    banners()
    if needs_data and st.session_state.dataset is None:
        st.info("Önce **League & Data** sayfasından bir veri seti yükleyin ya da sentetik veri üretin.")
        st.stop()


def banners() -> None:
    ds: Dataset | None = st.session_state.get("dataset")
    if ds is None:
        return
    if ds.is_synthetic:
        st.error("**SENTETİK VERİ — gerçek oyuncu değeri değildir.**")
    unknown = [m.get("source_name", k) for k, m in ds.manifests.items()
               if m.get("license_status") == "unknown"]
    if unknown:
        st.warning(f"Kullanım şartları doğrulanmamış kaynak(lar): {', '.join(map(str, unknown))} "
                   "(`license_status: unknown`).")


def config() -> Config:
    return st.session_state.config


def dataset() -> Dataset:
    return st.session_state.dataset


def set_config(cfg: Config) -> None:
    st.session_state.config = cfg
    reset_draft()


def set_dataset(ds: Dataset | None, report) -> None:
    """Yeni veri seti oturumdaki öncekinin yerine geçer (sentetik/gerçek karışamaz)."""
    st.session_state.dataset = ds
    st.session_state.report = report
    reset_draft()


def reset_draft() -> None:
    st.session_state.mock = None
    st.session_state.advisor_result = None
    st.session_state.scenario_result = None


@st.cache_resource(show_spinner="Bot evreni hazırlanıyor…")
def _universe(_ds: Dataset, _cfg: Config, ds_hash: str, cfg_hash: str) -> BotUniverse:
    return build_universe(_ds, _cfg)


def universe() -> BotUniverse:
    return _universe(dataset(), config(), dataset().content_hash, config().config_hash)


@st.cache_resource(show_spinner="Taban doldurma tablosu simüle ediliyor (önbelleklenir)…")
def _context(_ds: Dataset, _cfg: Config, ds_hash: str, cfg_hash: str, seed: int) -> AdvisorContext:
    return prepare_context(_ds, _cfg, seed, universe=_universe(_ds, _cfg, ds_hash, cfg_hash))


def advisor_context() -> AdvisorContext:
    return _context(dataset(), config(), dataset().content_hash, config().config_hash,
                    int(st.session_state.seed))


def mock() -> MockDraft:
    m = st.session_state.mock
    if m is None:
        m = MockDraft(dataset(), config(), int(st.session_state.seed), universe())
        st.session_state.mock = m
    return m


def name_of(pid: str) -> str:
    return str(dataset().names().get(pid, pid))


def fmt_prob(p: float, se: float | None = None, uncalibrated: bool = True) -> str:
    """``≈%62 ± 2`` biçimi (kalibre edilmemişse ``≈``)."""
    if p is None or (isinstance(p, float) and math.isnan(p)):
        return "—"
    s = f"{'≈' if uncalibrated else ''}%{100 * p:.0f}"
    if se is not None and not math.isnan(se):
        s += f" ± {100 * se:.0f}"
    return s


def fmt_pick(v: float, horizon: int | None = None) -> str:
    if v is None or (isinstance(v, float) and math.isinf(v)):
        return f"≥{horizon}" if horizon else "—"
    return f"{v:.0f}"


def format_sources(sources: list[dict]) -> str:
    """``projections: Yahoo… (alındı 2026-10-12, as_of 2026-10-12)`` biçimi."""
    parts = []
    for s in sources:
        extra = f", as_of {s['as_of']}" if s.get("as_of") else ""
        parts.append(f"{s['kind']}: {s['source_name']} (alındı {s['retrieved_at']}{extra})")
    return " · ".join(parts)


def sources_caption(ds: Dataset) -> str:
    return format_sources(ds.sources())


def state_key(log) -> str:
    """Draft state anahtarı (önbellek için): config'teki sıra + seçilen oyuncular."""
    import hashlib

    blob = "|".join(p.player_id for p in log.picks).encode()
    return f"{len(log)}:{hashlib.sha1(blob).hexdigest()[:12]}"


ADVISE_CACHE_SIZE = 32


def advise(log, *, mode: str, pins=(), pin_pairs=(), conditional: bool = True, uncertainty: bool = False,
           progress=None):
    """Advisor sonucu; ``(veri, config, state, seed, parametreler)`` anahtarıyla önbelleklenir (§8).

    Önbellek oturum durumundadır (``st.cache_resource`` değil): hesap sırasında ilerleme çubuğu
    güncellenir ve önbellekli fonksiyon içindeki Streamlit çağrıları tekrar oynatılamaz.
    """
    from fdo.advisor.pairs import recommend

    key = (dataset().content_hash, config().config_hash, int(st.session_state.seed), state_key(log), mode,
           tuple(pins), tuple(tuple(p) for p in pin_pairs), conditional, uncertainty)
    cache = st.session_state.setdefault("advise_cache", {})
    if key in cache:
        return cache[key]
    res = recommend(advisor_context(), log, mode=mode, pinned_players=list(pins),
                    pinned_pairs=list(pin_pairs), conditional_fill=conditional, uncertainty=uncertainty,
                    progress=progress)
    cache[key] = res
    while len(cache) > ADVISE_CACHE_SIZE:
        cache.pop(next(iter(cache)))
    return res


def style_reach(df: pd.DataFrame, cls: pd.DataFrame):
    """Hücre bazında reach rengi (``cls`` aynı şekilde sınıf etiketleri)."""
    return df.style.apply(lambda _: cls.map(lambda c: f"background-color: {REACH_STYLE[c][0]}"
                                            if REACH_STYLE.get(c, ("",))[0] else ""), axis=None)


def diverging_bg(v, vmax: float = 3.0) -> str:
    """Diverjan hücre arka planı: pozitif mavi, negatif kırmızı, 0 nötr (renksiz)."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return ""
    if math.isnan(x) or x == 0:
        return ""
    a = min(abs(x) / vmax, 1.0) * 0.45
    rgb = "42, 120, 214" if x > 0 else "227, 73, 72"
    return f"background-color: rgba({rgb}, {a:.2f})"


def prob_bg(p) -> str:
    """P(win) hücresi: 0.5 nötr, >0.5 mavi, <0.5 kırmızı."""
    try:
        return diverging_bg(float(p) - 0.5, 0.5)
    except (TypeError, ValueError):
        return ""
