# GÖREV-11: Otomatik Dinamik Sezon + 5 Güvenilir Kaynaklı Çoklu Veri Füzyonu (Multi-Source Cross-Validation)

## 1. Amaç ve Kapsam
Bu görevin amacı; sistemin tek bir kaynağa (Transfermarkt) ve sabit bir sezon stringine (`"2026-2027"`) bağımlılığını tamamen ortadan kaldırmak:
1. **Otomatik Dinamik Sezon:** Her yıl Temmuz ayında otomatik olarak yeni sezona (`YIL-(YIL+1)`) geçen, elle müdahale gerektirmeyen dinamik sezon motoru kurmak.
2. **5 Bağımsız Güvenilir Kaynaklı Veri Füzyonu:** Fikstür, skor, şut, isabetli şut, xG (beklenen gol) ve sakatlık/ceza verilerini en az **5 farklı kamuya açık güvenilir kaynaktan** çekip çapraz doğrulayan (Multi-Source Consensus) modüler bir veri füzyon katmanı oluşturmak.
3. **Gelişmiş Tahmin, İlk Yarı / Maç Sonucu (İY/MS) & Karşılaştırmalı Durum Değerlendirmesi:**
   - Sadece atılan/yenilen gole değil; **xG/xGA, maç başı isabetli şut, şut baskısı, ilk yarı/ikinci yarı tempo dağılımı ve çift kaynak onaylı sakatlıklara** dayanan model kurmak.
   - Her maç için hem **İlk Yarı (İY) skoru** hem **Maç Sonucu (MS) skoru** hem de **İY/MS (1/1, X/1, X/X, 2/2 vb.)** olasılık dağılımını (`FT_home >= HT_home` ve `FT_away >= HT_away` matematiksel tutarlılığıyla) hesaplamak.
   - 5 kaynaktan toplanan tüm verileri birbirleriyle karşılaştırıp sentezleyen, **"Neden bu İlk Yarı ve Maç Sonucu çıktı?"** sorusunu somut kanıtlarla açıklayan kapsamlı bir durum değerlendirmesi üretmek.
4. **Şeffaf Mobil Arayüz & Canlı Bulut Güncellemesi:** Ekranda `X/5 Kaynak Doğruladı` bilgisini, **İY/MS skor & olasılık kartını** ve **Kapsamlı Durum Değerlendirmesi** bölümünü göstermek; GitHub Actions iş akışını yeni 5 kaynaklı motorla canlıya alıp final Release APK'yı telefona kurmak.

---

## 2. Teknik Şartname ve Alt Ajan (Subagent) Görev Dağılımı

### A. Ön Aşama: Mimari Analiz (`graphify`)
- `graphify-out/` üzerinden `engine/config.py`, `engine/scrapers/pipeline.py`, `engine/predictors/ratings.py`, `engine/predictors/analyst.py` ve `engine/bulletin.py` bağımlılıklarını sorgula.

### B. Alt Ajan Delegasyonu (Subagents)

#### 🤖 Alt Ajan 1: Dinamik Sezon & 5 Kaynaklı Veri Füzyon Uzmanı (Backend/Data Subagent)
- **Hedef Dosyalar:** `engine/config.py`, `engine/scrapers/sources/` (yeni alt paket), `engine/scrapers/fusion.py`, `.github/workflows/update_bulletin.yml`
- **Yapılacaklar:**
  1. **Dinamik Sezon (`engine/config.py`):**
     - `get_current_season(today: date | None = None) -> str` fonksiyonunu yaz: `month >= 7` ise `f"{year}-{year + 1}"`, `month < 7` ise `f"{year - 1}-{year}"`.
     - `get_season_start_year()` ve `get_football_data_season_code()` (örn: `"2627"`) yardımcılarını ekle.
     - `DEFAULT_SEASON` ortam değişkeni açıkça verilmedikçe her zaman dinamik sezon kullan; `.github/workflows/update_bulletin.yml` ve `HF_DEPLOY.md` içindeki sabit `DEFAULT_SEASON: "2026-2027"` satırlarını kaldır.
  2. **5 Bağımsız Güvenilir Kaynak Adaptörü (`engine/scrapers/sources/`):**
     Her adaptör canlı HTTP 200 testiyle doğrulanmalı, hata/zaman aşımında diğer kaynakları asla bloke etmemelidir:
     - **Kaynak 1 — ESPN Public API (`espn.py`):** `site.api.espn.com/apis/site/v2/sports/soccer/{tur.1|eng.1|esp.1|fra.1}/scoreboard` ve `/standings` (4 ligin canlı fikstür, skor ve puan durumu doğrulaması).
     - **Kaynak 2 — Football-Data.co.uk (`football_data.py`):** `football-data.co.uk/mmz4281/{YYZZ}/{T1|E0|SP1|F1}.csv` (4 ligin tamamı için maç bazlı **ilk yarı skorları `HTHG/HTAG/HTR`**, şut `HS/AS`, isabetli şut `HST/AST`, korner `HC/AC`, kart ve piyasa olasılık dengesi).
     - **Kaynak 3 — Understat (`understat.py`):** `understat.com/league/{EPL|La_liga|Ligue_1}/{START_YEAR}` (EPL, La Liga, Ligue 1 gerçek `xG / xGA`; Süper Lig için Football-Data isabetli şut verisinden türetilmiş xG desteği).
     - **Kaynak 4 — Transfermarkt (`injuries.py` & `fixtures.py`):** Mevcut çalışan fikstür ve sakatlık/ceza kazıyıcısı.
     - **Kaynak 5 — İkinci Sakatlık/Fikstür Çapraz Doğrulama Kaynağı (`secondary_check.py`):** Canlı HTTP 200 veren bağımsız 5. kaynak (öncelik sırası: **SportsGambler** sakatlık sayfaları veya **TheSportsDB** `thesportsdb.com/api/v1/json/3/...` / **OpenFootball**; hangisi canlı ortamda bloklanmadan HTTP 200 temiz veri dönüyorsa aktif 5. kaynak olarak entegre edilir ve raporda belgelenir).
  3. **Çoklu Kaynak Füzyon & Takım Eşleyici (`engine/scrapers/fusion.py`):**
     - `TeamAliasResolver`: 5 kaynaktaki farklı takım yazılımlarını (örn. `"Fenerbahçe SK"`, `"Fenerbahce"`, `"PSG"`, `"Paris Saint-Germain"`, `"Man City"`, `"Manchester City"`) tekil kanonik kulübe eşler.
     - **Çapraz Sakatlık Doğrulaması:** 2 farklı kaynakta birden görünen sakat/cezalı oyuncular `verified_by_multiple_sources = True` (çift kaynak onaylı) olarak işaretlenir.
     - **Bülten Metadatası (`engine/bulletin.py`):** Kök JSON ve lig bloklarına `sources_used: list[str]`, `sources_count: int`, `sources_total: 5`, `source_diagnostics: dict[str, dict]` alanlarını ekle.

#### 🤖 Alt Ajan 2: xG/Şut + İlk Yarı/Maç Sonucu (İY/MS) Tahmin & Karşılaştırmalı Değerlendirme Uzmanı (ML/Analytics Subagent)
- **Hedef Dosyalar:** `engine/predictors/ratings.py`, `engine/predictors/poisson.py`, `engine/predictors/analyst.py`, `engine/predictors/service.py`, `engine/models/schemas.py`, `engine/bulletin.py`
- **Yapılacaklar:**
  1. **Çoklu Metrik Reyting & İlk Yarı/İkinci Yarı Tempo Profili (`ratings.py`):**
     - Takım hücum/savunma katsayılarını hesaplarken gerçek gol performansını (`%65`) + Understat `xG/xGA` veya Football-Data isabetli şut (`HST/AST`) baskısını (`%35`) harmanla.
     - Football-Data `HTHG/HTAG` verisinden her takımın **ilk yarı gol üretme/yeme payını** (`first_half_attack_share`, `first_half_concede_share`; veri eksikse futbol ortalaması `%43` ilk yarı / `%57` ikinci yarı) hesapla.
     - Çift kaynak onaylı sakatlıklar tam ağırlıkla (`1.0x`), yalnızca tek kaynakta görünen ve dönüş tarihi geçmiş/belirsiz kayıtlar hafifletilmiş güven ağırlığıyla (`0.75x`) modele girsin.
  2. **İlk Yarı / Maç Sonucu (İY/MS — HT/FT) Olasılık Modeli (`poisson.py` & `schemas.py`):**
     - İlk yarı beklenen golleri ($\lambda_{\text{HT}}, \mu_{\text{HT}}$) ve ikinci yarı beklenen golleri ($\lambda_{\text{2H}}, \mu_{\text{2H}}$) üzerinden iki aşamalı dağılımla:
       - `predicted_ht_home_score`, `predicted_ht_away_score` (İlk Yarı skoru),
       - `predicted_home_score`, `predicted_away_score` (Maç Sonucu skoru; **garantili olarak `FT_home >= HT_home` ve `FT_away >= HT_away`**),
       - `ht_ft_prediction` (en olası İY/MS kodu, örn. `"1/1"`, `"X/1"`, `"X/X"`),
       - `top_ht_ft_json` (en olası ilk 3 İY/MS senaryosu ve olasılıkları, örn. `[{"code": "1/1", "label": "Ev / Ev", "prob": 0.342}, ...]`) üret ve `bulletin.json` şemasına ekle.
  3. **Kapsamlı Karşılaştırmalı Durum Değerlendirmesi & "Neden Böyle Oldu?" Raporu (`analyst.py`):**
     - 5 kaynaktan toplanan **tüm verileri birbirleriyle karşılaştırıp sentezleyen** kapsamlı değerlendirme üret:
       - Puan durumu/form karşılaştırması + iç/dış saha gol ve ilk yarı/ikinci yarı tempo farkı + xG/xGA + şut/isabetli şut + korner baskısı + çift kaynak onaylı sakatlıkların taktiksel dengesi.
       - **`ht_ft_reasoning_text` (veya `match_overview_text` içinde net bölüm):** *"Neden İlk Yarı X-Y ve Maç Sonucu A-B (İY/MS: ...)? Tüm veriler karşılaştırıldığında..."* şeklinde ilk 45 dakika ile ikinci 45 dakikanın nasıl gelişeceğini somut veri karşılaştırmasıyla açıklasın.

#### 🤖 Alt Ajan 3: Mobil Arayüz, Bulut Güncellemesi & QA Uzmanı (Mobile/QA Subagent)
- **Hedef Dosyalar:** `mobile/lib/services/bulletin_api_service.dart`, `mobile/lib/widgets/data_transparency_banner.dart` (veya `home_screen.dart` / `match_detail_screen.dart`), `mobile/lib/widgets/injuries_list.dart`, `engine/tests/`, `mobile/test/widget_test.dart`
- **Yapılacaklar:**
  1. **Çoklu Kaynak Şeffaflık Bandı & İY/MS Kartları (Mobil):**
     - `DataTransparencyBanner` içinde artık tek site değil, aktif kaynak sayacı ve isimleri gösterilsin: örn. `5/5 Kaynak Doğruladı • ESPN, Football-Data, Understat, Transfermarkt, ... • Sezon: 2026-2027`.
     - `MatchCard` üzerinde ana skorun yanında kompakt **İY/MS rozeti** (örn: `İY 1-0 • İY/MS: 1/1`) gösterilsin.
     - `MatchDetailScreen` Hero kartında **İlk Yarı (`İY X - Y`)** ve **Maç Sonucu (`MS A - B`)**, altında **En Olası 3 İY/MS Olasılığı** çubukları ve **"Kapsamlı Durum Değerlendirmesi & Neden Bu İY/MS?"** analiz kartı yer alsın.
     - Sakatlık kartlarında çift kaynak onaylı oyunculara küçük bir `✓ Onaylı` rozeti ekle (360x800 dar ekranda taşmasız).
  2. **Testler & Doğrulama:**
     - Dinamik sezon testi (Haziran -> önceki sezon, Temmuz -> yeni sezon), 5 kaynak adaptör birim + canlı smoke testleri, `python -m unittest discover -s engine/tests -v` (0 hata).
     - `PUB_CACHE="E:\Users\nazif_acikgoz\AppData\Local\Pub\Cache"` ile `flutter analyze` (0 sorun) ve `flutter test` (tüm testler yeşil).
  3. **Canlı Bulut & Telefon Güncellemesi:**
     - Yeni kodu `naziffarm4/futbol-skor-analiz` reposuna `git push` et, `gh workflow run update_bulletin.yml` ile GitHub Actions üzerinde 5 kaynaklı canlı bülteni üretip `https://naziffarm4.github.io/futbol-skor-analiz/bulletin.json` üzerinde doğrulama yap.
     - Final Release APK'yı (`--dart-define=API_URL=https://naziffarm4.github.io/futbol-skor-analiz/bulletin.json`) yeniden derle ve bağlı telefona (`adb install -r`) yükleyip 0 hatayla açıldığını kanıtla.

### C. Kapanış (`graphify --update`)
- `/graphify --update` ile bilgi grafiğini güncelle ve 5 kaynağın canlı HTTP durum tablosu + yeni xG/şut destekli 2 gerçek maç analiz örneği ile birlikte tüm kanıtları `tasks/GOREV-11-RAPOR.md` dosyasına kaydet.

---

## 3. Doğrulama Kriteri
1. `get_current_season(date(2027, 6, 30)) == "2026-2027"` ve `get_current_season(date(2027, 7, 1)) == "2027-2028"` birim testiyle kanıtlanmalı; kodda sabit `"2026-2027"` kalmamalı.
2. En az **5 bağımsız kaynak** canlı test edilip `bulletin.json` içinde `sources_used` ve `sources_count` olarak görünmeli.
3. Python testleri + `flutter analyze` + `flutter test` sıfır hatayla geçmeli.
4. Canlı `https://naziffarm4.github.io/futbol-skor-analiz/bulletin.json` yeni 5 kaynaklı şemayla HTTP 200 dönmeli ve telefonda güncellenmiş Release APK hatasız açılmalı.
