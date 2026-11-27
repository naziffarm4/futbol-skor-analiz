# GÖREV-04: Otonom Arka Plan Servisi, CLI ve Hugging Face Spaces Dağıtım Hazırlığı

## 1. Amaç ve Kapsam
Bu görevin amacı; önceki adımlarda geliştirilen veri toplama (`IngestionPipeline`) ve skor tahmin/analiz (`PredictionService`) motorlarını:
1. Terminalden tek komutla çalıştırılabilen esnek bir **Komut Satırı Arayüzüne (CLI)** bağlamak,
2. Belirli aralıklarla (günde 1-2 kez) otonom çalışan bir **Zamanlanmış Görev Döngüsüne (Scheduler / Runner)** kavuşturmak,
3. %100 ücretsiz, uyku modu olmayan **Hugging Face Spaces (Docker)** ortamında 7/24 kesintisiz çalışmaya hazır bir **FastAPI mikro servisi** ve konteyner altyapısı haline getirmektir.

---

## 2. Teknik Şartname

### A. Modül ve Dosya Yapısı
Aşağıdaki bileşenler oluşturulmalı ve yapılandırılmalıdır:

1. **`engine/runner.py` (Birleşik Orkestratör & Runner):**
   - 4 ligin (Süper Lig, Premier League, La Liga, Ligue 1) fikstür ve sakatlıklarını sırayla çeken, ardından sıradaki hafta maçları için tahmin ve analizleri üretip Supabase'e kaydeden tekil `run_full_cycle(leagues=None, persist=True, only_next_round=True)` fonksiyonu.
   - Son çalışma zamanı, başarı/hata durumu, işlenen maç ve sakatlık sayılarını bellekte ve durum nesnesinde (`RunnerStatus`) tutan yapı.

2. **`engine/cli.py` (Komut Satırı Arayüzü):**
   - `python -m engine.cli` veya `python engine/cli.py` ile çalıştırılabilir:
     - `--league [super_lig|premier_league|la_liga|ligue_1]`: Belirli bir ligi çalıştırır.
     - `--all`: 4 ligin tamamını sırayla çalıştırır.
     - `--dry-run`: Supabase'e yazmadan yerel JSON/özet çıktısı verir.
     - `--schedule`: Arka planda zamanlayıcı modunda çalışır.

3. **`app.py` (Hugging Face Spaces FastAPI Servisi):**
   - Port: `7860` (Hugging Face Spaces varsayılan portu).
   - Uç Noktalar:
     - `GET /`: Şık, minimalist HTML/JSON durum paneli (Sistem durumu, son güncelleme tarihi, lig özetleri).
     - `GET /health`: Liveness ve readiness kontrolü (`{"status": "ok", "uptime": ...}`).
     - `GET /status`: 4 ligin son senkronizasyon durumları, maç ve sakatlık sayıları.
     - `POST /sync`: Tüm liglerin veya belirli bir ligin (`?league=super_lig`) manuel senkronizasyonunu başlatan uç nokta.
   - **Arka Plan Zamanlayıcı (Background Scheduler):**
     - Uygulama başlatıldığında (`lifespan` event), her gün belirlenen saatte (veya günde 1 kez) otomatik olarak `run_full_cycle` fonksiyonunu çalıştıran hafif zamanlayıcı (`asyncio.create_task` döngüsü veya `APScheduler`).

4. **`Dockerfile` ve Hugging Face Spaces Konfigürasyonu:**
   - `Dockerfile`:
     - `python:3.12-slim` tabanlı,
     - Gerekli sistem paketleri (`curl` vb.),
     - `engine/requirements.txt` kurulumu (FastAPI ve Uvicorn eklenmeli),
     - Kullanıcı izni (Hugging Face standardı: `user 1000`),
     - `CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]`.
   - `README.md` (veya HF Spaces uyumlu metadata başlığı):
     - `title: Futbol Skor ve Analiz Motoru`
     - `emoji: ⚽`
     - `colorFrom: green`
     - `colorTo: blue`
     - `sdk: docker`
     - `app_port: 7860`

### B. Bağımlılıklar (`engine/requirements.txt`)
- `fastapi>=0.115.0`
- `uvicorn[standard]>=0.32.0`
- Mevcut `supabase`, `pydantic`, `httpx`, `beautifulsoup4`, `lxml`, `python-dotenv` paketleri korunmalıdır.

---

## 3. Doğrulama ve Test Kriteri
- `engine/tests/test_runner.py` dosyası yazılmalıdır:
  1. `test_runner_full_cycle`: Mock veri akışıyla `run_full_cycle` fonksiyonunun Ingestion ve Prediction servislerini sıralı ve eksiksiz çalıştırdığı doğrulanmalıdır.
  2. `test_cli_argument_parsing`: CLI argüman ayrıştırıcısının (`--league`, `--all`, `--dry-run`) doğru parametreleri ürettiği test edilmelidir.
  3. `test_fastapi_endpoints`: `TestClient` (veya `httpx.AsyncClient`) ile `/health`, `/status` ve `/` uç noktalarının HTTP 200 döndürdüğü ve beklenen JSON şemasını sağladığı test edilmelidir.
- Tüm testler `python -m unittest -v` ile çalıştırılarak önceki testlerle birlikte sıfır hatayla geçtiği kanıtlanmalıdır.
- Tüm bulgular ve test çıktıları `tasks/GOREV-04-RAPOR.md` dosyasına kaydedilmelidir.
