# Veri Kaynakları, Kota Yönetimi ve Uyumluluk Mimarisi

Bu belge, tahmin ve bülten motorunun kullandığı resmi API'leri, açık veri kaynaklarını, kota/önbellek koruma mekanizmasını (`QuotaBudgetTracker`) ve Faz 0 canlı doğrulama bulgularını açıklar. Gizli anahtarlar hiçbir zaman kod deposuna, loglara veya tanılama çıktılarına yazılmaz (`<API_FOOTBALL_KEY>`, `<THE_ODDS_API_KEY>`, `***REDACTED***`).

---

## 1. Aktif Veri Kaynakları ve Rolleri

| Kaynak | Tür | Ana Rolü | Kimlik Doğrulama | Kota / Sınır |
|---|---|---|---|---|
| **The Odds API v4** (`api.the-odds-api.com`) | Resmi REST API | 4 lig için Avrupa bahis büroları (`regions=eu`) 1X2 (`h2h`) ve 2.5 Alt/Üst (`totals`) konsensüs marjsız olasılıkları | `?apiKey=<THE_ODDS_API_KEY>` (URL tanılama çıktılarında `***REDACTED***` olarak maskelenir) | Aylık **500 kredi** (`h2h,totals` + `eu` = çağrı başına 2 kredi) |
| **API-Football v3** (`v3.football.api-sports.io`) | Resmi REST API | Fikstür, ilk yarı / maç sonu skorları (`score.halftime` / `score.fulltime`), hafta numarası ve sakatlık/eksik kadro kayıtları | `x-apisports-key: <API_FOOTBALL_KEY>` | Günlük **100 istek**, dakikada **10 istek** (Ücretsiz planda sezon kapsamı kısıtı kontrol edilir) |
| **ESPN Public Site API** (`site.api.espn.com`) | Açık JSON API | Canlı puan durumu, oynanmış maç skorları ve gelecek 21 günlük takvim penceresi (`?dates=YYYYMMDD-YYYYMMDD`) | Gerektirmez | Kibar HTTP istemcisi |
| **Football-Data.co.uk & OpenFootball** | Açık CSV / JSON | Maç başı İY/MS golleri (`HTHG`, `HTAG`, `FTHG`, `FTAG`), şut, isabetli şut, korner, kart ve geçmiş piyasa kapanış oranları | Gerektirmez | Statik CSV/JSON |
| **Understat & Şut Tabanlı xG Vekili** | Açık İstatistik | Takım bazlı beklenen gol (`xG` / `xGA`) metrikleri; kapsam dışı liglerde şut/isabetli şut kalibrasyonu | Gerektirmez | Kibar HTTP istemcisi |
| **SportsGambler / TheSportsDB** | İkincil Çapraz Kaynak | Sakat ve cezalı oyuncu çapraz doğrulaması ve yedek puan durumu | Gerektirmez | Kibar HTTP istemcisi |
| **Transfermarkt** (`transfermarkt.com.tr`) | Kibar HTTP İstemcisi | Yerel/erişilebilir ağlarda fikstür ve sakatlık verisi; veri merkezi IP'lerinde HTTP 202/403 döndüğünde tarayıcı taklidi yapılmaz, boru hattı kesintisiz olarak resmi API + ESPN + Football-Data yedeklerine geçer | Gerektirmez | `min_delay` / `max_delay` hız sınırlamalı `httpx` |

### Lig Eşleme Tablosu

| Lig (`LeagueId`) | API-Football `league` ID | The Odds API `sport_key` | ESPN `slug` | Football-Data Kodu |
|---|---|---|---|---|
| `super_lig` (Süper Lig) | `203` | `soccer_turkey_super_league` | `tur.1` | `T1` |
| `premier_league` (Premier League) | `39` | `soccer_epl` | `eng.1` | `E0` |
| `la_liga` (La Liga) | `140` | `soccer_spain_la_liga` | `esp.1` | `SP1` |
| `ligue_1` (Ligue 1) | `61` | `soccer_france_ligue_1` | `fra.1` | `F1` |

---

## 2. Kota Koruma ve Disk Önbellek Mimarisi (`QuotaBudgetTracker`)

Ücretsiz plan kotalarının (özellikle The Odds API aylık 500 kredi ve API-Football günlük 100 istek sınırının) tekrarlı yerel çalışmalarda veya günde iki kez tetiklenen GitHub Actions iş akışlarında tükenmemesi için `QuotaBudgetTracker` devreye alınmıştır:

1. **6 Saatlik Disk Önbelleği (`engine/data/api_cache/`):**
   - Her GET isteği `sha256(provider + endpoint + sıralı_gizli_olmayan_parametreler)` anahtarıyla diske yazılır.
   - Önbellek dosyalarında **asla** `apiKey` veya `x-apisports-key` değeri tutulmaz.
   - Varsayılan TTL **6 saat** (`21600` saniye) olduğundan, aynı zaman penceresindeki tekrar çalışmalar **0 kredi** harcar.
2. **Kalan Kota Eşiği (`< 15` Koruma Kalkanı) ve `engine/data/quota_budget.json`:**
   - API-Football yanıtlarından `x-ratelimit-requests-remaining` ve `x-ratelimit-requests-limit` başlıkları (UTC gün bazında sıfırlanır) izlenir.
   - The Odds API yanıtlarından `x-requests-remaining`, `x-requests-used` ve `x-requests-last` başlıkları (UTC ay bazında sıfırlanır) izlenir.
   - Bilinen kalan kota **`15`'in altına düştüğünde** (`remaining < 15`), önbellekte taze kayıt yoksa yeni ağ çağrısı otomatik olarak durdurulur; varsa bayat (stale) önbellek verisi veya zarif tanılama (`diagnostic`) döndürülerek bülten üretiminin çökmesi önlenir.
3. **Sır Sızıntısı Koruması (`repr=False` ve `redact_secret`):**
   - `engine/config.py` içindeki `Settings` veri sınıfında `api_football_key` ve `the_odds_api_key` alanları `field(default="", repr=False)` ile tanımlanmıştır.
   - Tüm hata ve tanılama URL'leri `redact_secret()` süzgecinden geçirilerek `?apiKey=***REDACTED***` biçiminde maskelenir.

---

## 3. Kullanım Koşulları ve Sıfır Bot/WAF Atlatma İlkesi

`engine/scrapers/base.py` içerisindeki tüm başsız tarayıcı (Playwright) ve WAF atlatma mekanizmaları kalıcı olarak kaldırılmıştır:
- `--disable-blink-features=AutomationControlled`, `HeadlessChrome/` User-Agent değiştirme ve `aws-waf-token` çerez yoklama döngüleri **kullanılmaz**.
- `BaseScraper` yalnızca hız sınırlamalı (`min_delay` / `max_delay`) ve geçici sunucu hatalarında (`429, 500, 502, 503, 504`) üstel geri çekilme (exponential backoff) uygulayan temiz bir `httpx.Client` sarmalayıcısıdır.
- Bir kaynak HTTP `202` (WAF doğrulaması) veya `>= 400` döndürdüğünde başsız tarayıcı başlatılmaz; doğrudan `ScraperHTTPError` üretilir ve `IngestionPipeline` çoklu kaynak yedekleme katmanına geçer.

---

## 4. Faz 0 Canlı Doğrulama Bulguları (Maskelenmiş Özet)

Faz 0 kapsamında yalnızca 4 canlı HTTP çağrısı harcanarak her iki resmi API anahtarı ve yanıt şemaları doğrulanmıştır:

### 4.1. HTTP Yanıt ve Kota Başlıkları Özeti

| Çağrı | Uç Nokta (Maskelenmiş) | HTTP Durumu | Yanıt Başlıkları | Sonuç / Not |
|---|---|---|---|---|
| **1** | `GET https://v3.football.api-sports.io/fixtures?league=203&season=2025` | `200 OK` | Kota düşmedi | `errors.plan`: *"Free plans do not have access to this season, try from 2022 to 2024."* (`ApiFootballAdapter` bu plan kısıtını HTTP 200 gövdesinden yakalayıp tanılama kaydına işler ve gereksiz `/injuries` çağrısını atlar) |
| **2** | `GET https://v3.football.api-sports.io/fixtures?league=203&season=2024` | `200 OK` | `x-ratelimit-requests-limit: 100`, `x-ratelimit-requests-remaining: 99`, `x-ratelimit-limit: 10`, `x-ratelimit-remaining: 9` | **342 fikstür** (`score.halftime` ve `score.fulltime` + `Regular Season - N` hafta bilgisi doğrulandı) |
| **3** | `GET https://v3.football.api-sports.io/injuries?league=203&season=2024` | `200 OK` | `x-ratelimit-requests-limit: 100`, `x-ratelimit-requests-remaining: 98` | **1750 sakatlık/eksik kaydı** (`player.name`, `player.type`, `player.reason`, `team.name` şeması doğrulandı) |
| **4** | `GET https://api.the-odds-api.com/v4/sports/soccer_turkey_super_league/odds?regions=eu&markets=h2h,totals&oddsFormat=decimal&apiKey=***REDACTED***` | `200 OK` | `x-requests-remaining: 498`, `x-requests-used: 2`, `x-requests-last: 2` | **8 canlı Süper Lig maçı**, maç başına **20–21 Avrupa bahis bürosu** oranı |

### 4.2. Canlı Süper Lig Marjdan Arındırılmış (De-Vigged) Konsensüs Olasılık Örnekleri

Her bahis bürosu için $q_i = 1 / \text{oran}_i$ ve toplam marj $S = \sum q_i$ hesaplanarak $p_i = q_i / S$ ile bahisçi marjı (overround) temizlenmiş, ardından tüm büroların ortalaması alınarak $\sum p = 1.0$ olacak biçimde normalize edilmiştir:

| Maç | Başlangıç (UTC) | Büro Sayısı | Ortalama 1X2 Overround | Marjsız MS1 / X / MS2 | Marjsız 2.5 Üst / 2.5 Alt |
|---|---|---:|---:|---|---|
| **Samsunspor vs Gençlerbirliği SK** | `2026-11-28T13:00:00Z` | 21 | `1.0837` | `%50.39` / `%26.13` / `%23.48` | `%51.61` / `%48.39` |
| **Gazişehir Gaziantep vs Amed SK** | `2026-11-28T16:00:00Z` | 21 | `1.0835` | `%28.10` / `%25.76` / `%46.14` | `%56.40` / `%43.60` |
| **Çorum FK vs Kocaelispor** | `2026-11-29T10:30:00Z` | 20 | `1.0853` | `%49.66` / `%26.70` / `%23.64` | `%49.74` / `%50.26` |
| **Eyüpspor vs Başakşehir** | `2026-11-29T13:00:00Z` | 20 | `1.0856` | `%14.08` / `%19.82` / `%66.10` | `%59.78` / `%40.22` |
