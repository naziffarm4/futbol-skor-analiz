# GÖREV-01: Veritabanı Şeması, Veri Modelleri ve Temel Mimari Kurulumu

## 1. Amaç ve Kapsam
Türkiye Süper Ligi, İngiltere Premier League, İspanya La Liga ve Fransa Ligue 1 için otonom çalışan haftalık skor tahmini ve takım analiz sisteminin temel mimari iskeletini ve Supabase (PostgreSQL) veritabanı şemasını kurmak.

Bu aşamada:
1. Supabase üzerinde çalışacak eksiksiz SQL şeması (`schema.sql`) hazırlanacak.
2. Python tabanlı tahmin ve scraping motoru için modüler dizin yapısı (`engine/`) oluşturulacak.
3. Supabase istemci bağlantı konfigürasyonu ve Pydantic veri modelleri tanımlanacak.

---

## 2. Teknik Şartname

### A. Supabase PostgreSQL Şeması (`engine/db/schema.sql`)
Aşağıdaki tablolar ilişkisel (Foreign Key), indeksli ve zaman damgalı olarak tanımlanmalıdır:
1. **`leagues`**:
   - `id` (VARCHAR PRIMARY KEY - örn: 'super_lig', 'premier_league', 'la_liga', 'ligue_1')
   - `name` (VARCHAR)
   - `country` (VARCHAR)
   - `season` (VARCHAR)
2. **`teams`**:
   - `id` (SERIAL PRIMARY KEY)
   - `league_id` (FK -> leagues.id)
   - `name` (VARCHAR)
   - `short_name` (VARCHAR)
   - `logo_url` (TEXT)
3. **`matches`**:
   - `id` (SERIAL PRIMARY KEY)
   - `league_id` (FK -> leagues.id)
   - `home_team_id` (FK -> teams.id)
   - `away_team_id` (FK -> teams.id)
   - `match_date` (TIMESTAMPTZ)
   - `round` (INT)
   - `status` (VARCHAR - 'SCHEDULED', 'FINISHED', 'POSTPONED')
   - `home_score` (INT NULL)
   - `away_score` (INT NULL)
4. **`injuries`**:
   - `id` (SERIAL PRIMARY KEY)
   - `team_id` (FK -> teams.id)
   - `player_name` (VARCHAR)
   - `position` (VARCHAR - 'GK', 'DEF', 'MID', 'FW')
   - `reason` (VARCHAR - sakatlık türü veya ceza)
   - `return_date` (VARCHAR / DATE)
   - `impact_level` (VARCHAR - 'HIGH', 'MEDIUM', 'LOW')
   - `updated_at` (TIMESTAMPTZ)
5. **`predictions`**:
   - `id` (SERIAL PRIMARY KEY)
   - `match_id` (FK -> matches.id UNIQUE)
   - `predicted_home_score` (INT)
   - `predicted_away_score` (INT)
   - `confidence_rate` (FLOAT)
   - `top_scores_json` (JSONB - örn: `[{"score": "2-1", "prob": 0.17}, ...]`)
   - `updated_at` (TIMESTAMPTZ)
6. **`team_analyses`**:
   - `id` (SERIAL PRIMARY KEY)
   - `match_id` (FK -> matches.id UNIQUE)
   - `match_overview_text` (TEXT - Maçın genel özeti ve akış beklentisi)
   - `home_analysis_text` (TEXT - Ev sahibi takımın form ve eksik durumu analizi)
   - `away_analysis_text` (TEXT - Deplasman takımının form ve eksik durumu analizi)
   - `home_offense_rating` (FLOAT)
   - `home_defense_rating` (FLOAT)
   - `away_offense_rating` (FLOAT)
   - `away_defense_rating` (FLOAT)
   - `updated_at` (TIMESTAMPTZ)

### B. Proje Dizin Yapısı
`e:\apk\futbol\` altında aşağıdaki yapı kurulmalıdır:
```
e:\apk\futbol\
├── tasks\
│   └── GOREV-01-RAPOR.md
├── engine\
│   ├── db\
│   │   ├── __init__.py
│   │   ├── schema.sql
│   │   └── client.py          # Supabase bağlantı yöneticisi
│   ├── models\
│   │   ├── __init__.py
│   │   └── schemas.py         # Pydantic veri modelleri (Match, Injury, Prediction vb.)
│   ├── config.py              # Ortam değişkenleri ve 4 ligin sabit metadata tanımları
│   └── requirements.txt       # supabase, pydantic, httpx, python-dotenv
├── .env.example
└── README.md
```

### C. Doğrulama ve Test Kriteri
- `requirements.txt` bağımlılıkları tanımlanmalı.
- Pydantic modelleri `engine/models/schemas.py` içinde `schema.sql` ile birebir uyumlu olmalı.
- `engine/config.py` içinde 4 ligin kodları, ülke bilgileri ve yapılandırmaları yer almalı.
- Yapılan işlemler ve doğrulama sonuçları `tasks/GOREV-01-RAPOR.md` dosyasına kaydedilmelidir.
