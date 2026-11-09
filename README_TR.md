# Fantasy Trade Lab / Fantasy Draft Optimizer (FDO)

İngilizce sürüm: [README.md](README.md).

Trade Lab'in kapsamı, veri denetimi, model formülleri, testleri ve açık sınırlamaları:
[Claude / geliştirici devir raporu](docs/TRADE_LAB_HANDOFF.md).

## Sezon içi Trade Lab

`streamlit run src/fdo/ui/app.py` ile açılır. Varsayılan başlangıç artık Trade Lab'dir;
önceki draft araçları arşiv menülerinden kullanılabilir.

- **Üç ayrı lig sıralaması:** sezon öncesi projeksiyon, gerçekleşen sezon toplamı ve güncel
  kalan sezon projeksiyonu. Her biri güncel kadroları kullanır. Gerçekleşen görünüm,
  oyuncuların mevcut kadrolara uygulanmış sezon toplamıdır; Yahoo'da geçmişte aktif
  slotlardan kazanılmış takım istatistikleri veya geçmiş puan tablosu değildir.
- **Takas Analizi:** iki taraf için kategori değerleri ve lig sıralarındaki değişim,
  kalan sezon ECW ve tipik haftada P(5+) değişimi, her rakibe karşı karşılaştırma.
  Her iki takımın yeni kadrosu aynı anda değerlendirilir. Stratejiler ayrı seçilir.
- **Takas Önerileri:** 1x1, 2x1, 1x2, 2x2 ve isteğe bağlı 3x2/2x3 paketleri. Her iki tarafın
  stratejiye göre ECW ve P(5+) eşiklerini geçen paketler, ortak fayda ve paket dengesiyle
  sıralanır. Çok oyunculu arama kısa liste/bütçeyle sınırlıdır; tüm olası paketlerin
  tarandığı iddia edilmez. Kabul puanı ve komisyon riski sezgiseldir; insan kabulü veya
  komisyon onayı için kalibre edilmiş olasılık değildir.
- **Punt:** dengeli, tek/çift punt, özel 0–3 ağırlıklar veya zayıf kategoriye göre varsayımsal
  rakip stratejisi. Fiziksel kazanma olasılıkları ve ligdeki dokuz kategori değiştirilmez.
- **Kadro planı:** normal kapasite ve IL ayrı tutulur. Eşit olmayan paketlerde bırakılacak
  ve eklenecek oyuncular açıkça gösterilir. Boşta havuzundan eklemeler waiver/alım hakkı
  koşullarına bağlıdır. Önceden var olan boş slotlar takas faydası olarak doldurulmaz.
- Analizler JSON, sıralamalar CSV olarak indirilebilir; senaryolar aynı oturumda karşılaştırılır.

Veri `data/real/rosters.json`, `league_info.json`, `player_stat_pages.json`, eski
`players_yahoo_*.csv` ve `projections_yahoo_*.csv` dosyalarından okunur. Yeni katman
`fdo.trade` içindedir; Streamlit bağımlılığı yoktur. Draft koltuğu ile Yahoo takım ID'si
ayrıdır. Varsayılan takım eldeki tek takım fikstüründen seçilir ve kenar çubuğundan
değiştirilebilir. `Max Teams` yerine gerçekten kadrosu bulunan takım sayısı kullanılır.

Yeni kişisel Yahoo lig export'ları Git dışında, yerelde tutulur. Yeni bir klonda
Trade Lab için bu üç JSON dosyasını ayrıca sağlamak gerekir; dosya sözleşmesi
[devir raporunda](docs/TRADE_LAB_HANDOFF.md#6-yerel-çalıştırma-ve-veri-sözleşmesi) açıklanır.

FG% = toplam FGM / toplam FGA, FT% = toplam FTM / toplam FTA. Kaynaktaki yüzde
sütunlarının ortalaması alınmaz. Sezon öncesi maç başına veri GP ile çarpılır; diğer
iki kaynak zaten dönem toplamıdır. Hiçbir kaynak diğerinin eksik alanını doldurmaz.
Ham hatalı/eksik veriler değiştirilmez; sıralamalar eldeki sayısal katkıları toplar ve
kapsamı gösterir. ROS modeli yalnızca tam ve kullanılabilir katkıları içerir; eksik
oyuncular kadrodan silinmez ve otomatik öneri paketlerine dahil edilmez.

ROS olasılıkları toplamları **anlık görüntü tarihinden NBA sezon sonuna kadar kalan
haftalara** yayar; kalan GP'yi 82'ye bölmez. Tarih seçimi yalnızca takas son tarihi
kontrolündedir, eski projeksiyonları yeni tarihe tahmin etmez. Model Normal yaklaşım,
oyuncular arası bağımsız varyans ve ayarlanabilir ortalama lineup kullanım oranı
kullanır. P(5+) ayrıca kategori bağımsızlığı varsayar. Bunlar kalibre edilmemiş
tipik hafta göstergeleridir; gerçek haftalık lineup, playoff veya sezon simülasyonu değildir.
Eksik rakip H2H fikstürleri kullanılmaz; tüm rakiplerle eşit ağırlıklı karşılaştırılır.
Kaynak dosyaları değiştiğinde önbellek dosya imzasıyla yenilenir.

Doğrulama: `python -m pytest tests/unit/test_trade.py tests/integration/test_trade_ui.py`.
CLI: `python scripts/analyze_trade.py --help` (oyuncu kimlikleri Yahoo ID'leridir).

---

## Draft araçlarının referans dokümanı

Yahoo Fantasy Basketball 2026–27 için **16 takımlı, H2H 9-Cat Each Category** draft simülatörü ve karar destek sistemi.

> **Durum:** V1 (M0–M6) implementasyonu tamamlandı; sentetik veriyle uçtan uca çalışır ve testleri geçer.
> Gerçek veri kaynağı kararı ve manifest'ler kullanıcı eylemidir (§5.1, §10 M0).
> Bu dosya projenin referans dokümanıdır. Kodla çeliştiği yerde ya kod düzeltilir ya da README bilinçli olarak güncellenir.
>
> **Normatif dil:** **ZORUNLU** = kabul kriteri, **ÖNERİLİR** = gerekçesi olmadan sapılmaz, **OPSİYONEL** = zaman kalırsa.

---

## İçindekiler

1. [Amaç ve kapsam](#1-amaç-ve-kapsam)
2. [Değişmez ilkeler](#2-değişmez-ilkeler)
3. [Lig konfigürasyonu](#3-lig-konfigürasyonu)
4. [Mimari ve repo yapısı](#4-mimari-ve-repo-yapısı)
5. [Veri: kaynaklar, yasal durum, şema, validasyon](#5-veri-kaynaklar-yasal-durum-şema-validasyon)
6. [Bileşen şartnameleri](#6-bileşen-şartnameleri)
7. [Simülasyon gerçekçiliği ölçümü](#7-simülasyon-gerçekçiliği-ölçümü)
8. [Streamlit arayüzü](#8-streamlit-arayüzü)
9. [Test stratejisi](#9-test-stratejisi)
10. [Kilometre taşları ve kabul kriterleri](#10-kilometre-taşları-ve-kabul-kriterleri)
11. [Performans bütçeleri](#11-performans-bütçeleri)
12. [Bilinen sınırlamalar ve açık sorular](#12-bilinen-sınırlamalar-ve-açık-sorular)
13. [V2](#13-v2)
14. [Kurulum ve çalıştırma](#14-kurulum-ve-çalıştırma)
15. [Sözlük](#15-sözlük)

---

## 1. Amaç ve kapsam

### 1.1 V1'in tek cümlelik hedefi

> 16. sıradan draft ederken, **16–17. seçimlerde hangi ikiliyi alırsam 48–49. seçimlerime hangi olasılıklı oyuncu havuzuyla ulaşacağımı** ve bunun sezon boyu rakiplere karşı **beklenen kategori galibiyetine (ECW)** etkisini görebilmek.

### 1.2 V1 kapsamı

| Dahil (V1) | Hariç (V2+) |
|---|---|
| CSV ingestion, validasyon, veri manifesti | Yahoo API / OAuth / canlı senkronizasyon |
| Z-score (varsayılan) ve G-score (alternatif) ranking | Geçmiş sezon backtest'i (yalnızca arayüzü V1'de) |
| Hacim ağırlıklı FG%/FT%, custom ağırlıklar, punt presetleri | Günlük lineup çözücü, NBA takvimi, B2B |
| Snake draft motoru (3RR konfigüre edilebilir), undo/replay, export | Sakatlık senaryoları, rookie rol modelleri |
| Thurstone ADP botları, bot profilleri, ADP fallback | 13 tur boyunca derin rollout / beam search / MCTS |
| Pozisyon uygunluğu ve slot ataması | H-score tarzı gelecek pick ağırlık optimizasyonu |
| Varyans destekli haftalık matchup modeli (Normal yaklaşım) | Tam Monte Carlo sezon simülasyonu |
| Survival probability, çift-pick önerisi, sonraki çifte kadar rollout | nba_api ile varyans kalibrasyonu |
| Gerçekçilik raporu, reach uyarıları, alternatif kadro senaryoları (hafif) | Veritabanı, ayrı backend, deployment |

### 1.3 Teknoloji

Python 3.11+, NumPy, Pandas, SciPy, Streamlit, pytest, PyYAML. Başka zorunlu bağımlılık yok. Veritabanı yok, durum JSON/CSV dosyalarında tutulur. İnternet bağlantısı gerekmez.

---

## 2. Değişmez ilkeler

Bu kurallar kod incelemesinde kontrol edilir ve mümkün olduğunda testle korunur.

1. **ADP ≠ değer.** ADP yalnızca *rakip davranışı ve kalma olasılığı* için kullanılır. Projeksiyon yalnızca *oyuncu katkısı* için kullanılır. `valuation/` ve `matchup/` paketleri ADP tablosunu **import edemez**. Bu bir test ile denetlenir (§9.3). Tek istisna ADP imputasyonudur (§5.6): ADP'si olmayan oyuncu için değer sırasından ADP *tahmini* üretilir ve bu tahmin `adp_status=imputed` olarak işaretlenir.
2. **Ranking ≠ objective.** Z ve G yalnızca Projection Explorer'da ve bot profillerinde kullanılır. Kullanıcıya yapılan çift-pick önerileri **yalnızca ECW** (expected category wins) ile sıralanır.
3. **Punt yalnızca ranking'i etkiler.** Bir kategorinin ağırlığı `0` olduğunda o kategori oyuncu değerinden düşer. Matchup modeli ise **her zaman 9 kategoriyi** sayar.
4. **Oranlar daima toplamdan hesaplanır.** `FG% = ΣFGM / ΣFGA`, `FT% = ΣFTM / ΣFTA`. Yüzdelerin ortalaması hiçbir yerde alınmaz.
5. **TO düşük olan iyidir.** Bu kural tek bir yerde (`config.lower_is_better`) tanımlanır ve her modül oradan okur.
6. **Simetrik ADP uzaklığı yasak.** `−|ADP − pick|` biçimindeki hiçbir skor bot kararında kullanılmaz. Düşmüş (ADP'si geçmiş) bir oyuncunun seçilme olasılığı pick ilerledikçe **artmalıdır** (§9 testi).
7. **Sert yasak yok, kuyruk var.** Bot reach'leri hard ban ile engellenmez. Uç olaylar modelin dağılım kuyruğundan gelir ve gerçekçilik raporunda ölçülür.
8. **Uydurma gerçek veri yok.** Gerçek oyuncu adıyla uydurma istatistik yazılmaz. Sentetik veri `is_synthetic=true` ve `SYN_` önekli adlarla işaretlenir. Sentetik ve gerçek veri aynı oturumda karıştırılamaz (§5.7).
9. **Tekrarlanabilirlik.** Her rastgele işlem dışarıdan verilen `numpy.random.Generator` ile çalışır. Aynı veri, config ve seed aynı çıktıyı üretir.
10. **Dürüst olasılık gösterimi.** Kalibre edilmemiş parametrelere dayanan her olasılık UI'da `uncalibrated` rozetiyle gösterilir. Monte Carlo tahminleri standart hatasıyla (SE) birlikte gösterilir.
11. **Saf çekirdek.** `ui/` dışındaki hiçbir modül Streamlit import etmez. Algoritmalar saf fonksiyonlar ya da açık bağımlılıklı sınıflardır.

---

## 3. Lig konfigürasyonu

### 3.1 Kesinleşmiş ayarlar — `config/league.yaml`

```yaml
league:
  platform: yahoo
  season: "2026-27"
  teams: 16
  my_seat: 16
  rounds: 13               # toplam 208 seçim
  draft_type: snake
  third_round_reversal: false   # varsayılan kapalı; true yapılabilir

scoring:
  format: h2h_each_category
  categories: [FG_PCT, FT_PCT, FG3M, PTS, REB, AST, STL, BLK, TOV]
  lower_is_better: [TOV]
  ratio_categories:
    FG_PCT: {makes: FGM, attempts: FGA}
    FT_PCT: {makes: FTM, attempts: FTA}

roster:
  slots: {PG: 1, SG: 1, G: 1, SF: 1, PF: 1, F: 1, C: 2, UTIL: 2, BN: 3}   # 10 aktif + 3 bench = 13
  active_slots: [PG, SG, G, SF, PF, F, C, UTIL]
  slot_eligibility:
    PG:   [PG]
    SG:   [SG]
    G:    [PG, SG]
    SF:   [SF]
    PF:   [PF]
    F:    [SF, PF]
    C:    [C]
    UTIL: [PG, SG, SF, PF, C]
    BN:   [PG, SG, SF, PF, C]
```

Bu ligde `FC` slotu **yoktur** ve iki `C` slotu vardır. Config yüklenirken `sum(slots) == rounds` kontrolü yapılır (13 = 13).

### 3.2 Lig kuralları — doğrulanan ve doğrulanmamış ayarlar

Ayarlar kullanıcı tarafından doğrulandı (12–13 Ekim 2026). Bir alan `null` yapılırsa doğrulanmamış sayılır.

```yaml
unverified:
  tie_value: 0.5              # doğrulandı: kategori beraberliği T yazılır (5-3-1 gibi); win% için 0.5
  pick_timer_seconds: 45      # doğrulandı: gerçek draft'ta advisor bütçesi (mock'ta süre yok)
  lineup_lock: daily_today    # doğrulandı: maç başlayana kadar günlük değişiklik → utilization (§6.6.1)
  il_slots: 3                 # doğrulandı: draft kadrosuna dahil değil (13 pick)
  il_plus_slots: 0            # doğrulandı: IL+ yok; Q (questionable) oyuncu hiçbir etki almaz (§5.8)
  playoff_weeks: 3            # doğrulandı: fantasy playoff'u son 3 eşleşme haftası (V2 takvim)
  keepers: false
  position_limits_enforced_in_draft: true   # doğrulandı: Yahoo draft sırasında pozisyon kuralını uygular
```

Ligde otomatik draft eden menajer yoktur (kullanıcı); bot karışımında `AutoDrafter` 0'dır (§6.4.3).

`null` değerler hiçbir hesapta sessizce varsayılana çevrilmez. Hesabı etkileyen bir değer `null` ise ilgili ekranda uyarı gösterilir.

### 3.3 Pick sırası

Genel pick numarası `k` (1-tabanlı), takım sayısı `T` için:

```
r = ceil(k / T)                 # tur
p = k − (r − 1)·T               # tur içi sıra (1..T)

ileri(r):
  3RR kapalı: r tek ise ileri, çift ise geri
  3RR açık  : r = 1 ileri, r = 2 geri, r ≥ 3 için r çift ise ileri, tek ise geri

seat(k) = p            (ileri ise)
        = T + 1 − p    (geri ise)
```

**Beklenen değerler (ZORUNLU test):**

| Mod | Seat 16'nın seçimleri | Bitişik çiftler |
|---|---|---|
| 3RR kapalı | 16, 17, 48, 49, 80, 81, 112, 113, 144, 145, 176, 177, 208 | (16,17) (48,49) (80,81) (112,113) (144,145) (176,177), tek: 208 |
| 3RR açık | 16, 17, 33, 64, 65, 96, 97, 128, 129, 160, 161, 192, 193 | (16,17) (64,65) (96,97) (128,129) (160,161) (192,193), tek: 33 |

"Turn" (sıra bloğu) kavramı koddan **türetilir**, hard-code edilmez. Turn, kullanıcının arada rakip seçimi olmayan ardışık seçimlerinden oluşan maksimal kümedir. Advisor turn'lerle çalışır. 1 elemanlı turn tek seçim, 2 elemanlı turn çift seçimdir.

---

## 4. Mimari ve repo yapısı

### 4.1 Bileşenler ve bağımlılık yönü

```
                ┌──────────────┐
                │ 1. ingest    │  CSV → doğrulanmış tablolar, manifest, ADP fallback
                └──────┬───────┘
          ┌────────────┼──────────────────────┐
          ▼            ▼                      ▼
 ┌──────────────┐ ┌──────────────┐   ┌──────────────┐
 │ 2. valuation │ │ 5. roster    │   │ 3. draft     │  snake sırası, event log
 │  Z / G / W   │ │ eligibility  │   │   engine     │
 └──────┬───────┘ └──────┬───────┘   └──────┬───────┘
        │                │                  │
        │         ┌──────▼───────┐          │
        │         │ 6. matchup   │◄─────────┤  (kadrolar draft state'ten)
        │         │  ECW modeli  │          │
        │         └──────┬───────┘          │
        ▼                │                  ▼
 ┌──────────────┐        │          ┌──────────────┐
 │ 4. bots      │◄───────┼──────────│ draft state  │
 │ Thurstone    │        │          └──────────────┘
 └──────┬───────┘        │
        └───────┬────────┘
                ▼
        ┌──────────────┐
        │ 7. advisor   │  survival, çift önerisi, rollout, senaryolar
        └──────┬───────┘
               ▼
        ┌──────────────┐
        │ 8. ui        │  Streamlit (tek Streamlit bağımlısı)
        └──────────────┘
   + realism/  (bot çıktısı ölçümü; advisor ve ui tarafından kullanılır)
```

Kurallar:
- Oklar tek yönlüdür ve döngüsel import yoktur.
- `valuation` ve `matchup` ADP okuyamaz (İlke 1).
- `bots` ADP'yi ve opsiyonel olarak bot profili için `valuation` çıktısını okuyabilir.
- `advisor` için ECW tek optimizasyon hedefidir.

### 4.2 Repo yapısı

```text
fantasy-draft-optimizer/
  README.md
  pyproject.toml
  config/
    league.yaml               # §3
    model.yaml                # bot, varyans, advisor parametreleri (§6)
  data/
    synthetic/                # üretilen sentetik veri (repoda olabilir)
    real/                     # kullanıcının gerçek CSV'leri (+ raw/ ham dışa aktarımlar)
    manifests/                # her veri seti için manifest (§5.2)
  src/fdo/
    __init__.py
    config.py                 # YAML yükleme + doğrulama (dataclass)
    types.py                  # ortak tipler: PlayerId, Category, Slot vb.
    ingest/
      schema.py               # kolon tanımları, tipler
      load.py                 # CSV okuma, kolon eşleme
      validate.py             # kurallar → ValidationReport
      adp_fallback.py         # ADP güven sınıfları + imputasyon
      synthetic.py            # sentetik veri üretici
    valuation/
      pool.py                 # referans havuz iterasyonu
      zscore.py
      gscore.py
      weights.py              # ağırlıklar, punt presetleri
    draft/
      order.py                # pick → seat, turn'ler
      events.py               # DraftPick event, log, undo/replay
      state.py                # event log'dan türetilen DraftState
      io.py                   # draft log CSV/JSON import/export
    bots/
      thurstone.py            # algılanan sıra, seçim
      profiles.py             # MarketFollower, ValueHunter, ...
      league_mix.py           # 15 rakibe profil ataması
    roster/
      eligibility.py          # pozisyon ayrıştırma, slot uygunluğu
      assignment.py           # optimal slot ataması, tamamlanabilirlik
    matchup/
      player_week.py          # oyuncu haftalık ortalama/varyans
      team_totals.py          # takım toplamları
      fill.py                 # eksik kadro doldurma profilleri
      ecw.py                  # P(win), ECW, kategori matrisi
    advisor/
      simulate.py             # rakip seçim simülasyonu (CRN)
      survival.py             # kalma olasılığı
      pairs.py                # aday üretimi + çift skorlama
      rollout.py              # sonraki turn'e kadar rollout
      scenarios.py            # alternatif kadro arketipleri (hafif)
      deep.py                 # V2: tam ufuk rollout + kademeli yarılama (§13.3)
      uncertainty.py          # V2: sakatlık/rol senaryoları (§13.5)
    realism/
      metrics.py              # pick−ADP dağılımı, reach, çeşitlilik
      report.py
    evaluation/
      interface.py            # SeasonEvaluator protokolü
      evaluators.py           # V2: projeksiyon+gürültü ve game log değerlendiricileri (all-play)
      backtest.py             # V2: strateji karşılaştırması (§13.1)
    schedule/                 # V2: takvim, fantasy haftaları, günlük lineup (§13.4)
    calibration/              # V2: varyans (§13.2) ve bot (§13.6) kalibrasyonu
    ui/
      app.py
      pages/
        1_League_and_Data.py
        2_Projection_Explorer.py
        3_Mock_Draft.py
        4_Draft_Assistant.py
        5_Team_Dashboard.py
        6_Realism_Report.py
  scripts/
    make_synthetic.py
    run_mock_batch.py         # N mock → realism raporu
    profile_advisor.py        # süre ölçümü
    estimate_utilization.py   # lineup kilidine göre utilization tahmini (§6.6.1)
    import_yahoo_json.py      # Yahoo JSON → şema CSV + manifest
    fetch_nba_schedule.py     # V2: NBA takvimi → schedule CSV
    fetch_gamelogs_nba_api.py # V2: game log'ları (nba_api, opsiyonel)
    calibrate_variance.py     # V2: φ, oyuncu varyansı, kategori korelasyonu
    calibrate_bots.py         # V2: σ₀/σ₁ uyumu, survival güvenilirliği
    backtest.py               # V2: strateji karşılaştırması
  tests/
    unit/ ...                 # modül başına
    statistical/ ...          # seed'li dağılım testleri
    integration/ ...          # uçtan uca mock
    test_architecture.py      # import kuralları
```

---

## 5. Veri: kaynaklar, yasal durum, şema, validasyon

### 5.1 Yasal durum ve kaynak politikası

**Bu repo hiçbir web sitesinden veri çekmez** (scraper, gizli API veya paywall aşma yok). Bütün veri, kullanıcının kendi sağladığı CSV dosyalarından gelir. Bir kaynağın verisinin bu şekilde kullanılıp kullanılamayacağına, o kaynağın kullanım şartlarını okuyarak **kullanıcı karar verir** ve kararını manifest'e yazar (§5.2). Kod bu kararı doğrulayamaz. Yalnızca kaydeder ve UI'da gösterir.

Aşağıdaki tablodaki durumlar 12 Ekim 2026 itibarıyla **doğrulanmamıştır**. "Kullanıcı eylemi" sütunu yapılması gerekenleri gösterir.

| Kaynak | Sağladığı | Erişim | Lisans / şart durumu | Kullanıcı eylemi | V1 rolü |
|---|---|---|---|---|---|
| Kullanıcının kendi projeksiyonu | Her şey | Tam | Kullanıcıya ait | — | Projeksiyon |
| Hashtag Basketball | Projeksiyon, ADP | Sayfa / premium | **Doğrulanmadı**: export ve kişisel kullanım şartları | ToS ve abonelik şartlarını oku, manifest'e yaz | Projeksiyon (izin varsa) |
| Yahoo Draft Analysis | Yahoo ADP, olası % drafted | Public sayfa | **Doğrulanmadı**: public sayfa otomatik alma izni anlamına gelmez | Manuel kopyalama şartlarını kontrol et | ADP |
| Fantasy Alarm ADP / Mock | ADP download, mock CSV | Ücretsiz sayfa | **Doğrulanmadı** | Download şartlarını kontrol et | ADP / bot karşılaştırma |
| Yahoo Fantasy API | Lig ayarı, pozisyon, draft sonuçları | Başvuru ve onay, varsayılan salt-okunur, atıf zorunlu | Yahoo API sözleşmesi | V2'de başvuru | V2 |
| nba_api (MIT istemci) | Tarihsel game log | Ücretsiz | İstemci MIT, NBA.com verisi kendi şartlarına tabi | V2'de şartları oku | V2: varyans kalibrasyonu |
| Sentetik üretici | Test verisi | Yerel | Repo'ya ait | — | Geliştirme ve test |

**Yahoo pozisyon uygunluğu**, V1'de kullanıcının CSV'sindeki `yahoo_positions` kolonundan okunur. Yahoo'nun gerçek pozisyon uygunluğu NBA pozisyonundan farklı olabilir. Kolon boşsa oyuncu draft havuzuna girmez ve validasyon hatası üretilir.

### 5.2 Veri manifesti (ZORUNLU)

Her gerçek veri dosyasının yanında bir manifest bulunur: `data/manifests/<dosya_adı>.yaml`.

```yaml
file: data/real/projections_hashtag_2026-10-11.csv
kind: projections            # projections | adp | players | variance | draft_log
source_name: "Hashtag Basketball"
source_url: "https://..."
retrieved_at: "2026-10-11"
retrieved_by: "manual export"
license_status: personal_use_confirmed   # personal_use_confirmed | assumed | unknown
license_notes: "Abonelik şartları md. X okundu; kişisel kullanım."
season: "2026-27"
basis: per_game
is_synthetic: false
```

- `license_status: unknown` → dosya yüklenir, fakat UI'da kalıcı sarı uyarı gösterilir.
- Manifest yoksa → dosya **yüklenmez**.
- Her öneri ve export, kullandığı manifest'lerin `source_name` ve `retrieved_at` alanlarını taşır.

### 5.3 Dosya şemaları

Projeksiyon ve ADP **ayrı dosyalardır** ve `player_id` üzerinden birleşir. Böylece İlke 1 veri katmanında da korunur.

#### `players.csv` — kimlik ve uygunluk

| Kolon | Tip | Zorunlu | Açıklama |
|---|---|---|---|
| `player_id` | str | ✔ | Provider'dan bağımsız iç ID (örn. `p_0001`) |
| `name` | str | ✔ | Görünen ad |
| `nba_team` | str | | 3 harfli kod |
| `yahoo_positions` | str | ✔ | Virgülle ayrılmış: `PG,SG` / `SF,PF` / `C` (izinli: PG, SG, SF, PF, C) |
| `yahoo_player_id` | str | | V2 eşleşmesi için |
| `nba_person_id` | str | | V2 nba_api eşleşmesi için |
| `aliases` | str | | `;` ile ayrılmış alternatif yazımlar |
| `is_synthetic` | bool | ✔ | |
| `injury_status` | str | | Kaynağın durum etiketi (`O`, `Q`, `NA`…); `NA` draft edilmez (§5.8) |
| `is_rookie` | bool | | V2 senaryolarında daha geniş belirsizlik (§13.5) |

#### `projections_<kaynak>_<tarih>.csv` — maç başına projeksiyon

| Kolon | Tip | Zorunlu | Birim |
|---|---|---|---|
| `player_id` | str | ✔ | |
| `projected_gp` | float | ✔ | Beklenen NBA maç sayısı (0–82) |
| `minutes` | float | | Dakika / maç |
| `fgm`, `fga` | float | ✔ | / maç |
| `ftm`, `fta` | float | ✔ | / maç |
| `fg3m`, `pts`, `reb`, `ast`, `stl`, `blk`, `tov` | float | ✔ | / maç |
| `projection_source` | str | ✔ | |
| `as_of` | date | ✔ | |
| `is_synthetic` | bool | ✔ | |
| `notes` | str | | Rol / sakatlık notu (V1'de hesaplamaya girmez) |

Ham yüzde kolonu yoktur. Yüzdeler `fgm/fga`, `ftm/fta` üzerinden türetilir. Kaynak dosyada yalnızca yüzde ve deneme sayısı varsa, `load.py` içindeki kolon eşleyici `fgm = fg_pct × fga` dönüşümünü yapar ve bunu bir validasyon notu olarak kaydeder.

#### `adp_<kaynak>_<tarih>.csv` — draft pazarı

| Kolon | Tip | Zorunlu | Açıklama |
|---|---|---|---|
| `player_id` | str | ✔ | |
| `adp` | float | | Boş olabilir → fallback (§5.6) |
| `adp_std` | float | | Kaynak veriyorsa Thurstone σ için kullanılır |
| `adp_min`, `adp_max` | float | | Kaynak veriyorsa |
| `pct_drafted` | float | | 0–100; kaynak veriyorsa güven sınıfında kullanılır |
| `default_rank` | float | | Platformun varsayılan ön sıralaması (AutoDrafter botu için) |
| `adp_source` | str | ✔ | Örn. `yahoo_draft_analysis` |
| `adp_window` | str | | Örn. `preseason_all` / `last_7_days` (kaynakta ne yazıyorsa) |
| `as_of` | date | ✔ | |
| `is_synthetic` | bool | ✔ | |

#### `variance_<kaynak>.csv` — OPSİYONEL (V1'de genelde yok)

| Kolon | Tip | Açıklama |
|---|---|---|
| `player_id` | str | |
| `stat` | str | `fgm, fga, ftm, fta, fg3m, pts, reb, ast, stl, blk, tov` |
| `per_game_var` | float | Maç başına varyans |
| `n_games` | int | Tahmin örneklemi |
| `seasons` | str | |

Bu dosya yoksa §6.6.2'deki model varsayılanları kullanılır ve sonuçlar `uncalibrated` olarak etiketlenir. V2'de `scripts/calibrate_variance.py` bu dosyayı game log'larından üretir (§13.2).

#### `schedule_<kaynak>.csv` — V2, OPSİYONEL (§13.4)

| Kolon | Tip | Zorunlu | Açıklama |
|---|---|---|---|
| `game_date` | date | ✔ | Yerel (ET) maç tarihi |
| `home_team`, `away_team` | str | ✔ | `players.nba_team` ile aynı kodlar (GS, NY, SA… gibi alternatifler çevrilir) |
| `game_id` | str | | |

#### `gamelogs_<kaynak>.csv` — V2, OPSİYONEL (§13.1, §13.2)

| Kolon | Tip | Zorunlu | Açıklama |
|---|---|---|---|
| `player_id` | str | ✔ | Yoksa `name` ile eşlenir; eşleşmeyen satırlar düşürülüp uyarılır |
| `game_date` | date | ✔ | |
| `season` | str | ✔ | Örn. `2025-26` |
| `nba_team`, `minutes` | str, float | | |
| `fgm` … `tov` | float | ✔ | Maçtaki değerler |

#### `draft_log.csv` / `.json` — draft event'leri

| Kolon | Tip | Açıklama |
|---|---|---|
| `overall_pick` | int | 1–208 |
| `round` | int | |
| `seat` | int | 1–16 |
| `player_id` | str | |
| `source` | str | `user` / `bot:<profil>` / `import` / `manual` |
| `observed_at` | datetime | |

### 5.4 Ad eşleme

CSV'lerdeki adlar `player_id`'ye şu sırayla eşlenir:
1. `player_id` doğrudan eşleşir.
2. Normalize edilmiş ad ile eşleşme. Normalizasyon: küçük harf, aksan kaldırma (`unicodedata`), noktalama ve `Jr./Sr./II/III` temizliği.
3. `aliases` kolonu üzerinden eşleşme.

Eşleşmeyen ya da birden fazla adaya eşleşen satır **hata** sayılır ve UI'da düzeltme tablosu gösterilir. Fuzzy eşleşme otomatik uygulanmaz, yalnızca öneri olarak sunulur.

### 5.5 Validasyon kuralları

`validate.py` bir `ValidationReport(errors, warnings, notes)` döndürür. `errors` boş değilse veri seti kullanılamaz.

| Kural | Seviye |
|---|---|
| Zorunlu kolon eksik / tip dönüştürülemiyor | error |
| Tekrarlanan `player_id` | error |
| `fgm > fga` veya `ftm > fta` | error |
| Negatif istatistik | error |
| `projected_gp ∉ [0, 82]` | error |
| `yahoo_positions` boş veya izinsiz değer | error |
| `fga = 0` veya `fta = 0` | not (geçerli: oran katkısı 0) |
| Projeksiyonu olmayan oyuncu (players'ta var, projections'ta yok) | warning → havuzdan çıkarılır |
| ADP'si olan ama projeksiyonu olmayan oyuncu | warning → bot havuzunda kalır, değer = bilinmiyor; kullanıcıya önerilmez |
| `abs(pts − (2·fgm + fg3m + ftm)) > 0.5` (projeksiyonlarda yuvarlama payı) | warning |
| `fg3m > fgm` | error |
| `as_of` sezondan önce veya 60 günden eski | warning |
| Sentetik ve gerçek dosya karışımı | error (§5.7) |
| Manifest yok | error |

Eksik değer **asla 0 ile doldurulmaz**. Eksik zorunlu stat → oyuncu havuz dışında kalır ve raporlanır.

### 5.6 ADP güven sınıfları ve fallback

Her oyuncuya bir `adp_status` ve bir efektif ADP `A_i` atanır. Thurstone σ'sı da bu sınıfa göre büyütülür.

| `adp_status` | Koşul | `A_i` | σ çarpanı |
|---|---|---|---|
| `ok` | ADP var; `pct_drafted ≥ τ_pct` veya `pct_drafted` verilmemiş; `adp ≤ coverage_limit` | `adp` | 1.0 |
| `low_confidence` | ADP var ama `pct_drafted < τ_pct` veya `adp > coverage_limit` | `w·adp + (1−w)·Â_i`, `w = clip(pct_drafted/τ_pct, 0, 1)` (pct yoksa `w = 0.5`) | 1.5 |
| `imputed` | ADP yok, değer sırası ≤ N | `Â_i` | 2.0 |
| `tail` | ADP yok, değer sırası > N | `Â_i` (`after_coverage`) / `max(A) + (değer sırası − N)` (`isotonic`) | 2.0 |

`Â_i` (imputasyon): `ok` sınıfındaki oyuncular üzerinde **dengeli Z-değer sırası → ADP** monoton eşlemesi (izotonik regresyon, `scipy`/elle PAV) kurulur. Eşleme, kapsamın ötesine son %20'lik dilimin eğimiyle doğrusal olarak uzatılır.

**`missing_adp_policy` (varsayılan `after_coverage`, gerçek Yahoo verisiyle değiştirildi).** Yahoo Draft Analysis ADP'si yalnızca ~187 oyuncuyu ve en fazla ~123. pick'i kapsıyor (çoğunlukla 10–12 takımlı ligler); 16 takımlı lig 208 pick ister. Aşağıdaki izotonik yöntemle ADP'si olmayan oyuncular kapsamın *içine* (92–121) sıkışıyor ve 208. en küçük efektif ADP 121 çıkıyordu; botlar 9–13. turlarda ~100 oyuncuyu "geç kalmış" görüyordu (medyan `pick − A` +81'e kadar). `after_coverage`'da:

```
Â_i = max(gözlenen adp) + (ok olmayan oyuncular arasındaki değer sırası)
imputed / tail : A_i = Â_i
low_confidence : A_i = w·adp + (1−w)·Â_i      (w = pct/τ: liglerin pct'sinde ADP civarında, kalanında kapsam sonrasında)
```

Kaynakta listelenmeyen ya da az draft edilen oyuncu pratikte kaynağın kapsadığı pick'lerde seçilmiyordur; bu yüzden kapsamın sonrasına değer sırasıyla yerleşir ve `k.` en küçük efektif ADP ≈ `k` korunur (gerçek veride 100/130/160/190/208 → 102/122/148/180/200). Aşağıdaki ilk şartname yöntemi `missing_adp_policy: isotonic` ile seçilebilir.

*Uygulama notu (ilk gerçekçilik raporundan sonra, `isotonic` politikası için):* `ok` sınıfı `adp ≤ coverage_limit` ile seçildiği için kesilme ADP ekseni üzerindedir. Eşleme bu yüzden **ADP → değer sırası** yönünde fit edilip ters çevrilir (seçim regresör üzerinde olduğundan yanlılık yok). Uzatma eğimi, PAV basamaklarının uç noktaları yerine son %20'lik dilimdeki ham noktalara en küçük kareler ile fit edilir. Değer → ADP yönünde doğrudan fit, imputasyonu geç turlarda belirgin biçimde erkene sıkıştırıyordu. Bu, değerin ADP'ye sızdığı **tek** yerdir. `adp_status` her ekranda görünür.

Varsayılanlar (`config/model.yaml`, kalibre edilmemiş):

```yaml
adp_fallback:
  pct_drafted_threshold: 50     # τ_pct
  coverage_limit: 150           # çoğunlukla 12 takımlı lig ADP'sinin güvenilir kapsamı (varsayım)
  missing_adp_policy: after_coverage   # | isotonic
```

**Not:** 16 takımlı ligin 145–208 arası seçimleri, 12 takımlı ağırlıklı ADP verisinin seyrek olduğu bölgeye düşer. Bu nedenle geç turlarda ADP'den gelen olasılıklar daha belirsizdir ve UI bunu gösterir.

### 5.7 Sentetik veri politikası

`scripts/make_synthetic.py --n 400 --seed 7` şunları üretir:
- `SYN_001 … SYN_400` adlı oyuncular. Gerçek ad, takım veya ID kullanılmaz. `nba_team = "SYN"`.
- Parametrik bir modelden çekilen istatistikler: dakika → hacim, pozisyon arketipine göre kategori profili, korelasyonlu gürültü. Gerçek oyunculardan kopyalanan değer yoktur.
- ADP, Yahoo Draft Analysis gibi 12 takımlı lig kaynaklarını taklit eder: oyuncunun pick pozisyonu `dengeli değer sırası + N(0, σ(sıra))`; `% drafted = P(pozisyon ≤ 156)`, `ADP = E[pozisyon | pozisyon ≤ 156]` (kesik ortalama), %2'nin altındakiler listelenmez. Bu sayede bot ve fallback yolları gerçek veriye benzer koşullarda test edilebilir.
- Pozisyon dağılımı yaklaşık PG %20, SG %20, SF %18, PF %20, C %22, oyuncuların yaklaşık %35'i çoklu pozisyon.
- Her dosyada `is_synthetic=true` ve otomatik manifest (`license_status: personal_use_confirmed`, `source_name: synthetic`) bulunur.

UI'da sentetik veri yüklüyken her sayfada kırmızı bir **"SENTETİK VERİ — gerçek oyuncu değeri değildir"** bandı gösterilir. Sentetik ve gerçek dosyalar aynı oturumda birleştirilemez.

### 5.8 Oyuncu durumu

Yahoo Draft Analysis'teki durum etiketi `players.csv`'de `injury_status` olarak saklanır (gerçek veride 21 `O`, 109 `Q`, 127 `NA`). Kullanıcı kararı (13 Ekim 2026):

- **`NA` (aktif kadroda değil):** draft havuzuna alınmaz. Kullanıcıya önerilmez, botlar seçmez, log'da da kabul edilmez.
- **`O`, `Q`, `GTD`:** hiçbir hesabı değiştirmez. Sakatlığın etkisi projeksiyonun beklenen maç sayısındadır (`projected_gp`, örn. Jimmy Butler III: 35). IL slotları draft'ta dolmadığı için (13 pick = 13 slot) ayrıca modellenmez.

```yaml
availability:
  undraftable_statuses: [NA]
```

CSV okunurken `injury_status` kolonundaki `NA` metni eksik değer sayılmaz (diğer kolonlarda pandas varsayılanları geçerlidir).

---

## 6. Bileşen şartnameleri

Her bileşen için: amaç, girdi/çıktı, algoritma, parametreler. Fonksiyon imzaları yol göstericidir, isimler değişebilir. Ama girdi/çıktı sözleşmeleri değişmez.

### 6.1 Ingestion (`fdo.ingest`)

```python
load_dataset(players_csv, projections_csv, adp_csv, variance_csv=None,
             column_map: dict | None = None) -> tuple[Dataset, ValidationReport]
make_synthetic(n_players: int, rng: np.random.Generator) -> Dataset
```

`Dataset` alanları: `players`, `projections`, `adp` (ayrı DataFrame'ler), `manifests`, `is_synthetic`, `content_hash`. `content_hash`, önbellekleme ve önerilerin kaynak kaydı için kullanılır. ADP fallback (§5.6) `Dataset` oluşturulurken bir kez uygulanır. `adp` tablosuna `adp_eff`, `adp_status` ve `sigma_mult` kolonları eklenir.

### 6.2 Category valuation (`fdo.valuation`)

Valuation yalnızca projeksiyonları okur.

#### 6.2.1 Temel miktarlar

Oyuncu `i`, kategori `c`. Hesap tabanı (`basis`) seçilebilir:
- `per_game`: `x_ic` = maç başına değer.
- `total` (**varsayılan**): `x_ic` = maç başına × `projected_gp`. H2H'de kaçırılan maç haftalık katkıyı düşürdüğü için draft sıralamasında toplam daha anlamlıdır. Explorer her iki tabanı da gösterir.

#### 6.2.2 Referans havuz (döngüselliği kırmak için iterasyon)

```
P₀ ← projeksiyonu olan tüm oyuncular
tekrar et (en fazla 10 kez):
    istatistikleri P_k üzerinden hesapla (μ, σ, p̄)
    V ← dengeli ağırlıklarla toplam Z
    P_{k+1} ← V'ye göre ilk N oyuncu
    P_{k+1} == P_k ise dur
```

`N = teams × rounds = 208` (varsayılan). Duyarlılık için Explorer'da 180/208/240 seçenekleri sunulur. Havuz istatistikleri **dengeli ağırlıklarla** bir kez belirlenir. Kullanıcı ağırlıkları havuzu değiştirmez, böylece slider oynatıldığında ölçek kaymaz.

#### 6.2.3 Z-score

Sayma kategorileri `c ∈ {FG3M, PTS, REB, AST, STL, BLK}`:

```
z_ic = (x_ic − μ_c) / σ_c          μ, σ: havuz üzerinden, ddof = 0
```

TOV (ters yön):

```
z_i,TOV = (μ_TOV − x_i,TOV) / σ_TOV
```

Oran kategorileri (FG için gösterilmiştir, FT aynı şekilde):

```
p̄_FG   = Σ_{j∈P} FGM_j / Σ_{j∈P} FGA_j
I_i    = FGM_i − p̄_FG · FGA_i            # hacim ağırlıklı katkı (impact)
z_i,FG = (I_i − mean_P(I)) / std_P(I)     # mean_P(I) yapısı gereği ≈ 0
```

Kontrol örneği (ZORUNLU test): `p̄ = 0.47` ile A oyuncusu 3 FGA'da %55 (1.65 FGM), B oyuncusu 20 FGA'da %52 (10.4 FGM) atıyor. `I_A = 1.65 − 1.41 = 0.24`, `I_B = 10.4 − 9.4 = 1.00`. Sonuç olarak B'nin FG katkısı A'nınkinden büyük olmalıdır.

Kenar durumları:
- `σ_c < 1e-9` → bu kategori için `z = 0` atanır ve "kategori ayrıştırmıyor" uyarısı verilir.
- `FGA = 0` → `I = 0` (geçerli).
- Eksik stat değeri → oyuncu havuz dışında kalır (0 kabul edilmez).

#### 6.2.4 G-score (alternatif)

Z-score, haftadan haftaya belirsizliği yok sayar. G-score paydaya oyuncu içi varyansı ekler (Rosenof, *Improving Algorithms for Fantasy Basketball*, arXiv:2307.02188):

```
G_ic = (x_ic − μ_c) / sqrt(σ_c² + κ · τ_c²)
τ_c² = mean_{j∈P} Var_within(j, c)          # oyuncu içi varyansın havuz ortalaması, x ile aynı tabanda
```

- `Var_within`, §6.6.2'deki oyuncu varyans modelinden gelir: varyans dosyası varsa oradan, yoksa model varsayılanından.
- Oran kategorilerinde `x` yerine `I` ve `I`'nın varyansı kullanılır.
- `κ` konfigüre edilebilir, varsayılan `1.0`. **Makaledeki kesin katsayı, implementasyondan önce makaleden doğrulanmalıdır.** Doğrulanana kadar UI `κ` değerini gösterir.
- ZORUNLU test: `τ = 0` olduğunda `G == Z`.

#### 6.2.5 Ağırlıklar ve punt

```
V_i(w, yöntem) = Σ_c w_c · s_ic          s ∈ {z, g}
```

- `w_c ∈ [0, 3]`, adım 0.05. `w_c = 0` o kategorinin **punt** edildiği anlamına gelir.
- Presetler (`config/model.yaml`): `balanced`, `punt_FT`, `punt_FG`, `punt_TO`, `punt_AST`, `punt_PTS`, `punt_3PM`, `punt_FT_TO`, `punt_FG_FT`. Kullanıcı kendi presetini JSON olarak kaydedebilir.
- Çıktı tablosu: oyuncu, `V`, sıra, 9 kategori skoru, `adp_eff` (yalnızca **gösterim**), `value_rank − adp_eff` farkı ("ADP'ye göre ucuz/pahalı"), `adp_status`.
- İlke 3: ağırlıklar yalnızca `V`'yi değiştirir. Matchup modeline hiçbir şekilde aktarılmaz (testle korunur).

### 6.3 Snake draft engine (`fdo.draft`)

#### 6.3.1 Sıra

```python
seat_for_pick(k, teams, third_round_reversal) -> int
picks_for_seat(seat, teams, rounds, trr) -> list[int]
turns_for_seat(seat, teams, rounds, trr) -> list[tuple[int, ...]]   # [(16,17), (48,49), ..., (208,)]
```

#### 6.3.2 Event sourcing

```python
@dataclass(frozen=True)
class DraftPick:
    overall_pick: int
    round: int
    seat: int
    player_id: str
    source: str              # user | bot:<profil> | import | manual
    observed_at: datetime

class DraftLog:              # değişmez liste + yardımcılar
    append(pick) -> DraftLog
    undo() -> DraftLog
    truncate(overall_pick) -> DraftLog   # "şu pick'e geri dön"
```

`DraftState` her zaman `DraftLog`'dan **türetilir** (`state_from_log(log, config, dataset)`). State içinde şunlar bulunur: mevcut pick, sıradaki seat, uygun oyuncular, her takımın kadrosu, her takımın kalan pick numaraları.

Kurallar:
- Bir oyuncu yalnızca bir kez seçilebilir.
- `seat` değeri `seat_for_pick(overall_pick)` ile tutarlı olmalıdır. Import sırasında tutarsızlık hata sayılır.
- **Pozisyon kuralı** (`position_limits_enforced_in_draft: true`, §3.2): bir pick, takımın kalan pick'leriyle tüm aktif slotları doldurmasını imkânsız kılıyorsa geçersizdir (`fdo/draft/rules.py`). `DraftLog` pozisyon bilmediği için kural log'a pick ekleyen katmanlarda uygulanır: kullanıcı/manuel seçim ve import (`MockDraft`), botlar (bu durumda `enforce_completion_feasibility` kapalı olsa bile zorunlu), advisor'ın çift filtresi, π politikası ve senaryolar. Kural `false` yapılırsa yalnızca botlarda ve advisor'da yumuşak/sert kural olarak kalır.

Undo + replay aynı state'i üretmelidir (ZORUNLU test). Export formatları CSV ve JSON'dur ve manifest referansları ile seed bilgisi de eklenir.

### 6.4 ADP-based opponent bots (`fdo.bots`)

#### 6.4.1 Thurstone gürültülü sıralama

Her draft (simülasyon) başında, her bot `b` ve her oyuncu `i` için **kalıcı** bir algılanan sıra çekilir:

```
q_bi = A_i + σ_i · ε_bi,     ε_bi ~ t_ν (Student-t, ölçeklenmiş, varyans 1)
σ_i  = min(σ_cap, sigma_mult_i · max(σ_floor, adp_std_i))     adp_std varsa
     = min(σ_cap, sigma_mult_i · (σ₀ + σ₁ · A_i))               yoksa
```

`σ_cap` ilk gerçekçilik raporundan sonra eklendi: üst sınır olmadan σ, ADP ile sınırsız büyüyor ve ADP'si havuzun çok ötesindeki (`tail`, A ≈ 400–600) oyuncular t-kuyruğu yüzünden ilk turlarda seçilebiliyordu. Sınır sınıf çarpanından **sonra** uygulanır: önce uygulandığında gerçek Yahoo verisinde kapsam dışındaki yüzlerce oyuncu σ = 2 × 25 = 50 ile draft başına ~10 kez 9–13. turlara reach ediyor, ADP'si 97–160 olan oyuncuları ortalamada ~+18 pick kaydırıyor ve ADP'si 161–208 olanların yalnızca %44–75'i seçilebiliyordu.

Her pick'te küçük bir anlık titreşim eklenir: `q_bi(t) = q_bi + ρ · σ_i · η_bit`, `η ~ N(0,1)`, `ρ` küçük. Gürültünün büyük kısmı kalıcı olduğu için bot draft boyunca **tutarlı** tercihler sergiler. Bir oyuncuyu "beğenen" bot onu beğenmeye devam eder.

Bot, uygun oyuncular arasından **en küçük skora** sahip olanı seçer:

```
score_bi(t) = q̃_bi(t) − need_bonus_b(i, t) + penalty_b(i, t)
seçim      = argmin_{i ∈ Available, feasible_b(i)} score_bi(t)
```

`q̃`, profile göre `q`'nun değiştirilmiş hâlidir (§6.4.2).

Bu modelin özellikleri:
- **Monoton:** ADP'si geçmiş bir oyuncunun skoru zaten düşüktür, bu yüzden hızla seçilir. Simetrik ceza (İlke 6) yoktur.
- **Sert yasak yok:** Student-t kuyruğu (`ν` küçük) nadir reach'lere izin verir. Sıklıkları §7'de ölçülür.
- **Geç turlarda geniş yayılım:** `σ₁ · A_i` terimi sayesinde belirsizlik ADP ile büyür.

#### 6.4.2 Profiller

| Profil | `q̃` | Ek davranış | σ çarpanı |
|---|---|---|---|
| `MarketFollower` | `q` | — | 0.8 |
| `ValueHunter` | `(1−λ)·q + λ·R_b,i` | `R_b,i`: botun kendi dengeli Z-değer sırası | 1.0 |
| `PositionAware` | `q` | Güçlü `need_bonus` | 1.0 |
| `PuntBuilder` | `(1−λ)·q + λ·R^punt_b,i` | `r_punt` turundan sonra, kadrosunun en zayıf kategorisinin ağırlığını 0 yaparak sıralama | 1.0 |
| `AutoDrafter` | `default_rank` varsa o, yoksa `A` | Ortada olmayan menajeri temsil eder | 0.3 |
| `RandomHuman` | `q` | Daha kalın kuyruk (`ν` daha küçük) | 1.5 |

`need_bonus_b(i,t)`: Oyuncu, botun henüz doldurulmamış bir **pozisyonel aktif** slotunu (PG/SG/G/SF/PF/F/C; her pozisyonu kabul eden UTIL hariç) dolduruyorsa (§6.5 ataması ile kontrol edilir), bonus `β_need · f(tur)` kadardır; `f(tur) = tur / rounds`. `f` turla artar, çünkü erken turlarda pozisyon ihtiyacı daha az önemlidir. UTIL dahil edildiğinde UTIL açık kaldığı sürece herkes "ihtiyaç" karşıladığı için bonus ayrıştırıcı olmuyordu.

`penalty_b(i,t)` için kullanılan eşik: saf pozisyon P'nin "kapasitesi" = P'ye özgü aktif slot sayısı + 1 (PG/SG/SF/PF: 2, C: 3); bu sayıyı aşan her saf-P oyuncu için `β_stack`.

`penalty_b(i,t)`: Aynı saf pozisyondan (örn. yalnızca C) aşırı birikim varsa yumuşak ceza uygulanır (`β_stack`).

`feasible_b(i)` **sert** kuraldır: Oyuncu eklendikten sonra kalan pick sayısı, doldurulamayan aktif slotları tamamlamaya hâlâ yetmelidir. Bu kural `config` ile kapatılabilir.

`ValueHunter` ve `PuntBuilder` profilleri projeksiyon kullanır. Bu, İlke 1'e aykırı değildir: bot *davranışı* modelleniyor, kullanıcıya değer önerilmiyor.

#### 6.4.3 Lig kompozisyonu ve parametreler

`config/model.yaml` (tamamı **kalibre edilmemiş** varsayılanlar; §7 raporuyla ayarlanır):

```yaml
bots:
  mix: {MarketFollower: 5, ValueHunter: 4, PositionAware: 2, PuntBuilder: 3, RandomHuman: 1, AutoDrafter: 0}   # toplam 15
  # ilk şartname: {MarketFollower: 6, ValueHunter: 3, PositionAware: 2, PuntBuilder: 2, RandomHuman: 1, AutoDrafter: 1};
  # ligde otomatik draft eden olmadığı için AutoDrafter 0, değer ve punt odaklı profillerin payı artırıldı
  seat_assignment: random_per_draft      # veya fixed
  user_auto_profile: MarketFollower       # "oynat" işlemlerinde kullanıcı koltuğu
  sigma0: 1.5
  sigma1: 0.12
  sigma_floor: 1.0
  sigma_cap: 25.0         # ilk rapordan sonra eklendi
  t_df: 8                 # ilk rapordan sonra 5 → 8
  t_df_random_human: 5    # ilk rapordan sonra 3 → 5
  jitter_rho: 0.15
  value_lambda: 0.3
  punt_lambda: 0.4
  punt_after_round: 3
  beta_need: 4.0          # pick birimi
  position_aware_need_mult: 3.0
  beta_stack: 3.0
  enforce_completion_feasibility: true
  profile_sigma_mult: {MarketFollower: 0.8, ValueHunter: 1.0, PositionAware: 1.0,
                       PuntBuilder: 1.0, AutoDrafter: 0.3, RandomHuman: 1.25}   # RandomHuman 1.5 → 1.25
```

İlk gerçekçilik raporu (sentetik veri, 200 mock) varsayılanlarla erken turlarda %8–18 uygunsuz reach (z > 2.5) ve tail oyuncuların 1. turda seçildiği örnekler gösterdi. Yukarıdaki üç değişiklikten sonra (500 mock, seed 1): erken tur uygunsuz reach ≈ %2.2–2.9, orta–geç turlarda ≤ %1; ADP≈90 oyuncunun ilk 16'da gitmesi 4 olay / 4500 oyuncu-mock; Kendall τ ≈ 0.77; tamamlanamayan kadro 0.

Gerçek Yahoo verisiyle (σ sınırı çarpandan sonra, yeni karışım, 500 mock, seed 1): uygunsuz reach 1–4. turlarda %2.3–3.0, 5. turdan sonra ≤ %1.7; `pick − A` medyanı 1–7. turlarda −1.3…+1.9, 8–13. turlarda +6.5…+16.3; ADP≈90 oyuncunun ilk 16'da gitmesi 2 olay / 4500 oyuncu-mock; Kendall τ ≈ 0.76; tamamlanamayan kadro 0. Arayüzde mock sayfasından karışım ve koltuk ataması değiştirilebilir.

*Denenip bırakılan yöntem:* oyuncu başına konum düzeltmesi (`q = A + δ_i + σ·ε`; `δ_i` simülasyonla `medyan pick − A`'ya göre iteratif) ve tur başına düğümlü düzgün bir `δ(A)`. İkisi de yakınsamadı: pick'ler bir permütasyon olduğundan düzeltmeler birbirini itiyor ve sansür (seçilmeyen oyuncu) farkları sistematik pozitif gösteriyordu. Asıl neden olan büyük tail σ'sı yukarıdaki sınırla giderildi.

#### 6.4.4 Arayüz

```python
class BotLeague:
    @classmethod
    def sample(cls, dataset, config, rng) -> "BotLeague"   # kalıcı q_bi ve profiller burada çekilir
    def choose(self, seat, state, rng) -> str              # player_id
```

Vektörizasyon: `q` matrisi `(15, n_players)` boyutunda NumPy dizisidir. Uygun oyuncu maskesi ile `argmin` tek satırda hesaplanır.

#### 6.4.5 Rakip stratejisi tahmini (`fdo.bots.inference`)

Gerçek (ya da elle girilen) draft'ta her rakip pick'i `(k, koltuk b, oyuncu i)` için, o andaki gerçek
durumda (kadrolar, pozisyon kuralı, punt durumu) her profil `p` ile `M = 200` bağımsız Thurstone
çekilişi yapılır ve botun `i`'yi seçme frekansı `f_p` ölçülür. Olabilirlik `ε + (1−ε)·f_p`
(`ε = 0.02`: modelin açıklayamadığı seçimlere tolerans); sonrası `∝ öncel · Π olabilirlik`, öncel lig
bot karışımıdır. Hesap artımlıdır (yeni pick başına ~40 ms; undo'da baştan kurulur). Olası punt:
koltuğun kadrosunun dengeli z toplamında en zayıf kategori ikinciden ≥ 1.5 gerideyse.

Advisor'da açıkken (Canlı Draft'ta varsayılan) rakip koltuklarının profilleri simülasyonlarda karışım
yerine bu sonradan çekilir: koşullu doldurma tablosu, rollout ve tam ufuk.

Ölçüm (gerçek Yahoo verisi, botların oynadığı 6 draft = 90 rakip koltuğu, profiller biliniyor):

| Tur | En olası profil doğru | Gerçek profilin olasılığı (öncel 0.24) |
|---|---|---|
| 4 | %58 | 0.51 |
| 7 | %70 | 0.61 |
| 13 | %68 | 0.64 |

Survival etkisi (12 draft, 48→80, 80→112, 112→144 ufuklarında ADP'ce ilk 60 uygun oyuncu için Brier):
karışım 0.094 / 0.124 / 0.155, tahmin 0.093 / 0.125 / 0.156 — **fark yok** (gürültü içinde). Botlar
arasında kalma olasılığını profil kimliğinden çok her koltuğun kalıcı kişisel gürültüsü belirliyor ve o
gözlemden çıkarılamıyor. Gerçek menajerler profiller arasında daha uç davranıyorsa (sert punt, pozisyon
toplama) etki büyüyebilir; gerçek draft log'u olmadan doğrulanamaz. Tahmin zarar vermediği ve rakip
kadrolarının (dolayısıyla ECW'nin) gelecekteki gelişimini stratejiye göre simüle ettiği için açık tutulur.
LLM kullanılmaz: olabilirlik bot modelinden doğrudan hesaplanabiliyor; LLM 45 s'lik pick süresinde
gecikme ve tekrarlanamazlık getirir.

### 6.5 Team composition ve position eligibility (`fdo.roster`)

```python
parse_positions("PG,SG") -> frozenset({"PG", "SG"})
eligible_slots(positions, slot_eligibility) -> set[Slot]
best_assignment(roster: list[PlayerId]) -> Assignment       # aktif slotları maksimum doldur
open_active_slots(roster) -> Counter[Slot]
can_complete(roster, n_remaining_picks, available_pool) -> bool
```

- Atama bir bipartite eşleme problemidir. Satırlar oyuncular, sütunlar slot örnekleridir (PG, SG, G, SF, PF, F, C₁, C₂, UTIL₁, UTIL₂, BN₁₋₃). Uygun olmayan hücreler büyük bir maliyet alır. Aktif slotun maliyeti, bench slotunun maliyetinden düşüktür. Çözüm `scipy.optimize.linear_sum_assignment` ile yapılır.
- Spesifik slotlar önce dolsun diye maliyet sırası şöyledir: spesifik (PG/SG/SF/PF/C) < esnek (G/F) < UTIL < BN.
- `can_complete`: Kalan pick'lerin, eksik aktif slotları en az bir uygun oyuncu tipiyle doldurabileceği kontrol edilir. V1'de havuzda o pozisyondan yeterli oyuncu olup olmadığına bakılmaz, yalnızca sayısal yeterlilik kontrol edilir.

### 6.6 Matchup evaluation (`fdo.matchup`)

Matchup modeli yalnızca projeksiyonları ve opsiyonel varyans dosyasını okur. **Kategori ağırlıklarını okumaz.**

#### 6.6.1 Birim: bir haftalık eşleşme

```yaml
matchup:
  games_per_week: 3.5          # ortalama; takvim V2. Varsayım.
  utilization: 0.98            # oynanan maçların aktif slotta sayılan oranı (lineup_lock = daily_today)
  games_cap: 82
```

Oyuncu `i` için:

```
a_i = min(projected_gp_i, 82) / 82               # müsaitlik
k_i = utilization · games_per_week · a_i          # haftalık beklenen sayılan maç
```

`utilization`, `scripts/estimate_utilization.py` ile tahmin edildi: 480 mock kadrosu (13 oyuncu, pozisyon uygunluğuyla 10 aktif slot), her gün o gün oynayanlar aktif slotlara en iyi yerleştirilir.

| lineup_lock | 2026-27 NBA takvimi (24 eşleşme haftası) | Varsayımsal takvim (Pzt–Paz 8/6/9/5/8/6/7 maç, σ = 3) |
|---|---|---|
| daily_today | **0.987** (kullanılan) | 0.982 |
| daily_tomorrow | 0.971 | 0.961 |
| weekly | 0.821 | 0.864 |

Kayıp neredeyse tamamen kalabalık gecelerden gelir. IL slotlarıyla yapılan stream/yerine oyuncu alma modellenmez.

#### 6.6.2 Oyuncu haftalık ortalama ve varyansı

Sayma stati `s` (fg3m, pts, reb, ast, stl, blk, tov, ayrıca fgm, fga, ftm, fta) için:

```
m_is  = k_i · x_is                                  # haftalık ortalama
v_is  = per_game_var_is                             # varyans dosyası varsa
      = φ_s · x_is                                  # yoksa: aşırı yayılımlı Poisson varsayılanı
s²_is = k_i · v_is                                  # haftalık varyans
```

`φ_s` varsayılanı `1.0`'dır ve **kalibre edilmemiştir**. V2'de nba_api game log'ları ile kalibre edilecektir. Maç sayısının rastgeleliği V1'de yok sayılır (§12).

Oran kategorileri (FG gösterilmiştir). Maç başına `p_i = FGM_i/FGA_i` için, `r` referans oranına göre `Y = FGM − r·FGA` tanımlanır:

```
Var_game(Y_i) = FGA_i · p_i (1 − p_i)  +  (p_i − r)² · v_i,FGA       # binom atış + hacim varyansı
E_week(Y_i)   = k_i · (FGM_i − r · FGA_i)
Var_week(Y_i) = k_i · Var_game(Y_i)
```

#### 6.6.3 Takım toplamları ve kazanma olasılığı

Takım `A` ile `B` karşılaştırılır. Kadrodaki bütün oyuncular (doldurma profilleri dahil, §6.6.4) toplanır.

Sayma kategorileri (TO hariç):

```
D = M_A − M_B,   Var(D) = S²_A + S²_B
P(A kazanır) = Φ( E[D] / sqrt(Var(D)) )
```

TO için işaret ters çevrilir: `P = Φ((M_B − M_A) / sqrt(S²_A + S²_B))`.

Oran kategorileri: `r = (ΣFGM_A + ΣFGM_B) / (ΣFGA_A + ΣFGA_B)` (beklenen havuzlanmış oran). A'nın FG%'si B'ninkinden büyükse ve ancak o zaman `Y_A − Y_B > 0` olur. Bu yüzden:

```
P(A kazanır FG) ≈ Φ( (E[Y_A] − E[Y_B]) / sqrt(Var(Y_A) + Var(Y_B)) )
```

Beraberlik: Normal yaklaşımda `P(tie) = 0`'dır. `tie_value` V2'nin ayrık Monte Carlo değerlendiricisinde kullanılır.

`Var(D) = 0` olursa (yalnızca dejenere testlerde): `E[D] > 0 → 1`, `< 0 → 0`, `= 0 → 0.5`.

#### 6.6.4 Eksik kadroların etkisi (doldurma profilleri)

Draft ortasında her takımın kadrosu eksiktir. Takım `t`'nin kalan her pick'i `n` için bir **doldurma profili** `F(n)` eklenir. `F(n)`, `n` numaralı pick'te seçilmesi beklenen oyuncunun haftalık ortalama ve varyans vektörüdür.

- **Taban tablo:** Başlangıç durumundan `M_fill` adet (varsayılan 200) tam bot draft'ı simüle edilir. Her pick numarası için seçilen oyuncuların haftalık istatistik ortalaması ve varyans ortalaması alınır. Sonuç `±w` (varsayılan 5) pencereyle yumuşatılır. Tablo `(dataset_hash, config_hash)` ile önbelleğe alınır.
- **Koşullu güncelleme (ÖNERİLİR):** Kullanıcının sırası geldiğinde mevcut state'ten `M_fill_cond` (varsayılan 100) hızlı simülasyonla tablo yeniden hesaplanır. Böylece erken düşen ya da erken giden oyuncular dikkate alınmış olur.
- Doldurma profili **nötrdür**. Rakiplerin ve kullanıcının gelecekteki punt eğilimlerini modellemez (§12).
- Her ECW çıktısı "gerçek oyuncular / doldurma" oranını gösterir. Örneğin `2/13 gerçek` ise UI bir belirsizlik uyarısı verir.

#### 6.6.5 ECW

```
ECW(A vs j) = Σ_c P_c(A, j)                      # 0–9 arası beklenen kategori galibiyeti
ECW(A)      = (1/15) · Σ_{j≠A} ECW(A vs j)       # sezon boyu rastgele rakip varsayımı
```

Beklenti doğrusal olduğu için ECW, kategoriler arası bağımsızlık **gerektirmez**. `P(≥5 kategori)` yalnızca ek gösterge olarak verilir. Bu gösterge bağımsızlık varsayımına dayanır ve `assumes_independence` rozetiyle gösterilir. Hiçbir optimizasyonda kullanılmaz.

Çıktılar:
- `ecw_matrix`: 16 × 15 × 9 boyutunda P değerleri.
- Takım × kategori ortalama P tablosu.
- Kullanıcı takımı için kategori bazında "kazanılabilir / sınırda / kaybedilmiş" sınıflandırması. Eşikler: `P ≥ 0.6`, `0.4–0.6`, `≤ 0.4`.

Marjinal değer:

```
ΔECW(i | R) = ECW(R ∪ {i}) − ECW(R ∪ {F(n_i)})
```

Burada oyuncu, aynı pick'teki **doldurma profiliyle** karşılaştırılır, boş slotla karşılaştırılmaz. Böylece erken turlarda "herkes pozitif" yanılgısı oluşmaz.

Performans: Bütün P hesapları `(adaylar × rakipler × kategoriler)` boyutunda vektörize edilir. `scipy.special.ndtr` kullanılır.

### 6.7 Pair recommendation ve Monte Carlo lookahead (`fdo.advisor`)

Advisor yalnızca ECW'yi optimize eder. Z ve G burada aday ön elemesi dışında kullanılmaz.

#### 6.7.1 Simülasyon çekirdeği ve Common Random Numbers

```python
simulate_until(state, until_pick, bot_league_samples, rng_streams) -> list[DraftState]
```

- `S` adet simülasyon yapılır. Her simülasyon `s` için bir `BotLeague` örneği (kalıcı `q_bi` gürültüleri) ve bir RNG akışı bir kez çekilir.
- **CRN:** Farklı aday çiftler **aynı** `S` bot örneğiyle değerlendirilir. Çiftler arasındaki tek fark havuzdan çıkan iki oyuncudur. Bu, çift karşılaştırmalarındaki varyansı ciddi biçimde düşürür.
- Seed hiyerarşisi: `master_seed → (simülasyon s) → (pick)`. Aynı seed aynı sonucu verir.

#### 6.7.2 Survival probability

```
P_surv(i, n | state, alınacaklar) = (1/S) · Σ_s 1[i, simülasyon s'de n. pick'te hâlâ uygun]
SE = sqrt(P(1−P) / S)
```

Ek çıktı: oyuncunun hangi pick'te gittiğinin dağılımı (medyan, P10, P90). Survival her zaman **koşulludur**. "16/17'de {a, b} alınırsa" bilgisi simülasyona girer, çünkü a ve b'nin havuzdan çıkması botların seçimlerini değiştirir.

#### 6.7.3 Çift önerisi algoritması (V1)

Bu algoritma kullanıcının mevcut turn'ü `(t₁, t₂)` (örn. 16/17) ve bir sonraki turn'ü `(u₁, u₂)` (örn. 48/49) için çalışır. Tek seçimli turn'ler (208, 3RR'de 33) aynı algoritmanın 1 elemanlı hâlidir.

```
1. Aday kümesi C:
     ΔECW'ye göre ilk K₁ (20)
   ∪ ADP aciliyeti: P_surv(sonraki turn) < 0.5 olan ve ΔECW'si ilk K₂ (35) içinde olanlar
   ∪ kullanıcının pinlediği oyuncular
   (tekrarlar atılır, |C| ≤ 25)

2. Çiftler: C'den sırasız 2'li kombinasyonlar (≤ 300).
   Kadroyu tamamlanamaz yapan çiftler elenir (§6.5).

3. Hızlı skor (statik):
     Q(a,b) = ECW(R ∪ {a, b} ∪ fill) − ECW(R ∪ fill)
   İlk M çift (30) ve pinlenmiş çiftler bir sonraki aşamaya geçer.

4. Rollout (CRN ile her çift için S simülasyon, varsayılan 500):
     a, b havuzdan çıkarılır
     u₁'e kadar rakip pick'leri simüle edilir (16/17 → 48/49 arası 30 pick)
     u₁ anındaki uygun havuzdan kullanıcının "sonraki çift" politikası π uygulanır:
        π = havuzdaki ΔECW ilk L (12) oyuncu arasından ECW'yi maksimize eden çift (miyopik)
     Değer:
        W_s(a,b) = ECW( R ∪ {a, b} ∪ π_s ∪ fill_{u₂ sonrası},
                        rakipler: simülasyondaki kadroları ∪ fill )

5. Çift başına sonuç:
     E[W], P10, P50, P90, SE
     regret: en iyi çifte göre E[W] farkı ± CRN eşleşmeli SE
```

Sıralama `E[W]`'ye göre yapılır. İstatistiksel olarak ayırt edilemeyen çiftler (fark < 2·SE_fark) aynı "kademe"de gösterilir. Bu, sahte kesinlik göstermemek içindir.

`R` boşsa (16/17 durumu) adımlar aynıdır. 48/49'da `R` dolu, sonraki turn 80/81'dir. Yöntem her turn'de aynıdır.

#### 6.7.4 "48/49 havuzu" çıktısı (V1'in ana ekranı)

Seçilen her aday çift için şunlar gösterilir:

1. **Uygunluk tablosu:** `u₁` anında ΔECW'ye göre ilk 30 oyuncu. Her biri için `P_surv(u₁ | a,b)`, SE, `adp_eff`, `adp_status` ve "beklenen gidiş pick'i" dağılımı.
2. **Kademe (tier) görünümü:** Oyuncular ΔECW kademelerine ayrılır. Her kademe için 48'de **beklenen uygun oyuncu sayısı** ve "kademeden en az 1 / en az 2 oyuncu kalma" olasılığı verilir.
3. **Sonraki çift dağılımı:** π'nin seçtiği çiftlerin frekans tablosu (ilk 10) ve her birinin olasılığı.
4. **Kategori profili:** 4 pick sonrası (doldurma dahil) her kategori için ortalama P(win), P10–P90 bandı.
5. **Karşılaştırma modu:** İki aday çift yan yana gösterilir. Uygunluk farkları ve kategori profili farkları sunulur.
6. **Bekleme maliyeti** (oyuncu başına basit gösterge):
   ```
   wait_cost_i = ΔECW_i · (1 − P_surv(i, u₁))
   ```
   Bu değer yüksekse "şimdi al", düşükse "kalabilir" anlamına gelir. Yalnızca açıklama içindir, karar `E[W]` ile verilir.

Her öneri kartında şunlar bulunur: kullanılan projeksiyon ve ADP kaynakları ile `as_of` tarihleri, seed, `S`, hesap süresi, `uncalibrated` rozetleri.

#### 6.7.5 Alternatif kadro senaryoları (hafif, M6)

Tam draft rollout'u (`S_full`, varsayılan 200) şöyle yapılır: kullanıcı her turn'de π politikasını uygular, botlar oynar. Final kadrolar "kaybedilen kategori imzası"na göre (P < 0.4 olan kategoriler kümesi) gruplanır. Çıktı: en sık 3–5 arketip ("punt FT+TO benzeri" gibi). Her arketip için frekans, ortalama ECW ve tipik kadro listesi gösterilir. Bu bir *ulaşılabilirlik* göstergesidir. Optimal plan iddiası taşımaz.

#### 6.7.6 Parametreler (`config/model.yaml`)

```yaml
advisor:
  k1_top_ecw: 20
  k2_urgency_pool: 35
  max_candidates: 25
  m_pairs_to_rollout: 30
  sims_per_pair: 500        # hızlı mod: 200
  next_policy_top_l: 12
  fill_sims_base: 200
  fill_sims_conditional: 100
  fill_smoothing_window: 5
  scenario_full_sims: 200
```

---

## 7. Simülasyon gerçekçiliği ölçümü

`scripts/run_mock_batch.py --n 500 --seed 1` komutu tam mock'lar üretir ve `realism/report.py` bir rapor (Markdown ve tablolar) çıkarır. Bot parametreleri **yalnızca** bu rapor üzerinden ayarlanır.

| Metrik | Tanım | Hedef / yorum |
|---|---|---|
| Tur bazında `pick − A` dağılımı | Medyan, P10, P90 | Medyan ≈ 0 civarı; yayılım tur ilerledikçe artar |
| Reach skoru | `z_reach = (A_i − pick) / σ_i` | `z_reach > 2.5` olan pick'ler "uygunsuz reach" sayılır |
| Uygunsuz reach oranı | Tur bazında `z_reach > 2.5` olan pick yüzdesi | Erken turlarda çok düşük (< %2, hedef varsayımı), sıfır değil |
| Uç reach örneği | ADP≈90 oyuncunun ilk 16'da gitme sıklığı | Pratikte ≈ 0 ama > 0 (hard ban yok) |
| Slide oranı | `pick − A > 2.5·σ` | Raporlanır |
| Mock çeşitliliği | Mock'lar arası ilk 32 pick kümesinin Jaccard benzerliği, Kendall τ | Mock'lar birbirinin kopyası olmamalı (τ < 0.98 hedef varsayımı) |
| Pozisyon dağılımı | Tur bazında pozisyon payları; 13. turda tamamlanamayan kadro sayısı | Tamamlanamayan kadro = 0 (feasibility açıkken) |
| Bot tutarlılığı | Aynı botun mock içindeki tercih sıralamasının stabilitesi | Raporlanır |
| Dış karşılaştırma (opsiyonel) | Gerçek draft log'u (örn. kullanıcının indirdiği mock CSV) varsa `pick − A` dağılımı ile KS testi | V2'de kalibrasyon girdisi |

Hedef değerler gerçek veriyle **doğrulanmış değildir**. İlk raporla birlikte gözden geçirilir. Gerçek draft log'u olmadan "botlar Yahoo insanları gibi seçiyor" iddiasında bulunulmaz.

**Mock sırasında görünürlük:**
- Draft board'da her hücre `z_reach`'e göre renklenir: nötr, sarı (1.5–2.5), kırmızı (> 2.5). Slide'lar mavi tonla gösterilir.
- Seçim logunda reach ve slide rozetleri bulunur.
- Kullanıcının kendi seçimleri de aynı ölçüyle değerlendirilir ("bu pick ADP'ye göre 2.1σ erken").

---

## 8. Streamlit arayüzü

Tek uygulama ve çok sayfa (`st.navigation` veya `pages/`). Durum `st.session_state` içinde tutulur: `dataset`, `config`, `draft_log`, `seed`, `weights`. Ağır hesaplar `(dataset_hash, config_hash, state_hash, seed, params)` anahtarına göre önbelleklenir (advisor sonuçları oturum durumunda: hesap sırasında ilerleme çubuğu güncellendiği için `st.cache_*` tekrar oynatma hatası verir).

| Sayfa | İçerik |
|---|---|
| **Draft Analizi** | Yan sekmede açık tutulur (§13.10): arka planda hesaplanan öneri, önerilen çiftler, renkli oyuncu panosu, punt önerisi, rakip stratejileri |
| **1. League & Data** | Lig config görüntüleme/düzenleme (kesin alanlar kilitli, doğrulanmamış alanlar uyarılı); CSV yükleme, kolon eşleme, validasyon raporu, manifest durumu; sentetik veri üret butonu; `adp_status` dağılımı; V2: takvim yükleme ve hafta özeti |
| **2. Projection Explorer** | Oyuncu tablosu: Z/G seçimi, `per_game`/`total`, 9 kategori skoru, `V`, sıra, `adp_eff` ve `value_rank − ADP`, `adp_status`, pozisyonlar; ağırlık slider'ları ve presetler; havuz boyutu (180/208/240) duyarlılığı; filtre ve arama |
| **3. Mock Draft** | 16×13 board; seed; bot karışımı; "sıradaki pick'i oynat", "kullanıcıya kadar oynat", "sona kadar oynat"; manuel seçim (arama); undo, "pick k'ye dön", replay; CSV/JSON export ve import; reach renkleri |
| **4. Draft Assistant** | Kullanıcının sırası geldiğinde: aday çift tablosu (E[W], P10–P90, SE, kademe); seçili çift için **48/49 havuzu** (§6.7.4); iki çift karşılaştırması; bekleme maliyeti; hesap parametreleri ve süre; "hızlı / tam" mod; V2: tam ufuk derin analiz, sakatlık/rol belirsizliği kutusu, rakip stratejisi tahmini, strateji ağırlıkları (kendi punt'unuz), punt planı karşılaştırması |
| **5. Team Dashboard** | 16 takım × 9 kategori ortalama P(win); kullanıcı vs her rakip matrisi; kazanılabilir/sınırda/kaybedilmiş kategoriler; gerçek/doldurma oranı; FG%/FT% toplamdan hesaplanmış takım oranları; V2: takvim yüklüyse kadronun haftalık maç / sayılan maç tablosu |
| **6. Realism Report** | §7 metrikleri: son mock ve batch raporu; histogramlar; uygunsuz reach listesi |
| **7. Canlı Draft** | Gerçek draft'ı elle takip (§8.1): tek kutudan pick girişi, otomatik öneri, rakip stratejisi tablosu, otomatik kayıt |

UI kuralları:
- Sentetik veri bandı (§5.7) ve `uncalibrated` rozetleri (İlke 10) her zaman gösterilir.
- Olasılıklar SE ile gösterilir, örneğin `%62 ± 2`. Kalibre edilmemiş modelden gelen değerlerde "≈" işareti kullanılır.
- Advisor hesabı çalışırken `st.status` ile ilerleme gösterilir. Uzun hesaplar iptal edilebilir.
- Mock'ta advisor, rakip pick'leri oynanırken **önceden** hesaplanabilir (opsiyonel). V1'de ÖNERİLİR olan, kullanıcının sırası gelince hesaplamaktır, hızlı mod varsayılandır.

### 8.1 Canlı draft (Sayfa 7)

Yahoo API kullanılamadığı için (§13.7) gerçek draft simülatörde elle takip edilir:

- "Yeni canlı draft başlat" → bot oynatma kapanır (Mock Draft ve Draft Assistant'taki oynat düğmeleri
  devre dışı). Sıradaki takım, tur ve sonraki 5 pick gösterilir; takım adları kenar çubuğundan girilir.
- Pick girişi tek kutudur: oyuncu adını yazıp Enter → pick kaydedilir (ADP sıralı, Yahoo pozisyon
  kuralına aykırı oyuncular listede yoktur). Undo vardır.
- Analiz yan sekmedeki **Draft Analizi** sayfasındadır (§13.10): her pick arka plan işçisine yayınlanır;
  sıra kullanıcıya gelince önce hızlı, ardından tam mod öneri rakip stratejisi tahminiyle hesaplanır.
  Draft sayfasında yalnızca tek satır öneri özeti görünür. Ayrıntı (havuz, karşılaştırma, tam ufuk)
  Detaylı Advisor'dadır.
- Log her pick'te `data/live/live_draft.json`'a yazılır (git dışı); sayfa yenilense ya da uygulama
  kapansa "Kayıtlı canlı draft'a devam et" ile sürer.

---

## 9. Test stratejisi

`pytest`, seed'li ve deterministik. İstatistiksel testler sabit seed ve tolerans ile çalışır. Kaba (flaky) eşiklerden kaçınılır ve tolerans her testte belgelenir.

### 9.1 Birim testleri (ZORUNLU)

**ingest**
- Zorunlu kolon eksikse error üretilir.
- `fgm > fga` error üretir. `fga = 0` kabul edilir.
- Tekrarlanan `player_id` error üretir.
- Sentetik + gerçek karışımı error üretir.
- Manifest yoksa dosya yüklenmez.
- ADP boş olduğunda `imputed` atanır. `pct_drafted` düşük olduğunda `low_confidence` atanır ve harmanlama formülü doğru çalışır.
- İzotonik eşleme monotondur.
- Ad normalizasyonu: aksanlı ve aksansız yazımlar eşleşir. Belirsiz eşleşme error üretir.

**valuation**
- TOV: daha az TO daha yüksek skor alır.
- §6.2.3'teki FG hacim örneği.
- Havuz üzerinden `Σ I_i ≈ 0`.
- `σ = 0` durumunda çökme olmaz ve uyarı verilir.
- Havuz iterasyonu ≤ 10 adımda durur.
- `τ = 0` olduğunda `G == Z`.
- `w_c = 0` → `V` o kategoriden bağımsız olur (kategori değeri değiştirildiğinde `V` değişmez).
- Ağırlık değişimi havuz istatistiklerini değiştirmez.

**draft**
- 208 benzersiz pick.
- §3.3'teki iki tablonun birebir karşılığı (3RR kapalı/açık).
- `turns_for_seat` doğru çiftleri ve tek seçimleri döndürür.
- Undo + replay sonrası state eşitliği.
- Tutarsız seat ile import error üretir.
- Aynı oyuncunun iki kez seçilmesi error üretir.

**roster**
- 2 C slotu: 3 C'li kadroda biri UTIL'e veya BN'ye gider.
- G slotu PG'yi kabul eder, C'yi kabul etmez.
- Çoklu pozisyonlu oyuncu doğru slota atanır.
- `can_complete` tamamlanamaz kadroyu yakalar.

**matchup**
- İki özdeş takım → her kategoride `P = 0.5`, `ECW = 4.5`.
- Bir takıma pozitif katkılı oyuncu eklemek o kategoride `P`'yi artırır (monotonluk).
- TO yönü: daha çok TO yapan takımın TO kategorisinde `P < 0.5` olur.
- Oran: eşit hacimde daha yüksek yüzde `P > 0.5` verir.
- Hacim: %50'lik takıma yüksek hacimli %42'lik şutör eklemek FG `P`'sini düşürür.
- **Punt bağımsızlığı:** kategori ağırlıkları değişince ECW değişmez.
- `Var(D) = 0` dejenere durumu doğru işlenir.
- ECW'nin 15 rakip üzerinden ortalaması alınır.

**bots**
- **Monotonluk (İlke 6):** Pick 50'de ADP'si 20 olan oyuncu uygunsa, sonraki 3 pick içinde seçilme oranı (1000 simülasyon) ≥ %90 olmalıdır (varsayılan parametrelerle).
- **Kuyruk:** ADP≈90 oyuncunun ilk 16 pick'te gitme oranı > 0 ve < %1 olmalıdır (10.000 simülasyon).
- **Tutarlılık:** Aynı draft içinde botun algılanan sıralaması pick'ler arasında yüksek korelasyonlu olmalıdır (`jitter_rho` küçük).
- `σ → 0` limitinde botlar ADP sırasını birebir izler.
- Feasibility açıkken 13. tur sonunda tüm kadrolar tamamlanabilir olmalıdır.
- Aynı seed aynı draft'ı üretir.

**advisor**
- Deterministik ADP (`σ → 0`) ile survival değerleri 0/1 olur ve beklenen sonuçla eşleşir.
- **Oyuncak problem:** Eşit ΔECW'li X ve Y oyuncularından X'in 48'e kalması kesin, Y'ninki imkânsız → öneri Y'yi şimdi almaktır.
- Çiftler sırasızdır: (a,b) ≡ (b,a).
- CRN: aynı seed aynı E[W] verir. Aynı çiftin iki kez değerlendirilmesinde fark 0'dır.
- SE, `S` arttıkça yaklaşık `1/√S` ile küçülür.
- Tek seçimli turn (208) 1 elemanlı yolla doğru çalışır.

### 9.2 Entegrasyon testleri
- Sentetik veriyle uçtan uca: yükle → değerle → tam mock → advisor (hızlı mod) → export → import → aynı state.
- 3RR açık konfigürasyonla uçtan uca.

### 9.3 Mimari testi (`test_architecture.py`)
- `fdo.valuation` ve `fdo.matchup` modülleri `adp` tablosuna veya `fdo.bots`'a erişmez (AST ile import taraması).
- `ui/` dışında `streamlit` import'u yoktur.

### 9.4 Ölçüm, test değil
§7 gerçekçilik raporu ve §11 süre ölçümleri CI'da **raporlanır**, fakat test eşiği olarak kullanılmaz. İstisna: §9.1'deki bot monotonluk ve kuyruk testleri.

---

## 10. Kilometre taşları ve kabul kriterleri

Her kilometre taşı bağımsız olarak çalışır ve testleri geçer. Bir sonraki kilometre taşı öncekini bozmaz.

### M0 — Veri temeli
- [x] Repo iskeleti, `pyproject.toml`, `config/league.yaml`, `config/model.yaml`
- [x] Şemalar, loader, kolon eşleme, validasyon raporu, manifest zorunluluğu
- [x] Sentetik veri üretici ve sentetik bandı politikası
- [x] ADP güven sınıfları ve imputasyon
- [x] §9.1 ingest testleri
- [ ] **Kullanıcı eylemi:** gerçek projeksiyon ve ADP kaynağı kararı, manifest'lerin doldurulması (§5.1 tablosu)

### M1 — Projection Explorer
- [x] Havuz iterasyonu, Z, hacim ağırlıklı FG/FT, G (κ etiketli), ağırlıklar ve presetler
- [x] Sayfa 1 ve 2
- [x] §9.1 valuation testleri

### M2 — Snake engine ve manuel draft board
- [x] Sıra, turn'ler, event log, undo/replay, import/export
- [x] Roster eligibility ve assignment
- [x] Sayfa 3 (yalnızca manuel seçim)
- [x] §9.1 draft ve roster testleri

### M3 — Thurstone botları ve mock simülatörü
- [x] `BotLeague`, profiller, feasibility
- [x] Sayfa 3'te bot oynatma ve reach renkleri
- [x] `run_mock_batch.py` ve sayfa 6 (realism report)
- [x] §9.1 bot testleri, ilk gerçekçilik raporu ve buna göre parametre gözden geçirme

### M4 — Matchup modeli
- [x] Oyuncu haftalık ortalama/varyans, takım toplamları, P(win), ECW
- [x] Doldurma profilleri (taban ve koşullu)
- [x] Sayfa 5
- [x] §9.1 matchup testleri

### M5 — Pair advisor ve 48/49 havuzu (V1'in asıl hedefi)
- [x] CRN simülasyon çekirdeği, survival, aday üretimi, çift skorlama, rollout
- [x] Sayfa 4: çift tablosu, 48/49 havuzu, karşılaştırma, bekleme maliyeti
- [x] §9.1 advisor testleri, §11 süre ölçümü
- [x] **Kabul:** Sentetik veriyle 16/17'de en az 5 aday çift için, 48/49'da uygun oyuncu olasılıkları SE ile birlikte görüntülenir. İki çift yan yana karşılaştırılabilir. Sonuç aynı seed ile tekrar üretilebilir.

### M6 — Alternatif kadro senaryoları (hafif)
- [x] Tam rollout, arketip gruplama, sayfa 4'e sekme olarak eklenir

---

## 11. Performans bütçeleri

Hedefler sıradan bir dizüstü bilgisayar içindir ve **ölçülerek doğrulanacaktır**. `scripts/profile_advisor.py` her kilometre taşında çalıştırılır ve sonuçları raporlar.

| İşlem | Hedef | Ölçülen (Windows dizüstü, gerçek Yahoo verisi, 508 oyuncu) |
|---|---|---|
| Valuation (600 oyuncu, ağırlık değişimi) | < 0.5 s | 0.03 s |
| Tek tam mock (208 pick, 15 bot) | < 0.2 s | 0.08 s |
| 500 mock batch | < 90 s | 16 s |
| Doldurma tablosu (200 mock) | < 40 s (önbellekli) | 6 s |
| Advisor hızlı mod (`S = 200`, 30 çift) | < 15 s | 8–12 s (16/17 ve 48/49) |
| Advisor tam mod (`S = 500`, 30 çift) | < 45 s | 21–36 s |
| V2 tam ufuk (8 çift, kademeli yarılama 40/40/80) | < 45 s | ~15 s (pick 16) |

Gerçek veride ilk ölçümler bütçeyi aşıyordu (tek mock 0.52 s, hızlı mod 16–26 s). Neden: 3 pozisyonlu oyuncularla 12 pozisyon grubu oluşuyor ve bot kadro analizi her durumda `linear_sum_assignment` çözüyordu. Bot analizi grup × slot tipi düzeyinde kapasiteli eşlemeye (`GroupFlow`) çevrildi; "bu oyuncu boş slotu azaltır mı" sorusu tek eşlemeden artık-graf erişilebilirliğiyle cevaplanıyor (eski çözücüyle eşdeğerliği testle korunur). CI her push'ta bu ölçümü raporlar.

Hedef aşılırsa sırayla şunlar uygulanır: (1) ECW değerlendirmesi vektörize edilir, (2) aday ve çift sayısı küçültülür, (3) ardışık yarılama (successive halving) kullanılır: önce `S = 100` ile kötü çiftler elenir, kalanlara `S` artırılır. Yahoo pick süresi (§3.2) öğrenildiğinde tam mod bütçesi buna göre ayarlanır.

---

## 12. Bilinen sınırlamalar ve açık sorular

### 12.1 Model sınırlamaları (V1'de bilinçli olarak kabul edilenler)
- **Normal yaklaşım:** STL/BLK gibi düşük sayılı kategorilerde haftalık dağılım çarpık ve ayrıktır. Beraberlikler yok sayılır.
- **Maç sayısı** takvim yoksa sabittir (`games_per_week`); takvim yüklüyse takım ortalamasıdır (§13.4). Varyans opsiyoneldir ve oyuncular arası kovaryans yoktur.
- **Varyans parametreleri (`φ`) kalibre edilmemiştir.** Oran kategorilerinde binom terimi yapısal olarak doğrudur. Hacim varyansı ise varsayımdır.
- **Utilization tek bir katsayıdır** (advisor'da). Günlük lineup çözücü Team Dashboard, utilization tahmini ve backtest'te kullanılır (§13.4).
- **Doldurma profilleri nötrdür.** Rakip ve kullanıcı punt eğilimlerini modellemez.
- **Sonraki çift politikası miyopiktir** (π). V1'de 49'dan sonrası doldurma profiliyle temsil edilir; V2 tam ufuk modu draft'ı sonuna kadar açgözlü ECW π ile oynar (§13.3).
- **Bot σ₁ 11 gerçek Yahoo draft log'uyla kalibre edildi** (§13.6, 14 takımlı mock/lig); profil karışımı ve geç tur konum kayması kalibre edilmedi, olasılıklar `uncalibrated` etiketini korur.
- **Geç turlarda `pick − A` medyanında pozitif kayma.** Reach'ler `pick − A` dağılımına sol kuyruk ekler; medyan bu yüzden ortalamadan büyüktür. Gerçek Yahoo verisinde kalan kayma 8–13. turlarda +6.5…+16.3 (σ sınırı çarpandan sonraya alınmadan önce +17…+26). ADP'si 97–160 bandındaki oyuncular ortalamada ADP'lerinden birkaç pick geç gider; bu bölgede survival olasılıkları hafif iyimser olabilir. Oyuncu başına konum kalibrasyonu denendi ve yakınsamadı (§6.4.3); gerçek draft log'larıyla kalibrasyon V2'dedir.
- **ADP büyük ölçüde 10/12 takımlı liglerden gelir.** 16 takımlı ligin geç turlarında belirsizlik yüksektir.
- **Sezon boyu rastgele rakip varsayımı:** Gerçek H2H takvimi ve playoff haftaları yok sayılır.

### 12.2 Kullanıcının doğrulaması gereken açık sorular
1. ~~Kategori beraberlik kuralı~~ — cevaplandı: kategori beraberliği T yazılır (W-L-T), `tie_value: 0.5`.
2. ~~Draft pick süresi~~ — cevaplandı: 45 s (yalnızca gerçek draft için advisor bütçesi; mock'ta süre yok).
3. ~~Yahoo'nun draft sırasında pozisyon sınırı uygulayıp uygulamadığı~~ — cevaplandı: uygular (§6.3.2).
4. Lineup kilit kuralı, IL/IL+ slotları. **Yanıtlandı (13 Ekim 2026):** daily_today → `utilization` 0.987 (§6.6.1); 3 IL (draft'ta dolmaz), IL+ yok; NA draft edilmez, O/Q etkisiz (§5.8).
5. ~~Projeksiyon kaynağının kullanım şartları~~ — kullanıcı kararı: Yahoo sayfaları public, kişisel kullanım (`personal_use_confirmed`).
6. ~~ADP kaynağının kolonları~~ — Yahoo Draft Analysis: `% drafted`, preseason / all / last 7 days ADP var; std ve min/max yok. ADP en fazla ~123. pick'i kapsıyor (§5.6 `after_coverage`).
7. ~~Otomatik draft eden menajer~~ — cevaplandı: yok, `AutoDrafter: 0`.
8. ~~Fantasy playoff ve birleşik haftalar~~ — cevaplandı: playoff son 3 hafta; yalnızca All-Star haftası birleşir (§13.4).
9. ~~NBA takvimi ve game log'ları~~ — kullanıcı kararı: kişisel kullanım (`personal_use_confirmed`).
10. ~~Yahoo API~~ — kullanıcı kararı: bireysel kullanım için API onayı alınamaz; canlı senkronizasyon yok, gerçek draft'ta pick'ler elle girilir.
11. ~~Gerçek draft log'ları~~ — 10 mock + 1 gerçek lig draft'ı (14 takım) eklendi; σ₁ 0.12 → 0.18 (§13.6).

### 12.3 Doğrulanmamış teknik iddialar
- G-score paydasındaki kesin katsayı (`κ`). Makaleden doğrulanacak.
- Yahoo autodraft'ın varsayılan sıralamayı kullandığı. Doğrulanmadı; AutoDrafter profili bu varsayıma dayanıyor (bu ligde kullanılmıyor).
- Yahoo pozisyon kuralının tam tanımı. "Kalan pick'lerle aktif slotlar doldurulamıyorsa pick reddedilir" yorumu uygulanıyor.
- §7'deki gerçekçilik hedef değerleri birer varsayımdır.

---

## 13. V2

V2 yol haritasının altı maddesi uygulanmıştır; yedincisi (Yahoo API canlı senkronizasyonu) kullanıcı
kararıyla yapılmamıştır (§13.7). Dış veri isteyen parçalar (takvim, game log, draft log) **dosya
tabanlıdır**: veri script'lerle indirilir ve manifest'le yüklenir (§5.1–5.2). `load_data_dir` bir veri
dizinindeki `variance*.csv` ve `schedule*.csv` dosyalarını veri setiyle birlikte yükler (UI'da
"Diskten yükle" sekmesi de bunları önerir).

### 13.1 Backtest (`fdo.evaluation`)

`SeasonEvaluator` protokolünün iki uygulaması vardır; ikisi de **all-play** skorlar (her hafta
her takım diğer 15 takımla kategori bazında karşılaştırılır, beraberlik `tie_value`).
`category_wins[seat]` eşleşme başına ortalama kategori galibiyetidir (0–9, ECW ile aynı ölçek).

- `ProjectionNoiseEvaluator`: gerçekleşen sezon simüle edilir. Oyuncunun gerçek maç başı üretimi
  `projeksiyon × exp(σ·z − σ²/2)` (`--projection-sd`, varsayılan 0.12), maç oranı Beta(κ = 8),
  haftalık toplamlar normal yaklaşımla çekilir. **İyimserdir** (projeksiyon hatası modelden gelir)
  ve rapora bu not yazılır.
- `GameLogEvaluator`: gerçekleşen maç kayıtları; fantasy haftaları `assign_weeks`, her gün oynayan
  oyuncular günlük lineup çözücüsüyle (§13.4) aktif slotlara yerleştirilir, yalnızca sayılan maçlar toplanır.

Stratejiler (`fdo.evaluation.backtest`): `adp` (en düşük ADP), `z` / `g` (dengeli Z / G), `ecw`
(V1 advisor'ın en iyi seçimi, hızlı ayarlarla). Her draft `d` için tüm stratejiler aynı bot
gürültüsünü ve aynı gerçekleşen sezonu görür (CRN); rapor ortalama kategori galibiyeti, lig sırası,
ilk 3 oranı ve `adp`'ye göre eşleşmeli farkı verir.

```bash
python scripts/backtest.py --data data/real/ --n 30 --strategies adp,z,g,ecw
```

Ölçüm (gerçek Yahoo verisi + 2026-27 takvimi + kalibre varyans, `noise`, 12 draft, koltuk 16, 58 s; küçük örneklem):

| Strateji | Eşleşme başına kategori galibiyeti | SE | Ortalama sıra (16) | İlk 3 |
|---|---|---|---|---|
| ecw | 5.29 | 0.10 | 3.4 | %75 |
| g | 5.13 | 0.12 | 4.3 | %42 |
| z | 5.03 | 0.17 | 5.7 | %42 |
| adp | 4.60 | 0.15 | 8.1 | %8 |

`adp`'ye göre eşleşmeli fark: ecw +0.69 ± 0.18, g +0.53 ± 0.20, z +0.43 ± 0.23. Gerçekleşen sezon
projeksiyon + gürültü olduğu için bu farklar iyimserdir (projeksiyonu iyi kullanan strateji ödüllenir).
İlk backtest, advisor'ın geç turlarda hiç geçerli çift bulamadığı bir hatayı ortaya çıkardı (aday
kümesi pozisyon kuralını yok sayıyordu); aday kümesi artık kurala uygun oyunculardan kurulur ve geçerli
çift yoksa her pozisyon grubundan en iyi oyuncularla genişletilir.

**Veri sorunu sürüyor:** geçmiş sezonların sezon öncesi projeksiyon/ADP snapshot'ları yok. Bu
yüzden `gamelogs` değerlendiricisi bu veri setiyle ancak içinde bulunulan sezonun sonunda
(o sezonun log'larıyla) anlamlıdır.

### 13.2 Varyans kalibrasyonu (`fdo.calibration.variance`)

Girdi `gamelogs` şemasıdır (§5.3). `scripts/fetch_gamelogs_nba_api.py` bir sezonu `nba_api` ile
indirir (opsiyonel bağımlılık `.[nba]`; lisans kararı `--license-status` ile manifest'e yazılır).
`scripts/calibrate_variance.py` (bir ya da birden fazla sezon):

- `φ_s` = oyuncu başına `s²/μ` oranlarının medyanı (≥ `min_games` maç),
- oyuncu varyansı: oran `φ_s`'ye büzülür `d̂ = ((n−1)·d + n₀·φ_s)/(n−1+n₀)`, projeksiyon
  ortalamasıyla ölçeklenir (`Var = d̂ · μ_proj`; oyuncunun yeni rolüne uyar) → `variance` CSV + manifest,
- kategori korelasyonu: oyuncu içi standartlaştırılmış maç kalıntılarının havuzlanmış korelasyonu
  (oran kategorileri `makes − p̄·att`, TOV ters) → `model.variance.category_corr` için YAML parçası.

Korelasyon yalnızca **P(≥5 kategori)** göstergesinde kullanılır (Gauss kopulası: `z ~ N(0, R)`,
kategori kazanılır ⇔ `z_c < Φ⁻¹(p_c)`; marjinaller korunur). ECW beklenti olduğu için korelasyondan
etkilenmez. Korelasyon yoksa gösterge `assumes_independence` rozetini taşır.

```bash
python scripts/fetch_gamelogs_nba_api.py --season 2024-25 --license-status personal_use_confirmed
python scripts/fetch_gamelogs_nba_api.py --season 2025-26 --license-status personal_use_confirmed
python scripts/calibrate_variance.py --gamelogs data/real/gamelogs_nba_2024-25.csv data/real/gamelogs_nba_2025-26.csv
python scripts/mark_rookies.py --gamelogs data/real/gamelogs_nba_2024-25.csv data/real/gamelogs_nba_2025-26.csv
```

**Gerçek veri (13 Ekim 2026):** 2024-25 + 2025-26, 596 oyuncu, 46 858 maç (oyuncu dosyasıyla
eşleşmeyen 90 oyuncu — emekli/yurt dışı — düşürüldü). `data/real/variance_nba_2024-25_nba_2025-26.csv`
veri setiyle birlikte yüklenir; `φ` ve korelasyon `config/model.yaml`'dadır:

| stat | fgm | fga | ftm | fta | fg3m | pts | reb | ast | stl | blk | tov |
|---|---|---|---|---|---|---|---|---|---|---|---|
| φ | 1.37 | 1.65 | 1.95 | 2.19 | 1.18 | 3.46 | 1.40 | 1.27 | 1.08 | 1.07 | 1.07 |

V1 varsayılanı φ = 1 (Poisson) idi; PTS ve serbest atış hacmi belirgin aşırı yayılımlı. En güçlü
kategori korelasyonları: PTS–3PM 0.67, PTS–FG% 0.60, 3PM–FG% 0.40, REB–PTS 0.31; TOV (kazanma
yönünde) diğer sayma kategorileriyle negatif (−0.08…−0.16). Varyans dosyası olmayan oyuncular (rookie)
`φ · μ` alır.

**Rookie bayrağı:** `scripts/mark_rookies.py` son iki sezonda hiç NBA maçı olmayan oyuncuları
`players.is_rookie` ile işaretler (139 oyuncu, draft havuzunda 34; 2026 draft sınıfı: Boozer,
Dybantsa, Wilson, Peterson…). Senaryolarda (§13.5) daha geniş belirsizlik alırlar.

### 13.3 Derin lookahead (`fdo.advisor.deep`)

**Tam ufuk rollout.** V1 sonraki turn'den sonrasını doldurma profiliyle temsil eder. Tam ufuk
modunda her aday çift için draft sonuna kadar simüle edilir: kullanıcının her sonraki pick'inde π,
o simülasyonda uygun ve kadroyu tamamlanabilir bırakan oyuncular arasından
`ECW(mevcut kadro + i + kalan pick doldurması)`'nı en büyükleyeni seçer (kısa liste her pick'te
ΔECW ile yeniden kurulur, `deep_shortlist_k`). `W`, 16 takımın 13'er gerçek oyuncusuyla hesaplanır.
π her pick'te kadroya göre ECW'yi optimize ettiği için punt/denge kararları kendiliğinden oluşur
(H-score'un "gelecek pick'ler kadroya uyum sağlar" fikrinin simülasyonla karşılığı).

**Kademeli yarılama.** V1 sıralamasının ilk `deep_pairs` (8) çifti `deep_rungs` (40, 40, 80) yeni
simülasyonla basamak basamak değerlendirilir; her basamakta en iyi yarı (en az 2) devam eder. Yeni
simülasyonlar `sim_offset` ile eklenir: önceki simülasyonlar yeniden hesaplanmaz, CRN korunur.

Gerçek Yahoo verisinde (Windows dizüstü): pick 16'da ~15 s; draft ilerledikçe kısalır (pick 144'te birkaç saniye).
Sıralama V1'den farklılaşabilir (pick 16 örneği: V1'in ilk çifti tam ufukta 5. sıraya düştü).
Draft Assistant'ta "Derin analiz" bölümünden çalıştırılır.

**Uygulanmayan:** beam search (π her turn'de zaten kısa liste üzerinde tam arama yapar) ve
H-score'un kapalı biçimli ağırlık optimizasyonu.

### 13.4 Takvim ve günlük lineup (`fdo.schedule`)

- `schedule` şeması (§5.3); `scripts/fetch_nba_schedule.py` NBA takvim JSON'unu normal sezon
  maçlarına çevirir (`--download` ya da `--input`). cdn.nba.com bu ağdan 403 döndürdüğü için aynı
  yapıdaki stats.nba.com `scheduleleaguev2` endpoint'ine (nba_api) düşer. Takımı belli olmayan maçlar
  (NBA Cup eleme turu) atlanır.
- Fantasy haftası `schedule.week_start` (pazartesi) gününde başlar; `schedule.merge_with_next`
  birleşen haftalar. Son `unverified.playoff_weeks` hafta playoff'tur.
- **2026-27 (13 Ekim 2026'da alındı):** 1 200 maç, 24 eşleşme haftası (20 Ekim – 11 Nisan). All-Star
  arası 19–24 Şubat 2027 → 18. hafta 19. haftayla birleşik (15–28 Şubat, takım başına ortalama 4.1
  maç). Playoff: 22–24. haftalar (22 Mart – 11 Nisan). NBA Cup eleme turu ve ona bağlı ~30 maç (takım
  başına 2) henüz takvimde yok: 7–8. haftalar (30 Kasım – 13 Aralık) eksik sayılır; Aralık ortasında
  takvim yeniden çekilmeli.
- Takvim yüklüyse oyuncunun haftalık beklenen maçı sabit `games_per_week` yerine takımının eşleşme
  başına ortalamasıdır; playoff haftaları `matchup.playoff_weight` ile ağırlıklanır.
  `matchup.games_variance: true` haftadan haftaya maç sayısı varyansını ekler
  (`Var(X) = E[N]σ² + Var(N)μ²`, oran bileşenlerine de; oyuncular arası kovaryans yok).
- Günlük lineup çözücü: her gün oynayanlar aktif slotlara pozisyon uygunluğuyla en büyük atama.
  Team Dashboard kadronuzun hafta başına takvim maçı / sayılan / yedekte kalan maçını gösterir.
  `scripts/estimate_utilization.py` veri dizininde takvim varsa utilization'ı gerçek takvimle tahmin eder.

### 13.5 Sakatlık ve rol senaryoları (`fdo.advisor.uncertainty`)

Simülasyon başına oyuncu çarpanı `m = (a/ā)·r`: maç oranı `a ~ Beta(ā·κ, (1−ā)·κ)`
(`ā = projected_gp/82`), rol `r = exp(σ_r·z − σ_r²/2)`. Rookie'ler (`players.is_rookie`) için
κ küçük (5 vs 8), σ_r büyük (0.20 vs 0.08). Çarpanın beklentisi 1'dir: E[W] az değişir, P10–P90
riski yansıtır. Draft Assistant'ta "Sakatlık/rol belirsizliği" kutusuyla açılır; V1 rollout'unda
kullanıcı ve rakip kadrolarına, tam ufukta final kadrolara uygulanır (π gelecekteki sakatlığı
bilmez). Çarpanlar simülasyon kimliğiyle tohumlanır (CRN). Kalibre edilmemiştir.

### 13.6 Bot kalibrasyonu (`fdo.calibration.bots`)

Draft log'ları (`draft_log` şeması: Mock Draft export'u, elle girilen Yahoo mock/lig draft'ları) ile σ₀, σ₁ **simülasyonlu momentler** yöntemiyle uydurulur: ADP bandı (16 pick) başına
`pick − A` dağılımının P10/P50/P90'ı hedeftir; ızgaranın her noktası aynı seed'le (CRN) simüle
edilir. σ₀/σ₁ yalnızca `adp_std`'si olmayan oyuncuların σ'sını belirler (Yahoo verisinde hepsi).
Survival güvenilirliği: kullanıcının pick'lerinde tahmin edilen `P(uygun)` aralıklarına göre gözlenen
frekans ve Brier skoru (mevcut ve uyumlu parametrelerle). Sentetik testte gerçek (σ₀ = 3, σ₁ = 0.1)
3 × 3 ızgarada geri bulunur. Profil karışımı uydurulmaz.

**Farklı lig büyüklüğü.** Yahoo'da 16 takımlı mock yok; 14 takımlı log'lar `--teams 14` ile
kullanılır: simülasyon 14 takım × 13 tur, bot karışımı 13 rakibe orantılı ölçeklenir
(`league_config`). `pick − A` pick sırasına (kaçıncı seçilen oyuncu) göre ölçüldüğü için σ₀/σ₁ 16
takıma büyük ölçüde taşınır; 183–208. pick'ler gözlenmez.

**İsimli log ve otomatik pick'ler.** Log `player_id`'siz olabilir: `pick`, `player` (Yahoo yazımı) ve
opsiyonel `auto` kolonlu CSV/TSV, ad/alias ile eşlenir. Mock'tan ayrılan menajerlerin yerine Yahoo'nun
seçtiği pick'ler (`auto` dolu) draft'ta kalır ama momentlere girmez — aksi hâlde sapma olduğundan küçük
çıkar (bu ligde autodraft yok).

```bash
python scripts/convert_draft_results.py --user Hüsamettin --json-user "New York Hav Havs"
python scripts/calibrate_bots.py --logs "data/real/draft_logs/*.csv" --teams 14
```

**Ölçüt.** Varsayılan ölçüt sabit kümede survival Brier'idir (`survival_brier`: her 6 pick'te ADP'si
`n ± 40` olan tüm oyuncular için `P(uygun @ n)`); advisor'ın kullandığı büyüklük budur. Momentler
(`--objective moments`) gerçek log'larda σ'yı fazla daraltıp survival'ı kötüleştirdi (Brier 0.130 → 0.166):
geç turlardaki merkez kaymasını σ'yı küçülterek telafi etmeye çalışıyor. `survival_reliability`'nin Brier'i
yalnızca 0.01–0.99 tahminleri sayar; küme σ ile değiştiği için σ'lar arası karşılaştırmada kullanılmaz.

**Gerçek log'larla sonuç (13 Ekim 2026).** `data/real/draft_logs/`: 10 Yahoo mock + 1 gerçek lig draft'ı
(14 takım × 13 tur; ham metin/JSON `raw/` altında). "Team N" adlı takımlar Yahoo botu, kullanıcının
pick'leri strateji denemesi olduğu için dışlandı → 1 313 pick (gizli otomatik pick'ler ayıklanınca 1 007). Izgara σ₀ ∈ {0.5, 1.5, 3, 5},
σ₁ ∈ {0.08, 0.12, 0.18, 0.25, 0.35}, σ_cap ∈ {25, 40, 60}:

| | σ₀ | σ₁ | σ_cap | Survival Brier |
|---|---|---|---|---|
| Önceki varsayılan | 1.5 | 0.12 | 25 | 0.113 |
| **Seçilen** | 1.5 | **0.18** | 25 | **0.106** |
| Brier'de en iyi | 3.0 | 0.18 | 25 | 0.106 |
| σ_cap 40 / 60 | — | — | 40 / 60 | 0.12–0.18 (kötü) |

**Mock'lardaki gizli otomatik pick'ler.** Mock'tan ayrılan menajerin adı kalır ama pick'lerini Yahoo yapar.
Yahoo'nun kuralı "Team N" pick'lerinden çıkarıldı: kadroyu tamamlanabilir bırakan oyuncular arasında en iyi
xrank (`autopick_rule_matches`; bot pick'lerinin %91.5'i birebir uyar). Gerçek lig draft'ındaki insanlar
bu kurala %17 uyar; mock'lardaki "insan" takımlar %22–72 ve birçoğu draft'ın tamamını ya da son 3–13
pick'ini birebir kuralla seçmiş. Adı olan takımda art arda ≥ 3 kural uyumu otomatik sayılır
(`infer_autopicks`; tesadüf olasılığı ~%0.17³ ≈ %0.5) → 475 pick daha dışlandı, 1 007 insan pick'i kaldı.
Kalanların kurala uyumu %16.9 — gerçek lig draft'ıyla aynı. Temizlikten sonra da seçim değişmedi
(σ₁ = 0.18). Temizlenmiş veride 33–96. pick'lerde insanlar ADP'nin 2–4 pick **önünde** seçiyor
(medyan −1…−4); simülasyon aynı bölgede +1…+4 — konum kayması, σ ile düzelmez.

İyileşme log'ların iki yarısında da tutar (0.116 → 0.109, 0.107 → 0.102); tek gerçek lig draft'ında
başa baş. σ₀ ∈ {0.5, 1.5, 3} Brier'de gürültü içindedir; 1.5, ADP'si ilk 48 olan oyuncuların gözlenen
yayılımına en yakındır (gözlenen 1–16 bandı P10/P90 −2.7/+3.0; σ₀ = 3 ile −4.0/+5.0). İnsanlar 33–96.
pick'lerde ADP'den ±10–13 pick sapar; önceki σ₁ bu bölgede fazla dardı ("%5 kalır" denen oyuncular
%18 kalıyordu). Kalan sapma: geç turlarda (113–160) simülasyonun `pick − A` medyanı gözlenenden
+4…+8 pick yüksek (konum kayması, σ ile düzelmez).

### 13.7 Yahoo API senkronizasyonu — yapılmadı

Kullanıcı kararı (13 Ekim 2026): Yahoo Fantasy API uygulama onayı bireysel kullanım için alınamaz.
Bir ara sürümde yazılan OAuth/draftresults istemcisi kaldırıldı; gerçek draft'ta pick'ler Mock Draft
sayfasından elle girilir (ya da log CSV'si import edilir). Sezon içi veri için kullanıcının oturumuyla sayfa okuyan
senkronizasyon: §13.20.

### 13.9 Strateji araçları ve bot davranışı (13 Ekim 2026)

**Strateji ağırlıkları.** Draft Assistant ve Canlı Draft'ta 9 kategori için 0–2 ağırlık (0 = punt; preset'ler
`valuation.presets`'ten). Verilirse advisor adayları, çiftleri, rollout'u ve tam ufku `Σ_c w_c·P_c` ile
sıralar — İlke 2'nin (yalnızca ECW) kullanıcı isteğiyle bilinçli istisnası. Her seçimin ağırlıksız ECW'si
ayrıca gösterilir; stratejinin gerçek kategori galibiyetine maliyeti böylece görünür.

**Punt planı karşılaştırması** (`compare_punt_plans`, Senaryolar sekmesi). Dengeli, 9 tek kategori punt'u,
yaygın ikili punt'lar ve (varsa) kullanıcının ağırlıkları aynı draft senaryolarında (CRN) sona kadar
oynanır; kullanıcının sonraki pick'leri plandaki ağırlıklarla seçilir, final kadro 9 kategoriyle
değerlendirilir. Dengeli = advisor'ın kendi politikası; ECW kaybedilen kategorilere yatırımı zaten
kendiliğinden bıraktığı için bir punt ancak kadro belirli bir yöne kaymışsa öne geçer. Gerçek veride
16 plan × 60 simülasyon ~28 s.

**Botların kadroya uyumu.** Tüm botlar zaten boş pozisyonel slot bonusu, pozisyon yığma cezası ve
pozisyon kuralıyla kadroya bakar; PuntBuilder (3/15) en zayıf kategorisini punt eder. Ek olarak
"güçlü kategorileri güçlendirme" kaydırması eklendi (`bots.team_fit_lambda`, saf kaydırma
`q + λ·(R_fit − R_düz)`). 12 gerçek log'da isabeti artırmadı (λ 0.1: Brier 0.1049 → 0.1047, gürültü;
0.3: 0.1089); projeksiyon değerine çeken versiyon belirgin kötüleştirdi (insanlar ADP'yi izliyor).
Varsayılan kapalı.

**ADP fallback denemeleri.** Düşük güvenli oyuncunun σ çarpanı 1.5 → 1.0 (Brier 0.1059 → 0.1048, iki
yarıda da). Düşük güvenlide gerçek ADP ağırlığını artırmak ve kapsam dışı Â'ya ofset iyileştirmedi.
İlk taramada görülen büyük "iyileşme" (0.090) ölçüm hatasıydı: değerlendirme kümesi A ile birlikte
kayıyordu; sabit referans kümesinde (oyuncu kimliğiyle) ölçüm yapılır.

### 13.10 Draft Analizi: arka plan advisor ve kategori panosu (13 Ekim 2026)

Draft ekranı sade, analiz ayrı sekmede. Uygulama açılınca `data/real` diskten ve `config/league.yaml`
(16 takım, koltuk 16) ile kendiliğinden yüklenir; menü gruplu (`st.navigation`: Draft / İnceleme / Ayarlar).

- **Draft sayfaları** (Mock, Canlı): pick isimle aranıp Enter'la girilir; mock'ta botlar sıra kullanıcıya
  gelene kadar otomatik oynar (Undo son kendi pick'inin öncesine döner). Her durum
  `AnalysisWorker`'a yayınlanır (`common.publish_draft`); sayfada yalnızca tek satır öneri özeti kalır.
- **Arka plan işçisi** (`fdo.advisor.background`, sunucu genelinde tek, `st.cache_resource`): yeni pick
  gelince süren işi iptal edip (ilerleme geri çağrısında `Cancelled`) en son durumdan başlar. Sıra:
  rakip strateji modeli (canlı draft) ve kategori panosu (<1 s) → sıra kullanıcıdaysa hızlı mod (~9 s)
  ardından tam mod (~25 s), ikisi de rakip modeliyle → boşta punt planları (~30 s; kullanıcının kadrosu
  ya da ağırlıklar değişince yenilenir, sıra beklerken de çalışır). Ayarlar `advisor.background_*`.
- **Draft Analizi sayfası** (`/analiz`, yan sekmede açık tutulur): sonuçları işçiden okur, saniyede bir
  yeni sonuç var mı bakıp yenilenir. Takımın kategori P(kazan) şeridi; solda oyuncu panosu, sağda
  önerilen çiftler (ör. 16/17, E[W] ve kademe), punt önerisi ("ağırlıklara uygula" düğmesi) ve rakip
  stratejileri. Strateji ağırlıkları kenar çubuğunda; değişince işçi yeniden hesaplar.
- **Oyuncu panosu** (`fdo.advisor.board`, hashtagbasketball tarzı): maç başı istatistikler oyuncunun
  z-skoru kademesine göre boyanır (Elite ≥1.5 · Great ≥1.0 · Good ≥0.5 · Avg · Below ≤−0.5 · Poor ≤−1.0);
  "Takımına katkı" görünümünde aynı hücreler `ΔP_c = P_c(R ∪ {i} ∪ fill) − P_c(R ∪ F(t₁) ∪ fill)` (puan;
  toplamı ΔECW). Sütunlar: Katkı (ağırlıklı ΔECW), Etkisi (en çok yükselttiği/düşürdüğü kategoriler),
  Kalır (kullanıcının pick'ine — sıradaysa sonraki turn'e — kadar kalma olasılığı, 64 bot simülasyonu).
  Sıralama "Öneri": advisor'ın önerdiği oyuncular önce, sonra katkı; beklerken kalma olasılığı < %10
  olanlar sona. Kullanıcının pozisyon kuralı yüzünden alamayacağı oyuncular gizli. Kategori kıtlığı:
  kalan oyuncularda kategori başına Elite/Great/Good sayısı.
- **Projeksiyonsuz oyuncular** botlarca seçilmez (yalnızca projeksiyonlu aday kalmazsa serbest). Örnek:
  Bronny James'in ADP'si (106.9) Yahoo draft'larının yalnızca %3'ünden geliyordu ve projeksiyonu yok.

### 13.11 İlk çift × strateji senaryoları (`scripts/draft_scenarios.py`)

Draft öncesi hazırlık: 16/17 çifti zorlanarak draft sonuna kadar simüle edilir (`play_draft`: zorlanan
pick'ler, `BatchDraft.reserve` ile "çift 16'ya kalırsa" koşullaması, turn başına politika). Aday çiftler
16'da kalma olasılığı ≥ %8 olan ve ΔECW'si yüksek oyunculardan + kullanıcının verdiği çiftlerden kurulur;
dengeli ve uyarlanabilir stratejiyle elenir, en iyileri 44 stratejilik ızgarada (tek/ikili punt'lar,
"48/49 dengeli → X" ve "baştan X", kadroya göre 1.25/1.5/0.5 ağırlıklı karışımlar) ölçülür, en iyi
~100 senaryo yeni simülasyonlarla yeniden ölçülür. Çıktı `reports/draft_senaryolari.xlsx`: senaryolar,
13'lü kadrolar (pick numarası sütunlarıyla Excel'de filtrelenebilir), çift özeti, ızgara, eleme ve 16'da
uygunluk. `pip install -e ".[excel]"` (openpyxl) gerekir.

### 13.12 Auction draft (`fdo.auction`, Auction Draft sayfası)

`config/league_14_auction.yaml`: 14 takım, koltuk 9, 2 C (FC yok), 13 oyuncu, `draft_type: auction`,
`auction: {budget: 200, min_bid: 1, nomination: round_robin}` (bütçe ve en düşük teklif doğrulanmadı;
sayfadan oturum için değiştirilebilir). Auction sayfası seçili lig snake ise auction ligini yükleme düğmesi gösterir.

- **Değerler** (`values.py`): model değeri = dengeli z toplamının yedek seviyesine (N+1., N = T·rounds) göre
  fazlası lig parasına (`T·bütçe − N·min_bid`) dağıtılır. Piyasa fiyatı = Yahoo ortalama auction fiyatı (AAV;
  `fdo.ingest.auction.parse_costs` JSON/CSV/yapıştırılmış satırları okur, `data/real/auction_aav_yahoo.csv`
  olarak saklanır) aynı toplam paraya ölçeklenir. Taban fiyat: AAV varsa o, yoksa model değeri.
- **Canlı durum** (`state.py`): satışlar (oyuncu, takım, fiyat), kalan bütçe, boş slot, max teklif
  `kalan − min_bid·(boş − 1)`, tahmini aday gösteren (koltuk döngüsü, dolu takım atlanır);
  `data/live/auction.json`'a kaydedilir.
- **Öneri** (`advice.py`): enflasyon = (kalan para − min_bid·kalan slot) / Σ(taban − min_bid) (kalan en iyi
  `kalan slot` oyuncu); beklenen fiyat = min_bid + (taban − min_bid)·enflasyon. Senin için değeri: oyuncunun
  kadrona ECW katkısı (yedek seviyesine göre, boş slotlar havuzun ortalama oyuncusuyla, strateji
  ağırlıklarıyla) havuzun beklenen fiyat toplamına göre dolara çevrilir; ortalama bir takımda ≈ beklenen
  fiyat. Teklif tavanı = min(değer, max teklif). Aday gösterme: pahalı ama senin için fiyatını hak etmeyenler
  (rakipler harcasın) ve değeri fiyatından yüksek hedefler.
- **Eksik**: rakip teklif davranışı modeli ve auction mock'u (gerçek auction draft verisi yok).

### 13.13 Sezon içi: Bu Hafta ve Boştaki Oyuncular (`fdo.inseason`)

Trade Lab verisini (kadrolar, kalan sezon projeksiyonu, NBA takvimi) kullanır; Trade Merkezi menüsünde.

- **Hafta tarihleri** (`weeks.py`): pazartesi başlayan haftalar, 1. hafta sezonun ilk maç günüyle başlar,
  `merge_with_next` (All-Star) birleşir. Lig ayarındaki `Playoffs` metninden playoff haftaları ve bitiş günü
  okunur; hesaplanan son playoff haftası daha erken bitiyorsa o güne uzatılır (dört ligde de son tur iki
  takvim haftası çıkıyor). 93992 sıralamasında 31 Ekim'de herkesin 9 kategori oynamış olması 1. haftanın
  20–25 Ekim olduğunu doğrular. Fikstürde tarih yoktur; tarihler bu kuralla türetilir.
- **Fikstür** (`fixtures.py`): `fixtures*.csv` (league_id, team_id, week, opponent_team_id) ve
  `league_info.json` `schedules.teams`; A–B eşleşmesi B–A olarak tamamlanır. Kayıt yoksa rakip elle seçilir.
- **Bu Hafta** (`weekly.py`): kalan her gün o gün oynayan oyuncular aktif slotlara yerleştirilir
  (`daily_today` çözücüsü, öncelik = stratejiye göre maç başı z). Katkı = sayılan maç × uygunluk
  (`min(1, ROS GP / takımın kalan maçı)`) × maç başı ROS vektörü; haftanın şu ana kadarki skoru elle girilir
  ve sabit eklenir. NA ve (isteğe bağlı) O durumundakiler oynamaz, Q oynar, IL'dekiler kadro dışıdır.
  Çıktı: kategori başına P(kazan), beklenen kategori, P(5+) (kopula), gün gün kadro (▶/B/✕).
- **Streaming planı**: kalan haftalık alım hakkı kadar açgözlü adım; her adım (bırak d, al f, gün t)
  içinden haftalık strateji puanını en çok artıranı seçer. f, d'nin kalan günlerini devralır (kadro her
  gün sabit), t yalnızca f'nin maç günleridir; eklenen oyuncu sonra yeniden bırakılabilir. Son plan gün
  sıralı işlem listesine çevrilir; her işlemin "kalıcı olsaydı" kalan sezon etkisi gösterilir.
- **Boştaki Oyuncular** (`waiver.py`): her boştaki oyuncu için kadrodan en iyi bırakma eşi; kalan sezon
  vektörüyle `R − v_d + v_f` ligdeki diğer takımlara karşı (strateji ΔECW, ağırlıksız ΔECW, kategori ΔP).
  Bırakma sonrası doldurulamayan aktif slot artmaz; IL'deki oyuncu bırakma adayı değildir.
- **Sınırlar**: waiver'daki oyuncular, Can't Cut listesi ve maç saatleri doğrulanmaz; oyuncular arası
  bağımsızlık ve Normal yaklaşım (kalibre edilmedi). Plan açgözlüdür, global optimum değildir.

### 13.14 Sezon simülasyonu (`fdo.inseason.season`, Sezon Simülasyonu sayfası)

Tam H2H fikstürü (`fixtures*.csv`, dört lig 56 takım 519 eşleşme) ve mevcut sıralama (`standings.py`:
`yahoo_fantasy_snapshot.json`, `league_<id>_standings_raw.json` ya da `standings*.csv`) ile.

- Tam sıralaması olan ligde tamamlanan hafta `(W+L+T)/9` kabul edilir ve gerçek W-L-T'den başlanır;
  sıralaması olmayan ligde (şu an 229303, 104375) 1. haftadan itibaren hepsi simüle edilir (uyarı gösterilir).
- Her takımın her haftalık gücü o haftanın NBA takvimi ve günlük lineup'ıyla (`WeekModel.team_week`);
  içinde bulunulan hafta güncel sakatlık ve IL ile, sonrakiler tam kadroyla (kayıp maçlar ROS GP'de).
  Kadrolar sezon boyu sabit.
- **İçinde bulunulan hafta**: veri tarihinden önceki günlerin gerçek skoru veride yok (matchup kaydında yalnız biten
  haftalar var). Bu günler takas öncesi gerçek kadronun beklenen katkısıdır ve her senaryoda aynıdır; takas sonrası
  kadro yalnız veri tarihinden itibaren kalan günlerde oynar. Önceden takas sonrası kadro haftanın tamamına (31 Ekim
  verisinde 26 Ekim – 1 Kasım) uygulanıyordu: takasta giden oyuncunun geçmiş günlerdeki maçları da silinip gelen
  oyuncuya yazılıyordu.
- Eşleşme: kategori olasılıkları + Gauss kopulası; sıralama (W + T/2)/oynanan, eşitlikte rastgele.
  Playoff: ilk n takım (`Playoffs` ayarı), `2^tur` braket, boş koltuk bay; `Playoff Reseeding` açıksa her
  turda en yüksek–en düşük, değilse sabit braket. Playoff haftaları kendi takvimiyle (son tur 14 gün).
- Çıktı: takım başına P(playoff), P(bay) ya da P(1.), P(şampiyon), ortalama sıra, beklenen W-L-T; seçili
  takımın kalan fikstürü (hafta başına beklenen kategori ve P(kazan)); playoff haftalarında sayılan maç.
- **Takas etkisi**: Takas Analizi'nde ve Sezon Simülasyonu'nda, takassız/takaslı kadrolar aynı çekilişlerle
  (CRN, seed 1) — iki takımın ΔP(playoff), ΔP(şampiyon), ortalama sıra farkı.
- Kullanıcının takımı fikstürdeki `is_user_team` işaretinden seçilir (tam fikstürle tek takım kuralı bozulmuştu).
- **Güç belirsizliği**: her simülasyonda her takımın vektörü sezon boyu `λ ~ lognormal(0, sd)` ile
  ölçeklenir (varsayılan sd 0.06, sayfadan 0–0.15). Olmadan güçler kesin bilinir sayılır: 93992'de playoff
  %100, tek takas +50 puan gibi aşırı kesin sonuçlar çıkıyordu. Kalibre edilmedi; takas ve öneri etkileri
  aynı ayarla hesaplanır.
- Sıralama `standings*.csv` (league_id, team_id, wins, losses, ties) dahil üç kaynaktan; dört ligin
  sıralaması 31 Ekim'de tamamlandı, hepsi 1. haftanın gerçek sonucundan başlar.
- Sınırlar: kategori beraberliği, kadro değişiklikleri, sakatlık dönüş zamanları ve oyuncular arası maç
  kovaryansı modellenmez; olasılıklar kalibre edilmedi.

### 13.15 Öneri türleri: karşılıklı fayda, sat yüksek, al düşük (`fdo.trade.perception`, `suggest.py`)

Takas Önerileri'nde üç ayrı tür (`SearchOptions.mode`), her biri kendi eşikleriyle:

- **Karşılıklı fayda** (`mutual`, önceki davranış): iki takımın da kalan sezon strateji kazancı ve paket
  piyasa (ROS) dengesi.
- **Algılanan değer**: rakibin baktığı değer — bu sezonun rakamları (maç başı z; 3 maçtan azı sezon
  öncesine düşer), sezon öncesi isim değeri (ligin draftı ve Yahoo ADP'si, §13.30) ya da ikisinin sıra ortalaması (varsayılan). Algılanan sıra,
  ROS piyasa değer merdivenindeki aynı sıranın fiyatına çevrilir; `edge = algılanan − ROS`. Oran
  kullanılmaz (yedek seviyesinde anlamsız büyür).
- **Sat yüksek** (`sell_high`): verdiğin pakette `edge ≥ min_edge` oyuncu; rakibin gözünde denge
  (aldığı / verdiği algılanan değer) ≥ eşik; senin kazancın eşiği geçer. Rakibin ROS kazancı şart değil.
- **Al düşük** (`buy_low`): aldığın pakette `−edge ≥ min_edge` oyuncu; aynı denge ve kazanç şartı.
- Puan: karşılıklıda önceki formül; diğerlerinde `senin birleşik kazancın × min(1, algılanan denge)`.
- **Gerçekçilik (1 Kasım 2026)**: karşılıklı faydada da rakibin gözündeki denge (algılanan aldığı / verdiği,
  `SearchOptions.min_opponent_view`, arayüz varsayılanı 0.8) şarttır; çok takımlıda takastaki diğer her takım için.
  Yahoo ROS bazı oyunculara neredeyse tüm kalan maçları verdiği için (ör. Caruso 72 maç, sezon öncesi 58) ROS değeri
  ile rakibin baktığı değer çok ayrışabilir; model kazanç görse de rakibin isimlere bakıp reddedeceği takaslar elenir.
- **Bedava waiver** (`TradeEngine.waiver_best`): takasa giren takım hem önce hem sonra boştaki oyuncularla yapabileceği
  bedava hamleleri yapmış sayılır (boş aktif yer en iyi boştakiyle dolar; boştakinden zayıf aktif oyuncu değişir).
  Önceden 2'ye 1 takasta açılan yere giren boştaki oyuncu takasın kazancı sayılıyordu: ör. Caruso ↔ Jalen Johnson +
  Shannon'da 4-2-3-1 Gegen'in "kazancı" (+0.36) aslında takassız da alabileceği iki boştaki oyuncudandı (gerçekte −0.36).
  Değersiz ek oyuncuyla şişirilmiş paketler (aynı takasın + ek oyunculu kopyaları) listeden çıkarılır.
  Takas öncesi tablo (`before_matrix`) takastaki **bütün** takımlara bu hamleleri uygular; ilk sürümde yalnız
  değerlendirilen takıma uygulanıyor, takas sonrası ise iki tarafa birden uygulanıyordu. Karşı tarafın bedava
  iyileşmesi takasın bedeli gibi görünüyordu: istatistikleri aynı iki oyuncunun takası iki tarafa −0.23 / −0.27 ECW
  yazıyordu (şimdi 0, test). METU IE'de bu sapma Kekstra için rakibe göre −0.002 ile −0.073 ECW arasındaydı; öneriler
  gereksiz eleniyordu (ör. losadanas takası +0.037 → +0.060). Çok takımlı önerilerin yerel taraması tek takım
  değişiyormuş gibi (`before_row`) kalır; adaylar tam modelde bu ortak tabanla yeniden puanlanır.
- Sayfada kadrondaki sat-yüksek adayları / rakiplerdeki al-düşük hedefleri tablosu; öneriler için
  "playoff etkisini hesapla" (sezon simülasyonu, CRN) ve ΔP(playoff) / ΔP(şampiyon) ile sıralama.
- Uyarı: en üst oyuncularda değer merdiveni dik olduğu için (ör. SGA bu sezon 17.) büyük negatif edge
  çıkabilir; gerçek menajer isim değerine bakar — bu yüzden varsayılan algılanan değer ortalamadır.

### 13.16 Sakatlık dönüş tarihleri (`fdo.inseason.injuries`, `scripts/fetch_injuries.py`)

`python scripts/fetch_injuries.py` CBS Sports NBA injury report'unu indirir (ESPN otomatik isteği reddediyor)
ve `data/real/injuries_cbs_<tarih>.csv` yazar (yerelde kalır). Durum metni yorumu: "Expected to be out
until at least Nov 22" → dönüş 22 Kasım; "Out for the season" → kalan sezonda yok; Game Time Decision /
Day-To-Day / Questionable / Probable → oynar. Eşleşme ad (normalize) + gerekirse takım; olmazsa aynı takım +
soyad + ilk harf (CBS "Nicolas Claxton" = Yahoo "Nic Claxton"). 31 Ekim raporu: 88/88 eşleşti.

- `apply_injuries`: dönüşten sonra takımın oynayacağı maç < ROS GP ise ROS toplamları orantılı kısılır
  (31 Ekim'de Yahoo ROS'u dönüşlerle zaten uyumluydu; kısılan yok). Ham dosyalar değişmez; trade
  ekranlarında kenar çubuğundaki "Sakatlık dönüş tarihlerini uygula" ile açılıp kapanır.
- Haftalık model ve sezon simülasyonu: oyuncu dönüş gününe kadar oynamaz (gün gün tabloda ✕), sonrasında
  uygunluk `ROS GP / dönüş sonrası takım maçı`. Önceden kaçırılan maçlar sezona eşit yayılıyordu; artık
  zamanlama doğru, özellikle playoff haftaları için (ör. Banchero 22 Kasım'da dönüp playoff'ta tam oynar).
- Trade motoru: kapasite aşılırsa önce kadrodaki O/INJ oyuncu boş IL yerine taşınır, bırakma ancak sonra.
- **IL dönüşü bedeli** (`TradeEngine.crunch_vector`, `SeasonSim.drop_schedule`): IL'deki oyuncu döndüğünde aktif
  kadroda ona yer açılmalı. Boş aktif yer yoksa dönüş sırasıyla (erken dönen önce) aktifler ve dönen oyuncu arasında en
  düşük faydalı olan bırakılır: aktif oyuncu bırakılırsa dönüş sonrası payı (`pay × katkı`, pay = dönüşten sonraki
  takım maçı / kalan takım maçı; tarih bilinmiyorsa ROS maç / kalan maç), dönen oyuncunun kendisi bırakılırsa tüm
  katkısı düşülür. Sezon boyu yok sayılan oyuncu dönmez (bedel yok). Takas ve waiver hesaplarında değişen takım kendi
  stratejisiyle, diğer takımlar ve sezon simülasyonu dengeli değerle karar verir. Önceden model dönen oyuncuları
  kimseyi bırakmadan fazladan sayıyordu: 31 Ekim'de METU IE'de Kekstra'nın 4 IL oyuncusu 13/13 aktif kadroya dönüyor;
  playoff olasılığı %92 → %70, şampiyonluk %17 → %6 oldu (220594'te NY Hav Havs %18 → %30). IL'deki oyuncuyu vermek
  artık bu bedeli kaldırdığı için doğru değerlenir; IL'den oyuncu almak bedeli ekler.

### 13.17 Öneri yönleri ve öneri ayrıntıları (31 Ekim 2026)

Takas Önerileri'nde senin takımın birden çok **yön** (strateji) ile aranır; her yön ayrı bir taramadır ve sonuçlar
sekmelerde, ayrıca birleşik "Tümü" görünümünde yan yana gelir:

| Yön | Strateji | Ne arar |
|---|---|---|
| D Dengeli | 9 kategori ağırlık 1 | genel güç |
| P / P2 Otomatik punt | en zayıf 1 / 2 kategori 0 (`auto_punt`) | zayıf kategoriyi verip kalanları güçlendiren takas |
| C / C2 Zayıfı canlandır | en zayıf 1 / 2 kategori ×3 (`auto_revive`, `Strategy.revive`) | punt'lanmış gibi duran kategoriyi geri kazandıran takas |
| G Haftalık galibiyet | dengeli, `ecw_weight = 0` | ECW yerine doğrudan P(5+); kıl payı kategorilere ağırlık |
| Ö Seçtiğin strateji | hazır punt ya da özel ağırlıklar | kendi tercihin |

- **Sağlamlık**: takasın senin kategori değişimin her yönün ağırlıklarıyla yeniden puanlanır (galibiyet yönünde
  ΔP(5+)); "4/4" takas stratejin değişse de kazançlı demektir. Birleşik görünümde takasın bulunduğu yönler etiketlenir.
- Her öneride: senin ve rakibin **kategori etkisi** (en çok değişen 3 kategori, kazanma olasılığı puanı), **PO maç**
  (fantezi playoff haftalarında kadronun toplam NBA maçı farkı; otomatik bırak/ekle ve sakatlık dönüşü dahil),
  **pozisyon uyarısı** (takastan sonra doldurulamayan aktif pozisyon), **rakibin gözünde** denge (algılanan değer, her
  türde) ve ağırlıksız ΔECW. Sıralama: öneri puanı, sağlamlık, ΔECW ya da playoff + şampiyonluk etkisi.
- Arama hızı: motorun sıcak yolu (otomatik bırak/ekle sırası, paket değeri, sakatlık durumu) numpy dizilerinden okunur;
  yön başına 4000 paket ~5 saniye (önce ~15).

### 13.18 Çok takımlı takas (`fdo.trade.multi`, Çok Takımlı Takas sekmesi)

Yahoo 3–4 takımlı takası tek işlemde yapmaz; elle, aynı anda kabul edilen ikili takaslarla yapılır. Bu modül bunu
tek bir senaryo olarak değerlendirir.

- **İstek**: `MultiTradeRequest(moves=((oyuncu, veren, alan), ...), drops, adds, auto_balance)`; 2–4 takım, her takım
  en az bir oyuncu verir ve alır. Kadro dengesi iki takımlı takasla aynı kuraldır: `TradeEngine.resolve` artık takım
  sayısından bağımsız `resolve_moves` üzerinden çalışır (gelen sakat IL'e, kapasite aşımında kadrodaki O/INJ IL'e, sonra
  en düşük değerli bırakılır, boşalan yer boştakiyle dolar). `score_many` değişen tüm takımlarla lig olasılıklarını
  yeniden hesaplar. İki takımlı istek, iki takımlı motorla birebir aynı sonucu verir (test).
- **Analiz** (`analyze_multi`): her takım için ECW, P(5+), strateji puanı (her takım kendi stratejisiyle), kategori
  etkisi, alınan/verilen ROS değeri ve algılanan değer, PO maç, otomatik işlemler, üç kaynağa göre sıra değişimi;
  "hepsi kazanıyor mu", **değer dengesi** = en dengesiz takımın aldığı/verdiği oranı, komisyon riski, sezon etkisi
  (her takım için playoff/şampiyonluk, aynı çekilişler).
- **Öneriler** (`suggest_multi`): döngüler sen → T1 → T2 (→ T3) → sen. Şekiller: 1-1-1, sen 2 verirsin (2-1-1),
  ortadaki 2 verir (1-2-1), sen 2 alırsın (1-1-2), 4 takım 1-1-1-1. İki aşama: (1) yerel tarama — her takımın kazancı
  yalnız kendi kadro değişikliğiyle, lig geri kalanı sabit kabul edilerek vektörel hesaplanır (13 takımlı ligde ~640
  bin döngü ~2–3 saniye; bire bir değişimde kesin modelle aynı sonuç, test); (2) en iyi 200 aday tam modelle
  (otomatik bırak/ekle + değişen tüm takımlar) yeniden puanlanır, her takımın strateji kazancı ≥ eşik ve değer dengesi
  ≥ eşik şartı burada uygulanır. Puan `(en küçük kazanç + geometrik ortalama) × (0.5 + 0.5 × denge)` (iki takımlı
  karşılıklı fayda ile aynı biçim). Çeşitlilik: her şekle eşit pay, aynı takım grubundan en fazla 3, senin aynı verdiğin
  paketten en fazla 3 öneri.
- API: `POST /api/leagues/{lig}/trade/multi/analyze`, `.../multi/season`, `.../multi/suggest`.
- Sekme: **Analiz** — 3–4 takım seç, kadrolarda oyuncuya tıkla (varsayılan hedef döngüdeki sonraki takım), her
  hareketin hedefini değiştir, her takımın stratejisini seç, isteğe bağlı bırak/boştan al. **Öneriler** — şekiller,
  senin stratejin (yön), diğer takımların varsayımı, eşikler; "Analizde aç" öneriyi Analiz'e taşır. İki takımlı Takas
  Analizi değişmedi.

### 13.19 Dayanıklılık: kalan sezon maçı (`fdo.inseason.durability`, 1 Kasım 2026)

Yahoo'nun kalan sezon (ROS) projeksiyonu sakatlık riskini yok sayar: 31 Ekim'de kadrolu oyuncuların %90'ına takımının
kalan maçlarının ≥ %95'ini veriyordu (Caruso 72 maç; sezon öncesi projeksiyonu 82'de 58). Sık sakatlanan oyuncular
dayanıklılara göre fazla değerli görünüyordu. `apply_durability` sakatlık dönüş tarihlerinden sonra, API'de her zaman
uygulanır:

- **Oynama oranı**: önsel = sezon öncesi projeksiyon maçı / 82 (Yahoo'nun sakatlık geçmişini içeren tahmini). Bu sezon
  oynanan / takımın oynadığı maç, 20 maçlık önselle birleştirilir ve oranı **yalnız yukarı** çeker (rotasyona girip her
  maça çıkan oyuncu, ör. Quenton Jackson .41 → .55). Kaçırılan maçlar oranı düşürmez: güncel sakatlık dönüş tarihiyle
  zaten modellenir, çift sayılmaz.
- **Tavan** = oran × dönüşten sonraki takım maçı (dönüş tarihi bilinmiyorsa bugünden). ROS maçı tavanı aşıyorsa ROS
  toplamları orantılı küçülür, maç başı değerler korunur. Yahoo'nun zaten kıstığı oyuncu (ör. Anthony Davis 59) değişmez;
  sezon öncesi projeksiyonu olmayan oyuncuya dokunulmaz.
- Etki her yerde: takas motoru (haftalık vektör, piyasa değeri), haftalık model ve sezon simülasyonu (uygunluk
  `ROS GP / kalan takım maçı`), IL dönüş payı. Kalan sezon kaynağında GP sütununda kısılan oyuncu `*` ile işaretli; üzerine
  gelince Yahoo'nun maçı ve oran görünür. Bu haftanın görünümünde de sağlıklı oyuncu beklenen değerle (oran kadar) oynar.
- 31 Ekim: 416 oyuncu kısıldı (toplam 30 140 → 24 328 maç). METU IE değer sırası: Kawhi 11 → 48, Kyrie 23 → 60,
  Caruso 37 → 78; Mikal Bridges 90 → 54, Alexander-Walker 45 → 19. Playoff olasılığı: Kekstra %70 → %62, NY Hav Havs
  %30 → %20, Galatasaray Cafe Crown %25 → %37, Karaali SK %19 → %27.

### 13.20 Yahoo senkronizasyonu (`fdo.ingest.yahoo_sync`, `scripts/yahoo_sync.py`, 8 Kasım 2026)

Resmi API yolu kapalı kaldığı için (§13.7) lig sayfaları kullanıcının kendi oturumuyla okunur:

- **Giriş**: `python scripts/yahoo_login.py` otomasyonsuz bir Chrome penceresi açar; ayrı profil
  (`%LOCALAPPDATA%\fdo\yahoo-chrome`, depo dışı) ile bir kez giriş yapılır. Senkronizasyon bu profilin çerezlerini
  Playwright ile (görünmez pencere) bir kez alır; sayfaları düz HTTP ile, aralarında 0,8 sn bekleyerek çeker.
- **Okunanlar** (`fdo.ingest.yahoo_html`, standart kütüphane HTML ayrıştırıcısı): lig ana sayfası (puan durumu, FAB,
  waiver sırası, haftanın eşleşmeleri, kullanıcının takımı), başlangıç kadroları, eşleşme `date=totals` (haftanın şu ana
  kadarki takım toplamları ve kategori skoru), takım sayfası (bu hafta kullanılan alım hakkı, IL, FAB), waiver listesi
  (`W (Nov 9)` → serbest kalma günü), sezon toplamı ve kalan sezon projeksiyonu sayfaları (30 + 30 sayfa, isteğe bağlı).
  Biten haftaların sonuçları yalnız eksikse çekilir (`matchups.json`'a takım toplamlarıyla). Ardından CBS sakatlık raporu.
- **Yazılanlar** mevcut biçimdedir (`rosters.json`, `player_stat_pages.json`), `load_trade_data` değişmeden okur; ek
  olarak `standings_live.csv` ve `yahoo_live.json`. Bir sayfa okunamazsa hiçbir dosya yazılmaz. Yazmadan önceki ve
  sonraki girdiler değiştirilemez arşive alınır (§13.31). Hepsi git dışı.
- **Tarih**: `roster_date` ABD Doğu saatine göre bugündür. Hafta toplamı çekildiği ana kadardır; ABD Doğu 02:00–12:00
  (Türkiye ~10:00–20:00) arası maç oynanmadığından bu aralıkta toplam tam "dünküne kadar"dır. Dışında `live` işaretlenir
  (bugünün kısmi skoru dahil; uyarı gösterilir). Eşleşme sayfasının takım tablosu tarih seçilse de hafta toplamını verir,
  gün gün ayrım yalnız oyuncu satırlarında ve orada isabet/deneme yok; bu yüzden ayrıştırma yapılmaz.
- **Kullanım**: Bu Hafta sayfasında skor elle girilmezse Yahoo'daki toplamdır; streaming planının kalan alım hakkı
  Yahoo'daki kullanılan alımdan. Sezon simülasyonunda içinde bulunulan haftanın geçmiş günleri gerçek toplamdır
  (yalnız bütün takımların toplamı varsa; yoksa §13.14'teki beklenen değer). Canlı veri ancak kadrolarla aynı çekimden ve
  aynı haftadan ise kullanılır. Kadroda olmayan oyuncunun takımı ve sakatlık durumu da artık oyuncu sayfalarından gelir.
- **Uygulama**: üst çubukta "Yahoo'dan güncelle" (arka plan işi, `GET/POST /api/sync`); "projeksiyonlar" kapalıyken
  ~50 sayfa (~1 dk), açıkken ~110 sayfa (~3 dk). İlk çalıştırma biten haftalar dahil 160 sayfa, 4 dk 44 sn sürdü.
  Her sabah için Görev Zamanlayıcı'ya `python scripts/yahoo_sync.py` eklenebilir.
- **Yahoo projeksiyonları rol değişimine tepki veriyor mu** (31 Ekim → 7 Kasım anlık görüntüleri): kalan sezon
  projeksiyonları haftalık güncelleniyor (744 oyuncunun 271'inde maç başı sayı değişti; Paul George 15,2 → 17,3), ama
  takım arkadaşı sakatlığına neredeyse tepki yok: Jalen Johnson "O" → ATL'de en çok +0,4 sayı/maç; Josh Hart "O" →
  Brunson ve Anunoby değişmedi. Sakatlanan oyuncunun yalnız maç sayısı düşüyor (73 → 69). Kısa vadeli rol değişimi
  haftalık kararlar için ayrıca modellenmeli.

### 13.21 Sit/Start (`fdo.inseason.sitstart`, Sit/Start sekmesi)

Maçı olan oyuncu aktif slottan fazlaysa kim oynasın; karar oyuncunun genel değerine değil, o haftaki eşleşmeye göre:

- **Maç değeri**: oyuncunun bir maçının haftalık strateji puanına (dengelide beklenen kategori galibiyeti) katkısı,
  mevcut düzende sayılıyorsa `S(V) − S(V − a·u)`, sayılmıyorsa `S(V + a·u) − S(V)` (`V` iki takımın haftalık vektörü,
  gerçek hafta skoru dahil; `a` uygunluk; `u` maç başı vektör, rol değişimi süresince rollü). Oranlar isabet/deneme ile.
- **Düzen**: her gün maçı olan ve değeri −0.002'den büyük oyuncular değer önceliğiyle pozisyon kuralına göre slotlara
  (`slot_assignment`); değerler yeni düzene göre yeniden hesaplanır, düzen değişmeyene kadar (en çok 6 tur). Değeri
  −0.002'nin altındaki oyuncu boş slot olsa da oturur (**oran koruma**: sayım kategorileri kesinleşmişken düşük
  isabetli hacimli şutçu FG%/FT%'yi riske atar). Rakibin düzeni statik önceliktedir.
- **Bugün**: önerilen düzen Yahoo'daki düzenle (senkronizasyon günündeki `rosters.json` slotları) karşılaştırılır:
  "Başlat" (yedekte ama oynamalı) ve "Oturt" (aktif ama oturmalı) listesi. Maçı başlamış oyuncu değiştirilemez.
- 7 Kasım (WNBA 26-27, Galatasaray Cafe Crown): sayım kategorileri belliyken 8 oyuncu-maçı oran koruma ile oturdu,
  beklenen kategori 2.71 → 2.84; METU IE'de Kekstra'nın düzeni zaten önerilenle aynıydı.

### 13.22 Add/Drop: kalan sezon ve bu hafta (`fdo.inseason.adddrop`, Add/Drop sekmesi)

İki ayrı menü:

- **Kalan sezon**: §13.13'teki boştaki oyuncular tablosu (ROS ECW, pozisyon kuralı, IL dönüş bedeli) + alınabilirlik:
  FA hemen; waiver'daki oyuncu Yahoo'nun gösterdiği günden itibaren (`W (Nov 9)`, senkronizasyon; tarihsiz kayıtta bugün
  + lig ayarındaki waiver süresi). Bu hafta kalan alım hakkı, FAB bütçesi ve waiver kuralı başlıkta.
- **Bu hafta**: kısa listedeki (30) her boştaki oyuncu için en iyi tek hamle (bırakılacak oyuncu ve gün) ve etkisi:
  beklenen kategori, P(5+), kategori olasılıkları ve hamle kalıcı olsaydı kalan sezon etkisi; altında kalan alım hakkıyla
  açgözlü gün gün plan (§13.13 streaming). Waiver'daki oyuncu serbest kaldığı günden önce planlanmaz. İki hedef:
  - *Haftayı kazan*: stratejine göre beklenen kategori galibiyeti.
  - *Kritik kategori*: seçilen kategorilere oyna (ağırlık 1, diğerleri 0.05). Otomatik seçim: her kategori için tek bir
    boştaki oyuncuyu kalan günlere kısıtsız eklemenin en iyi 5 adayının ortalama kazanma olasılığı artışı
    ("kıpırdatılabilir"); en büyük iki kategori (≥ 0.02). Kesinleşmiş kategoride bu artış ~0'dır.
- 7 Kasım: Kekstra için kritik kategori BLK (%44, +9 puan kıpırdatılabilir); 4 alımlık plan beklenen kategoriyi
  1.50 → 1.87'ye çıkarıyor.

### 13.23 Performans: haftalık kategori sıralaması (`fdo.inseason.history`, Performans sekmesi)

Biten haftaların takım toplamları (`matchups.json`, §13.20) ve süren haftanın şu ana kadarki toplamı ile takımın her
kategoride ligdeki sırası (1 = en iyi, TO'da en az; eşitlikte en iyi sıra paylaşılır), haftanın kategori skoru ve sezon
toplamının sırası. Isı tablosu iki yönlü (üst/alt üçte bir), değerler hücrede; üzerine gelince lig ortancası ve haftanın
en iyisi.

### 13.24 Sakatlıkta rol değişimi (`fdo.inseason.roles`)

Yahoo projeksiyonları takım arkadaşı sakatlığına neredeyse tepki vermediği için (§13.20) bu sezonun NBA maç kayıtlarından
(`gamelogs_nba_2026-27.csv`, her senkronizasyonda yenilenir, git dışı) ölçülür:

- **Önemli oyuncu**: bu sezon ≥ 3 maç, maç başı ≥ 20 dk. **Yok kümesi**: takımın şu an oynamayan önemli oyuncuları
  (Yahoo O/INJ/NA ya da CBS dönüş tarihi gelecekte / sezon boyu). Bütün sezonu kaçıran oyuncu sayılmaz.
- Takımın maçları: yok kümesinin hiçbirinin oynamadığı (W) ve hepsinin oynadığı (H); W boşsa en çok dakika alan tek
  oyuncu. Takım arkadaşının farkı `ort(W) − ort(H)` (W ≥ 1, H ≥ 2 maç), küçültme `n_W / (n_W + 4)`, kalan sezon maç
  başına eklenir. Geçerlilik: en erken bilinen dönüşe kadar (bilinmiyorsa 14 gün).
- Haftalık model (dolayısıyla Bu Hafta, Sit/Start, Add/Drop ve sezon simülasyonunun içinde bulunulan/sonraki haftaları)
  bu günlerde rollü maç başı vektörü kullanır. Ad eşleştirme: ad + takım, ad, baş harf + soyad + takım
  ("N. Alexander-Walker"); 7 Kasım'da satırların %100'ü eşleşti, 106 oyuncuda rol değişimi (ör. OKC'de Holmgren ve
  Jalen Williams yokken Bennett Stirtz +11 dk, +5.9 sayı).

### 13.25 Haber analizi (`fdo.inseason.news`, Haberler sekmesi, `scripts/news_refresh.py`)

- **Kaynaklar**: CBS fantezi oyuncu haberleri (RotoWire notları; genel akışın ilk sayfası, son 30 not ≈ 4–8 saat — 8
  Kasım'dan beri ikinci sayfa, sakatlık ve pozisyon akışları otomatik istemciye 406 dönüyor) ve ESPN NBA haber akışı (50
  başlık + özet, ≈ 1 gün).
  Haber kimliği bağlantısıdır; bir kez saklanır, bir kez analiz edilir, 21 günden eskisi silinir (`news.json`, git dışı).
  Boşluk kalmaması için 2 saatte bir yenilenmeli (Görev Zamanlayıcı: `scripts/news_refresh.py`); yenileme ücretsizdir,
  yalnız yeni ve ilgili haberler modele gider.
- **Süzme** (ücretsiz, model öncesi): CBS haberi Yahoo oyuncu havuzuna eşleşmeli ve başlığında rol/sakatlık/takas
  sinyali olmalı (maç özetleri listede kalır, analiz edilmez); ESPN haberinde havuzdaki bir oyuncunun tam adı geçmeli.
- **Model**: `claude-opus-5-5`, efor `low`, JSON şemalı yapılandırılmış çıktı, 30 haberlik partiler, sabit sistem talimatı
  önbellekli, sunucu tarafı yedek model (`fallbacks: "default"`). `FDO_NEWS_MODEL` ile değişir (ör. `claude-sonnet-5-5`
  yaklaşık yarı fiyat). Anahtar `ANTHROPIC_API_KEY` ya da depo kökündeki `.env` (git dışı). Yanıtı reddedilen ya da
  kesilen parti sonraki yenilemede yeniden denenir.
- **Çıktı**: olay türü (sakatlık, dönüş, rol ↑/↓, takas, takas söylentisi, dinlenme…), durum, tahmini dönüş, kaçırılacak
  maç, süre kazanan/kaybeden takım arkadaşları, fantezi etkisi (−2…+2) ve Türkçe tek cümle özet. Uygulama oyuncuları lige
  göre etiketler: senin, bu haftaki rakibinin, FA / waiver (fırsat).
- **Maliyet**: her çağrının token kullanımı kaydedilir. İlk yenileme (8 Kasım): 70 haber, 42'si analiz edildi, ~$0.15
  (haber başına ~$0.0036); günde 40–80 ilgili haberle ayda ~$6–10.

### 13.26 Sadece bırak: IL dönüşünde kimi bırakmalı (`fdo.inseason.drops`, Add/Drop → Sadece bırak, 9 Kasım 2026)

Sakatlıktan dönen oyuncu aktif kadroya alınırken yer açmak için. IL'deki oyunculardan dönenler işaretlenir (varsayılan:
dönüş tarihi 2 gün içinde ya da tarih yok ve durum artık "oynamaz" değil; elle değiştirilebilir). Adaylar aktif
oyuncular ve dönenlerin kendisidir; bırakılması gereken sayı `aktif + dönen − kadro kapasitesi`. Her aday için:

- **Kalan sezon**: aday çıkınca kadronun tipik hafta vektörü (kalan IL'liler dönüş bedeliyle) ligdeki diğer takımlara
  karşı; stratejiyle `9·Σ w_c·ΔP_c`. Ekranda önerilen seçeneğe göre haftalık ek kayıp ve en çok kaybedilen kategoriler.
- **Bu hafta**: kalan günlerde eşleşmeye etkisi (beklenen kategori, P(5+)); dönen, dönüş gününden itibaren oynar.
- Maç sayısı (bu hafta / gelecek hafta), ligdeki değer sırası (yüksekse bırakılınca başkası alabilir), boşta ondan iyi
  oyuncu varsa adı (§13.13 `drop_ranking`), bırakınca doldurulamayan aktif pozisyon uyarısı.

Öneri: pozisyonu bozmayan adaylar arasında kalan sezon kaybı en düşük oyuncu(lar); değişim kalıcı olduğu için varsayılan
sıra kalan sezondur, "Bu hafta" sıralaması yalnızca eşleşmeye bakar. 9 Kasım: Kekstra'da Jaylon Tyson dönüyor
(14/13); öneri Robert Williams III, Collin Sexton neredeyse eşit (haftada 0.006 kategori).

### 13.27 Seçimden takas tamamlama ve dengeleme (`fdo.trade.suggest.complete_trade`, Takas Analizi, 9 Kasım 2026)

Takas Analizi'nde oyuncu seçtikten sonra tek düğme; seçili oyuncular sabit kalır, öneri onların etrafında kurulur:

- **Yalnız senin oyuncuların seçili** → "Karşılığında ne isteyebilirim?": karşı takımdan 1–3 oyunculuk paketler.
- **Yalnız onun oyuncuları seçili** → "Karşılığında ne verebilirim?": senin kadrondan 1–3 oyunculuk paketler.
- **İki taraf da seçili** → "Takası dengele / tamamla": iki tarafa toplam en çok 3 oyuncu eklenir, paket en çok 3'e 3
  (ör. 2'ye 1 → 2'ye 2, 3'e 2, 3'e 3). Üstte şu anki seçimin değerlendirmesi (neden dengesiz olduğu) gösterilir.

Tek oyunculuk eklemelerde bütün kadro, daha büyüklerde taraf başına 10 aday (strateji uyumu + piyasa değeri) taranır;
en çok 4000 paket (gerçek veride 0,2–2,5 sn). Her paket takas analiziyle aynı şekilde puanlanır (seçilen stratejiler,
otomatik kadro dengeleme). Eşikler kabul edilebilirlik içindir: değer dengesi (küçük/büyük
paket; modelin kalan sezon değerinde ya da piyasanın algıladığı değerde, hangisi yüksekse, §13.30) en az %55 ve rakibin gözünde (algılanan değer: aldığı/verdiği) en az 0.80. Sıra: **ikisi de kazanır** (iki
tarafın puanı artar; `suggest_trades`'teki karşılıklı fayda puanı), **sen kazanırsın** (rakip modelde kaybeder ama
isim değeri dengeli görünür), **sen kaybedersin**. Aynı ya da daha iyi türde daha küçük paketi listede olan ve aynı
sonucu veren (eklenen oyuncu değer katmayan, ör. otomatik bırakılan) paketler çıkarılır. "Uygula" paketi seçime
taşır ve tam analizi açar; liste açık kalır. API: `POST /api/leagues/{lid}/trade/complete`.

### 13.28 Değerlendirme temelleri ve IL dönüş takvimi (`fdo.inseason.scenarios`, Takas Analizi, 9 Kasım 2026)

Takas hesapları "kalan sezon maç başı oran × kalan maç" üzerinden yapılır. Önceden oranlar yalnız Yahoo'nun kalan sezon
projeksiyonuydu; Yahoo projeksiyonu yavaş güncellenir ve rol değişimini (çaylağın beklenenden büyük rolü, yedeğe düşen
veteran) geç yansıtır. Artık dört temel var; kalan maç sayısı (dayanıklılık dahil) hep Yahoo'nunkidir, bütün lig
(rakipler, boştakiler, yerine koyma düzeyi, IL dönüşünde kimin bırakılacağı) aynı temelle değerlenir:

- **Yahoo projeksiyonu** (varsayılan).
- **Bu sezonki oranlar**: gerçekleşen maç başı ortalamalar (en az 3 maç; yoksa Yahoo).
- **Son 10 maç**: NBA maç kayıtlarından (en az 3 maç; yoksa bu sezon, o da yoksa Yahoo).
- **Karma**: Yahoo ile bu sezon arasında oynanan maça göre ağırlık `n / (n + 10)`.

Takas Analizi'nde "Değerlendirme" seçimi bütün analizi (kategori etkisi, sezon simülasyonu, fikstür) o temelle yapar;
"Değerlendirme temelleri" tablosu aynı takası dört temelde yan yana gösterir (temeller aynı yönü gösteriyorsa karar
sağlam; ayrışıyorsa hangi orana inandığına bağlı) ve oyuncuların her temeldeki maç başı oranlarını açar.

**IL dönüş takvimi** (`TradeEngine.crunch_plan`, değerlendirmenin kullandığı kuralla aynı): takastan sonra IL'den
dönüş sırasıyla kim döner, kim bırakılır. Dönen oyuncu en zayıf aktif oyuncudan değersizse kimseyi yerinden etmez
("kadroya girmez"); takasla gelen oyuncu bir dönüşte bırakılıyorsa işaretlenir (katkısı yalnız o tarihe kadar).
Dönüş tarihi CBS sakatlık raporundan.

9 Kasım, tsg fentezi Acuff → Garland + McCollum: Yahoo +0,36 kategori/hafta, bu sezonki oranlar −0,26, son 10 maç −0,25,
karma +0,03. Gelen iki oyuncu da hiçbir temelde Aralık dönüşlerinde bırakılmıyor.

### 13.29 Detaylı analiz (Claude; `fdo.inseason.trade_report`, Takas Analizi, 9 Kasım 2026)

Takas Analizi'nde "Detaylı analiz yaz": uygulama bir veri paketi kurar ve Claude (`claude-opus-5-5`, efor `medium`,
JSON şema) Türkçe yapılandırılmış bir değerlendirme yazar: karar (kabul et / karşı teklif ver / reddet / bekle) ve güven,
bölümler, karşı teklifler ("Takas ekranında aç" ile seçime taşınır) ve izlenecekler. Paket (~8 bin token):

- Oyuncu başına bu sezon, Yahoo kalan sezon ve sezon öncesi maç başı değerleri, değer ve algılanan sıra, dayanıklılık,
  son 5 maç ortalaması ve son 10 maç tek tek (dakika, sayı, isabet), playoff haftası maçları.
- NBA takımındaki rol: son 5 maçta rotasyon (dakika, şut, sayı) ve sakat takım arkadaşları (dönüş tarihi, bu sezon
  oynadığı maç: ör. Garland'ın bütün maçları Ingram ve Beal yokken).
- Dört temelde model sonuçları ve IL dönüş takvimi (§13.28), iki takımın kadrosu ve kategori sıraları, son 14 günün
  haberleri, karşı teklif adayları (§13.27 tamamlama aracıyla, eşikler teklifin kendi dengesine göre; Yahoo ve bu sezonki
  oranlarla).

Model yalnız paketteki verileri kullanır; genel basketbol bilgisi (yaş, kariyer normları) veriyle çelişmediği sürece ve
belirtilerek. Üretim arka planda çalışır (~1 dk; Cloudflare 100 sn sınırı), arayüz durumu sorar
(`POST /api/leagues/{lid}/trade/report`, `GET /api/trade/report/{key}`). Raporlar `data/real/trade_reports.json`'da
(git dışı; sunucuya gönderilmez) veri imzası + takas + stratejiler anahtarıyla saklanır: aynı veriyle aynı takas yeniden
ücret ödemeden açılır. Maliyet rapor başı ~0,13 $ (9 Kasım denemesi: 13 bin girdi, 3,7 bin çıktı token, 70 sn).
Anahtar `.env`'deki `ANTHROPIC_API_KEY` (§13.25). Salt okunur sunucuda yalnız `FDO_REPORT_CODE` ayarlıysa çalışır ve
arayüz bir kez erişim kodu ister (adres herkese açık; ücretli çağrı korunur).

### 13.30 Algılanan değer: draft piyasası (`fdo.trade.perception`, 9 Kasım 2026)

Rakibin gözündeki değerin "sezon öncesi isim değeri" bileşeni önceden Yahoo'nun sezon öncesi projeksiyonunun 9
kategori z sırasıydı; yani rakibin de modelle aynı hesabı yaptığı varsayılıyordu. Menajerler ise oyuncuyu draftta
ödedikleri fiyatla tanır. Örnek (METU IE, 9 Kasım): Banchero 9 kategoride maç başı #107 (top kaybı, serbest atış,
top çalma), sezon öncesi projeksiyonuyla #136; ama Yahoo ADP 35,7, ligin açık artırmasında 22 $ (Clingan 28 $, Jaren
Jackson Jr. 21 $). Eski algı Banchero'yu #142 görüyor ve "Banchero + Jackson → Clingan"ı rakibin gözünde 0,87 (rakip
için az) sanıyordu; menajerlerin gözünde 1,53, yani açık bir fazla ödeme.

Artık isim değeri sırası:

- Ligin kendi draftı (`draft_results.csv`): açık artırmada ödenen fiyat (yüksek = değerli), yılan draftta seçim
  sırası.
- Yahoo ADP'si (`adp_yahoo_*.csv`).
- İkisi de varsa sıraların ortalaması; draft edilmeyenler draft edilenlerin arkasında, sezon öncesi projeksiyon
  sırasıyla. Draft verisi yoksa eskisi gibi projeksiyon sırası.

"Bu sezonun rakamları" (en az 3 maç) ve varsayılan ortalama aynı kalır. Değişiklik algılanan değeri kullanan her şeye
yansır: rakibin gözünde denge, yanlış fiyatlama (sat-yüksek / al-düşük), öneriler, tamamlama, detaylı analiz.

**Tamamlamada değer dengesi** (§13.27): önceden yalnız modelin kalan sezon değeriyle (küçük / büyük paket) ölçülüyordu;
modelin bir tarafı çok üstün bulduğu ama menajerlerin dengeli gördüğü takaslar (isim değeriyle sat-yüksek) eşikte
eleniyordu. Artık denge modelin ya da piyasanın (algılanan değer) gözünde, hangisi yüksekse; rakibin gözünde eşiği
(0,80) aynı. Aynı örnekte tamamlama önceden Banchero karşılığında yalnız Gobert ve Jalen Smith'i (ikisi de senin
kaybın) buluyordu; şimdi Banchero → Clingan (sen +0,33 / +0,16 / +0,28 kategori/hafta, Yahoo / bu sezon / karma;
rakibin gözünde 0,97), → Mobley (+0,25 / +0,20 / +0,24; 0,94).

### 13.31 Veri arşivi, kimlik eşleştirme, güncellik ve karar günlüğü (`fdo.ingest`, `fdo.evaluation`, 10 Kasım 2026)

Yahoo API erişimi olmadan, veri elle (kendi oturumunla "Yahoo'dan güncelle") çekilirken aynı analizin tekrar
üretilebilmesi ve kararın hangi veriye dayandığının görülmesi için:

- **Değiştirilemez arşiv** (`fdo.ingest.archive`, `scripts/archive_data.py`): her senkronizasyonun ve haber yenilemenin
  sonunda analiz girdileri (`rosters.json`, oyuncu sayfaları, lig ayarları, sakatlık raporu, NBA maç kayıtları, takvim,
  projeksiyon, ADP, draft, fikstür; ayrıca haberler ve işlem geçmişi) içerik özetiyle (sha256) saklanır:
  `snapshots/objects/` (gzip, aynı içerik bir kez) ve `snapshots/batches/<parti>.json` (dosya → özet, zamanlar, eksik
  dosyalar, önceki parti). Önceden aynı gün ikinci senkronizasyon o günün kopyasının üzerine yazıyordu; artık her çekim ayrı
  parti, değişmeyen girdiler yeni parti açmaz. Önce nesneler, en son manifest yazılır: yarıda kalan arşivleme parti
  bırakmaz. `--legacy` eski `snapshots/<gün>/` klasörlerini (eksik) parti olarak içe alır; `--verify` özetleri doğrular,
  `--restore` bir partiyi boş dizine çıkarır. Arşiv git dışında kalır, sunucuya gönderilmez. İlk tam parti 33 dosya,
  sıkıştırılmış 2,1 MB.
- **Zaman alanları** (`fdo.ingest.timestamps`): her dosya için kaynağın anlattığı an (`source_as_of`: kadro tarihi, son
  maç günü, projeksiyon tarihi), çekim anı (`captured_at`, dosyanın kendi kaydından) ve diskte değiştiği an ayrı tutulur.
  Dosyada zaman kaydı yoksa çekim zamanı boş kalır; disk zamanı onun yerine geçmez.
- **Oyuncu kimliği** (`fdo.inseason.identity`): CBS sakatlık raporu, NBA maç kayıtları ve haberler Yahoo kimliğine tek
  kuralla bağlanır: ad + takım, yalnız ad (havuzda tek oyuncu; takım tutmuyorsa raporlanır), baş harf + soyad + takım. Bir
  kural yalnız **tek** aday bırakırsa eşleşir. Önceden sakatlık raporunda aynı adlı iki oyuncu varken ve takım tutmazken
  satır ilk adaya bağlanıyordu; şimdi belirsiz kalır. Eşleşmeyen ve belirsiz satırlar veri notlarında adıyla listelenir.
  Elle düzeltme: `data/real/id_overrides.csv` (`source, name, nba_team, player_id, note`; git dışı). 9 Kasım verisinde
  davranış değişmedi: CBS 96/96, NBA kayıtları 3.294/3.294 satır eşleşiyor.
- **Kalite kontrolleri** (`fdo.trade.data.quality_issues`): eksik alan, negatif sayım, isabet > deneme yanında artık
  3PM > FGM, sayının şut bileşenleriyle (2·FGM + 3PM + FTM) uyuşmaması (kaynağın bir ondalıklı yuvarlaması için pay: en az
  1 sayı ya da %3) ve maç oynamadan istatistik. Ham veri değiştirilmez, yalnız raporlanır.
- **Güncellik** (`fdo.ingest.freshness`, `GET /api/freshness`): tek "son güncelleme" yerine bileşen bazında yaş (kadro,
  oyuncu istatistikleri, bu hafta, sakatlık, haber, NBA kayıtları, lig ayarları...). Karar türüne göre durum: **normal**,
  **koşullu** (sonuç gösterilir, hangi verinin eski olduğu söylenir) ya da **bekletilir** (önce şu bileşen yenilenmeli).
  Üst çubuktaki "Veri: …" tıklanınca açılır; Add/Drop sayfası durum normal değilse uyarır ("oyuncu hâlâ boştaysa
  geçerli"). Eşikler (ör. add/drop için kadro 12 saate kadar normal, 36 saate kadar koşullu) **başlangıç varsayımıdır**,
  ölçülerek doğrulanmadı; `config/freshness.yaml` ile değiştirilir. Oyuncu sayfalarının kapsamı da gösterilir: boştaki
  havuzu Yahoo sıralamasında ilk ~750 oyuncudur, "en iyi boştaki" yüklenen havuzda en iyidir.
- **Karar günlüğü** (`fdo.evaluation.decisions`): takas önerileri ve tamamlama (`recommendation`) ile Takas Analizi'nde
  incelenen takaslar (`scenario`) ayrı türlerde `data/real/decisions/<ay>.jsonl` dosyasına yalnız eklenerek yazılır: istek,
  sonucun özeti, veri imzası (içerik özeti; dosya yolu ve zamanından bağımsız), arşivdeki son parti, kod sürümü.
  `FDO_DECISION_LOG=0` kapatır. Senaryo gerçek kadroyu değiştirmez. Takas Analizi'ndeki "Bu takası yaptım" üçüncü türü
  (`user_reported`) yazar: veri ve kadrolar değişmez; durum her okumada güncel kadrolarla karşılaştırılır (kadrolarda /
  kısmen / bekliyor), yani bir sonraki Yahoo güncellemesinde kendiliğinden uzlaşır. Sunucunun günlüğü veri gönderimiyle
  ezilmez.
- **Veri sağlayıcıları** (`fdo.ingest.provider`): analiz verinin nereden geldiğini bilmez; elle alınan güncel dosyalar
  (`ManualSnapshotProvider`), arşiv partisi (`ArchivedSnapshotProvider`) ve kapalı `YahooApiProvider` aynı dosya
  sözleşmesini verir. Yahoo API onayı hiçbir özelliğin ön koşulu değil; onay gelirse yalnız okuma varsayılır.
- **Referans vakalar** (`fdo.evaluation.cases`, `scripts/run_cases.py`): hatalı bulunan öneriler `data/real/cases.json`
  (git dışı) içinde sabit API istekleri ve "bu paket listelenmemeli" türü beklentilerle tutulur; sonuçlar
  `data/real/evaluation/` altına kod sürümü ve veri imzasıyla yazılır. `--batch <parti>` aynı vakaları arşivdeki girdilerle
  çalıştırır (replay), `--compare` iki kaydın farkını verir. 9 Kasım arşiv partisiyle replay, güncel dosyalarla birebir
  aynı önerileri üretti.
- **Bilinen sorunlar** (`tests/unit/test_known_issues.py`): doğrulanmış hatalar sentetik vakalar olarak; düzeltilmemişler
  `xfail(strict=True)`. Rakip için gerekçesiz takas önerisi (Banchero → Giannis) §13.32 ile giderildi.

**Kimlik bilgileri ve kapalı özellikler**: Yahoo için API anahtarı yok; senkronizasyon `scripts/yahoo_login.py` ile bir
kez giriş yapılmış Chrome profilini kullanır (yoksa güncelleme çalışmaz, mevcut dosyalarla analiz sürer). `ANTHROPIC_API_KEY`
(`.env`) yalnız haber analizi ve detaylı analiz içindir; yoksa bu ikisi kapalıdır, takas, add/drop ve sezon hesapları
LLM'siz çalışır.

### 13.32 Rakip için gerekçe ve piyasa bandı (`fdo.trade.suggest.counterpart`, 10 Kasım 2026)

Önceden tamamlama, rakibin hem modelde hem kendi gözünde kaybettiği takası "sen kazanırsın" türünde normal öneri olarak
listeliyordu (METU IE, Banchero → Giannis: rakip −0,24, rakibin gözünde 0,82). Rakibin gözündeki eşik (≥ 0,80) bir
kabul ölçüsü değil, yalnız "çok dengesiz değil" filtresiydi. Şimdi her öneri rakip için iki gerekçeye bakar:

- **Modelde kazanç**: rakip kendi stratejisiyle kalan sezonda kazanıyor mu (tür sınıflandırmasıyla aynı ölçü).
- **Kendi gözünde**: algılanan değerle (draft fiyatı + bu sezon) aldığı / verdiği ≥ 0,95 ("aşağı yukarı eşit";
  algının gürültüsü için pay).

İkisi de varsa kabul gerekçesi **yüksek**, biri varsa **orta**, hiçbiri yoksa **düşük**: düşükler listelenmez, sayısı
gösterilir (`require_reason=false` ile görülebilir). Bu bir kabul olasılığı değildir; menajer davranışı modellenmedi,
yüzde gösterilmez. Rozet ve gerekçeler tamamlama ve öneri tablolarında "Kabul gerekçesi" sütununda.

**Piyasa bandı**: rakibin gözündeki oran 1,25'i (= 1 / 0,80) aşarsa piyasa gözünde sen fazla ödüyorsun, karşılığında daha
fazlası istenebilir; tamamlamada ve karşılıklı faydada bu paketler de listelenmez (`max_view`, 0 = kapalı). Sat-yüksek /
al-düşükte piyasa farkı zaten aranan şey olduğu için uygulanmaz. Örnek: Banchero + Jackson → Clingan rakibin gözünde 1,53,
yani ilk şikâyetteki fazla ödeme; artık listede yok, yerine Clingan + Ausar Thompson (0,97).

Etki (9 Kasım verisi, referans vakalar): Banchero karşılığında The Last Führer'den önerilenler Clingan (sen +0,33, rakip
kendi gözünde 0,97), Ty Jerome ve Zion; Giannis, Mobley (0,94) ve fazla ödeme olanlar (Castle 1,49, LaVine 1,57)
elendi. Varsayılan karşılıklı fayda önerileri korunuyor. 0,95 ve 1,25 başlangıç varsayımıdır, doğrulanmadı; gerçek teklif
ve cevap kayıtları biriktikçe ayarlanmalı.

### 13.8 V3 adayları

Beam search ve H-score ağırlık optimizasyonu; profil karışımı uyumu; oyuncular arası maç sayısı
kovaryansı; gerçek H2H takvimi ve playoff eşleşmeleri; geçmiş sezon snapshot'larıyla gerçek backtest.

---

## 14. Kurulum ve çalıştırma

Aşağıdaki komutlar V1 ile doğrulanmıştır.

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# sentetik veri
python scripts/make_synthetic.py --n 400 --seed 7 --out data/synthetic/

# testler
pytest -q

# gerçekçilik raporu
python scripts/run_mock_batch.py --n 500 --seed 1 --data data/synthetic/

# performans ölçümü (§11); --batch ile 500 mock dahil
python scripts/profile_advisor.py

# arayüz
streamlit run src/fdo/ui/app.py
```

Raporlar `reports/` altına yazılır (git'e girmez). GitHub Actions (`.github/workflows/ci.yml`) her push'ta testleri Python 3.11 ve 3.13'te çalıştırır; gerçekçilik raporu ve performans ölçümünü test eşiği olmadan job özetine ve artifact olarak raporlar (§9.4). Sentetik veri manifest'leri `data/synthetic/manifests/` altındadır; loader manifest'i önce CSV'nin yanındaki `manifests/`, sonra bir üst dizindeki `manifests/` (ör. `data/manifests/`) altında arar.

Gerçek veri: CSV'ler `data/real/` altına, manifest'ler `data/manifests/` altına konur ve sayfa 1'den yüklenir. Repoda Yahoo dışa aktarımından (12 Ekim 2026) üretilmiş veri seti ve ham JSON'ları bulunur; yeniden üretmek için:

```bash
python scripts/import_yahoo_json.py --players data/real/raw/yahoo_players_2026-10-12.json \
    --adp data/real/raw/yahoo_adp_2026-10-12.json --license-status personal_use_confirmed \
    --license-notes "Kullanıcı kararı (2026-10-12): Yahoo sayfaları public; kişisel kullanım."

# utilization tahmini (§6.6.1); --schedule ile gerçek takvim
python scripts/estimate_utilization.py --data data/real/ --mocks 30

# V2 (§13)
python scripts/fetch_nba_schedule.py --download --season 2026-27 --license-status personal_use_confirmed
python scripts/fetch_gamelogs_nba_api.py --season 2025-26 --license-status personal_use_confirmed   # pip install -e ".[nba]"
python scripts/calibrate_variance.py --gamelogs data/real/gamelogs_nba_2024-25.csv data/real/gamelogs_nba_2025-26.csv
python scripts/mark_rookies.py --gamelogs data/real/gamelogs_nba_2024-25.csv data/real/gamelogs_nba_2025-26.csv
python scripts/calibrate_bots.py --logs "data/real/draft_logs/*.csv" --data data/real/
python scripts/backtest.py --data data/real/ --n 30 --strategies adp,z,g,ecw
```

---

### 14.1 Trade Lab web uygulaması (React + FastAPI)

Sezon içi araçların yeni arayüzü (31 Ekim 2026). Draft ve auction sayfaları Streamlit'te kalır.
Öneri yönleri §13.17, çok takımlı takas §13.18.

```powershell
.venv\Scripts\python.exe -m pip install -e ".[dev,web,yahoo,nba,news]"   # bir kere
.venv\Scripts\python.exe scripts\yahoo_login.py                  # bir kere: Yahoo girişi (§13.20)
.venv\Scripts\python.exe run_app.py                              # http://127.0.0.1:8000
```

Veri üst çubuktaki "Yahoo'dan güncelle" ile (ya da `scripts\yahoo_sync.py`) tazelenir: Yahoo, CBS sakatlık raporu,
NBA maç kayıtları ve haberler. Haber analizi için `pip install -e ".[news]"` ve `.env` içinde `ANTHROPIC_API_KEY=...`.
Önerilen zamanlama (Görev Zamanlayıcı): her sabah ~10:30 `scripts\yahoo_sync.py` (Türkiye 10:00–20:00 arası hafta skoru
tam "dünküne kadar"dır), gün içinde 2 saatte bir `scripts\news_refresh.py`.

`run_app.py` arayüz derlenmemişse ya da `frontend/src` değiştiyse önce `npm install` / `npm run build` çalıştırır
(Node.js gerekir), sonra FastAPI'yi başlatıp tarayıcıyı açar. Sekmeler: Takas Analizi, Takas Önerileri, Çok Takımlı
Takas, Bu Hafta, Sit/Start (§13.21), Add/Drop (kalan sezon + bu hafta, §13.22; sadece bırak, §13.26), takasta seçimden tamamlama/dengeleme (§13.27), Haberler (§13.24–13.25), Performans
(§13.23), Sezon Simülasyonu, Lig Sıralamaları. Lig, takım, sakatlık dönüş tarihleri, renk skalası
(yeşil↔kırmızı ya da renk körlüğüne uygun mavi↔kırmızı) ve tema üst çubuktadır.

**Telefondan** (8 Kasım 2026): ekran 760 px'ten darsa üstte sayfa adı ile lig/takım (dokununca ayarlar paneli) ve
Yahoo güncelleme düğmesi, altta sekme çubuğu (Bu Hafta, Sit/Start, Add/Drop, Haberler, Daha). Geniş tablolar kart ve
listeye döner: kategori olasılıkları satır/karo, tek hamleler ve alım planı kart (plan üstte), Sit/Start'ta "bugün
yapılacaklar" en üstte; kalan tablolar yatay kayar, ad sütunu sabit. Uygulama ana ekrana eklenebilir (manifest, ikonlar,
yalnız arayüz kabuğunu önbelleğe alan service worker; veri hiç önbelleğe alınmaz). Arka plandan dönünce arada bir
senkronizasyon olduysa sayfa kendiliğinden yenilenir.

Bilgisayar dışından erişim için [Tailscale](https://tailscale.com) (kişisel kullanım ücretsiz, aynı Wi-Fi gerekmez,
uygulama internete açılmaz):

```powershell
# bilgisayara ve telefona Tailscale kur, ikisinde aynı hesapla giriş yap; yönetim panelinde DNS → HTTPS Certificates aç
.venv\Scripts\python.exe run_app.py --no-browser          # uygulama 127.0.0.1:8000'de kalır
tailscale serve --bg 8000                                 # bir kere: https://<bilgisayar>.<tailnet>.ts.net → 8000
```

Telefonda `https://<bilgisayar>.<tailnet>.ts.net` adresini aç → Safari: Paylaş → Ana Ekrana Ekle; Chrome: ⋮ → Ana ekrana
ekle / Uygulamayı yükle. HTTPS adresi gerekir (service worker ve tam ekran uygulama yalnız güvenli bağlamda çalışır).

- **Takas Analizi**: Yahoo tarzı iki kadro tablosu (seçilebilir kaynak: kalan sezon / bu sezon / sezon öncesi;
  maç başı istatistikler z seviyesine göre renkli, sakatlık ve dönüş tarihi rozetleri). Satıra tıklamak oyuncuyu
  pakete ekler; analiz seçim değiştikçe kendiliğinden çalışır: iki takımın beklenen kategori, P(5+), strateji
  puanı, ortak ölçekli kategori etki grafiği, kadro işlemleri (IL / bırak / ekle), değer ve algılanan denge,
  sezon etkisi (playoff ve şampiyonluk), üç kaynağa göre lig sıra değişimi.
  Kaynak "Bu sezon" ya da "Sezon öncesi" seçiliyken Değer'in yanında **algı sütunu**: o kaynağa bakan menajerin
  gözündeki sıra ve bu sıranın kalan sezon piyasasındaki karşılığı (Değer ile aynı ölçek, `perceived_prices`; bu sezon
  maç başı, 3 maçtan azı * ile sezon öncesine düşer). ▲/▼ sıra farkı; fark ≥ 1 değer kalın (turuncu: olduğundan iyi
  görünüyor → sat, mor: olduğundan kötü → al). Başlığa tıklamak farka göre sıralar. Değer ve takas hesapları her zaman
  kalan sezondur: takasla yalnız kalan maçlar el değiştirir.
  Kalan sezon kaynağında GP sonundaki `*`: Yahoo'nun verdiği maç oynama oranıyla kısıldı (§13.19; üzerine gelince ayrıntı).
- **Takas ekranı ekleri**: iki taraf için elle "bırak" ve aranabilir boştaki oyuncu "al" (otomatik dengeleme bunlardan
  sonra uygulanır); strateji seçici her sekmede: dengeli, hazır punt'lar, **otomatik punt** (takımın kategori profilinden
  en zayıf 1 ya da 2 kategori, `StrategyIn.auto_punt`), **zayıfı canlandır** (en zayıf 1–2 kategori ×3,
  `StrategyIn.auto_revive`) ve özel ağırlıklar (0–3); **kayıtlı senaryolar** (tarayıcıda,
  JSON dışa/içe aktarma): ΔECW, strateji Δ, ΔP(5+), değer ve algılanan denge, playoff/şampiyonluk etkisi yan yana;
  "Aç" senaryoyu bütün seçimleriyle geri yükler.
- **Fikstür etkisi** (iki takımlı ve çok takımlı analizde kendiliğinden): fikstürdeki her kalan normal sezon haftası için
  haftayı kazanma olasılığı takassız → takaslı (Sezon Simülasyonu'ndaki fikstür tablosuyla aynı nokta tahmini:
  o haftanın NBA maçları, sakatlık dönüşleri, IL dönüşü bedeli), beklenen galibiyet toplamı ve takımlar arası geçiş;
  rakip de takastaysa "takasta" işareti. `POST /trade/fixtures`, `/trade/multi/fixtures`.
- **Takas Önerileri**: karşılıklı fayda, sat yüksek, al düşük ayrı türler; her biri birden çok yönde aranır (§13.17);
  yanlış fiyatlama tabloları; öneriler için playoff etkisi; "Takas ekranında aç" öneriyi seçili olarak Takas
  Analizi'ne taşır.
- **Çok Takımlı Takas**: 3–4 takımlı elle analiz ve döngü önerileri (§13.18).
- **Bu Hafta / Boştaki Oyuncular / Sezon Simülasyonu / Lig Sıralamaları**: §13.13–§13.16'daki modellerin arayüzü.

Yapı: `src/fdo/api/` (FastAPI: `state.py` önbellekli veri/motorlar, `serialize.py` JSON dönüşümü, `app.py` kadro,
takas analizi ve sezon etkisi, `inseason.py` öneriler, yanlış fiyatlama, haftalık + streaming, boştakiler, sezon,
sıralamalar, `multi.py` çok takımlı takas), `frontend/` (Vite + React + TypeScript, ek UI kütüphanesi yok; `src/pages/*`, `src/components/*`,
`styles.css` tasarım belirteçleri, açık/koyu tema). Geliştirme: `uvicorn` ile API'yi (8000) ve `npm run dev` ile
arayüzü (5173, `/api` 8000'e yönlendirilir) ayrı çalıştır. `frontend/node_modules` ve `frontend/dist` git'e girmez.
CI arayüzü tip kontrolüyle derler; API testleri `tests/integration/test_api*.py`.

### 14.2 Sunucuda salt okunur çalıştırma (9 Kasım 2026)

Uygulama bir sunucuda salt okunur çalışabilir: veri bilgisayarda çekilir ve gönderilir, sunucu yalnızca gösterir.
Sunucu yapılandırması (servis, ters vekil, sertifika, alan adı) depoda tutulmaz; yalnızca sunucuda durur.

- **Salt okunur mod**: `FDO_READ_ONLY=1` ile `POST /api/sync` ve `POST /api/news/refresh` 403 döner; arayüzde
  "Yahoo'dan güncelle" ve "Haberleri yenile" yerine sunucudaki son veriyi yeniden yükleyen "Yenile" düğmesi.
  Çalıştırma: `PYTHONPATH=src FDO_READ_ONLY=1 python -m uvicorn fdo.api.app:create_app --factory --port 8610`
  (önce `npm run build`).
- **Veri gönderme** (bilgisayarda, güncellemeden sonra):

  ```powershell
  .venv\Scripts\python.exe scripts\yahoo_sync.py                    # kadrolar, skorlar, CBS, NBA maç kayıtları, haberler
  .venv\Scripts\python.exe scripts\news_refresh.py                  # gün içinde 2 saatte bir
  .venv\Scripts\python.exe scripts\push_data.py --host <ssh-host>   # ya da $env:FDO_PUSH_HOST
  ```

  `push_data.py`, `data/real` altındaki git dışı dosyaları tek tar.gz olarak `ssh` ile gönderir (`--app`, varsayılan
  `/srv/fantasy/app`); sunucuda `scripts/receive_data.py` her dosyayı geçici dizinden `os.replace` ile yerine koyar.
  `snapshots/`, yönetici iletişim bilgileri ve ham yakalamalar gitmez. **Yeniden başlatma gerekmez**: uygulama dosya
  imzası değişince veriyi kendisi yeniden yükler (ilk istek birkaç saniye). Kod değişince sunucuda `git pull`, arayüz
  derlemesi ve servis yeniden başlatma gerekir.
- **Detaylı analiz sunucuda** (isteğe bağlı, ücretli): sunucudaki repo kökünde `.env` (`ANTHROPIC_API_KEY=...`, servis
  kullanıcısı okuyabilmeli) ve servise `FDO_REPORT_CODE=<kod>` ortam değişkeni; arayüz bu kodu bir kez sorar. Kod yoksa
  sunucuda kapalıdır.

## 15. Sözlük

| Terim | Anlamı |
|---|---|
| **ADP / `A_i`** | Average Draft Position. Yalnızca seçilme zamanını modellemek için kullanılır. `A_i` fallback sonrası efektif ADP'dir |
| **ECW** | Expected Category Wins: rakip başına beklenen kategori galibiyeti (0–9), 15 rakip ortalaması |
| **ΔECW** | Oyuncu eklemenin ECW'ye etkisi, aynı pick'in doldurma profiline göre |
| **Turn** | Kullanıcının arada rakip seçimi olmayan ardışık seçimleri (örn. 16/17) |
| **Doldurma profili `F(n)`** | n. pick'te seçilmesi beklenen oyuncunun haftalık istatistik ortalaması ve varyansı |
| **Survival `P_surv`** | Oyuncunun belirli bir pick'te hâlâ uygun olma olasılığı (simülasyondan) |
| **CRN** | Common Random Numbers: adayları aynı rastgele senaryolarla karşılaştırma |
| **Thurstone modeli** | Her botun oyunculara kalıcı gürültülü bir sıra atadığı ve en iyi algılananı seçtiği model |
| **π (politika)** | Rollout içinde kullanıcının sonraki turn'deki seçim kuralı (V1: miyopik en iyi çift) |
| **Punt** | Bir kategorinin ranking ağırlığını 0 yapmak. Lig skoru 9 kategori olarak kalır |
| **`uncalibrated`** | Gerçek veriyle ayarlanmamış parametreye dayanan çıktı rozeti |
