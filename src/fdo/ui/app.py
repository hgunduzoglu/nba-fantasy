"""Fantasy Draft Optimizer — Streamlit girişi.

    streamlit run src/fdo/ui/app.py
"""

from __future__ import annotations

import streamlit as st

from fdo.ui import common

common.page("Fantasy Draft Optimizer", needs_data=False)

cfg = common.config()
lg = cfg.league
st.markdown(
    f"""
Yahoo Fantasy Basketball **{lg.season}** · **{lg.teams} takım** · H2H 9-Cat each category ·
{lg.rounds} tur snake{' (3RR açık)' if lg.third_round_reversal else ''} · koltuğunuz **{lg.my_seat}**.

**V1 hedefi:** 16/17'de hangi ikiliyi alırsanız 48/49'a hangi olasılıklı oyuncu havuzuyla
ulaşacağınızı ve bunun sezon boyu **beklenen kategori galibiyetine (ECW)** etkisini görmek.
"""
)

ds = st.session_state.dataset
c1, c2, c3 = st.columns(3)
c1.metric("Veri seti", "yüklü" if ds is not None else "yok",
          help=None if ds is None else f"hash {ds.content_hash}")
m = st.session_state.mock
c2.metric("Mock draft", f"pick {m.log.next_pick}/{lg.total_picks}" if m else "başlamadı")
c3.metric("Seed", st.session_state.seed)

st.markdown(
    """
### Sayfalar
1. **League & Data** — lig ayarları, CSV yükleme, manifest, validasyon, sentetik veri
2. **Projection Explorer** — Z/G değerleme, ağırlıklar ve punt presetleri
3. **Mock Draft** — 16×13 board, bot oynatma, manuel seçim, undo/replay, import/export
4. **Draft Assistant** — çift önerisi, 48/49 havuzu, karşılaştırma, senaryolar
5. **Team Dashboard** — takım × kategori P(win), kazanılabilir/sınırda/kaybedilmiş
6. **Realism Report** — bot gerçekçiliği ölçümleri
7. **Canlı Draft** — gerçek draft'ı elle takip: hızlı pick girişi, otomatik öneri, rakip stratejisi tahmini

### Değişmez ilkeler (özet)
- ADP yalnızca rakip davranışı ve kalma olasılığı içindir; oyuncu değeri projeksiyondan gelir.
- Öneriler **yalnızca ECW** ile sıralanır; Z/G yalnızca Explorer ve bot profillerinde.
- Punt yalnızca ranking'i etkiler; matchup modeli her zaman 9 kategoriyi sayar.
- Kalibre edilmemiş parametrelere dayanan olasılıklar """ + common.UNCALIBRATED + """ ile gösterilir.
"""
)
