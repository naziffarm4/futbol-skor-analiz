# GÖREV-14: Operasyonel Dayanıklılık, Dürüst Kaynak Etiketi, CI Sertleştirme ve Hold-Out / Bootstrap Backtest (v3)

## 1. Amaç ve Kapsam
İkinci bağımsız kod ve istatistik denetiminde öne çıkan "Hemen" ve "Kısa Vade" bulgularını tek bir temiz, ölçülebilir ve disiplinli görevde kapatmak:

1. **Kota Kalkanı & Tek Kanonik Üretici:**
   - Kullanılmayan `playwright>=1.49.0` bağımlılığını `engine/requirements.txt`'den kaldır.
   - `.github/workflows/update_bulletin.yml` içinde `engine/data/api_cache` ve `engine/data/quota_budget.json` için `actions/cache@v4` ekle ve zamanlamayı günde 1'e (`0 7 * * *` UTC — TSİ 10:00, ayda ~240/500 kredi ile %50 güvenlik marjı; `workflow_dispatch` her zaman açık) indir.
   - `app.py` içinde `SCHEDULER_ENABLED` varsayılanını `"false"` yap (kanonik üretici = GitHub Actions + Pages; çift kota tüketimini önle) ve `Dockerfile` içine `/health` kullanan `HEALTHCHECK` ekle.
2. **Dürüst Kaynak Etiketi & Temiz HTTP Başlıkları:**
   - Süper Lig xG verisi FotMob/Şut-Vekili'nden geldiğinde `sources_used` içinde `"Understat"` yerine gerçek kaynak adıyla (`"FotMob-xG"` veya `"ShotProxy-xG"`) etiketle.
   - `engine/scrapers/base.py` içinde rastgele masaüstü UA rotasyonu ve tüm isteklere Transfermarkt `Referer` gönderme davranışını kaldır; dürüst, projeyi tanıtan tekil `User-Agent` (`FutbolSkorAnaliz/1.0 (+https://github.com/naziffarm4/futbol-skor-analiz)`) kullan.
3. **CI Sertleştirme (`.github/workflows/ci.yml` + Canlı Test İzolasyonu):**
   - Tüm dış ağa bağlı `test_live_*` testlerini `@unittest.skipUnless(os.getenv("RUN_LIVE_TESTS") == "1", ...)` ile ayır (ağsız ortamlarda 0 başarısızlık).
   - `ci.yml` içinde `mypy` adımını 3 dosya yerine tam `python -m mypy engine app.py` yap ve Flutter job'ı (`flutter analyze` + `flutter test`) ekle.
4. **İstatistiksel Backtest v3 (`reports/backtest_v3_holdout.md`):**
   - `α` harman ızgarasını `0.0..1.0` aralığına uzat.
   - **Hold-Out Ayrımı:** Hiperparametre (`ξ`, `α`) seçimi yalnızca `2425 + 2526` sezonlarında yapılsın; **`2627` sezonu hiç görülmemiş ayrı test (hold-out) seti** olarak raporlansın.
   - **Eşleştirilmiş Bootstrap Güven Aralığı (95% CI, N=1000):** Zaman sönümü ve piyasa harmanı RPS farkının anlamlılığını raporla.
   - **Power / Shin Marj Arındırma:** Orantısal de-vigging vs **Power (güç) yöntemi** karşılaştırmasını özellikle favori `[0.6, 0.8)` dilimi üzerinde ölç; iyileşme kanıtlanırsa üretimde aktif et.
   - Raporda açık ve dürüstçe *"harman modeli piyasaya yaklaştırıyor; saf piyasa kapanışını geçme iddiası yok, asıl katma değer şeffaf 9'lu İY/MS dağılımı + canlı sakatlık + Türkçe taktiksel analiz"* notunu yer ver.
5. **Mobil Bülten Yaşı Uyarısı & Güncel `README.md`:**
   - `DataTransparencyBanner` içine bülten yaşı `> 36 saat` olduğunda belirgin turuncu **"Bülten güncel değil (X saat önce)"** uyarısı ekle ve widget testiyle doğrula.
   - `README.md` dosyasını tek kanonik mimari (GitHub Actions + GitHub Pages + Flutter + `python -m engine.backtest` + `reports/` bağlantıları) ile güncelle.

---

## 2. Alt Ajan (Subagent) Görev Dağılımı

### 🤖 Alt Ajan 1: Operasyon, Kaynak Dürüstlüğü, CI & Dockerfile (Backend/DevOps Subagent)
- `engine/requirements.txt` (`playwright` kaldır), `engine/scrapers/base.py` (tekil dürüst UA, ilgisiz Referer kaldır), `engine/scrapers/fusion.py` & `engine/bulletin.py` (Süper Lig gerçek xG kaynak adı), `app.py` (`SCHEDULER_ENABLED` default `"false"`), `Dockerfile` (`HEALTHCHECK`).
- `.github/workflows/update_bulletin.yml` (`actions/cache@v4` + günlük 1 kez `0 7 * * *` UTC) ve `.github/workflows/ci.yml` (tam `mypy engine app.py` + Flutter job'ı).
- `engine/tests/test_scrapers.py` & `test_sources_and_fusion.py` içindeki canlı ağ testlerini `RUN_LIVE_TESTS=1` bayrağına bağla.
- `README.md` güncelle.

### 🤖 Alt Ajan 2: Hold-Out, Bootstrap & Power De-Vigging Backtest Uzmanı (Quant/ML Subagent)
- `engine/backtest/` içinde: `α ∈ [0.0..1.0]`, `2425+2526` eğitim / `2627` hold-out ayrımı, eşleştirilmiş 95% bootstrap güven aralığı (N=1000) ve orantısal vs Power de-vigging karşılaştırmasını ekle.
- `reports/backtest_v3_holdout.md` raporunu üret (4 lig + Süper Lig `T1` ayrı) ve deterministik birim testlerini `engine/tests/test_backtest.py` içine ekle.

### 🤖 Alt Ajan 3: Mobil Bülten Yaşı Uyarısı, QA & Canlı Doğrulama (Mobile/QA Subagent)
- `mobile/lib/widgets/data_transparency_banner.dart` içine `> 36 saat` bayat bülten uyarısı + `mobile/test/widget_test.dart` testi ekle.
- Tam kalite kapısı:
  - `python -m mypy engine app.py` (0 hata)
  - `python -m ruff check engine app.py` (0 hata)
  - `python -m unittest discover -s engine/tests -v` (ağsız/varsayılan modda **0 başarısızlık**, canlı testler `RUN_LIVE_TESTS` ile temiz atlanır)
  - `PUB_CACHE="E:\Users\nazif_acikgoz\AppData\Local\Pub\Cache"` ile `flutter analyze` (0 sorun) ve `flutter test` (tüm testler OK).
- Değişiklikleri `main` dalına push et, `ci.yml` (Python + Flutter job'ları) ve `update_bulletin.yml` (cache + günlük yayın) koşumlarını yeşil doğrula.
- Release APK derle, bağlı telefona (`adb install -r`) yükle ve 0 logcat hatasıyla açıldığını doğrula.

### Kapanış (`graphify --update`)
- `/graphify --update` çalıştır ve tüm kanıtları `tasks/GOREV-14-RAPOR.md` dosyasına kaydet.
