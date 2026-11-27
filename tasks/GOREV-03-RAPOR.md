# GÖREV-03 Teknik Uygulama ve Doğrulama Raporu

**Görev:** Skor Tahmin Motoru, Sakatlık Etki Modeli ve Takım Analiz Üreticisi  
**Tarih:** 2026-11-26  
**Durum:** Tamamlandı ve Doğrulandı (`18/18` test başarılı)

---

## 1. Oluşturulan Dosya Yapısı

`tasks/GOREV-03-SKOR-TAHMIN-VE-ANALIZ-MOTORU.md` şartnamesine uygun olarak sıfır ek harici paket bağımlılığı ile (standart `math` + mevcut `pydantic` v2 ve `supabase` katmanı kullanılarak) aşağıdaki modüller eklendi:

```text
e:\apk\futbol\
├── tasks\
│   ├── GOREV-03-SKOR-TAHMIN-VE-ANALIZ-MOTORU.md
│   └── GOREV-03-RAPOR.md
└── engine\
    ├── predictors\
    │   ├── __init__.py
    │   ├── ratings.py               # Baz takım güçleri ve Injury Degradation modeli
    │   ├── poisson.py               # Dixon-Coles / Poisson 6x6 skor matrisi ve confidence_rate
    │   ├── analyst.py               # Açıklanabilir Türkçe maç ve takım analiz üreticisi
    │   └── service.py               # Prediction & TeamAnalysis orkestrasyon ve Supabase upsert servisi
    └── tests\
        └── test_predictors.py       # GÖREV-03 kapsamlı birim ve entegrasyon testleri
```

---

## 2. Teknik Uygulama Detayları

### 2.1. Takım Güç ve Sakatlık Etki Modeli (`engine/predictors/ratings.py`)
- **Lig Baz Çizgisi ve İç Saha Avantajı (`calculate_league_baseline`):**
  - Her ligin `FINISHED` maçlarından ev sahibi ve deplasman gol ortalamaları (`avg_home_goals`, `avg_away_goals`) ve iç saha avantajı (`home_advantage = avg_home_goals / avg_away_goals`, `[1.05, 1.60]` bandında korumalı) hesaplanır.
  - Henüz oynanmış maç olmayan sezon başı senaryolarında varsayılan `1.45 / 1.15` lig ortalamalarına güvenli geri dönüş yapılır.
- **Bayesyen Sönümlemeli Baz Katsayılar (`build_team_ratings`):**
  - Küçük örneklem oynaklıklarını engellemek üzere `prior_weight = 3.0` maç sönümlemesi ile iç saha, deplasman ve genel hücum/savunma oranları (`base_attack`, `base_defense`, `home_attack`, `away_attack`, `home_defense`, `away_defense`) hesaplanır.
  - Tek geçişte son 5 maç form dizisi (`G/B/M`), iç/dış saha galibiyet-beraberlik-mağlubiyet karnesi ve gol yemeden tamamlanan maç sayıları (`clean_sheets`, `away_clean_sheets`) çıkarılır.
- **Sakatlık Zayıflatma Çarpanı (`INJURY_PENALTY_MATRIX`, `calculate_injury_degradation`):**
  - `GK` (Kaleci): Savunma zaafiyetini artırır (`HIGH: +%22`, `MEDIUM: +%10`, `LOW: +%3`).
  - `DEF` (Stoper/Bek): Savunma zaafiyetini artırır (`HIGH: +%12` + `-%1` hücum katkısı, `MEDIUM: +%7`, `LOW: +%2.5`).
  - `MID` (Orta Saha): Çift yönlü etki (`HIGH: -%8` hücum / `+%7` savunma zaafiyeti, `MEDIUM: -%6` hücum / `+%5` savunma zaafiyeti, `LOW: -%2.5` hücum / `+%2` savunma zaafiyeti).
  - `FW` (Santrafor/Kanat): Hücum bitiriciliğini düşürür (`HIGH: -%16`, `MEDIUM: -%8`, `LOW: -%3`).
  - Çoklu eksik yığılmalarında gerçekçi alt/üst sınırlar (`MIN_ATTACK_MULTIPLIER = 0.45`, `MAX_DEFENSE_VULNERABILITY_MULTIPLIER = 1.85`) uygulanır ve `0.0 - 100.0` aralığında monotonik normalize edilmiş `adjusted_offense_rating` ile `adjusted_defense_rating` üretilir.

### 2.2. Dixon-Coles / Poisson Skor Dağılım Matrisi (`engine/predictors/poisson.py`)
- **Beklenen Goller (`calculate_expected_goals`):**
  - $\lambda = \text{Home\_Attack} \times \text{Away\_Defense} \times \text{Home\_Advantage}$
  - $\mu = \text{Away\_Attack} \times \text{Home\_Defense}$
- **Dixon-Coles Düşük Skor Korelasyonu (`dixon_coles_tau`, `build_score_matrix`):**
  - `0-0`, `0-1`, `1-0` ve `1-1` hücrelerine $\rho = -0.10$ parametresiyle $\tau_{\lambda,\mu}(x, y)$ düzeltmesi uygulanır.
  - $0 \le x, y \le 5$ ($6 \times 6 = 36$ skor hücresi) matrisi kendi toplam kütlesine bölünerek olasılık toplamının tam `1.0` olması garanti altına alınır.
- **Skor Sıralaması ve Güven Oranı (`predict_score_distribution`, `calculate_confidence_rate`):**
  - En yüksek olasılıklı skor `predicted_home_score` ve `predicted_away_score` olarak seçilir; ilk 3 skor azalan olasılık sırasıyla `list[ScoreProbability]` (`top_scores_json`) olarak döndürülür.
  - `confidence_rate`, en olası skorun olasılığı (`top_score_prob`), baskın maç sonucu olasılığı (`max(1, X, 2)`) ve takımların oynanmış maç derinliği (`sample_matches`) birleştirilerek `[0.15, 0.95]` bandında üretilir.

### 2.3. Türkçe Spor Analiz Üreticisi (`engine/predictors/analyst.py`)
- **`match_overview_text`:** Derbi/zirve veya güç dengesi tespiti, toplam xG ve 2.5 üst olasılığı üzerinden tempo/kısırlık teşhisi, maçın en kritik kırılma faktörü (en yüksek sakatlık kaybı veya hücum-savunma eşleşme farkı) ve Dixon-Coles ilk 3 skor senaryosunu birleştirir.
- **`home_analysis_text`:** Düzeltilmiş 0-100 hücum/savunma reytingleri, son 5 maç form serisi ve puanı, iç saha maç başı atılan/yenilen gol ortalamaları ve sakat/cezalı oyuncuların isim-mevki-neden bazında yüzdesel etkisini açıklar.
- **`away_analysis_text`:** Dış saha karnesi ve gol ortalamaları, son form grafiği, genel ve deplasman kalesini gole kapatma (`clean sheet`) performansı ve eksik oyuncuların yarattığı savunma/hücum zaafiyetlerini somut rakamlarla yorumlar.

### 2.4. Tahmin ve Analiz Servisi (`engine/predictors/service.py`)
- `PredictionService` ve `run_prediction_pipeline()` fonksiyonu; maçları lig bazında ayırarak her `SCHEDULED` karşılaşma için `Prediction` ve `TeamAnalysis` Pydantic v2 nesnelerini üretir.
- `persist=True` ve Supabase yapılandırılmışsa `predictions` ve `team_analyses` tablolarına `on_conflict="match_id"` ile toplu `upsert` yapar (`match.id` boş gelen kayıtlar için `matches` tablosundan otomatik ID eşlemesi içerir); aksi halde yerel model / `dict` / JSON çıktısı döndürür.

---

## 3. Karşılaşılan Detaylar / Engeller ve Uygulanan Çözümler

1. **Yerel Modda `Match.id = None` Kayıtlarının `Prediction.match_id > 0` Kısıtıyla Çakışma Riski:**
   - **Sebep:** `IngestionPipeline(persist=False)` çıktısındaki `Match` nesnelerinde veritabanı `id` alanı `None` iken, `Prediction` ve `TeamAnalysis` şemalarında `match_id: int = Field(..., gt=0)` zorunludur.
   - **Çözüm:** `PredictionService.run()` içinde yerel modda deterministik pozitif `match_id` ataması, Supabase modunda ise `matches` tablosundan `(round, home_team_id, away_team_id)` üzerinden otomatik ID geri doldurma (`_backfill_missing_match_ids`) eklendi.
2. **Dinamik Yüzde Sayılarında Türkçe Ek Uyumu (`%34'lik` vb.):**
   - **Sebep:** Canlı Süper Lig verisi üzerinde yapılan uçtan uca duman testinde dinamik yuvarlanan yüzdelerin sonuna sabit `'lik` eki geldiğinde bazı sayılarda ünlü uyumunun bozulduğu görüldü.
   - **Çözüm:** Sabit ek yerine her sayıyla dilbilgisi açısından tam uyumlu `"%{oran} oranındaki / düzeyindeki"` ve `"{lam:.2f} xG seviyesindeki"` ifadeleri kullanıldı.

---

## 4. Doğrulama ve Test Sonuçları

- **Statik Derleme (`py_compile`):** Tüm `engine/predictors/*.py` ve `engine/tests/test_predictors.py` dosyaları sıfır hatayla derlendi.
- **Tüm Birim ve Entegrasyon Testleri (`18/18 OK`):**
  - `python -m unittest discover -s engine/tests -v` -> **18/18 OK**
  - `python -m unittest -v` -> **18/18 OK**
  - **GÖREV-03 Test Kapsamı (`PredictorEngineTests` - 4 ana test metodu):**
    1. `test_ratings_calculation`: Baz hücum/savunma sıralaması, iç saha avantajı, `0-100` sınırları ve `FW` (`-%16`), `GK` (`+%22` zaafiyet), `MID` (`-%6` hücum / `+%5` zaafiyet) sakatlık etkileri doğrulandı.
    2. `test_poisson_probability_matrix`: Farklı $(\lambda, \mu)$ çiftlerinde $6 \times 6$ matris toplamının $1.0 \pm 0.01$ olduğu, ilk 3 skorun azalan sırası, `1-X-2` olasılık toplamı ve veri derinliğine duyarlı `confidence_rate` doğrulandı.
    3. `test_analyst_text_generation`: Türkçe analiz metinlerinin çok cümleli yapısı, derbi ve xG vurgusu, son form, gol yememe istatistiği ve sakat oyuncu isim/neden referansları doğrulandı.
    4. `test_service_prediction_pipeline`: `Prediction` ve `TeamAnalysis` çıktılarının `engine/db/schema.sql` kolonlarıyla birebir uyumu, `as_dict=True` çıktısı ve mock Supabase `upsert(on_conflict="match_id")` akışı doğrulandı.
- **Canlı Süper Lig Uçtan Uca Duman Testi:** `run_ingestion_pipeline(LeagueId.SUPER_LIG, persist=False)` çıktısı doğrudan `run_prediction_pipeline(..., only_next_round=True, persist=False)` servisine verilerek sıradaki haftanın `9` maçı için eksiksiz `Prediction` ve `TeamAnalysis` üretildiği doğrulandı.
