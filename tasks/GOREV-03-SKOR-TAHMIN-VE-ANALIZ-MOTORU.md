# GÖREV-03: Skor Tahmin Motoru, Sakatlık Etki Modeli ve Takım Analiz Üreticisi

## 1. Amaç ve Kapsam
Bu görevin amacı; 4 hedef lig için oynanmış maç verileri ve sakatlık/ceza durumlarını birleştirerek:
1. İstatistiksel **Dixon-Coles / Poisson** skor tahmin modelini kurmak,
2. Sakatlık ve cezaların mevkilerine ve ciddiyetlerine göre takımların hücum/savunma katsayılarını dinamik olarak zayıflatan **Sakatlık Etki Modelini (Injury Impact Model)** geliştirmek,
3. Her maç için zengin, akıcı ve gerekçeli **Takım ve Maç Analiz Metinleri (Explainable Football Analyst Engine)** üretmek,
4. Çıktıları doğrudan `engine.models.schemas` altındaki `Prediction` ve `TeamAnalysis` modellerine dönüştürmektir.

---

## 2. Teknik Şartname

### A. Modül Mimarisi (`engine/predictors/`)
Aşağıdaki bileşenler oluşturulmalıdır:

1. **`engine/predictors/ratings.py` (Takım Güç ve Sakatlık Etki Modeli):**
   - **Baz Hücum / Savunma Gücü:** Oynanmış maçlardan her takım için iç saha ve deplasman bazlı atılan/yenilen gol ortalamalarını lig genel ortalamasına göre oranlayan temel hücum ve savunma katsayıları (`base_attack`, `base_defense`, `home_advantage`).
   - **Sakatlık Zayıflatma Çarpanı (Injury Degradation Factor):**
     - Bir takımdaki sakat ve cezalı oyuncular listesini alır.
     - Mevki katsayıları:
       - `GK` (Kaleci): Savunma direncini düşürür (yenilen gol beklentisini artırır; HIGH: +%18-25, MEDIUM: +%10, LOW: +%3).
       - `DEF` (Stoper/Bek): Savunma direncini düşürür (HIGH: +%12, MEDIUM: +%7 per oyuncu).
       - `MID` (Orta Saha): Hem top kazanmayı hem hücum beslemesini etkiler (Savunma zaafiyeti +%5, Hücum gücü -%6).
       - `FW` (Santrafor/Kanat): Hücum bitiriciliğini doğrudan düşürür (HIGH: -%16, MEDIUM: -%8, LOW: -%3).
     - Netice: `adjusted_offense_rating` ve `adjusted_defense_rating` (0.0 - 100.0 arası normalize skorlar).

2. **`engine/predictors/poisson.py` (Dixon-Coles / Poisson Dağılım Matrisi):**
   - Ev sahibi beklenen gol ($\lambda$) ve Deplasman beklenen gol ($\mu$) parametrelerini hesaplar:
     $$\lambda = \text{Home\_Attack} \times \text{Away\_Defense} \times \text{Home\_Advantage}$$
     $$\mu = \text{Away\_Attack} \times \text{Home\_Defense}$$
   - Dixon-Coles düşük skor düzeltmesini ($\tau_{x,y}$ ile 0-0, 1-0, 0-1, 1-1 katsayı ayarlaması) veya Poisson bağımsız olasılık matrisini $0 \le x, y \le 5$ için hesaplar.
   - En olası 1. skor (`predicted_home_score`, `predicted_away_score`) ve en olası ilk 3 skor listesini (`top_scores_json`, örn: `[{"score": "2-1", "prob": 0.165}, ...]`) üretir.
   - Güven oranını (`confidence_rate`: en olası ilk skorun olasılığı ve veri derinliğine bağlı normalizasyon) hesaplar.

3. **`engine/predictors/analyst.py` (Doğal Spor Analiz Metni Üreticisi):**
   - Kullanıcının bültende okuyacağı **profesyonel maç ve takım analiz raporlarını** üretir:
     - `match_overview_text`: Maçın genel temposu, gol beklentisi (yüksek tempolu/kısır), derbi/denge durumu ve en kritik kilit faktör.
     - `home_analysis_text`: Ev sahibi takımın son form grafiği, iç saha performansı ve sakatlıkların hücum/savunma dengesine net etkisi.
     - `away_analysis_text`: Deplasman takımının deplasman direnci, kalesini gole kapatma başarısı ve eksik oyuncuların yarattığı zaafiyetler.
   - Şablonlar zengin, doğal Türkçe ifadeler ve somut veri referansları içermelidir (robotik veya tekrara düşen tek satırlık çıktılar yerine analitik spor yorumcusu dili).

4. **`engine/predictors/service.py` (Tahmin & Analiz Servisi):**
   - Oynanmış maçlar (`FINISHED`), sıradaki maçlar (`SCHEDULED`) ve güncel sakatlıkları girdi olarak alır.
   - Her sıradaki maç için:
     1. Reytingleri hesaplar,
     2. Skor olasılık matrisini çıkarır,
     3. Analiz metinlerini üretir,
     4. `Prediction` ve `TeamAnalysis` Pydantic v2 nesnelerini oluşturur.
   - İsteğe bağlı olarak Supabase `predictions` ve `team_analyses` tablolarına `upsert` eder veya yerel sözlük/JSON çıktısı verir.

---

## 3. Doğrulama ve Test Kriteri
- `engine/tests/test_predictors.py` dosyası yazılmalıdır:
  1. `test_ratings_calculation`: Baz reytinglerin hesaplandığı ve forvet/kaleci sakatlığı eklendiğinde hücum/savunma oranlarının beklendiği yönde değiştiği doğrulanmalıdır.
  2. `test_poisson_probability_matrix`: Olasılık matrisinin toplamının $1.0 \pm 0.01$ olduğu, en olası skor ve `top_scores_json` listesinin sıralı ve geçerli olduğu doğrulanmalıdır.
  3. `test_analyst_text_generation`: Analiz metinlerinin boş olmadığı, sakatlık durumlarına atıfta bulunduğu ve Türkçe dilinde anlamlı paragraflar ürettiği doğrulanmalıdır.
  4. `test_service_prediction_pipeline`: Sıradaki maçlar için `Prediction` ve `TeamAnalysis` Pydantic modellerinin `schema.sql` kolonlarıyla tam uyumlu oluştuğu test edilmelidir.
- Tüm testler `python -m unittest discover -s engine/tests -v` ile çalıştırılmalı ve `tasks/GOREV-03-RAPOR.md` dosyasına kaydedilmelidir.
