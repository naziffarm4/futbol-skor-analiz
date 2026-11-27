---
title: Futbol Skor ve Analiz Motoru
emoji: ⚽
colorFrom: green
colorTo: blue
sdk: docker
app_port: 7860
---

# Futbol Haftalık Skor Tahmini ve Takım Analiz Motoru

Türkiye Süper Ligi, İngiltere Premier League, İspanya La Liga ve Fransa Ligue 1 için otonom haftalık fikstür/sakatlık toplama, Dixon-Coles/Poisson skor tahmini ve Türkçe takım analiz mikro servisi.

## Mimari ve Dizin Yapısı

- `app.py`: Hugging Face Spaces uyumlu FastAPI mikro servisi (`7860` portu) ve günlük otonom zamanlayıcı
- `Dockerfile`: `python:3.12-slim` ve `UID 1000` tabanlı konteyner tanımı
- `engine/config.py`: Ortam değişkenleri ve desteklenen 4 ligin metadata tanımları
- `engine/db/`: Supabase (PostgreSQL) şeması (`schema.sql`) ve istemci katmanı (`client.py`)
- `engine/models/schemas.py`: Veritabanı ile birebir uyumlu Pydantic v2 modelleri
- `engine/scrapers/`: Fikstür, sakatlık/ceza kazıyıcıları ve `IngestionPipeline`
- `engine/predictors/`: Takım güç/sakatlık etki modeli, Dixon-Coles/Poisson skor matrisi ve Türkçe analiz üreticisi
- `engine/runner.py`: 4 ligi sırayla çalıştıran birleşik orkestratör (`run_full_cycle`) ve `RunnerStatus`
- `engine/cli.py`: Terminal üzerinden esnek çalıştırma arayüzü

## Kurulum

1. Bağımlılıkları yükleyin:
   ```bash
   pip install -r engine/requirements.txt
   ```
2. `.env.example` dosyasını `.env` olarak kopyalayıp Supabase bağlantı anahtarlarınızı tanımlayın.
3. `engine/db/schema.sql` dosyasını Supabase SQL Editor üzerinde çalıştırın.

## CLI Kullanımı

```bash
# Tek bir ligi Supabase'e yazmadan yerel JSON çıktısıyla çalıştır
python -m engine.cli --league super_lig --dry-run

# 4 ligin tamamını sırayla çalıştır ve Supabase'e kaydet
python -m engine.cli --all

# Arka planda günlük zamanlayıcı modunda çalıştır
python -m engine.cli --all --schedule
```

## FastAPI Servisi ve Uç Noktalar

Yerel başlatma:
```bash
uvicorn app:app --host 0.0.0.0 --port 7860
```

- `GET /`: Minimalist HTML/JSON sistem ve lig durum paneli
- `GET /health`: Liveness ve readiness kontrolü (`{"status": "ok", "uptime": ...}`)
- `GET /status`: 4 ligin son senkronizasyon zamanı, maç, sakatlık ve tahmin sayıları
- `POST /sync`: Tüm liglerin veya tek bir ligin (`?league=super_lig`) manuel senkronizasyonu

## Hugging Face Spaces Dağıtımı

1. Yeni bir **Docker** Space oluşturun.
2. Space **Settings -> Variables and secrets** bölümüne `SUPABASE_URL`, `SUPABASE_KEY` ve `SUPABASE_SERVICE_ROLE_KEY` değerlerini ekleyin.
3. Depoyu Space'e gönderdiğinizde servis `7860` portunda otomatik olarak ayağa kalkar ve günde 1 kez tam senkronizasyon döngüsünü çalıştırır.
