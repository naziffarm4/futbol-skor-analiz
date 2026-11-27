# GÖREV-02: Kamuya Açık Veri Toplama Motoru (Scrapers & Ingestion Pipeline)

## 1. Amaç ve Kapsam
Bu görevin amacı; 4 hedef lig (Süper Lig, Premier League, La Liga, Ligue 1) için kamuya açık web kaynaklarından fikstür, maç sonuçları ve özellikle **sakatlık / ceza verilerini** otonom olarak toplayan, temizleyen ve Pydantic modellerine dönüştüren veri toplama altyapısını kurmaktır.

Bu modül:
- Transfermarkt üzerinden 4 ligin güncel sakatlık ve ceza listelerini çekecektir.
- Kamuya açık fikstür ve maç sonuçlarını ayrıştıracaktır.
- Bot korumalarına karşı nazik (polite crawling: rate-limiting, gerçekçi başlıklar, exponential backoff) bir HTTP altyapısına sahip olacaktır.
- Çekilen verileri `engine.models.schemas` modellerine dönüştürüp Supabase kayıt formatına hazır hale getirecektir.

---

## 2. Teknik Şartname

### A. Modül Mimarisi (`engine/scrapers/`)
Aşağıdaki dosya ve bileşenler oluşturulmalıdır:

1. **`engine/scrapers/base.py` (Temel HTTP ve Ayrıştırma İstemcisi):**
   - Gerçekçi `User-Agent` ve tarayıcı başlıkları (`Accept-Language`, `Referer` vb.).
   - İstekler arası gecikme (rate limiting: 1-2 saniye bekleme).
   - Ağ hataları ve 429/503 durumlarında yeniden deneme mekanizması (`httpx` ile retry + backoff).
   - HTML yanıtlarını `BeautifulSoup` (lxml / html.parser) ile güvenli ayrıştırma yardımcıları.

2. **`engine/scrapers/injuries.py` (Sakatlık ve Ceza Scraper'ı):**
   - Transfermarkt lig URL kodları:
     - Süper Lig: `TR1` (`/super-lig/sperrenundverletzungen/wettbewerb/TR1`)
     - Premier League: `GB1` (`/premier-league/sperrenundverletzungen/wettbewerb/GB1`)
     - La Liga: `ES1` (`/laliga/sperrenundverletzungen/wettbewerb/ES1`)
     - Ligue 1: `FR1` (`/ligue-1/sperrenundverletzungen/wettbewerb/FR1`)
   - Ayrıştırılacak Alanlar:
     - Takım adı
     - Oyuncu adı
     - Mevki (GK, DEF, MID, FW eşlemesi)
     - Sakatlık/ceza nedeni (örn: "Çapraz bağ", "Sarı kart cezalısı")
     - Tahmini dönüş tarihi
     - **Otomatik Etki Derecesi (Impact Level):** Sakatlığın ciddiyetine veya oyuncunun durumuna göre `HIGH`, `MEDIUM`, `LOW` hesaplama mantığı (örn. 3+ aydan uzun veya ameliyat -> HIGH; ufak sakatlık/şüpheli -> LOW/MEDIUM).

3. **`engine/scrapers/fixtures.py` (Fikstür ve Takım Scraper'ı):**
   - 4 ligin haftalık fikstürünü, oynanmış maç skorlarını ve sıradaki haftanın maç eşleşmelerini çeker.
   - Takım isimlerini standartlaştırır (`Team` modeli ile eşleme).
   - Maç tarihi, saati, hafta (`round`) ve durum (`SCHEDULED`, `FINISHED`) bilgilerini çıkarır.

4. **`engine/scrapers/pipeline.py` (Orkestratör):**
   - Belirtilen lig veya tüm 4 lig için sırayla:
     1. Takımları ve haftalık fikstürü çeker.
     2. Sakatlık/ceza listesini çeker.
     3. Elde edilen verileri `Match` ve `Injury` Pydantic modellerine dönüştürür.
     4. Supabase istemcisi yapılandırılmışsa doğrudan veritabanına `upsert` eder; yapılandırılmamışsa yerel JSON/dict olarak döndürür.

### B. Bağımlılıklar
- `engine/requirements.txt` dosyasına gerekiyorsa `beautifulsoup4` ve `lxml` eklenmelidir.

### C. Doğrulama ve Test Kriteri
- `engine/tests/test_scrapers.py` test dosyası yazılmalıdır:
  - Mock HTML örnekleri üzerinden `injuries.py` ve `fixtures.py` ayrıştırıcılarının doğru çalıştığı test edilmelidir (dış ağa bağımlı olmadan deterministik birim testleri).
  - Canlı tek bir lig/örnek sorgusu için entegrasyon smoke-testi yapılmalıdır (bağlantı hatası durumunda zarif şekilde atlayan/uyaran mekanizma).
  - Tüm modellerin `schema.sql` ve Pydantic modelleri ile uyumu doğrulanmalıdır.
- Tüm bulgular ve test çıktıları `tasks/GOREV-02-RAPOR.md` dosyasına kaydedilmelidir.
