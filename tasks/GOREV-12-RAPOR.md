# GÖREV-12 Uygulama ve Doğrulama Raporu: Beklenen Gol Ölçek Düzeltmesi, Walk-Forward Backtest, Güvenlik/Hijyen ve Mobil Üretim Sertleştirmesi

**Tarih:** 2026-11-27  
**Durum:** ✅ TAMAMLANDI (Poisson Beklenen Gol Ölçek Düzeltmesi + 2.845 Maçlık Walk-Forward Backtest + API Auth & Supabase RLS + CI/Hijyen + Bulut Varsayılanlı HTTPS Release APK + Fiziksel Cihaz Doğrulaması %100 Başarılı)

---

## 1. Ön Aşama: `graphify` Bağımlılık Sorgusu Özeti

Uygulama öncesinde `graphify-out/graph.json` (`1,315` düğüm, `2,739` kenar, `70` topluluk) üzerinde BFS ve `get_neighbors` sorguları çalıştırılarak etki alanı doğrulandı:
- **`engine/predictors/poisson.py` (`calculate_expected_goals`, `predict_score_distribution`):** `service.py` (`PredictionService.run`), `predictors/__init__.py`, `test_predictors.py` ve `test_ht_ft_and_xg.py` tarafından çağrıldığı; `ratings.py` içindeki katsayıların zaten `baseline.avg_home_goals` ve `baseline.avg_away_goals` etrafında `~1.0` olarak normalize edildiği doğrulandı.
- **`engine/predictors/ratings.py` (`LeagueBaseline`, `calculate_league_baseline`):** Oynanmış maçlardan lig bazlı `avg_home_goals` ve `avg_away_goals` değerlerini sönümlemeli ürettiği görüldü.
- **`app.py` (`health`, `get_bulletin`, `sync`, `sync_v1`):** `engine/bulletin.py` (`get_cached_bulletin`, `update_bulletin_cache`) ve `engine/runner.py` (`run_full_cycle`) ile doğrudan bağlı olduğu haritalandı.
- **`mobile/lib/config/constants.dart` (`AppConstants`):** `BulletinApiService`, `HomeScreen`, `MatchDetailScreen` ve `DataTransparencyBanner` bileşenlerinin kök sabit kaynağı olduğu doğrulandı.

---

## 2. Alt Ajan 1: Matematiksel Model Düzeltmesi ve Walk-Forward Backtest (`engine/predictors/` & `engine/backtest/`)

### 2.1. Beklenen Gol Ölçek Düzeltmesi ve `DEFAULT_MAX_GOALS = 10`
- **`engine/predictors/poisson.py`:**
  - Eski formülde boyutsuz takım katsayıları (`~1.0`) lig gol ortalamasıyla çarpılmadığı için toplam beklenen goller `-%15` ila `-%20` düşük çıkıyor ve iç saha avantajı tutarsız ölçekleniyordu.
  - `calculate_expected_goals` ve `predict_score_distribution` imzaları `avg_home_goals` ve `avg_away_goals` parametreleriyle güncellendi:
    $$\lambda_{\text{raw}} = \text{avg\_home\_goals} \times \text{home\_attack} \times \text{away\_defense}$$
    $$\mu_{\text{raw}} = \text{avg\_away\_goals} \times \text{away\_attack} \times \text{home\_defense}$$
  - İç saha avantajı `avg_home_goals / avg_away_goals` oranında doğal olarak taşındığından `home_advantage` çarpanının iki kez sayılması engellendi (geriye dönük imza uyumu korundu).
  - `DEFAULT_MAX_GOALS = 10` (`0..10`, `11x11` matris) yapılarak yüksek skorlu maçlardaki olasılık kütlesi kırpılması ortadan kaldırıldı.
- **`engine/predictors/service.py`:**
  - Her lig için `baseline = calculate_league_baseline(lg_finished)` hesaplanarak `predict_score_distribution(...)` çağrıları `avg_home_goals=baseline.avg_home_goals` ve `avg_away_goals=baseline.avg_away_goals` ile beslendi.
- **Sentetik 20 Takımlı Eşit Güçlü Lig Birim Testi (`engine/tests/test_predictors.py`):**
  - `test_synthetic_20_team_equal_strength_league_scale_calibration`: 38 haftalık çift devreli eşit güçlü 20 takımlı sentetik ligde ortalama $\lambda$ ve $\mu$ sapmasının gerçekleşen lig ortalamalarına **`< %1.2`** (`< %3` eşiğinin altında) yakınsadığı ve dengeli eşleşmede Üst 2.5 olasılığının **`[%48, %53]`** aralığında yer aldığı kalıcı birim testiyle garanti altına alındı.

### 2.2. Walk-Forward Backtest Sonuçları (`python -m engine.backtest` -> `reports/backtest_baseline.md`)
- **Veri Seti & Protokol:** Football-Data.co.uk gerçek maç ve oran CSV'leri (`2425`, `2526`, `2627` sezonları; `T1` Süper Lig, `E0` Premier League, `SP1` La Liga, `F1` Ligue 1). Toplam `3.217` tamamlanmış maç ayrıştırıldı; her lig-sezonda `30` maçlık ısınma penceresi sonrasında **`2.845` maç** sıfır gelecek sızıntısı (`kickoff_date < D`) garantisiyle değerlendirildi.

#### Dört Lig Toplu Karşılaştırma Tablosu (`T1 + E0 + SP1 + F1`, `2.845` Maç)

| Model / Referans | Maç | RPS (↓) | Brier 1X2 (↓) | Log-Loss 1X2 (↓) | 1X2 İsabet (↑) | Tahmin λ+μ | Gerçek Gol | Tahmin Üst 2.5 | Gerçek Üst 2.5 | Üst 2.5 Sapma | Üst 2.5 Brier (↓) | Üst 2.5 Log-Loss (↓) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **Post-Fix (Yeni Ölçek, max=10)** | **2845** | **0.2039** | **0.5915** | **0.9919** | **%52.44** | **2.772** | **2.816** | **%51.58** | **%53.81** | **-2.23 puan** | **0.2480** | **0.6896** |
| Pre-Fix (Eski Ölçek, max=5) | 2845 | 0.2052 | 0.5970 | 0.9998 | %51.49 | 2.245 | 2.816 | %38.37 | %53.81 | -15.44 puan | 0.2710 | 0.7400 |
| Lig Ortalaması Sabit Baz | 2845 | 0.2306 | 0.6471 | 1.0702 | %44.64 | 2.784 | 2.816 | %52.58 | %53.81 | -1.23 puan | 0.2496 | 0.6923 |
| Piyasa (De-vigged Kapanış) | 2845 | 0.1947 | 0.5715 | 0.9626 | %55.11 | — | 2.816 | %53.59 | %53.81 | -0.23 puan | 0.2365 | 0.6654 |

#### Türkiye Süper Lig (`T1`) Özel Karşılaştırma Tablosu (`663` Maç)

| Model / Referans | Maç | RPS (↓) | Brier 1X2 (↓) | Log-Loss 1X2 (↓) | 1X2 İsabet (↑) | Tahmin λ+μ | Gerçek Gol | Tahmin Üst 2.5 | Gerçek Üst 2.5 | Üst 2.5 Sapma | Üst 2.5 Brier (↓) | Üst 2.5 Log-Loss (↓) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **Post-Fix (Yeni Ölçek, max=10)** | **663** | **0.1958** | **0.5746** | **0.9689** | **%55.66** | **2.731** | **2.849** | **%50.59** | **%55.35** | **-4.76 puan** | **0.2485** | **0.6909** |
| Pre-Fix (Eski Ölçek, max=5) | 663 | 0.1979 | 0.5824 | 0.9787 | %53.24 | 2.174 | 2.849 | %36.59 | %55.35 | -18.77 puan | 0.2794 | 0.7592 |
| Lig Ortalaması Sabit Baz | 663 | 0.2291 | 0.6434 | 1.0652 | %44.95 | 2.745 | 2.849 | %51.65 | %55.35 | -3.70 puan | 0.2486 | 0.6904 |
| Piyasa (De-vigged Kapanış) | 663 | 0.1842 | 0.5515 | 0.9335 | %59.43 | — | 2.849 | %54.59 | %55.35 | -0.76 puan | 0.2324 | 0.6565 |

#### Diğer Ligler Özet Kırılımı (Pre-Fix -> Post-Fix)
- **Premier League (`E0`, `780` maç):** RPS `0.2100 -> 0.2092` | Brier `0.6155 -> 0.6113` | Log-Loss `1.0243 -> 1.0182` | Üst 2.5 Sapma `-18.77 -> -2.53 puan` | Üst 2.5 Brier `0.2871 -> 0.2551`.
- **La Liga (`SP1`, `794` maç):** RPS `0.2021 -> 0.2013` | Brier `0.5867 -> 0.5833` | Log-Loss `0.9865 -> 0.9815` | Üst 2.5 Sapma `-9.92 -> -1.82 puan` | Üst 2.5 Brier `0.2490 -> 0.2403`.
- **Ligue 1 (`F1`, `608` maç):** RPS `0.2109 -> 0.2096` | Brier `0.6026 -> 0.5951` | Log-Loss `1.0087 -> 0.9972` | Üst 2.5 Sapma `-14.76 -> +0.38 puan` | Üst 2.5 Brier `0.2699 -> 0.2482`.
- **Çevrimdışı Birim Testleri (`engine/tests/test_backtest.py`):** El hesabı RPS/Brier/Log-Loss/de-vig doğrulaması, gelecek hafta skorları değiştirildiğinde önceki hafta tahminlerinin değişmediğini kanıtlayan sıfır sızıntı testi ve çevrimdışı CLI testi eklendi.

---

## 3. Alt Ajan 2: Güvenlik, RLS, Kod Kalitesi & Depo Hijyeni

### 3.1. API Güvenliği ve Gözlemlenebilirlik (`app.py`, `engine/tests/test_security_api.py`)
- `require_sync_api_key`: `X-API-Key` veya `Authorization: Bearer <token>` başlığını UTF-8 baytları üzerinde `secrets.compare_digest` ile sabit zamanda `SYNC_API_KEY` karşısında doğrular; eksik/hatalı/yapılandırılmamış anahtarda `HTTP 401` (`WWW-Authenticate: Bearer`) döner.
- Korunan uç noktalar: `POST /sync`, `POST /api/v1/sync`, `GET /api/v1/bulletin?refresh=true`.
- Herkese açık uç noktalar: `GET /api/v1/bulletin` (`refresh=false`), `GET /`, `GET /health`, `GET /status`.
- `GET /health` yanıtına `bulletin_age_seconds` (`float | None`) alanı eklendi.

### 3.2. Supabase Row Level Security (`engine/db/schema.sql`)
- 6 tablonun tamamı (`leagues`, `teams`, `matches`, `injuries`, `predictions`, `team_analyses`) için `ALTER TABLE ... ENABLE ROW LEVEL SECURITY;` ve idempotent salt-okunur `SELECT` politikaları (`FOR SELECT USING (true)`) eklendi; yazma yetkisi yalnızca `service_role` anahtarına bırakıldı.

### 3.3. Statik Analiz, Gerçek Hata Düzeltmeleri ve CI (`pyproject.toml`, `.github/workflows/ci.yml`)
- `engine/bulletin.py`: Tarih alanlarında `isinstance(..., date)` tip daraltması yapılarak olası `None.isoformat()` çökme riski giderildi.
- `engine/scrapers/pipeline.py`: Aynı kapsamda çakışan `st` (`ScrapedTeam` vs `FootballDataTeamStats` -> `fd_stats`) ve `tid` (`inj_team_id`) değişken tipleri ayrıştırıldı.
- `engine/scrapers/sources/espn.py`: Döngü içi kapanışta `B023` değişken yakalama hatası varsayılan argümanla (`status_val: str = norm_status`) giderildi.
- `pyproject.toml` (`ruff` + `mypy`) ve push/PR `.github/workflows/ci.yml` iş akışı eklendi.

### 3.4. Depo Hijyeni ve Gizlilik (`LICENSE`, `.gitignore`)
- Kök dizine standart MIT `LICENSE` (`Copyright (c) 2026`) eklendi.
- `.gitignore` dosyasına `GEMINI.md` ve `CLAUDE.md` eklendi; `git rm --cached --ignore-unmatch GEMINI.md CLAUDE.md` ile yerel dosyalar diskte korunarak (`Test-Path == True`) public git takibinden çıkarıldı (`git ls-files GEMINI.md CLAUDE.md` -> boş).

---

## 4. Alt Ajan 3: Mobil Sertleştirme, Canlı Bulut Yayını ve Fiziksel Cihaz Doğrulaması

### 4.1. Mobil Üretim Sertleştirmesi (`mobile/`)
- **Üretim Varsayılan URL (`mobile/lib/config/constants.dart`):** Varsayılan `apiUrl` / `apiBaseUrl` doğrudan `https://naziffarm4.github.io/futbol-skor-analiz/bulletin.json` yapıldı; yerel LAN IP (`10.19.138.89`) kod ve testlerden tamamen temizlendi (`allowsUsbFallback == false`).
- **Cleartext Trafik Ayrımı:** `android:usesCleartextTraffic="true"` ana manifestten (`src/main/AndroidManifest.xml`) çıkarılarak yalnızca `src/debug/AndroidManifest.xml` içine (`tools:node="merge"`) taşındı; Release APK yalnızca HTTPS kabul eder.
- **Dürüst Etiketleme & Sorumluluk Reddi:** `"Güven"` etiketi **`"Model Netliği"`** (`Model Netliği: %...`) olarak güncellendi; hem `HomeScreen` hem `MatchDetailScreen` bilgi şeridine *"İstatistiksel analiz amaçlıdır; kesin sonuç garantisi veya bahis tavsiyesi değildir."* feragat metni eklendi (`360x800` dar ekranda `0` taşma).

### 4.2. Test, Statik Analiz ve Canlı GitHub Actions / GitHub Pages Kanıtları
- **`python -m ruff check engine app.py`:** `All checks passed!` (`0` hata)
- **`python -m mypy ...`:** `Success: no issues found in 10 source files` (`0` hata)
- **`python -m unittest discover -s engine/tests -v`:** **`61/61` test başarılı (`0` hata)**
- **`flutter analyze`:** `No issues found!` (`0` sorun)
- **`flutter test`:** **`11/11` test başarılı**
- **GitHub Push (`main`):** Commit `bee0d2b` (`https://github.com/naziffarm4/futbol-skor-analiz`)
- **GitHub Actions `ci.yml`:** Run [`46051045194`](https://github.com/naziffarm4/futbol-skor-analiz/actions/runs/46051045194) -> **`success`**
- **GitHub Actions `update_bulletin.yml`:** Run [`46051116370`](https://github.com/naziffarm4/futbol-skor-analiz/actions/runs/46051116370) -> **`success`**
- **Canlı `bulletin.json` (`HTTP 200 OK`):** `generated_at: "2026-11-27T18:40:40.227896+00:00"`, `5/5` kaynak (`ESPN, Football-Data, Understat, Transfermarkt, SportsGambler`), `38` maçta düzeltilmiş Poisson ölçeğiyle gerçekçi skor dağılımı (`1-1`: 22, `2-1`: 4, `2-0`: 3, `0-2`: 3, `1-0`: 3, `0-0`: 2, `0-1`: 1 — örn. `Fenerbahçe vs Erzurumspor: 2-1`, `Real Betis vs Rayo Vallecano: 2-1`, `Brighton vs Newcastle: 2-0`, `Beşiktaş vs Galatasaray: 2-0`).

### 4.3. Final Release APK ve Fiziksel Telefon (`VKVCX8EQBE9PAIXG`) Kanıtları
- **Derleme Komutu (`--dart-define` olmadan doğrudan varsayılan bulut URL'siyle):**
  `flutter build apk --release --target-platform android-arm64`
- **APK Yolu & Boyutu:** `E:\apk\futbol\mobile\build\app\outputs\flutter-apk\app-release.apk` — `17,197,080` bayt (`16.40 MiB`)
- **APK SHA-256:** `A486C1C87C01BEDA4F759FF841ED51F42D1D3F8580F44E1D8DE5847F91049E38`
- **İkili (`lib/arm64-v8a/libapp.so`) & Manifest Doğrulaması:**
  - `https://naziffarm4.github.io/futbol-skor-analiz/bulletin.json` -> `0x22EE6` konumunda gömülü.
  - `Model Netliği: %` -> `0x2D964` konumunda gömülü.
  - `İstatistiksel analiz amaçlıdır; kesin sonuç garantisi veya bahis tavsiyesi değildir.` -> `0x2E3B5` konumunda gömülü.
  - `10.19.138.89` ve Release `usesCleartextTraffic` -> **`ABSENT` (`0` eşleşme)**.
- **USB Tünelsiz Fiziksel Cihaz Doğrulaması (`VKVCX8EQBE9PAIXG`, `model:2602EPTC0G`):**
  - `adb reverse --remove-all` + `adb reverse --list` -> `0` aktif tünel.
  - `adb install -r app-release.apk` -> `Success`; soğuk başlatma `TotalTime: 204 ms` (`Impeller Vulkan`, `PID 32199`).
  - Ana ekranda doğrudan buluttan yüklenen `5/5 Kaynak Doğruladı • Sezon: 2026-2027 • Güncelleme: 27 Kas 21:40`, sorumluluk reddi şeridi, `Model Netliği: %54` / `Model Netliği: %57` rozetleri ve yeni ölçekli `1 - 1` tahminleri `uiautomator dump` ile doğrulandı.
  - `MatchDetailScreen` (`Çaykur Rizespor vs Kasımpaşa`): `İY 1 - 0`, `MS 1 - 1`, `İY/MS: 1/1`, `Model Netliği: %54`, Top 3 skor ve İY/MS olasılık çubukları eksiksiz doğrulandı.
  - `adb logcat -d` uygulama hata taraması (`E/flutter`, `FATAL EXCEPTION`, `BulletinApiException`, `SocketException`, `HandshakeException`, `CleartextNotPermitted`, `RenderFlex`): **`0` uygulama hatası** (`PID 32199` üzerinde yalnızca Xiaomi HyperOS/MediaTek sistem satırları `Zygote`/`FPSGO`/`MI-PreRender` görülmüştür).

---

## 5. Karşılaşılan Hatalar / Engeller ve Uygulanan Çözümler

1. **Yerel İSS SNI Engeli (`www.football-data.co.uk`):**
   - **Kök Neden:** Yerel ağda tarihsel `2425/2526/2627` CSV indirmesi SNI zaman aşımına takıldı.
   - **Çözüm:** `engine/backtest/runner.py` içinde birincil `football-data.co.uk` adresini deneyip zaman aşımında `web.archive.org/web/2026id_/` bayt-birebir (`id_`) ham CSV yansısına düşen otomatik yedek eklendi; `3.217` gerçek maç verisi eksiksiz işlendi.
2. **`secrets.compare_digest` UTF-8 Karakter Güvenliği (`app.py`):**
   - **Kök Neden:** `secrets.compare_digest(str, str)` ASCII dışı karakter içeren başlıklarda `TypeError` (`HTTP 500`) fırlatabilmektedir.
   - **Çözüm:** Karşılaştırma öncesi her iki dizge `.encode("utf-8")` ile bayt dizisine çevrildi ve birim testiyle doğrulandı.
3. **Debug Manifest Birleştirme Uyarısı (`AndroidManifest.xml`):**
   - **Kök Neden:** Ana manifestten `usesCleartextTraffic` çıkarılınca debug manifestteki `tools:replace` özniteliği hedef bulamadığı için Gradle uyarı üretti.
   - **Çözüm:** `tools:node="merge"` kullanılarak hem debug hem release manifest birleştirmesi `0` uyarıyla tamamlandı.
4. **Fiziksel Telefonun Derleme Bitiminde Bağlı Olmaması:**
   - **Kök Neden:** APK derlemesi bittiğinde `adb devices` listesi boştu.
   - **Çözüm:** Kullanıcı onayıyla telefon USB üzerinden bağlandıktan hemen sonra `VKVCX8EQBE9PAIXG` cihazına kurulum ve tünelsiz canlı doğrulama tamamlandı.

---

## 6. Kapanış: `/graphify --update` Bilgi Grafiği Güncellemesi

Görev kapanışında `/graphify --update` çalıştırılarak yeni `engine/backtest/*` paketi, `reports/backtest_baseline.md`, güncellenen `poisson.py` / `service.py` / `app.py` / `mobile/*` modülleri ve `tasks/GOREV-12-RAPOR.md` belgesi `graphify-out/` bilgi grafiğine işlenmiştir.
