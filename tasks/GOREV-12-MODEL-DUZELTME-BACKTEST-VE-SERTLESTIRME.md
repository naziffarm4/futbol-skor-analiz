# GÖREV-12 (Faz 1): Beklenen Gol Ölçek Düzeltmesi, Walk-Forward Backtest, Güvenlik/Hijyen ve Mobil Üretim Sertleştirmesi

## 1. Amaç ve Kapsam
Harici teknik denetim raporunda ölçülerek tespit edilen en yüksek etkili **Faz 1** bulgularını tek seferde, ölçülebilir kanıtlarla ve sıfır yeni ücretli bağımlılıkla çözmek:

1. **Matematiksel Model Düzeltmesi (M1 + M6):** `poisson.py` içindeki beklenen gol ölçeği hatasını (`-%14` sistematik düşük gol ve çift sayılan iç saha avantajı) lig ortalaması çarpanıyla düzeltmek, `max_goals` sınırını `5`'ten `10`'a çıkarmak ve sentetik 20 takımlı lig testiyle ortalama $\lambda/\mu$ sapmasının `< %3` olduğunu kalıcı birim testiyle garantiye almak.
2. **Walk-Forward Backtest Altyapısı (`engine/backtest/`):** Football-Data.co.uk CSV'leri (`T1` Süper Lig ayrı raporlanacak + `E0`, `SP1`, `F1`) üzerinden geleceği sızdırmadan haftalık tahmin → gerçekleşen sonuç karşılaştırması yapan backtest motorunu kurmak; **RPS, Brier, Log-Loss, Üst 2.5 kalibrasyonu** ve **piyasa olasılığı referansıyla** düzeltme öncesi/sonrası kıyaslamasını `reports/backtest_baseline.md` olarak üretmek.
3. **Güvenlik, Veritabanı (RLS) ve Depo Hijyeni:**
   - `POST /sync`, `POST /api/v1/sync` ve `GET /api/v1/bulletin?refresh=true` için `SYNC_API_KEY` (`X-API-Key` / `Authorization: Bearer`) kimlik doğrulaması eklemek.
   - `engine/db/schema.sql` içine tüm 6 tablo için `ENABLE ROW LEVEL SECURITY` ve salt-okunur `SELECT` politikaları eklemek.
   - Public GitHub deposundan kişisel ad/yerel Windows yolları içeren `GEMINI.md` ve `CLAUDE.md` dosyalarını git takibinden çıkarmak (`git rm --cached`, yerel dosyaları silmeden `.gitignore`'a eklemek) ve depoya `LICENSE` (MIT) eklemek.
4. **Kod Kalitesi & CI (`pyproject.toml`, `ruff`, `mypy`, `.github/workflows/ci.yml`):**
   - `ruff` ve `mypy` gerçek bug'larını (`bulletin.py` olası `None.isoformat()`, `pipeline.py` `st` tip çakışması, `B023` kapanış bulgusu) gidermek, `pyproject.toml` ve push/PR `ci.yml` iş akışını eklemek.
5. **Mobil Üretim Sertleştirmesi (`mobile/`):**
   - Varsayılan `apiBaseUrl` değerini yerel LAN IP (`10.19.138.89`) yerine doğrudan canlı üretim URL'sine (`https://naziffarm4.github.io/futbol-skor-analiz/bulletin.json`) çevirmek.
   - `usesCleartextTraffic="true"` ayarını ana manifestten çıkarıp yalnızca `android/app/src/debug/AndroidManifest.xml` içine taşımak (release'te HTTPS zorunlu).
   - Arayüzde kısa ve net bilgilendirme/sorumluluk reddi (*"İstatistiksel analiz amaçlıdır, bahis tavsiyesi değildir"*) ve "Güven Oranı" etiketinin daha dürüst bir ifadeyle (*"Model Netliği"*) sunulması.
   - Güncel Release APK'yı derleyip telefona yüklemek, yeni kodu GitHub'a push edip canlı bülteni tazelemek.

---

## 2. Teknik Şartname ve Alt Ajan (Subagent) Görev Dağılımı

### A. Ön Aşama (`graphify`)
- `graphify-out/` üzerinden `engine/predictors/poisson.py`, `engine/predictors/ratings.py`, `engine/predictors/service.py`, `app.py` ve `mobile/lib/config/constants.dart` bağımlılıklarını sorgula.

### B. Alt Ajan Delegasyonu (Subagents)

#### 🤖 Alt Ajan 1: Model Düzeltmesi & Walk-Forward Backtest Uzmanı (Quant/ML Subagent)
- **Hedef Dosyalar:** `engine/predictors/poisson.py`, `engine/predictors/service.py`, `engine/backtest/` (yeni paket), `reports/backtest_baseline.md`, `engine/tests/test_predictors.py`, `engine/tests/test_backtest.py`
- **Yapılacaklar:**
  1. **Beklenen Gol Ölçeği Düzeltmesi (`engine/predictors/poisson.py`):**
     - `calculate_expected_goals` imzasını `avg_home_goals` ve `avg_away_goals` alacak şekilde güncelle:
       - `raw_lam = avg_home_goals * home_attack * away_defense`
       - `raw_mu = avg_away_goals * away_attack * home_defense`
       - Ev avantajının (`home_advantage`) iki kez sayılmasını önle (oranlar zaten ev/deplasman ortalamalarına göre normalize edildiği için `avg_home_goals / avg_away_goals` doğal olarak iç saha avantajını taşır).
     - `DEFAULT_MAX_GOALS` değerini `5` yerine `10` yap (`0..10` ızgarası; hem yüksek skorlu maçlardaki kütle kırpılmasını ortadan kaldırır hem maliyeti ihmal edilebilirdir).
     - `service.py` çağrılarını `LeagueBaseline.avg_home_goals` ve `avg_away_goals` ile besle.
     - **Sentetik 20 Takımlı Lig Birim Testi:** Eşit güçlü 20 takımlı sentetik ligde modelin ortalama $\lambda$ ve $\mu$ çıktılarının gerçekleşen lig gol ortalamalarına `< %3` sapmayla yakınsadığını ve dengeli maçta Üst 2.5 olasılığının gerçekçi (~%48–%53) çıktığını kalıcı birim testiyle doğrula.
  2. **Walk-Forward Backtest Motoru (`engine/backtest/`):**
     - `engine/backtest/runner.py` & `metrics.py` & `cli.py` (`python -m engine.backtest` ile tek komutla çalışsın).
     - Football-Data.co.uk CSV verileriyle (`T1` Süper Lig ayrı raporlanacak + `E0`, `SP1`, `F1`) hafta hafta (yalnızca o güne kadar oynanmış maçları kullanarak, geleceği sızdırmadan) tahmin üretip gerçekleşen sonuçlarla karşılaştır.
     - Metrikler: **RPS (Ranked Probability Score — ana metrik)**, **Brier Score**, **Log-Loss**, **1/X/2 İsabet Oranı**, **Üst 2.5 Kalibrasyonu**, **Güvenirlik Dilimleri (Calibration Buckets)**.
     - Referanslar: (a) Lig ortalaması sabit baz tahmin, (b) CSV kapanış oranlarından marjı temizlenmiş piyasa olasılığı, (c) **Düzeltme Öncesi (eski ölçek)** vs **Düzeltme Sonrası (yeni ölçek)** karşılaştırması.
     - Çıktıyı `reports/backtest_baseline.md` dosyasına yaz (ağ gerektirmeyen deterministik örnek CSV fixture'ı ile `engine/tests/test_backtest.py` birim testlerini de ekle; canlı ağ varsa güncel sezonların gerçek CSV'leriyle `reports/backtest_baseline.md` üret).

#### 🤖 Alt Ajan 2: Güvenlik, RLS, Kod Kalitesi & Depo Hijyeni Uzmanı (Security/DevOps Subagent)
- **Hedef Dosyalar:** `app.py`, `engine/db/schema.sql`, `engine/bulletin.py`, `engine/scrapers/pipeline.py`, `pyproject.toml`, `.github/workflows/ci.yml`, `.gitignore`, `LICENSE`
- **Yapılacaklar:**
  1. **API Güvenliği (`app.py`):**
     - `require_sync_api_key` bağımlılığı ekle (`X-API-Key` veya `Authorization: Bearer <token>`, `secrets.compare_digest` ile `SYNC_API_KEY` kontrolü).
     - `POST /sync`, `POST /api/v1/sync` ve `GET /api/v1/bulletin?refresh=true` (yalnızca `refresh=true` istendiğinde) için bu korumayı zorunlu kıl; normal `GET /api/v1/bulletin`, `GET /health`, `GET /status` herkese açık kalsın.
     - `GET /health` yanıtına `bulletin_age_seconds` alanını ekle.
  2. **Supabase RLS (`engine/db/schema.sql`):**
     - Tüm 6 tabloda (`leagues`, `teams`, `matches`, `injuries`, `predictions`, `team_analyses`) `ALTER TABLE ... ENABLE ROW LEVEL SECURITY;` ve salt-okunur `SELECT` politikaları (`CREATE POLICY ... FOR SELECT USING (true)`) ekle; yazmayı `service_role`'a bırak.
  3. **Statik Analiz & Gerçek Bug Düzeltmeleri:**
     - `engine/bulletin.py` içinde `None` olabilecek tarih üzerindeki `.isoformat()` riskini düzelt.
     - `engine/scrapers/pipeline.py` içindeki `st` değişken tipi çakışmasını temizle.
     - `pyproject.toml` oluştur (`ruff` + `mypy` kuralları); `ruff check engine app.py` ile otomatik düzeltilebilir ve `B023` bulgularını temizle.
     - `.github/workflows/ci.yml` oluştur (push ve PR'larda Python `unittest` + `ruff` kontrolü).
  4. **Depo Hijyeni & Gizlilik:**
     - `LICENSE` (MIT) dosyasını ekle.
     - `.gitignore` içine `GEMINI.md`, `CLAUDE.md` ekle ve `git rm --cached GEMINI.md CLAUDE.md` ile yerel dosyaları silmeden yalnızca git takibinden/public repodan çıkar! (Kişisel Windows kullanıcı adı ve proje dışı ajan yönergeleri artık public repoda görünmeyecek).

#### 🤖 Alt Ajan 3: Mobil Sertleştirme, QA & Canlı Yayın Uzmanı (Mobile/QA Subagent)
- **Hedef Dosyalar:** `mobile/lib/config/constants.dart`, `mobile/android/app/src/main/AndroidManifest.xml`, `mobile/android/app/src/debug/AndroidManifest.xml`, `mobile/lib/widgets/`, `mobile/test/widget_test.dart`
- **Yapılacaklar:**
  1. **Üretim Varsayılan URL & Cleartext Güvenliği:**
     - `mobile/lib/config/constants.dart` içinde varsayılan `apiBaseUrl` değerini doğrudan üretim adresine (`https://naziffarm4.github.io/futbol-skor-analiz/bulletin.json`) çevir (yerel LAN IP `10.19.138.89` üretim kodundan çıkarılsın).
     - `android:usesCleartextTraffic="true"` ayarını `mobile/android/app/src/main/AndroidManifest.xml` dosyasından kaldır; yalnızca debug için `mobile/android/app/src/debug/AndroidManifest.xml` dosyasına taşı.
  2. **Dürüst Etiketleme & Sorumluluk Reddi:**
     - "Güven" etiketini kalibrasyon öncesi kullanıcıyı yanıltmamak için **"Model Netliği"** olarak güncelle.
     - `HomeScreen` alt bilgi veya `MatchDetailScreen` bilgi şeridine kısa sorumluluk reddi ekle: *"İstatistiksel analiz amaçlıdır; kesin sonuç garantisi veya bahis tavsiyesi değildir."*
  3. **Doğrulama, Push & Canlı Cihaz Kurulumu:**
     - `python -m unittest discover -s engine/tests -v` (tüm testler OK), `ruff check engine app.py` (0 hata).
     - `PUB_CACHE="E:\Users\nazif_acikgoz\AppData\Local\Pub\Cache"` ile `flutter analyze` (0 sorun) ve `flutter test` (tüm testler OK).
     - Değişiklikleri `naziffarm4/futbol-skor-analiz` reposuna push et, `gh workflow run update_bulletin.yml` ile düzeltilmiş ölçekli canlı `bulletin.json`'u yayınla.
     - `flutter build apk --release --target-platform android-arm64` (artık varsayılan URL zaten bulut!) ile Release APK derle, `adb install -r` ile telefona yükle ve USB tüneli olmadan 0 logcat hatasıyla açıldığını kanıtla.

### C. Kapanış (`graphify --update`)
- `/graphify --update` çalıştır; backtest öncesi/sonrası RPS/Brier/Log-Loss/Üst 2.5 özet tablosu ve tüm doğrulama kanıtlarını `tasks/GOREV-12-RAPOR.md` dosyasına kaydet.

---

## 3. Doğrulama Kriteri
1. Sentetik 20 takımlı lig testinde ortalama $\lambda/\mu$ sapması `< %3`.
2. `reports/backtest_baseline.md` içinde 4 ligin (Süper Lig `T1` ayrı) düzeltme öncesi vs sonrası RPS, Brier, Log-Loss, Üst 2.5 ve piyasa referansı karşılaştırması yer almalı.
3. `POST /sync` ve `?refresh=true` API anahtarı olmadan HTTP 401 dönmeli.
4. `GEMINI.md` ve `CLAUDE.md` `git ls-files` içinde görünmemeli, `LICENSE` mevcut olmalı.
5. Python testleri, `ruff`, `flutter analyze`, `flutter test` sıfır hata; canlı GitHub Pages ve telefondaki Release APK doğrulanmış olmalı.
