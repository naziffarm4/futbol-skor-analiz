---
title: Futbol Skor ve Analiz Motoru
emoji: ⚽
colorFrom: green
colorTo: blue
sdk: docker
app_port: 7860
---

# Futbol Haftalık Skor Tahmini ve Takım Analiz Motoru

Türkiye Süper Ligi, İngiltere Premier League, İspanya La Liga ve Fransa Ligue 1 için çoklu kaynak veri füzyonu, Dixon-Coles / Poisson + piyasa konsensüsü (market blend) skor tahmini, 9'lu İlk Yarı / Maç Sonucu (İY/MS) olasılık matrisi ve Türkçe takım analiz sistemi.

## Tek Kanonik Üretim Mimarisi

Proje, API kotalarını tek merkezden korumak ve mobil istemciye sıfır sunucu soğuk başlangıç gecikmesiyle hizmet vermek üzere **tek kanonik üretici** mimarisiyle çalışır:

1. **Kanonik Üretici — GitHub Actions (`.github/workflows/update_bulletin.yml`):**
   - Her gün `0 7 * * *` UTC (TSİ 10:00 — aylık ~240/500 kredi güvenlik marjı) zamanlamasıyla ve gerektiğinde manuel `workflow_dispatch` tetikleyicisiyle çalışır.
   - `actions/cache@v4` kota kalkanı (`bulletin-api-quota-${{ github.run_id }}` / `restore-keys: bulletin-api-quota-`) sayesinde `engine/data/api_cache` ve `engine/data/quota_budget.json` durumu ardışık çalışmalar arasında korunur.
   - `python -m engine.cli --export-bulletin dist/bulletin.json` komutu 4 ligin haftalık tahminlerini üretir, şema ve olasılık toplamlarını doğrular.
2. **Statik Dağıtım — GitHub Pages CDN (`bulletin.json`):**
   - Doğrulanan `bulletin.json` ve özet durum sayfası GitHub Pages üzerinden statik JSON CDN olarak yayınlanır.
3. **İstemci — Flutter Mobil Uygulama (`mobile/`):**
   - Güncel bülteni doğrudan GitHub Pages CDN üzerinden çeker; ağ kesintilerinde yerel **çevrimdışı önbellek** (`SharedPreferences` / disk önbelleği) üzerinden kesintisiz çalışır.
   - Her maç için tam **9'lu İY/MS olasılık matrisini** (`all_ht_ft_json`), en olası skor dağılımlarını ve Türkçe analiz metinlerini gösterir.
   - Bülten yaşı **36 saati** aştığında kullanıcıya açık **bayat bülten uyarısı** gösterir.
   - **Dürüst Kaynak Şeffaflığı:** Her ligde gerçekten kullanılan veri kaynakları şeffaf biçimde etiketlenir (gerçek Understat kapsamındaki liglerde `"Understat"`, Opta köprüsünde `"FotMob-xG"`, şut/isabetli şut kalibrasyonunda `"ShotProxy-xG"`).
4. **Opsiyonel Docker / FastAPI Servis Aynası (`app.py` & `Dockerfile`):**
   - Yerel ağda veya konteyner ortamında (`7860` portu) JSON/HTML durum paneli ve API aynası olarak çalıştırılabilir.
   - Çift kota tüketimini önlemek için `SCHEDULER_ENABLED` varsayılanı **`false`** olarak ayarlanmıştır; arka plan zamanlayıcısı yalnızca `SCHEDULER_ENABLED=true` açıkça verildiğinde devreye girer.
   - `Dockerfile` içinde Python standart kütüphanesiyle `/health` uç noktasını denetleyen yerleşik `HEALTHCHECK` tanımlıdır.

## Dizin Yapısı

- `.github/workflows/update_bulletin.yml`: Günlük kanonik bülten üretimi, kota önbelleği ve GitHub Pages dağıtımı
- `.github/workflows/ci.yml`: Python (`ruff`, tam `mypy engine app.py`, `unittest`) ve Flutter (`flutter pub get`, `flutter analyze`, `flutter test`) sürekli entegrasyon hattı
- `engine/scrapers/`: Dürüst tekil `User-Agent` (`FutbolSkorAnaliz/1.0`) tabanlı veri toplayıcılar, resmi API adaptörleri (`API-Football`, `TheOddsAPI`), açık kaynak adaptörleri (`ESPN`, `Football-Data`, `Understat` / `FotMob-xG` / `ShotProxy-xG`, `SportsGambler` / `TheSportsDB`), `QuotaBudgetTracker` ve `IngestionPipeline`
- `engine/predictors/`: Zaman sönümlü (time-decay) takım güç/sakatlık modeli, Dixon-Coles/Poisson skor + 9'lu İY/MS matrisi, piyasa harmanlama ve Türkçe analiz üreticisi
- `engine/backtest/`: Geçmiş sezonlar üzerinde ileriye dönük (walk-forward) kalibrasyon, Brier / Log-Loss ve holdout doğrulama motoru
- `engine/bulletin.py`: 4 lig birleşik `bulletin.json` üreticisi ve atomik disk önbelleği
- `mobile/`: Flutter mobil uygulaması (Android / iOS / Web uyumlu)
- `app.py` & `Dockerfile`: Opsiyonel FastAPI servis aynası (`SCHEDULER_ENABLED=false` varsayılanlı)

## Kurulum ve CLI Kullanımı

```bash
pip install -r engine/requirements.txt

# 4 lig için statik bülten JSON çıktısı üret
python -m engine.cli --export-bulletin dist/bulletin.json

# Tek bir ligi veritabanına yazmadan yerel JSON çıktısıyla çalıştır
python -m engine.cli --league super_lig --dry-run
```

Opsiyonel FastAPI servisini başlatmak için:
```bash
# Varsayılan olarak zamanlayıcı kapalıdır (SCHEDULER_ENABLED=false)
uvicorn app:app --host 0.0.0.0 --port 7860
```
- `GET /`: HTML/JSON sistem ve lig durum paneli
- `GET /health`: Liveness, zamanlayıcı durumu ve `bulletin_age_seconds` kontrolü
- `GET /api/v1/bulletin`: Önbellekteki güncel bülten (`?refresh=true` için `X-API-Key` / `Bearer` gerekir)
- `POST /api/v1/sync`: Yetkili manuel senkronizasyon (`SYNC_API_KEY` zorunlu)

## İstatistiksel Doğrulama (Backtest) ve Dokümantasyon

Modelin geçmiş maçlar üzerindeki olasılık kalibrasyonunu, Log-Loss / Brier skorlarını ve piyasa harmanlama etkisini doğrulamak için:

```bash
python -m engine.backtest
```

İlgili teknik belgeler ve doğrulama raporları:
- Veri kaynakları, kota kalkanı ve uyumluluk mimarisi: [`docs/veri-kaynaklari.md`](docs/veri-kaynaklari.md)
- Backtest v1 baz raporu: [`reports/backtest_v1.md`](reports/backtest_v1.md)
- Backtest v2 kalibrasyon ve piyasa harmanlama raporu: [`reports/backtest_v2.md`](reports/backtest_v2.md)
- Backtest v3 holdout doğrulama raporu: [`reports/backtest_v3_holdout.md`](reports/backtest_v3_holdout.md)

## Kalite Kapıları ve Testler

Varsayılan birim test koşumu dış ağa bağlanmaz; canlı duman testleri yalnızca `RUN_LIVE_TESTS=1` verildiğinde çalışır:

```bash
python -m ruff check engine app.py
python -m mypy engine app.py
python -m unittest discover -s engine/tests -v
```
