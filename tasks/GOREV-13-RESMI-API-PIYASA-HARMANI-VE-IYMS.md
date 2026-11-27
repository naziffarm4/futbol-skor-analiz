# GÖREV-13 (Faz 2): Resmi Ücretsiz API Omurgası (API-Football + The Odds API), Zaman Sönümü, Piyasa Harmanı ve Tam Yüzdelik İY/MS Olasılık Motoru

## 1. Amaç ve Kapsam
1. **Güvenli Anahtar & Resmi Ücretsiz API Geçişi:**
   - `API_FOOTBALL_KEY` (`v3.football.api-sports.io`) ve `THE_ODDS_API_KEY` (`api.the-odds-api.com`) anahtarlarını yalnızca yerel `.env` (git dışı) ve GitHub Repository Secrets üzerinden yönetmek (**hiçbir takip edilen dosyaya, rapora veya loga açık anahtar yazılmayacaktır!**).
   - **Faz 0 Doğrulama:** Minimum istek harcayarak (2–4 çağrı) Süper Lig (`league=203`) güncel sezon fikstürü, sakatlıkları ve The Odds API (`soccer_turkey_super_league`) 1X2/Alt-Üst oranlarının ücretsiz planda döndüğünü doğrulayıp `docs/veri-kaynaklari.md` dosyasına kaydetmek.
   - **Kota Planlayıcısı (`QuotaBudgetTracker`):** API-Football günde 100 istek ve The Odds API aylık kredi limitini önbellekleme + kalan kota başlığı (`x-ratelimit-requests-remaining`, `x-requests-remaining`) ile korumak.
   - `engine/scrapers/base.py` içindeki bot koruması aşma kodunu (Playwright otomasyon bayrağı gizleme, WAF token bekleme) tamamen kaldırmak.
   - **Kendi Veri Arşivimiz (`engine/archive.py`):** Her çalışmada piyasa oranları, sakatlık özeti ve model tahminlerini tarih damgalı küçük JSONL/JSON anlık görüntüsü (`data/snapshots/`) olarak kaydetmek.
2. **Backtest Kanıtlı Model İyileştirmeleri (M2 + M5 + Tam Yüzdelik İY/MS):**
   - **Üstel Zaman Sönümü (`time-decay`):** Oynanmış maçlara `w = exp(-ξ * Δgün)` ağırlığı ekle; `ξ` değerini 2.845 maçlık walk-forward backtestte doğrula.
   - **Piyasa Olasılığı Harmanı (`market blend`):** Poisson 1X2/Üst 2.5 olasılıklarını marjı temizlenmiş piyasa olasılıklarıyla (canlı: The Odds API, tarihsel: Football-Data CSV) harmanla; harman ağırlığını walk-forward backtestte **RPS / Brier / Log-Loss** ile ölç ve yalnızca iyileşme kanıtlanırsa aktif et (`reports/backtest_v2.md`).
   - **Tam Yüzdelik İlk Yarı / Maç Sonucu (İY/MS) + 1X2 / Üst 2.5 / KG Var-Yok Olasılıkları:**
     - Tüm **9 İY/MS senaryosunun (`1/1`, `X/1`, `2/1`, `1/X`, `X/X`, `2/X`, `1/2`, `X/2`, `2/2`)** yüzdelik olasılıklarını (`all_ht_ft_json`, toplamı tam `1.0000` / `%100.0`, azalan sırayla) üret.
     - Piyasa harmanı aktifse İY/MS marjinallerini harmanlanmış 1X2 olasılıklarıyla tutarlı (`sum(İY/MS where MS == 1) == p_home` vb.) şekilde ölçekle.
     - `p_home`, `p_draw`, `p_away`, `p_over25`, `p_under25`, `p_btts_yes`, `p_btts_no` olasılıklarını bülten JSON'una açıkça ekle.
3. **Mobil Uygulama — Yüzdelik İY/MS Olasılık Arayüzü & Çevrimdışı Önbellek (`mobile/`):**
   - **MatchCard:** Ana skorun yanında kompakt **1 / X / 2 yüzdeleri** ve **En Olası İY/MS yüzdesi** (örn: `İY/MS 1/1 %36 • 1:%54 X:%25 2:%21`).
   - **MatchDetailScreen:**
     - **Olasılık Özeti Paneli:** `1 / X / 2` yatay yüzdelik barı + `2.5 Üst / Alt` + `KG Var / Yok` yüzdeleri.
     - **İlk Yarı / Maç Sonucu (İY/MS) Tam Yüzdelik Dağılımı:** En olası 3 İY/MS çubuğu + **9 senaryonun tamamını (`1/1`..`2/2`) yüzdelik olarak gösteren kompakt 3×3 matris/tablo**.
     - Mevcut taktiksel analiz kartları korunur ve piyasa/form sönümü bulgularıyla zenginleştirilir.
   - **Çevrimdışı Önbellek:** Son başarılı `bulletin.json` cihazda yerel depolamaya kaydedilir; internet yoksa boş ekran yerine son önbellek *"Çevrimdışı Önbellek • Son güncelleme: ..."* bandıyla açılır.

---

## 2. Teknik Şartname ve Alt Ajan (Subagent) Görev Dağılımı

### A. Ön Aşama (`graphify` + Güvenlik)
- `graphify-out/` üzerinden `engine/scrapers/base.py`, `engine/scrapers/fusion.py`, `engine/predictors/ratings.py`, `engine/predictors/poisson.py`, `engine/backtest/` ve `mobile/lib/screens/match_detail_screen.dart` ilişkilerini sorgula.
- `.env` dosyasının `.gitignore` kapsamında olduğunu ve hiçbir gerçek anahtarın git ile takip edilmeyeceğini doğrula.

### B. Alt Ajan Delegasyonu (Subagents)

#### 🤖 Alt Ajan 1: Resmi API Adaptörleri, Kota Planlayıcı, Arşiv & Temizlik (Backend/Data Subagent)
- **Hedef Dosyalar:** `engine/config.py`, `.env.example`, `engine/scrapers/base.py`, `engine/scrapers/sources/api_football.py`, `engine/scrapers/sources/the_odds_api.py`, `engine/scrapers/fusion.py`, `engine/archive.py`, `docs/veri-kaynaklari.md`, `.github/workflows/update_bulletin.yml`
- **Yapılacaklar:**
  1. `.env.example` ve `engine/config.py` içine `API_FOOTBALL_KEY` ve `THE_ODDS_API_KEY` ayarlarını ekle.
  2. `engine/scrapers/sources/api_football.py`: `v3.football.api-sports.io` adaptörü (Süper Lig=`203`, Premier League=`39`, La Liga=`140`, Ligue 1=`61`), `QuotaBudgetTracker` (kalan kota başlığı izleme + önbellek + eşik `<15` koruması).
  3. `engine/scrapers/sources/the_odds_api.py`: `api.the-odds-api.com/v4` adaptörü (`soccer_turkey_super_league`, `soccer_epl`, `soccer_spain_la_liga`, `soccer_france_ligue_1`), `h2h` + `totals` marjı temizlenmiş (de-vigged) piyasa olasılıkları + kalan kredi takibi.
  4. **Faz 0 Canlı Doğrulama:** Minimum çağrıyla (2–4 istek) Süper Lig fikstür/sakatlık/oran erişimini test et; kaynak limitlerini, şartlarını ve maskeli test sonuçlarını `docs/veri-kaynaklari.md` dosyasına yaz.
  5. `engine/scrapers/base.py` içindeki Playwright otomasyon gizleme (`AutomationControlled`) ve AWS WAF token bekleme kodunu kaldır.
  6. `engine/archive.py`: Her çalışmada `data/snapshots/` altına tarih damgalı piyasa/sakatlık/tahmin özeti kaydet.
  7. `.github/workflows/update_bulletin.yml` içine `API_FOOTBALL_KEY: ${{ secrets.API_FOOTBALL_KEY }}` ve `THE_ODDS_API_KEY: ${{ secrets.THE_ODDS_API_KEY }}` bağla.

#### 🤖 Alt Ajan 2: Zaman Sönümü, Piyasa Harmanı & Tam Yüzdelik İY/MS Modeli (Quant/ML Subagent)
- **Hedef Dosyalar:** `engine/predictors/ratings.py`, `engine/predictors/poisson.py`, `engine/predictors/analyst.py`, `engine/predictors/service.py`, `engine/models/schemas.py`, `engine/bulletin.py`, `engine/backtest/`, `reports/backtest_v2.md`
- **Yapılacaklar:**
  1. `ratings.py`: Oynanmış maçlarda üstel zaman sönümü (`exp(-ξ * Δgün)`) ekle.
  2. `poisson.py` & `schemas.py`:
     - Tüm **9 İY/MS olasılığını (`all_ht_ft_json`, toplamı tam `1.0`)**, `p_home`, `p_draw`, `p_away`, `p_over25`, `p_under25`, `p_btts_yes`, `p_btts_no` alanlarını üret.
     - Marjı temizlenmiş piyasa olasılıkları (The Odds API / CSV) mevcutsa optimal ağırlıkla (`α`) 1X2 ve Üst 2.5 olasılıklarını harmanla; 9 İY/MS olasılığını harmanlanmış 1X2 marjinalleriyle tutarlı olacak şekilde yeniden ölçekle (`sum(İY/MS | MS=1) == p_home` vb.).
  3. `engine/backtest/` & `reports/backtest_v2.md`:
     - 2.845 gerçek maçta (Süper Lig `T1` ayrı raporlanacak) **Baz Post-Fix** vs **+Zaman Sönümü** vs **+Piyasa Harmanı** adım adım **RPS, Brier, Log-Loss, Üst 2.5 ve İY/MS Brier/Log-Loss** karşılaştırmasını üret. Yalnızca backtestte RPS/Log-Loss iyileşmesi kanıtlanan ağırlıkları üretim varsayılanı yap!
  4. `analyst.py`: Piyasa olasılığı vs model uyumu ve en güçlü İY/MS yüzdelik gerekçelerini doğal Türkçe analiz metnine yedir.

#### 🤖 Alt Ajan 3: Mobil Yüzdelik İY/MS Arayüzü, Çevrimdışı Önbellek, QA & Canlı Yayın (Mobile/QA Subagent)
- **Hedef Dosyalar:** `mobile/pubspec.yaml`, `mobile/lib/models/prediction_model.dart`, `mobile/lib/services/bulletin_api_service.dart`, `mobile/lib/widgets/`, `mobile/lib/screens/`, `mobile/test/widget_test.dart`
- **Yapılacaklar:**
  1. `PredictionModel`: `allHtFt` (9 senaryo), `pHome`, `pDraw`, `pAway`, `pOver25`, `pBttsYes`, `marketBlended` alanlarını ayrıştır (eski JSON ile geriye dönük uyumlu).
  2. **Olasılık & İY/MS UI:**
     - `MatchCard`: Kompakt `1 / X / 2` yüzdeleri ve en olası `İY/MS` yüzdesi.
     - `MatchDetailScreen`: `1 / X / 2` + `2.5 Üst/Alt` + `KG Var/Yok` olasılık kartı ve **9'lu İY/MS Yüzdelik Matrisi** (`1/1`, `X/1`, `2/1`, `1/X`, `X/X`, `2/X`, `1/2`, `X/2`, `2/2`) + mevcut analiz kartları. (360×800 dar ekranda 0 taşma!).
  3. **Çevrimdışı Önbellek:** `path_provider` veya `shared_preferences` (en az bağımlılıkla) kullanarak son başarılı `bulletin.json` yanıtını yerelde sakla; ağ hatasında önbellek varsa *"Çevrimdışı Önbellek"* rozetiyle göster.
  4. **Tam Doğrulama & Canlı Yayın:**
     - `mypy engine app.py` (0 hata), `ruff check engine app.py` (0 hata), `python -m unittest discover -s engine/tests -v` (0 hata).
     - `PUB_CACHE="E:\Users\nazif_acikgoz\AppData\Local\Pub\Cache"` ile `flutter analyze` (0 sorun) ve `flutter test` (tüm testler OK).
     - GitHub Secrets (`API_FOOTBALL_KEY`, `THE_ODDS_API_KEY`) tanımlandıktan sonra kodu push et, `ci.yml` ve `update_bulletin.yml` koşumlarını yeşil doğrula, canlı `bulletin.json` üzerinde 9'lu İY/MS yüzdelerini kontrol et.
     - Release APK derle (`flutter build apk --release --target-platform android-arm64`), bağlı telefona yükle (`adb install -r`) ve USB tüneli olmadan 0 logcat hatasıyla açıldığını kanıtla.

### C. Kapanış (`graphify --update`)
- `/graphify --update` çalıştır; Faz 0 API doğrulama özeti, `reports/backtest_v2.md` RPS/Brier/Log-Loss tablosu ve güvenlik kontrolü (repo içinde 0 açık API anahtarı) ile birlikte tüm kanıtları `tasks/GOREV-13-RAPOR.md` dosyasına kaydet.

---

## 3. Doğrulama Kriteri
1. **Sıfır Anahtar Sızıntısı:** `git grep` ile hiçbir takip edilen dosyada, testte veya raporda gerçek API anahtarı bulunmamalı!
2. `docs/veri-kaynaklari.md` içinde API-Football ve The Odds API canlı Faz 0 doğrulama sonuçları ve kota başlıkları belgelenmeli.
3. `reports/backtest_v2.md` içinde 4 lig + Süper Lig (`T1`) ayrı olarak Zaman Sönümü ve Piyasa Harmanı öncesi/sonrası RPS, Brier, Log-Loss ve İY/MS metrikleri kanıtlanmalı.
4. `all_ht_ft_json` 9 senaryo toplamı `1.000 ± 0.001` ve 1X2 marjinalleriyle tutarlı olmalı.
5. `mypy engine app.py` (0 hata), `ruff check engine app.py` (0 hata), `unittest` (0 hata), `flutter analyze` (0 sorun), `flutter test` (0 hata).
6. Canlı GitHub Pages `bulletin.json` + telefondaki Release APK doğrulanmalı.
