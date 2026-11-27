# GÖREV-02 Teknik Uygulama ve Doğrulama Raporu

**Görev:** Kamuya Açık Veri Toplama Motoru (Scrapers & Ingestion Pipeline)  
**Tarih:** 2026-11-25  
**Durum:** Tamamlandı ve Doğrulandı (`14/14` test başarılı)

---

## 1. Oluşturulan ve Güncellenen Dosya Yapısı

`tasks/GOREV-02-VERI-TOPLAMA-MOTORU.md` şartnamesine uygun olarak aşağıdaki modüller eklendi ve güncellendi:

```text
e:\apk\futbol\
├── tasks\
│   ├── GOREV-02-VERI-TOPLAMA-MOTORU.md
│   └── GOREV-02-RAPOR.md
└── engine\
    ├── requirements.txt             (güncellendi: beautifulsoup4, lxml)
    ├── scrapers\
    │   ├── __init__.py
    │   ├── base.py
    │   ├── injuries.py
    │   ├── fixtures.py
    │   └── pipeline.py
    └── tests\
        ├── __init__.py
        ├── test_foundation.py
        └── test_scrapers.py
```

---

## 2. Teknik Uygulama Detayları

### 2.1. Temel HTTP ve Ayrıştırma İstemcisi (`engine/scrapers/base.py`)
- **Tarayıcı Başlıkları (`build_browser_headers`):** Masaüstü Chrome/Firefox `User-Agent` havuzu, `Accept`, `Accept-Language`, `Referer`, `DNT` ve `Upgrade-Insecure-Requests` başlıklarıyla bot korumalarına uyumlu istemci yapılandırıldı.
- **Nazik Kazıma / Rate-Limiting (`BaseScraper`):** Ardışık istekler arasında yapılandırılabilir `1.0–2.0` saniye rastgele gecikme (`min_delay`, `max_delay`) uygulandı.
- **Yeniden Deneme ve Backoff:** `httpx.HTTPError` ağ/zaman aşımı hatalarında ve `429, 500, 502, 503, 504` HTTP yanıtlarında üstel geri çekilme (`exponential backoff + jitter`) ve `Retry-After` başlığı desteği eklendi.
- **Güvenli HTML Ayrıştırma:** `parse_html()` öncelikle `lxml`, bulunamazsa `html.parser` geri dönüşü ile çalışacak şekilde yazıldı; `clean_text()` ve `normalize_team_name()` ile boşluk ve sıra rozeti (`(1.)`) temizliği sağlandı.

### 2.2. Sakatlık ve Ceza Ayrıştırıcısı (`engine/scrapers/injuries.py`)
- **4 Lig Rotaları (`TRANSFERMARKT_LEAGUES`):**
  - Süper Lig: `TR1` (`/super-lig/sperrenundverletzungen/wettbewerb/TR1`)
  - Premier League: `GB1` (`/premier-league/sperrenundverletzungen/wettbewerb/GB1`)
  - La Liga: `ES1` (`/laliga/sperrenundverletzungen/wettbewerb/ES1`)
  - Ligue 1: `FR1` (`/ligue-1/sperrenundverletzungen/wettbewerb/FR1`)
- **Otomatik Uç Nokta Geçişi ve Sayfalama:** Birleşik `/sperrenundverletzungen/` yolu canlı Transfermarkt üzerinde müsabaka bazında `404` döndürdüğünde otomatik olarak `/verletztespieler/wettbewerb/{CODE}` ve `/sperrenausfaelle/wettbewerb/{CODE}` uç noktalarına geçip `ul.tm-pagination` sayfalarını tarayan ve `(takım, oyuncu, neden)` anahtarıyla tekilleştiren akış kuruldu.
- **Mevki Eşlemesi (`map_player_position`):** Türkçe, İngilizce ve Almanca mevki adları (`Kaleci` -> `GK`, `Stoper/Bek` -> `DEF`, `Ön Libero/Orta Saha/On Numara` -> `MID`, `Santrafor/Kanat/Forvet` -> `FW`) `PlayerPosition` enum'una eşlendi.
- **Tarih ve Etki Derecesi (`parse_return_date`, `calculate_impact_level`):**
  - Türkçe kısa ay (`27 Kas 2026`), noktalı (`02.12.2026`) ve ISO (`2026-12-15`) tarihleri `datetime.date` tipine dönüştürüldü; `?` ve belirsiz değerler `None` yapıldı.
  - 75+ gün süreli sakatlıklar, ameliyat/çapraz bağ/kırık/yırtık/kırmızı kart veya 4+ maç cezaları `HIGH`; şüpheli/soğuk algınlığı/hafif ağrı ve 7 gün altı ufak sakatlıklar `LOW`; sarı kart cezaları ve orta vadeli kas/eklem sakatlıkları `MEDIUM` olarak sınıflandırıldı.

### 2.3. Fikstür ve Takım Ayrıştırıcısı (`engine/scrapers/fixtures.py`)
- **Genel ve Haftalık Fikstür (`parse_fixtures_html`, `FixturesScraper`):** `div.box` hafta bloklarından hafta numarası (`round`), UTC zaman damgalı `match_date`, kulüp tam adı (`a[title]`), kısa adı (`short_name`) ve kulüp logosu (`data-src`/`src`) çıkarıldı.
- **Tarih/Saat Devretme (`Carry-Over`):** Transfermarkt'ın aynı gün veya saatte oynanan ardışık maç satırlarında tarih/saat hücrelerini boş bırakması durumu satırlar arası durum aktarımı ile çözüldü.
- **Skor ve Durum Ayrımı (`parse_score_and_status`):** Gerçek maç skorları (`FINISHED`), ön rapor ve saat görünümlü hücreler (`SCHEDULED`, örn. `-:-` veya `vorbericht` içindeki `21:30`) ve ertelenen maçlar (`POSTPONED`, örn. `ert.`) birbirinden ayrıldı; `LeagueFixturesData` üzerinde `played_matches`, `next_round` ve `next_round_matches` yardımcıları sunuldu.

### 2.4. Veri Toplama Orkestratörü (`engine/scrapers/pipeline.py`)
- `IngestionPipeline` ve `run_ingestion_pipeline()` ile tek lig veya 4 ligin tamamı için sırasıyla fikstür/takım ve sakatlık/ceza verileri çekilip `League`, `Team`, `Match` ve `Injury` Pydantic v2 modellerine dönüştürüldü.
- **Supabase & Yerel Geri Dönüş Modu:**
  - Supabase yapılandırılmışsa `leagues` (`on_conflict="id"`), `teams` (`on_conflict="league_id,name"`) ve `matches` (`on_conflict="league_id,round,home_team_id,away_team_id"`) tablolarına `upsert` yapılır; `injuries` tablosunda ise ilgili lig takımlarının güncel sakatlık anlık görüntüsü yenilenir.
  - Supabase yapılandırılmamışsa (`DatabaseConfigError`) veya `persist=False` ise deterministik yerel `team_id` atanarak doğrulanmış modeller ve `to_dict()` / `to_json()` çıktıları döndürülür.

---

## 3. Karşılaşılan Hatalar / Engeller ve Çözümler

1. **`bs4` Paket Eksikliği (`ModuleNotFoundError: No module named 'bs4'`):**
   - **Sebep:** Ortamda `beautifulsoup4` kurulu değildi.
   - **Çözüm:** `engine/requirements.txt` dosyasına `beautifulsoup4>=4.12.0` ve `lxml>=5.3.0` eklenip `python -m pip install -r engine/requirements.txt` ile kuruldu (`beautifulsoup4==4.15.0`, `lxml==6.1.3`).
2. **Canlı Transfermarkt `/sperrenundverletzungen/wettbewerb/{CODE}` 404 Yanıtı:**
   - **Sebep:** Transfermarkt müsabaka düzeyinde sakatlık ve cezaları `/verletztespieler/wettbewerb/{CODE}` ve `/sperrenausfaelle/wettbewerb/{CODE}` olarak iki ayrı uç noktada sunmaktadır.
   - **Çözüm:** Şartnamedeki birleşik yol korundu ve `404` alındığında otomatik olarak iki ayrık uç noktaya geçip önbelleğe alan (`_use_split_endpoints`) mekanizma eklendi.
3. **Fikstür Tablosunda Boş Tarih/Saat Hücreleri ve Saat/Skor Çakışması:**
   - **Sebep:** Ardışık aynı gün/saat maçlarında hücrelerin boş bırakılması ve `vorbericht` bağlantılarında başlama saatinin (`21:30`) skor formatına (`\d+:\d+`) benzemesi.
   - **Çözüm:** Hafta kutusu bazında tarih/saat devretme (`carry-over`) ve `vorbericht`/dakika deseni kontrolü eklendi.
4. **Kök Dizinden `python -m unittest` Çağrısında `NO TESTS RAN` Hatası:**
   - **Sebep:** `engine/tests/` dizininde `__init__.py` bulunmadığı için `unittest` paket keşfinin alt dizine inmemesi.
   - **Çözüm:** `engine/tests/__init__.py` eklenerek doğrudan `python -m unittest` çağrısının tüm testleri otomatik keşfetmesi sağlandı.

---

## 4. Doğrulama ve Test Sonuçları

- **Statik Derleme (`py_compile`):** Tüm modüller sıfır sözdizimi hatası ile derlendi.
- **Birim ve Entegrasyon Testleri (`python -m unittest -v` -> `14/14 OK`):**
  - `BaseScraperTests` (3 test): Tarayıcı başlıkları, `429 Retry-After` + `ConnectTimeout` retry/backoff, rate-limit bekleme hesabı ve `404` hızlı hata doğrulandı.
  - `InjuriesScraperTests` (3 test): 4 lig URL kodları (`TR1`, `GB1`, `ES1`, `FR1`), mevki/tarih/`ImpactLevel` mantığı, mock HTML ayrıştırma, 404 ayrık uç nokta geçişi ve sayfalama doğrulandı.
  - `FixturesScraperTests` (1 test): Oynanmış skorlar, tarih/saat devretme, ön rapor `SCHEDULED` ayrımı, ertelenen maçlar (`POSTPONED`) ve sıradaki hafta tespiti doğrulandı.
  - `PipelineTests` (2 test): Yerel JSON geri dönüşü, `engine/db/schema.sql` kolon uyumu ve mock Supabase `upsert/delete/insert` akışı doğrulandı.
  - `LiveSmokeTests` (1 test) + Canlı Süper Lig Özet Kontrolü: Canlı Transfermarkt üzerinden `18` takım, `306` maç (`108 FINISHED`, `198 SCHEDULED`) ve `70` sakatlık/ceza kaydı (`32 HIGH`, `28 MEDIUM`, `10 LOW`) eksiksiz çekilip Pydantic modellerinde doğrulandı.
