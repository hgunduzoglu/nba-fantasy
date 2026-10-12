# Fantasy Draft Optimizer (FDO)

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
13. [Yol haritası (V2+)](#13-yol-haritası-v2)
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
    realism/
      metrics.py              # pick−ADP dağılımı, reach, çeşitlilik
      report.py
    evaluation/
      interface.py            # V2 backtest arayüzü (V1'de yalnızca protokol)
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
| `injury_status` | str | | Kaynağın durum etiketi (`O`, `Q`, `NA`…); yalnızca `O` etkiler (§5.8) |

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

Bu dosya yoksa §6.6.2'deki model varsayılanları kullanılır ve sonuçlar `uncalibrated` olarak etiketlenir.

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

### 5.8 Oyuncu durumu (out katsayısı)

Yahoo Draft Analysis'teki durum etiketi `players.csv`'de `injury_status` olarak saklanır (gerçek veride 21 `O`, 109 `Q`, 127 `NA`). Kullanıcı kararı (13 Ekim 2026):

- **`O` (out):** `projected_gp × out_gp_factor` (varsayılan 0.85, kalibre edilmemiş). Yahoo projeksiyonunun `gp`'si bazı oyuncularda zaten düşüktür (örn. Jimmy Butler III: 35); katsayı dönüş tarihi ve tekrar sakatlanma belirsizliği için ek indirimdir.
- **`Q`, `GTD`, `NA`:** hiçbir etki yok; oyuncu durumsuz gibi değerlendirilir (ligde IL+ yok).

```yaml
availability:
  out_statuses: [O]
  out_gp_factor: 0.85
```

Katsayı ham tabloyu değiştirmez; değerleme (`total` tabanı) ve haftalık matchup vektörleri projeksiyonu `fdo.availability.effective_projections` üzerinden okur. Bu yüzden config değişince veri setinin yeniden yüklenmesi gerekmez. `per_game` tabanında maç sayısı kullanılmadığından katsayı değerlemeyi etkilemez (matchup'ı etkiler). Botlar katsayıyı değerleme üzerinden görür (ValueHunter, PuntBuilder); piyasa (ADP) durumu zaten fiyatlar.

Gerçek veride etkisi (dengeli Z sırası, katsayı 1.0 → 0.8 denemesi): Brandon Ingram 89 → 155, Isaiah Stewart 132 → 200, Jimmy Butler III 267 → 302. 0.8 sert bulunduğu için varsayılan 0.85 seçildi.

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
a_i = min(projected_gp_i, 82) / 82               # müsaitlik (out ise gp × out_gp_factor, §5.8)
k_i = utilization · games_per_week · a_i          # haftalık beklenen sayılan maç
```

`utilization`, `scripts/estimate_utilization.py` ile tahmin edildi. 480 mock kadrosu (13 oyuncu, pozisyon uygunluğuyla 10 aktif slot) 20 hafta simüle edildi. Takım takvimi varsayımsaldır: gün başına ortalama maç sayısı Pzt–Paz 8/6/9/5/8/6/7, haftalık sapma σ = 3 maç. Sonuçlar:

| lineup_lock | utilization |
|---|---|
| daily_today | 0.982 |
| daily_tomorrow | 0.961 |
| weekly | 0.864 |

Sapma olmadan (her hafta aynı takvim) daily_today 0.996 çıkar; kayıp neredeyse tamamen kalabalık gecelerden gelir. IL slotlarıyla yapılan stream/yerine oyuncu alma modellenmez. Gerçek takvim V2'dir.

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

Tek uygulama ve çok sayfa (`st.navigation` veya `pages/`). Durum `st.session_state` içinde tutulur: `dataset`, `config`, `draft_log`, `seed`, `weights`. Ağır hesaplar `st.cache_data` ile `(dataset_hash, config_hash, state_hash, seed, params)` anahtarına göre önbelleklenir.

| Sayfa | İçerik |
|---|---|
| **1. League & Data** | Lig config görüntüleme/düzenleme (kesin alanlar kilitli, doğrulanmamış alanlar uyarılı); CSV yükleme, kolon eşleme, validasyon raporu, manifest durumu; sentetik veri üret butonu; `adp_status` dağılımı |
| **2. Projection Explorer** | Oyuncu tablosu: Z/G seçimi, `per_game`/`total`, 9 kategori skoru, `V`, sıra, `adp_eff` ve `value_rank − ADP`, `adp_status`, pozisyonlar; ağırlık slider'ları ve presetler; havuz boyutu (180/208/240) duyarlılığı; filtre ve arama |
| **3. Mock Draft** | 16×13 board; seed; bot karışımı; "sıradaki pick'i oynat", "kullanıcıya kadar oynat", "sona kadar oynat"; manuel seçim (arama); undo, "pick k'ye dön", replay; CSV/JSON export ve import; reach renkleri |
| **4. Draft Assistant** | Kullanıcının sırası geldiğinde: aday çift tablosu (E[W], P10–P90, SE, kademe); seçili çift için **48/49 havuzu** (§6.7.4); iki çift karşılaştırması; bekleme maliyeti; hesap parametreleri ve süre; "hızlı / tam" mod |
| **5. Team Dashboard** | 16 takım × 9 kategori ortalama P(win); kullanıcı vs her rakip matrisi; kazanılabilir/sınırda/kaybedilmiş kategoriler; gerçek/doldurma oranı; FG%/FT% toplamdan hesaplanmış takım oranları |
| **6. Realism Report** | §7 metrikleri: son mock ve batch raporu; histogramlar; uygunsuz reach listesi |

UI kuralları:
- Sentetik veri bandı (§5.7) ve `uncalibrated` rozetleri (İlke 10) her zaman gösterilir.
- Olasılıklar SE ile gösterilir, örneğin `%62 ± 2`. Kalibre edilmemiş modelden gelen değerlerde "≈" işareti kullanılır.
- Advisor hesabı çalışırken `st.status` ile ilerleme gösterilir. Uzun hesaplar iptal edilebilir.
- Mock'ta advisor, rakip pick'leri oynanırken **önceden** hesaplanabilir (opsiyonel). V1'de ÖNERİLİR olan, kullanıcının sırası gelince hesaplamaktır, hızlı mod varsayılandır.

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

Gerçek veride ilk ölçümler bütçeyi aşıyordu (tek mock 0.52 s, hızlı mod 16–26 s). Neden: 3 pozisyonlu oyuncularla 12 pozisyon grubu oluşuyor ve bot kadro analizi her durumda `linear_sum_assignment` çözüyordu. Bot analizi grup × slot tipi düzeyinde kapasiteli eşlemeye (`GroupFlow`) çevrildi; "bu oyuncu boş slotu azaltır mı" sorusu tek eşlemeden artık-graf erişilebilirliğiyle cevaplanıyor (eski çözücüyle eşdeğerliği testle korunur). CI her push'ta bu ölçümü raporlar.

Hedef aşılırsa sırayla şunlar uygulanır: (1) ECW değerlendirmesi vektörize edilir, (2) aday ve çift sayısı küçültülür, (3) ardışık yarılama (successive halving) kullanılır: önce `S = 100` ile kötü çiftler elenir, kalanlara `S` artırılır. Yahoo pick süresi (§3.2) öğrenildiğinde tam mod bütçesi buna göre ayarlanır.

---

## 12. Bilinen sınırlamalar ve açık sorular

### 12.1 Model sınırlamaları (V1'de bilinçli olarak kabul edilenler)
- **Normal yaklaşım:** STL/BLK gibi düşük sayılı kategorilerde haftalık dağılım çarpık ve ayrıktır. Beraberlikler yok sayılır.
- **Maç sayısı sabit** (`games_per_week`). Takvim farkları ve B2B dikkate alınmaz. Maç sayısının varyansı ihmal edilir.
- **Varyans parametreleri (`φ`) kalibre edilmemiştir.** Oran kategorilerinde binom terimi yapısal olarak doğrudur. Hacim varyansı ise varsayımdır.
- **Utilization tek bir katsayıdır.** Günlük lineup çözülmez.
- **Doldurma profilleri nötrdür.** Rakip ve kullanıcı punt eğilimlerini modellemez.
- **Sonraki çift politikası miyopiktir** (π). 49'dan sonrası doldurma profiliyle temsil edilir. H-score tarzı gelecek pick stratejisi V2'dedir.
- **Bot parametreleri gerçek draft verisiyle kalibre edilmemiştir.** Olasılıklar `uncalibrated` olarak etiketlidir.
- **Geç turlarda `pick − A` medyanında pozitif kayma.** Reach'ler `pick − A` dağılımına sol kuyruk ekler; medyan bu yüzden ortalamadan büyüktür. Gerçek Yahoo verisinde kalan kayma 8–13. turlarda +6.5…+16.3 (σ sınırı çarpandan sonraya alınmadan önce +17…+26). ADP'si 97–160 bandındaki oyuncular ortalamada ADP'lerinden birkaç pick geç gider; bu bölgede survival olasılıkları hafif iyimser olabilir. Oyuncu başına konum kalibrasyonu denendi ve yakınsamadı (§6.4.3); gerçek draft log'larıyla kalibrasyon V2'dedir.
- **ADP büyük ölçüde 10/12 takımlı liglerden gelir.** 16 takımlı ligin geç turlarında belirsizlik yüksektir.
- **Sezon boyu rastgele rakip varsayımı:** Gerçek H2H takvimi ve playoff haftaları yok sayılır.

### 12.2 Kullanıcının doğrulaması gereken açık sorular
1. ~~Kategori beraberlik kuralı~~ — cevaplandı: kategori beraberliği T yazılır (W-L-T), `tie_value: 0.5`.
2. ~~Draft pick süresi~~ — cevaplandı: 45 s (yalnızca gerçek draft için advisor bütçesi; mock'ta süre yok).
3. ~~Yahoo'nun draft sırasında pozisyon sınırı uygulayıp uygulamadığı~~ — cevaplandı: uygular (§6.3.2).
4. Lineup kilit kuralı, IL/IL+ slotları. **Yanıtlandı (13 Ekim 2026):** daily_today → `utilization` 0.98 (§6.6.1); 3 IL, IL+ yok; Q etkisiz, O için maç sayısı katsayısı (§5.8).
5. ~~Projeksiyon kaynağının kullanım şartları~~ — kullanıcı kararı: Yahoo sayfaları public, kişisel kullanım (`personal_use_confirmed`).
6. ~~ADP kaynağının kolonları~~ — Yahoo Draft Analysis: `% drafted`, preseason / all / last 7 days ADP var; std ve min/max yok. ADP en fazla ~123. pick'i kapsıyor (§5.6 `after_coverage`).
7. ~~Otomatik draft eden menajer~~ — cevaplandı: yok, `AutoDrafter: 0`.

### 12.3 Doğrulanmamış teknik iddialar
- G-score paydasındaki kesin katsayı (`κ`). Makaleden doğrulanacak.
- Yahoo autodraft'ın varsayılan sıralamayı kullandığı. Doğrulanmadı; AutoDrafter profili bu varsayıma dayanıyor (bu ligde kullanılmıyor).
- Yahoo pozisyon kuralının tam tanımı. "Kalan pick'lerle aktif slotlar doldurulamıyorsa pick reddedilir" yorumu uygulanıyor.
- §7'deki gerçekçilik hedef değerleri birer varsayımdır.

---

## 13. Yol haritası (V2+)

1. **Backtest çerçevesi** (`fdo.evaluation`): Arayüz V1'de tanımlıdır:
   ```python
   class SeasonEvaluator(Protocol):
       def evaluate(self, rosters: dict[int, list[str]], season: str) -> EvaluationResult: ...
   ```
   Strateji karşılaştırması şunlar arasında yapılır: Z-greedy, G-greedy, ECW-advisor (aynı bot ligine karşı). Değerlendirme gerçekleşen haftalık istatistiklerle yapılır (nba_api, şartlara uygun olarak).
   **Veri sorunu:** Geçmiş sezonların *sezon öncesi* projeksiyon ve ADP snapshot'larına yasal olarak erişim belirsizdir. Erişilemezse yedek yöntem "gerçekleşen ortalama + gürültü" projeksiyonlarıdır. Bu yöntem iyimser sonuç verir ve sonuçlar bu kayıtla raporlanmalıdır.
2. **Varyans kalibrasyonu:** nba_api game log'ları ile oyuncu bazında `per_game_var`, kategori bazında `φ`, kategori korelasyonları.
3. **Derin lookahead:** 13 tura kadar rollout, beam search, successive halving. H-score tarzı gelecek pick ağırlık optimizasyonu (bağımsız implementasyon, Rosenof makaleleri referans alınarak).
4. **Haftalık takvim ve günlük lineup çözücü**, maç sayısı varyansı, playoff haftaları.
5. **Sakatlık ve rol senaryoları:** GP aralıkları, rookie belirsizlik genişletmesi.
6. **Bot kalibrasyonu:** Gerçek draft log'larından (indirilen mock CSV'leri, kendi liginin geçmişi) σ₀, σ₁ ve profil karışımının fit edilmesi; survival güvenilirlik grafiği.
7. **Yahoo API senkronizasyonu:** API başvurusu ve onay, OAuth, `draftresults` üzerinden polling, event dedupe ve boşluk tespiti, manuel override. Yahoo atıf gereksinimi uygulanır. Manuel giriş her zaman yedek olarak kalır.

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
    --adp data/real/raw/yahoo_adp_2026-10-12.json --license-status personal_use_confirmed     --license-notes "Kullanıcı kararı (2026-10-12): Yahoo sayfaları public; kişisel kullanım."

# utilization tahmini (§6.6.1)
python scripts/estimate_utilization.py --data data/real/ --mocks 30
```

---

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
