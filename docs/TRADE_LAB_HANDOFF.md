# Fantasy Trade Lab — Claude / geliştirici devir raporu

Rapor tarihi: **31 Ekim 2026**. Başlangıç commit'i: `29e0dbd`.
Bu belge, draft odaklı mevcut Python projesine eklenen sezon içi trade katmanını,
yerel veri denetimini ve uygulamanın gerçek sınırlarını açıklar. Kod incelemesi ve
geliştirmeye devam etmek için tek giriş belgesi olarak hazırlanmıştır.

## 1. İstenen sonuç ve mevcut durum

Kullanıcının amacı, dört Yahoo Fantasy Basketball liginde mevcut kadrolarla
takas analiz edebilmek ve iki tarafa da fayda sağlayan takaslar bulabilmekti.
Yahoo API erişimi olmadığından, daha önce tarayıcıdan alınmış yerel JSON/CSV
anlık görüntüleri kullanılıyor. Bu geliştirme canlı Yahoo bağlantısı kurmaz.

| Gereksinim | Uygulanan davranış |
|---|---|
| Üç istatistik kaynağını ayır | `preseason`, `season_total`, `remaining_games_projection`; kaynaklar birbirini doldurmaz |
| Her ligde tüm takımların kategori sıraları | Sezon öncesi, gerçekleşen ve ROS için üç ayrı menü |
| Takası her kaynakla ayrı değerlendir | Analizde üç sekme; iki tarafın kategori toplamı, sırası ve sıra farkı |
| FG% / FT% şut hacmine bağlı olsun | İsabet toplamı / deneme toplamı; oyuncu yüzdelerinin ortalaması alınmaz |
| Rakipleri yenme ihtimalindeki değişimi gör | Yalnızca ROS'tan tipik hafta kategori olasılıkları, ECW ve P(5+) |
| Karşı tarafın faydasını gözet | Ayrı stratejiler, iki taraflı kazanç eşikleri, paket değer dengesi |
| Kabul / komisyon etkisini değerlendir | Fayda/uyum puanı, değerlendirme riski, son tarih ve inceleme süresi; sezgisel göstergeler |
| Punt ve farklı stratejiler | Dengeli, tek/çift punt, özel ağırlıklar, varsayımsal zayıf kategori punt'u |
| Eşit olmayan paketleri ele al | Açık drop/add planı veya isteğe bağlı otomatik kadro dengeleme |
| Hatalı ham oyuncu verisi korunsun | Kaynak dosyalar değiştirilmez; eksikler görünür ve model kapsamı açıklanır |
| Diğer takımların eksik fikstürlerini takip etme | H2H fikstürü tamamlanmadı; bütün rakipler eşit ağırlıkla karşılaştırılır |

Streamlit'in varsayılan başlangıcı artık Trade Lab. Eski draft sayfaları arşiv
menülerinde korunuyor. Çekirdek hesaplama Streamlit'ten bağımsızdır ve CLI'dan
da çağrılabilir. Analiz Yahoo'da gerçek takas veya oyuncu alım/bırakım işlemi yapmaz.

## 2. Yerel veri denetimi

### Ligler ve kadro kuralları

Anlık görüntü tarihi **2026-10-31**. Toplam **56 takım**, **893 dolu oyuncu-kadro
kaydı**, ligler arasında tekrarlar çıkarılınca **264 farklı kadrolu oyuncu** var.
902 görünen slot satırının 9'u boş. Aynı lig içinde aynı oyuncu iki kadroda yok;
birleştirilmiş ve lig bazındaki roster JSON/CSV kayıtları denetlendi.

| Lig ID | Lig adı | Takım | Dolu oyuncu kaydı | Normal kapasite | IL | Haftalık alım sınırı | Varsayılan takım ID |
|---|---|---:|---:|---:|---:|---:|---:|
| 93992 | METU IE Fantasy Basketball | 14 | 214 | 13 | 4 | 4 | 7 |
| 220594 | METU IE Snake League | 14 | 208 | 13 | 3 | 5 | 4 |
| 229303 | WNBA 26-27 | 16 | 236 | 13 | 3 | 4 | 2 |
| 104375 | tsg fentezi | 12 | 235 | 17 | 4 | 5 | 11 |

`WNBA 26-27` burada yalnızca lig adıdır; toplanan veri NBA Fantasy verisidir.
104375'te `Max Teams = 14`, fakat mevcut takım sayısı 12'dir. Hesaplar 12 takımı
kullanır. Kapasite, görünen dolu BN/IL satırlarından değil lig kurallarından okunur.
Boş bench/IL satırları her zaman görünmediği için ekran satırı sayısı kapasite değildir.

Toplam 147 ayar alanı var (38 / 36 / 36 / 37). Dört lig de H2H 9 kategori ve
Daily Today formatında. Normal slotlar:

- 93992: PG, SG, G, SF, PF, F, C, C, UTIL, UTIL, UTIL, BN, BN.
- 220594: PG, SG, G, SF, PF, F, C, FC, UTIL, UTIL, UTIL, BN, BN.
- 229303: PG, SG, G, SF, PF, F, C, C, UTIL, UTIL, BN, BN, BN.
- 104375: PG, SG, G, G, SF, PF, F, F, C, C, UTIL, UTIL, UTIL, BN, BN, BN, BN.

Takas son tarihi ilk üç ligde **4 Mart 2027**, 104375'te **18 Mart 2027**.
İnceleme Commissioner; bekleme süreleri sırasıyla 2, 2, 3 ve 1 gün.
Varsayılan takım ID'si eldeki tek takım fikstüründen seçilir; Yahoo takım ID'si
draft koltuğuyla aynı şey değildir. Kullanıcı kenar çubuğundan değiştirebilir.

### Oyuncu ve istatistik kapsamı

`player_stat_pages.json` iki kaynak için 30'ar sayfa içeriyor. Her kaynakta
aynı 744 oyuncu ID'si var. Yahoo kaynak işaretleri gerçekleşen için `S_S_2026`,
kalan sezon için `S_PSR`. Sayfalar 31 Ekim'de yaklaşık 12:42–12:45 UTC arasında alınmış.

| Kaynak | Satır / ortak kayıt | Tam sayısal satır | 264 kadrolu oyuncudan tam olan |
|---|---:|---:|---:|
| Sezon öncesi CSV | 507 / 744 | 507 | 262 |
| Gerçekleşen sezon toplamı | 744 / 744 | 432 | 243 |
| Kalan sezon projeksiyonu (ROS) | 744 / 744 | 481 | 261 |

"Tam" burada GP ve bütün gerekli sayısal istatistiklerin bulunmasıdır; kaynakta
`-` olan alan sıfır sayılmaz. ROS'ta GP > 0 olan 486 oyuncunun beşinde başka sayısal
alan eksik; hepsi kadro dışındadır. ROS modeli 481 oyuncuyu kullanabiliyor.
Gerçekleşen veride 21 kadrolu oyuncunun tam sezon satırı yok; bu tek başına veri
bozulması demek değildir, henüz oynamamış oyuncuları da kapsar.

Kadrolu olup ROS modeline giremeyen üç oyuncu:

- Kevin Porter Jr. (`6218`): GP/istatistik alanları eksik.
- Ben Simmons (`5600`): GP 0 ve eksik alan.
- Tarik Biberovic (`10085`): GP 0 ve eksik alan.

Bu oyuncular kadrolarda kalır. Otomatik takas paketleri, otomatik FA ekleme ve
otomatik drop sıralaması için kullanılmazlar. Manuel analiz mümkündür; sonuç
kısmi model olarak işaretlenir. Kaynakları tamamlamak için diğer istatistik modu
kopyalanmaz. Sezon öncesi kapsam da 744 oyuncunun tamamı değildir.

Kaynakta kadro dışı Zyon Pullin (`10344`) için FG% `1.012` gibi geçersiz bir değer
görüldü. Ham değer korunuyor; takım yüzdesi hesaplaması kaynak yüzde sütununu
kullanmadığından isabet/deneme çiftinden hesaplanıyor. Bu bir veri düzeltmesi değildir.

Önceki master dosyasında 739 oyuncu var. 264 kadrolu ID'nin hepsi bu master'a
bağlanıyor; yeni istatistik sayfalarındaki ek ID'lerle ortak kayıt 744'e çıkıyor.
Eski `y_5352` biçimi yerine trade katmanında Yahoo `5352` metin ID'si kullanılır.
Güncel kadro metadatası eski takım/pozisyon/durum alanını günceller; örneğin
Ochai Agbaji'nin eski/yeni NBA takımı farkı bu yolla ele alınır.

### Kullanılan ve kullanılmayan ek veriler

- `schedule_nba_2026-27.csv`: 20 Ekim 2026–11 Nisan 2027 aralığı; ROS hafta
  ufkunu belirlemek için kullanılır. Takım bazında haftalık oynanacak maç/lineup
  simülasyonu yapılmaz.
- `variance_nba_2024-25_nba_2025-26.csv`: mevcut geçmiş maç varyansı katmanıdır.
  Oyuncu ID'leri normalize edilir; eksik varyanslar mevcut phi yaklaşımına gider.
- Kısmi H2H fikstürleri her ligde tek takımı kapsar. Diğer 52 takımın fikstürü
  kullanıcının isteğiyle tamamlanmadı ve modele gerekli kabul edilmedi.
- Menajer, draft sonucu, transaction ve diğer raw snapshot dosyaları trade
  hesaplamasının zorunlu girdisi değildir. İşlem geçmişinden davranışsal kabul
  modeli veya kalan acquisition hakkı çıkarılmıyor.

## 3. Modül ve dosya haritası

| Dosya | Sorumluluk |
|---|---|
| `src/fdo/trade/__init__.py` | Kamuya açık çekirdek API |
| `src/fdo/trade/data.py` | Yerel snapshot okuma, ID eşleme, üç kaynak, lig config'i, kapsam uyarıları, dosya imzası |
| `src/fdo/trade/strategy.py` | Dokuz kategori, presetler, özel ağırlıklar, varsayımsal punt |
| `src/fdo/trade/engine.py` | Toplamlar/sıralar, ROS vektörleri, roster çözümü, iki taraflı analiz, değer dengesi |
| `src/fdo/trade/suggest.py` | Bütçeli paket araması, iki taraflı fayda filtreleri ve öneri sırası |
| `src/fdo/trade/report.py` | Kategori/rank farkları, her rakibe karşı fark, strict JSON export |
| `scripts/analyze_trade.py` | Yerel snapshot üzerinden CLI analizi |
| `src/fdo/ui/trade_common.py` | Veri/engine cache'i, lig/takım/strateji seçimleri, ortak sonuç ekranları |
| `src/fdo/ui/pages/10_Trade_Home.py` | Başlangıç, lig özeti, oturum içi senaryo karşılaştırma |
| `src/fdo/ui/pages/11_Preseason_Ranks.py` | Sezon öncesi sıralama menüsü |
| `src/fdo/ui/pages/12_Current_Ranks.py` | Gerçekleşen sezon sıralama menüsü |
| `src/fdo/ui/pages/13_ROS_Ranks.py` | ROS sıralama menüsü ve olasılık özeti |
| `src/fdo/ui/pages/14_Trade_Analyzer.py` | Manuel paket/drop/add seçimi ve analiz |
| `src/fdo/ui/pages/15_Trade_Suggestor.py` | Rakip stratejileri, paketler, bütçe/eşikler, öneriler ve ayrıntıları |
| `src/fdo/ui/pages/16_Trade_Data.py` | Kaynaklar, kurallar, eksik veri ve kapsam görünümü |
| `src/fdo/ui/app.py` | Trade varsayılan navigasyonu ve eski draft arşivi |
| `tests/unit/test_trade.py` | Çekirdek davranış ve regresyon testleri |
| `tests/integration/test_trade_ui.py` | Streamlit sayfaları ve etkileşimli akışlar |

Eski `fdo.matchup`, `fdo.valuation` ve roster assignment modülleri yeniden
kullanılıyor. Çekirdeğe yeni zorunlu paket eklenmedi. `pyproject.toml` açıklaması
trade kapsamına güncellendi; paket adı/sürümü korunuyor.

## 4. Hesaplama sözleşmesi

### Üç ayrı kaynak ve rank

Sezon öncesi CSV maç başına istatistik içerir; her alan `projected_gp` ile
çarpılıp dönem toplamına dönüştürülür. Sezon öncesi dosyası sezonun ilk NBA
maçından önceki en yeni tarihli CSV'dir. Sonradan eklenen sezon içi projeksiyon
CSV'si bu kaynağın yerini alamaz. Gerçekleşen ve ROS kaynakları zaten dönem toplamıdır.

Her görünümde güncel kadro oyuncularının ilgili kaynaktaki toplamları kullanılır.
Gerçekleşen görünüm Yahoo'nun geçmişte aktif slotlardan kazandırdığı takım
istatistiği/puan tablosu değildir. BN ve IL oyuncuları da kaynak katkılarıyla
kadronun toplamına dahildir; sayfalar günlük aktif lineup sonucu iddiası taşımaz.

```text
FG% = ΣFGM / ΣFGA
FT% = ΣFTM / ΣFTA
rank_gain = rank_before - rank_after
```

Her oran için pay ve payda aynı, iki bileşeni de bilinen oyuncu kümesinden alınır.
Bir bileşen eksikse oyuncunun yalnızca bilinen denemesi paydaya eklenmez. Toplam
deneme sıfırsa oran bilinmiyor kalır. Sayım kategorileri mevcut sayısal katkıları
toplar; kapsam tablosu bu toplamların tam olup olmadığını gösterir. TO düşük
olan daha iyidir, diğer kategorilerde yüksek olan iyidir. Eşitliklerde ortalama
sıra, bilinmeyenlerde boş sıra kullanılır. Takas sonrası bütün lig yeniden sıralanır.

### ROS'tan tipik hafta ve kazanma göstergeleri

```text
H = (NBA sezon sonu - snapshot tarihi + 1 gün) / 7
oyuncu haftalık ortalaması = ROS toplamı / H × utilization
oyuncu haftalık varyansı = maç başına varyans × ROS_GP / H × utilization
ECW = Σ dokuz kategorinin kazanılma olasılığı
strateji_puanı = 9 × Σ(normalize kategori ağırlığı × kategori olasılığı)
```

Mevcut snapshot için `H = 23.285714...` hafta; varsayılan utilization **0.987**.
ROS GP **82'ye bölünmez**. UI'daki değerlendirme tarihi sadece takas son tarihi
kontrolünü değiştirir; eski istatistikleri yeni tarihe otomatik taşımak için kullanılmaz.

Maç başına ROS katkıları ile tarihsel varyans/phi fallback kullanılarak eski
matchup modelinin 24 boyutlu takım vektörleri hazırlanır. Oran kategorileri
isabet, deneme ve bunların varyans/kovaryans bileşenleriyle işlenir. Sıfır deneme
oyuncunun oran katkısını sıfır bırakır. Oyuncular arası varyans bağımsız varsayılır.

Kategori olasılıkları mevcut Normal yaklaşımıyla hesaplanır. P(5+), kategori
bağımsızlığı altında en az beş kategoriyi kazanma olasılığının DP hesabıdır.
H2H Each Category liginde ana çıktı ECW'dir; P(5+) ek bir göstergedir. P(5+)
playoff'a kalma veya sezonu kazanma olasılığı değildir.

Lig özeti bütün diğer takımlara karşı eşit ağırlıklı ortalamadır. Takas yapılan
rakibin değişmiş kadrosu da dahil edilir. Her rakip için kategori olasılığının
yüzde puan değişimi, ECW ve P(5+) önce/sonra değerleri ayrıca gösterilir.

Punt tercihi bu fiziksel olasılıkları değiştirmez. 0–3 ağırlıklar ayrı fayda/uyum
puanını değiştirir; ağırlıksız dokuz kategori ECW'si ayrıca korunur. Otomatik
zayıf kategori punt'u rakibin gerçek niyeti değil, açık bir strateji varsayımıdır.

### Kadro ve IL çözümü

Takımlar, sahiplik, ID'ler, tekrarlar, gönderilen/bırakılan/eklenen oyuncular ve
normal kapasite doğrulanır. İki taraf da en az bir oyuncu verir. FA eklemesi
ligde gerçekten boşta olan kayıtlar arasından yapılır; aynı oyuncu iki tarafa eklenmez.

IL normal kapasiteden ayrıdır. Mevcut IL yerleşimleri korunur; gelen oyuncu
önceki kadrosunda IL'deyse, uygun sakatlık durumuna ve boş IL kapasitesine göre
yeni takımda IL'e taşınabilir. İki yön de aynı kaynak yerleşimi üzerinden çözülür.
Bu, güncel Yahoo uygunluğunu doğrulayan bir API kontrolü değildir.

İsteğe bağlı auto-drop, kalan ve modellenebilen normal kadro oyuncuları arasında
strateji değeri en düşük olanı bırakır; yeni gelen oyuncuyu otomatik bırakmaz.
Auto-fill yalnızca takasın oluşturduğu eksilmeyi takas öncesi normal kadro
büyüklüğüne kadar tamamlar. Daha önce boş olan slotları doldurup takas kazancı
gibi göstermez. Drop/add/IL hareketleri analizde açıkça listelenir.

FA planı waiver sırası, henüz erişilemeyen oyuncular, kalan haftalık acquisition
hakkı ve Can't Cut listesi doğrulanmadığı için koşulludur. Pozisyon assignment
kontrolü doldurulamayan aktif slotlar için açıklama üretir; günlük lineup optimizasyonu değildir.

### İki taraflı öneri ve kabul değerlendirmesi

Varsayılan paketler 1x1, 2x1, 1x2, 2x2; UI'da 3x2/2x3 de açılabilir.
1x1 aday kümesi tüm modellenebilir kadrolu oyunculardır; büyük paketler strateji
uyumu, yüksek piyasa değeri ve tamamlayıcılardan oluşan kısa listeyle aranır.
Rakip ve paket tipleri sırayla ele alınır; bütçenin tamamı ilk rakipte harcanmaz.

Varsayılanlar: kısa liste 8, bütçe 8000 paket, en fazla 20 sonuç, değer dengesi
en az 0.55, iki tarafın da strateji puanı artışı en az 0.005, iki tarafın da
P(5+) değişimi en az 0. Eşikler UI'dan ayarlanabilir. İncelenen paket bütçesi
ön filtrelerden elenenleri de sayar. Sınıra ulaşmak aramanın tamamlandığını göstermez.

Dengeli ROS valuation üzerinden pozitif replacement-relative piyasa değeri
çıkarılır; referans havuz boyutu gerçek takım sayısı × normal kapasitedir.
Paket dengesi küçük paket değeri / büyük paket değeridir. Gönderilen paketlerin
değerini ölçer; garanti piyasa fiyatı veya komisyon kararı değildir.

```text
g_a = 0.65 × strateji_delta_a / 9 + 0.35 × P5_delta_a
g_b = 0.65 × strateji_delta_b / 9 + 0.35 × P5_delta_b
öneri_skoru = (min(g_a, g_b) + sqrt(g_a × g_b)) × (0.5 + 0.5 × denge)
```

ECW ağırlığı ayarlanabilir. İki birleşik kazanç da pozitif olmalıdır. Sadece
kullanıcıya faydalı görünen paket bu filtreyi geçemez. Bütçeli arama
deterministiktir; sonuç çıkmaması geçerli bir sonuçtur.

Manuel analiz ayrıca şu sezgisel fayda/uyum puanını verir:
`clip(50 + 250 × strateji_delta + 100 × P5_delta, 0, 100)`.
Komisyon riski son tarih, değer dengesi, karşılıklı fayda ve eksik gelen oyuncu
verisine bağlı sınıflandırmadır. **İnsan kabul yüzdesi veya komisyon onay
olasılığı eğitilmedi.** Export'taki `calibrated_acceptance_probability` bu
nedenle `null`'dır. Son tarih sonrası öneri üretilmez; manuel senaryo işaretlenerek incelenebilir.

## 5. Çıktı, durum ve önbellek

- Sıralamalar CSV, analizler JSON indirilebilir.
- JSON `schema_version = 1`: kaynaklar, veri tarihi/imzası, istek, stratejiler,
  iki tarafın metrikleri, değerlendirmeler, drop/add planı, takas sonrası kadrolar,
  üç kaynak için kategori/rank karşılaştırmaları, rakip farkları ve varsayımlar.
- NaN/sonsuz değerler JSON'da `null` olur; `allow_nan=False` ile strict JSON üretilir.
- Senaryo karşılaştırması Streamlit oturumu içindedir. Kalıcı veritabanı yoktur;
  saklamak için JSON export gerekir.
- Lig, veri, kullanım oranı, paket, strateji veya tarih değiştiğinde eski manuel
  analiz yeni isteğin sonucu gibi gösterilmez; istek imzası kontrol edilir.
- Kaynak dosya yolu/mtime/boyutu ve config imzaları cache yenilenmesinde kullanılır.
  Bu bir içerik hash'i veya arşivlenmiş snapshot kimliği değildir.
- Kadro vektör cache'i 20.000 kayıtla sınırlıdır. Analiz kaynak kadrolarını ve
  ham dosyaları değiştirmez; her senaryo başlangıç snapshot'ına karşı hesaplanır.

## 6. Yerel çalıştırma ve veri sözleşmesi

PowerShell, repo kökünde:

```powershell
.venv\Scripts\python.exe -m pip install -e '.[dev]'
.venv\Scripts\python.exe -m streamlit run src/fdo/ui/app.py
.venv\Scripts\python.exe scripts/analyze_trade.py --help
```

CLI parametreleri: `--data`, `--league`, `--team-a`, `--team-b`, `--give-a`,
`--give-b`, `--strategy-a`, `--strategy-b`, `--auto-balance`, zorunlu `--out`.
Takım/oyuncu ID'leri seçilen ligdeki güncel kadrolara ait olmalı. CLI otomatik
öneri taraması değil, belirtilen paketin analizidir.

Trade Lab'in zorunlu yeni yerel girdileri `data/real/` altında:

| Dosya | Beklenen yapı |
|---|---|
| `rosters.json` | `season`, ISO `roster_date`, `leagues[]`; her ligde `league_id`, `league_name`, `teams[]`; takımda `team_id`, `team_name`, `slots[]` |
| Slot kaydı | `slot`, `player_id` (boş olabilir), `player_name`, `nba_team`, `eligible_positions[]`, opsiyonel `status` / `is_injury_slot` |
| `league_info.json` | `leagues[]`; `league_id`, `settings.values` ve opsiyonel `schedules.teams` |
| `player_stat_pages.json` | Sayfa listesi; `kind`, `captured_at`, `source_url`, `table.headers` ve `table.rows`; satırda `player_id`, `player_name`, `cells[]` |

Player sayfasının son başlık satırında `GP*`, `FGM/A*`, `FG%`, `FTM/A*`, `FT%`,
`3PTM`, `PTS`, `REB`, `AST`, `ST`, `BLK`, `TO` bulunmalı. `FGM/A*` ve `FTM/A*`
isabet/deneme biçimindedir; binlik ayırıcı ve ondalıklı toplamlar desteklenir.
Kaynak `kind` değerleri `season_total` ve `remaining_games_projection`'dır.

Repodaki eski `players_yahoo_*.csv`, sezon öncesi `projections_yahoo_*.csv`,
config ve NBA takvimi de kullanılır. API'de açık `horizon_weeks` verilirse NBA
takvimi olmadan model kurulabilir; UI varsayılanı takvim dosyasını gerektirir.
Geçmiş varyans CSV'si opsiyoneldir. Bu importer mevcut Yahoo export şemasına
özeldir; herhangi bir CSV'yi otomatik tanıyan genel importer değildir.

**Public repo ve yerel veri:** Repo herkese açıktır. Yeni hesap/lig export'larının
bazıları menajer iletişim bilgileri içerdiği için bu dosyalar `.gitignore` ile
yerelde tutulur; bu commitlerle GitHub'a yüklenmez. Ham dosyaların içeriği
değiştirilmedi. Public repoyu yeni klonlayan kişi kendi yerel snapshot'ını
sağlamalıdır. Veri yoksa Trade Lab açıklayıcı yükleme hatası gösterir; kişisel
veri gerektiren iki test skip olur. Sentetik çekirdek/UI testleri yerel snapshot
gerektirmez. Claude bu çalışma dizinine erişiyorsa mevcut dosyaları okuyabilir;
yalnızca GitHub'a erişiyorsa bu rapordaki denetim özetini görebilir.

## 7. Doğrulama ve test kanıtları

Son geliştirme sırasında geniş regresyon paketi **244 passed, 2 deselected**
ile geçti. Ardından eksik oran bileşeni, sıfır deneme, sezon öncesi dosya seçimi
ve benzeri kenar durumlar eklendi/düzeltildi; son odaklı paket **45 passed** idi.
Bu rapor hazırlanırken son kodla geniş paket yeniden çalıştırıldı; nihai sonuç
aşağıdaki güncel kayıtta yer alır.

```powershell
# Geniş regresyon (uzun istatistiksel testler hariç)
.venv\Scripts\python.exe -m pytest -m 'not slow' -o addopts='' -q

# Trade + UI + mimari
.venv\Scripts\python.exe -m pytest tests/unit/test_trade.py tests/integration/test_trade_ui.py tests/test_architecture.py -o addopts='' -q
```

Güncel geniş paket sonucu (31 Ekim 2026): **248 passed, 2 deselected in 157.73s**.
Bu sonuç son kodu, yeni trade testlerini ve mevcut projenin diğer regresyonlarını kapsar.

Kapsanan davranışlar:

- Üç kaynağın ayrılığı, mevcut kadro kullanımı, şut hacmine bağlı oranlar,
  eksik bileşende eşleşen pay/payda, gerçek 0 ve `-` ayrımı, binlik/ondalık parser.
- Sezon içi CSV'nin preseason kaynağını değiştirememesi; sıfır şut denemesi;
  ROS haftalık ölçeğinin 82'ye bölünmemesi; TO yönü ve eşit sıralar.
- Takasta iki tarafın ve üç kaynağın güncellenmesi; değişen rakip kadrosunun
  olasılığa etkisi; kaynak kadro ve dosya hash'lerinin değişmemesi.
- Sahiplik/tekrar hataları; 2x1, 3x2/2x3 kapasite planları; önceden boş slotun
  yapay kazanç üretmemesi; bilinmeyen oyuncunun otomatik değersiz sayılmaması;
  simetrik IL transferi; stratejinin fiziksel olasılığı değiştirmemesi.
- Rank farkı ve strict JSON; eksik verinin başka kaynaktan doldurulmaması;
  son tarih; iki taraflı ve deterministik öneriler; bütçenin rakiplere dağılımı.
- Giriş dahil sekiz UI dosyasının render'ı, manuel analiz/üç sekme,
  değişen istekte eski sonucun gizlenmesi, senaryo kaydı ve gerçekten sonuç
  üreten suggestor akışı. Streamlit AppTest kullanılır; tarayıcı piksel testi değildir.
- Kişisel snapshot mevcutsa dört ligde yükleme ve 14/14/16/12 satırlı ROS rank
  görünümü; kişisel dosyalar yoksa bu iki gerçek veri testi skip edilir.

Ayrıca dört gerçek ligde lig başına 200 paketlik sınırlı uçtan uca denemede
sırasıyla 4, 7, 9 ve 13 öneri bulundu; seçilen sonuçların iki taraflı metrikleri
ve JSON export'u denetlendi. Bu sayılar belirli snapshot/eşiklerle yapılan smoke
denemesidir; gelecekte aynı sayıda öneri vaadi değildir. Yerel Streamlit sağlık
endpoint'i HTTP 200 döndü. Python derleme ve Git whitespace kontrolleri geçti.

Testlerin geçmesi, olasılıkların gerçek sonuçlara karşı kalibre edildiğini veya
insanların önerileri kabul edeceğini kanıtlamaz. `slow` işaretli iki test geniş
komutta özellikle çalıştırılmaz.

## 8. Bilinen sınırlar ve devam işi

1. **Takvim/lineup:** Ortalama kullanım oranı var; gerçek haftalık H2H takvimi,
   günlük lineup, B2B, maç çakışması, playoff haftası ve IL dönüş zamanı simüle edilmez.
   Bütün takımlara aynı kullanım varsayımı uygulanması takım yapılarına göre yanlı olabilir.
2. **Olasılık modeli:** Normal yaklaşım, tarihsel varyans ve oyuncular arası
   bağımsızlık; P(5+) için ek kategori bağımsızlığı. Backtest/kalibrasyon yapılmadı.
3. **Kaynak eksikleri:** Preseason tam kapsamlı değil; ROS'ta üç kadrolu oyuncu
   modellenemiyor. Kaynak toplamları ve model sonuçları kısmi olabilir. Kullanıcı
   kararı gereği ham hatalar düzeltilmedi ve eksik fikstürler toplanmadı.
4. **Piyasa/kabul:** Replacement-relative z-score paket dengesi, gerçek işlem
   fiyatı değildir. Menajer davranışı, kabul ve komisyon kararı için öğrenilmiş model yok.
5. **Arama kapsamı:** Kısa liste ve bütçe nedeniyle global optimum garantisi
   yoktur. Öneri filtresi ROS faydasına dayanır; preseason/current rank'leri ayrıntıda
   gösterilir, üç kaynak birleştirilip tek optimizasyon skoru yapılmaz.
6. **İşlem uygulanabilirliği:** Waiver, Can't Cut, kalan alım hakkı, güncel IL
   uygunluğu ve inceleme sırasında lig takviminin değişmesi otomatik doğrulanmıyor.
7. **Veri yaşam döngüsü:** Manuel snapshot dosyaları var; düzenleme/import sihirbazı,
   snapshot arşivi ve kalıcı senaryo deposu yok. `as_of` roster tarihinden gelir;
   farklı tarihlerde güncellenmiş dosyaların uyumunu operatör sağlamalıdır.
8. **Format:** Mevcut H2H dokuz kategori ve Yahoo şeması hedefleniyor. Points,
   roto veya farklı kategori setleri için ayrıca çalışma gerekir. Kadro dışı
   oyuncuların takım/durum metadatası eski master'dan geliyorsa güncelliği sınırlı olabilir.

Devam için öncelik sırası: (a) snapshot tarih/kapsam doğrulaması ve manuel import
akışı, (b) gerçek haftalık lineup/maç sayısı modeli, (c) geçmiş sonuçlarla
olasılık backtest'i, (d) kalıcı senaryo ve strateji profilleri. Bunlar bu teslimin
parçası olarak tamamlanmış özellikler değildir.

## 9. Claude için önerilen inceleme yolu

Önce `data.py` ve bu belgenin veri sözleşmesini, sonra `engine.py` içindeki
`_weekly_vectors`, `view`, `resolve`, `score`, `analyze` akışını oku. Ardından
`suggest.py` filtre/sıralamasını, `report.py` çıktısını ve UI/testleri incele.

Özellikle şu ayrımları koru: kaynaklar ayrı; oranlar hacim ağırlıklı; TO yönü
ters; iki tarafın kadrosu birlikte değişiyor; punt olasılığı değiştirmiyor;
ROS GP/82 kullanılmıyor; auto-fill önceden boş slotu doldurmuyor; eksik oyuncu
değersiz sayılmıyor; kabul puanı kalibre olasılık olarak sunulmuyor.
Kullanıcının açık tercihi olmadan ham player verisini düzeltme veya diğer
takımların H2H fikstürlerini tamamlamayı ön koşul haline getirme.

## 10. Git teslim yapısı

Değişiklikler üç mantıksal commit olarak hazırlanır:

1. **Trade çekirdeği:** veri katmanı, stratejiler, engine, öneri araması,
   rapor/export API'si, CLI ve unit testleri; proje açıklaması.
2. **Trade arayüzü:** varsayılan navigasyon, üç rank menüsü, analiz/öneri/veri
   ekranları, UI entegrasyon testleri ve eski smoke test uyarlaması.
3. **Dokümantasyon ve yerel veri sınırı:** bu rapor, README ve kişisel Yahoo
   export'larını yerelde tutan ignore kuralları.

Commitler tek `git push` ile `origin/main` dalına gönderilir. Nihai commit
kimlikleri teslim mesajında verilir; raporun kendi commit hash'ini içine yazıp
öz referans oluşturmak yerine Git geçmişi kaynak kabul edilir.
