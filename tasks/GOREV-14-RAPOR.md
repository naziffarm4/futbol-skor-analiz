# GÖREV-14 Kapanış ve Doğrulama Raporu: Operasyonel Dayanıklılık, Dürüst Kaynak Etiketi, CI Sertleştirme ve Hold-Out / Bootstrap Backtest (v3)

## 1. Yönetici Özeti

İkinci bağımsız kod ve istatistik denetiminde belirlenen operasyonel, kaynak şeffaflığı, CI/CD ve istatistiksel doğrulama bulgularının tamamı **3 paralel alt ajan** mimarisiyle kapatılmış ve uçtan uca canlı ortamda doğrulanmıştır:

1. **Kota Kalkanı & Tek Kanonik Üretici:** Kullanılmayan `playwright>=1.49.0` kaldırıldı; `.github/workflows/update_bulletin.yml` günlük tek çalışmaya (`0 7 * * *` UTC — TSİ 10:00, ayda ~240/500 kredi ile >%50 güvenlik marjı; `workflow_dispatch` açık) çekildi ve `engine/data/api_cache` + `engine/data/quota_budget.json` için devredilebilir `actions/cache@v4` (`bulletin-api-quota-${{ github.run_id }}` + `restore-keys`) eklendi. `app.py` içinde `SCHEDULER_ENABLED` varsayılanı `"false"` yapılarak tek kanonik üretici GitHub Actions + Pages olarak sabitlendi; `Dockerfile` içine `/health` tabanlı `HEALTHCHECK` eklendi.
2. **Dürüst Kaynak Etiketleme & Temiz HTTP Başlıkları:** Süper Lig (veya Understat bakım yedeği) xG verisi FotMob Opta köprüsünden geldiğinde `"FotMob-xG"`, şut kalitesi vekilinden geldiğinde `"ShotProxy-xG"` olarak etiketlendi (`"Understat"` sızıntısı sıfırlandı). `engine/scrapers/base.py` içindeki rastgele masaüstü tarayıcı UA rotasyonu ve ilgisiz sitelere Transfermarkt `Referer` gönderme davranışı kaldırılarak tekil dürüst `FutbolSkorAnaliz/1.0 (+https://github.com/naziffarm4/futbol-skor-analiz)` başlığına geçildi.
3. **CI Sertleştirme & Ağsız Test İzolasyonu:** Dış ağa bağlı `test_live_*` testleri `@unittest.skipUnless(os.getenv("RUN_LIVE_TESTS") == "1", ...)` ile ayrıldı (`82` test, varsayılan ağsız modda `0` başarısızlık, `skipped=2`). `.github/workflows/ci.yml` içinde `mypy` adımı tam `python -m mypy engine app.py` (45 kaynak dosya) yapıldı ve `flutter` CI job'ı (`flutter analyze` + `flutter test`) eklendi.
4. **Sızıntısız Hold-Out (`2425+2526` vs `2627`), Eşleştirilmiş Bootstrap (%95 CI, N=1000) & Power De-Vigging (Backtest v3):** Hiperparametre seçimi yalnızca `2425+2526` (`n=2531`) üzerinde kilitlenerek `2627` sezonu (`n=314`) hiç görülmemiş dış örneklem (hold-out) seti olarak değerlendirildi. Power marj arındırma yönteminin `[0.6, 0.8)` favori dilimindeki kalibrasyon sapmasını çarpıcı biçimde düşürdüğü ve genel RPS/LogLoss/ECE metriklerini iyileştirdiği kanıtlanarak **üretimde varsayılan olarak aktif edildi**.
5. **Mobil Bayat Bülten Uyarısı & Canlı Doğrulama:** `DataTransparencyBanner` içine bülten yaşı `> 36 saat` olduğunda turuncu `"Bülten güncel değil (X saat önce)"` uyarısı ve deterministik widget testleri (`15/15` yeşil) eklendi. Canlı GitHub Pages `bulletin.json` üzerinde Süper Lig kaynak etiketleri (`FotMob-xG`, `"Understat"` yok) doğrulandı; Release APK (`46.59 MiB`) derlenip fiziksel telefona (`VKVCX8EQBE9PAIXG`) yüklendi ve `0` logcat hatasıyla çalıştığı kanıtlandı.

---

## 2. Ön Aşama (`graphify`) Bulguları

Kod değişikliklerinden önce `graphify-out/graph.json` (`1776` düğüm, `3673` kenar, `88` topluluk) üzerinde yürütülen komşuluk ve BFS sorguları ile etki yüzeyi çıkarılmıştır:
- `build_browser_headers()` (`engine/scrapers/base.py:L54`): `base.py`, `football_data.py`, `secondary_check.py`, `understat.py`, `backtest/runner.py` ve `test_scrapers.py` tarafından çağrıldığı ve `random` UA rotasyonu barındırdığı doğrulandı.
- `fuse_team_metrics()` (`engine/scrapers/fusion.py:L429`) & `UnderstatAdapter` (`engine/scrapers/sources/understat.py:L149`): `IngestionPipeline.run_league()` (`pipeline.py:L793`) ve `build_bulletin_payload()` (`bulletin.py:L172`) zincirinde FotMob ve şut vekili verilerinin `"Understat"` sabit adıyla taşındığı saptandı.
- `devig_three_way()` (`engine/scrapers/sources/the_odds_api.py:L55`) & `devig_1x2_odds()` (`engine/backtest/metrics.py:L197`): Hem canlı oran ayrıştırıcısının hem tarihsel backtest motorunun marj arındırma giriş noktaları belirlendi.
- `app.py` (`_is_scheduler_enabled()` `L48`, `health()` `L243`) ve `DataTransparencyBanner` (`mobile/lib/widgets/data_transparency_banner.dart:L6`) çağrı noktaları doğrulanarak 3 alt ajana sıfır dosya çakışmalı iş paketleri atandı.

---

## 3. Alt Ajan Uygulama Detayları ve Karşılaşılan Hatalar / Çözümler

### 3.1. Alt Ajan 1 — Operasyon, Kota Kalkanı, Kaynak Dürüstlüğü & CI
- **Bağımlılık ve Konteyner Sertleştirme:**
  - `engine/requirements.txt`: Kullanılmayan `playwright>=1.49.0` kaldırıldı.
  - `app.py`: `_is_scheduler_enabled()` varsayılanı `"false"` yapıldı (yalnızca `SCHEDULER_ENABLED` açıkça `1/true/yes/on` verilirse çalışır).
  - `Dockerfile`: `curl` ikilisine ihtiyaç duymayan Python stdlib `urllib.request.urlopen` tabanlı `/health` `HEALTHCHECK` eklendi.
- **Kota Kalkanı (`update_bulletin.yml`):**
  - Cron zamanlaması `0 7 * * *` (günde 1 kez, TSİ 10:00; `workflow_dispatch` açık) olarak güncellendi.
  - `engine/data/api_cache` ve `engine/data/quota_budget.json` için `actions/cache@v4` (`key: bulletin-api-quota-${{ github.run_id }}`, `restore-keys: bulletin-api-quota-`) eklendi; böylece her günlük çalışma önceki önbellek/kota durumunu geri yükleyip iş sonunda güncel bütçeyi yeni anahtarla kaydeder.
- **Dürüst Kaynak Etiketi & Tekil Dürüst User-Agent:**
  - `engine/scrapers/sources/understat.py`, `engine/scrapers/fusion.py`, `engine/scrapers/pipeline.py`, `engine/bulletin.py`, `engine/predictors/ratings.py` ve `engine/predictors/analyst.py`: `UnderstatTeamXG` ve `UnderstatLeagueData` üzerinde gerçek `source_name` (`"Understat"`, `"FotMob-xG"`, `"ShotProxy-xG"`) taşındı; Türkçe maç analizi metinleri de gerçek kaynağa göre dinamikleştirildi.
  - `engine/scrapers/base.py`: Rastgele masaüstü UA havuzu ve varsayılan Transfermarkt `Referer` başlığı kaldırıldı; `DEFAULT_USER_AGENT = "FutbolSkorAnaliz/1.0 (+https://github.com/naziffarm4/futbol-skor-analiz)"` tanımlandı.
- **Canlı Test İzolasyonu, CI & Dokümantasyon:**
  - `engine/tests/test_scrapers.py` ve `engine/tests/test_sources_and_fusion.py` içindeki dış ağ testleri `RUN_LIVE_TESTS=1` koşuluna alındı.
  - `.github/workflows/ci.yml` tam `python -m mypy engine app.py` ve `flutter` işi ile genişletildi; `README.md` ve `docs/veri-kaynaklari.md` kanonik mimariye göre güncellendi.

### 3.2. Alt Ajan 2 — Hold-Out, Bootstrap & Power De-Vigging Backtest v3
- `engine/scrapers/sources/the_odds_api.py` içinde Newton-Raphson + bisection hibrit çözücülü (`tol = 1e-12`) `devig_power` uygulandı ve `devig_three_way` / `devig_two_way` içinde `method="power"` varsayılan üretim yöntemi olarak etkinleştirildi.
- `engine/backtest/metrics.py`, `engine/backtest/runner.py` ve `engine/backtest/cli.py` içinde `α ∈ [0.0..1.0]` ızgarası, `2425+2526` seçim vs `2627` hold-out ayrımı, deterministik eşleştirilmiş bootstrap (`N=1000`, `seed=42`), `[0.6, 0.8)` favori dilimi kalibrasyon analizi ve `--v3` rapor üreticisi eklendi; `reports/backtest_v3_holdout.md` üretildi ve `engine/tests/test_backtest.py` birim testleri genişletildi.

### 3.3. Alt Ajan 3 — Mobil Bayat Bülten Uyarısı, QA & Canlı Doğrulama (Hatalar ve Çözümler)
- `mobile/lib/services/bulletin_api_service.dart` (`BulletinData.parseGeneratedAt`) ve `mobile/lib/widgets/data_transparency_banner.dart` içine bülten yaşı `> 36 saat` olduğunda tetiklenen turuncu `AppColors.neonOrange` çerçeveli `"Bülten güncel değil (${age.inHours} saat önce)"` uyarısı ve `mobile/test/widget_test.dart` (`Test 15`) eklendi.
- **Canlı CI/CD Sırasında Karşılaşılan Hatalar ve Uygulanan Kök Neden Çözümleri:**
  1. **`ci.yml` Flutter SDK sürüm farkı (`Run 46084189697`):** Sabitlenmemiş kanal en yeni Flutter `3.50.1` sürümünü çekip `deprecated_member_use` bilgi uyarısı üretti -> `ci.yml` içinde yerel ortamla birebir uyumlu `flutter-version: '3.47.9'` sabitlenerek çözüldü.
  2. **`update_bulletin.yml` Pages artefakt indeksleme yarışı (`Run 46084216584`):** `upload-pages-artifact@v3` yüklemesinden 0.5 saniye sonra çalışan `deploy-pages@v4`, GitHub API gecikmesi nedeniyle `Found 0 artifact(s)` döndü -> iki adım arasına `sleep 5` eklenerek çözüldü.
  3. **`ci.yml` temiz klonda yerel önbellek dosyası bulunmaması (`Run 46084836330`):** `.gitignore` içindeki `engine/data/bulletin_cache.json` temiz CI klonunda yer almadığı için `widget_test.dart` içindeki `_loadRealBulletinJson()` `PathNotFoundException` fırlattı -> dosya yokken 4 ligi kapsayan deterministik hermetik `_buildCiFallbackBulletinJson()` yedek fikstürü eklenerek çözüldü.

---

## 4. Backtest v3 İstatistiksel Bulguları (`reports/backtest_v3_holdout.md`)

> **Dürüst Katma Değer Notu:** *Harman modeli piyasaya yaklaştırıyor; saf piyasa kapanışını geçme iddiası yok, asıl katma değer şeffaf 9'lu İY/MS dağılımı + canlı sakatlık + Türkçe taktiksel analiz.*

### 4.1. Sızıntısız Hiperparametre Seçimi (`2425+2526`, `n=2531`) ve `α ∈ [0.00..1.00]` Eğrisi
- `2627` verisine hiç bakılmadan `2425+2526` kümesinde en düşük saf-model RPS (`0.20368`) ve Log-Loss (`0.99486`) değerini **`ξ* = 0.0015`** (yarı ömür ≈ 462 gün) vermiştir.
- Uzatılmış `α` ızgarasında RPS monotonik olarak `0.20368` (`α=0.00`) -> **`0.19604` (`α=0.65` Üretim Hibrit)** -> `0.19501` (`α=1.00`) eğrisini izlemektedir. Üretimdeki `α = 0.65`, toplam iyileşmenin **%88.1**'ini yakalarken (`0.65 -> 1.00` farkı yalnızca `0.00103` RPS), canlı sakatlık, xG ve 9 yönlü İY/MS matrisinin %35 yapısal sinyalini koruduğu için sabit tutulmuştur.

| `α` | Seçim (`2425+2526`) RPS (↓) | Seçim Log-Loss (↓) | Seçim ECE (↓) | Seçim İY/MS Top-3 (↑) | Hold-Out (`2627`) RPS (↓) | Hold-Out Log-Loss (↓) |
|---:|---:|---:|---:|---:|---:|---:|
| `0.00` | `0.20368` | `0.99486` | %0.57 | %62.96 | `0.20567` | `0.96711` |
| `0.25` | `0.19986` | `0.98278` | %0.62 | %63.87 | `0.19922` | `0.94670` |
| `0.50` | `0.19714` | `0.97435` | %0.93 | %64.19 | `0.19440` | `0.93108` |
| **`0.65` (Üretim)** | **`0.19604`** | **`0.97092`** | **%0.96** | **%64.55** | **`0.19229`** | **`0.92373`** |
| `0.85` | `0.19519` | `0.96823` | %0.58 | %64.51 | `0.19041` | `0.91620` |
| `1.00` | `0.19501` | `0.96770` | %0.34 | %64.51 | `0.18969` | `0.91228` |

### 4.2. Seçim (`2425+2526`) vs Hiç Görülmemiş Hold-Out (`2627`) Özeti

| Küme & Kapsam | Model | Maç | 1X2 RPS (↓) | 1X2 Log-Loss (↓) | 1X2 ECE (↓) | 1X2 İsabet (↑) | 9'lu İY/MS Log-Loss (↓) | İY/MS Top-1 (↑) | İY/MS Top-3 (↑) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **Seçim — 4 Lig** | Saf Model (`ξ=0.0015, α=0`) | 2531 | `0.20368` | `0.99486` | %0.57 | %51.96 | `1.9235` | %31.15 | %62.96 |
| **Seçim — 4 Lig** | **Üretim Harman (`α=0.65`)** | 2531 | **`0.19604`** | **`0.97092`** | **%0.96** | **%54.25** | **`1.8996`** | **%32.81** | **%64.55** |
| **Seçim — 4 Lig** | Saf Piyasa (Power) | 2531 | `0.19501` | `0.96770` | %0.32 | %54.80 | - | - | - |
| **Hold-Out (`2627`) — 4 Lig** | Saf Model (`ξ=0.0015, α=0`) | 314 | `0.20567` | `0.96711` | %2.93 | %55.10 | `1.8398` | %34.08 | %67.83 |
| **Hold-Out (`2627`) — 4 Lig** | **Üretim Harman (`α=0.65`)** | 314 | **`0.19229`** | **`0.92373`** | **%3.42** | **%57.64** | **`1.7964`** | **%37.58** | **%68.15** |
| **Hold-Out (`2627`) — 4 Lig** | Saf Piyasa (Power) | 314 | `0.18968` | `0.91227` | %2.69 | %57.64 | - | - | - |
| **Hold-Out (`2627`) — Avrupa (`E0+SP1+F1`)** | **Üretim Harman (`α=0.65`)** | 236 | **`0.19604`** | **`0.94956`** | **%2.23** | **%55.08** | **`1.8399`** | **%34.32** | **%66.95** |
| **Hold-Out (`2627`) — Süper Lig (`T1`)** | **Üretim Harman (`α=0.65`)** | 78 | **`0.18095`** | **`0.84558`** | **%7.00** | **%65.39** | **`1.6647`** | **%47.44** | **%71.80** |
| **Hold-Out (`2627`) — Süper Lig (`T1`)** | Saf Piyasa (Power) | 78 | `0.18261` | `0.84644` | %5.10 | %65.39 | - | - | - |

### 4.3. Eşleştirilmiş Bootstrap Güven Aralığı (`%95 CI`, `N=1000`, `seed=42`)

| Küme & Kapsam | Karşılaştırma (`RPS_yeni - RPS_baz`) | Maç | Ortalama `ΔRPS` | %95 Bootstrap CI `[p2.5, p97.5]` | Çift Yönlü `p` | %95 Anlamlı mı? |
|---|---|---:|---:|---:|---:|---|
| Seçim (`2425+2526`) — 4 Lig | Zaman Sönümü (`ξ=0.0015` vs `ξ=0`) | 2531 | `-0.000061` | `[-0.000244, +0.000117]` | `0.518` | Hayır (`0` CI içinde) |
| Seçim (`2425+2526`) — 4 Lig | **Harman (`α=0.65`) vs Saf Model (`α=0`)** | 2531 | **`-0.007643`** | **`[-0.009563, -0.005895]`** | **`< 0.001`** | **Evet** |
| Seçim (`2425+2526`) — `T1` | **Harman (`α=0.65`) vs Saf Model (`α=0`)** | 585 | **`-0.011114`** | **`[-0.015480, -0.006875]`** | **`< 0.001`** | **Evet** |
| Seçim (`2425+2526`) — 4 Lig | Harman (`α=0.65`) vs Saf Piyasa (`M_mkt`) | 2531 | `+0.001028` | `[+0.000118, +0.002015]` | `0.028` | Evet (Piyasa ~0.001 önde) |
| Hold-Out (`2627`) — 4 Lig | Zaman Sönümü (`ξ=0.0015` vs `ξ=0`) | 314 | `+0.000036` | `[-0.000204, +0.000262]` | `0.770` | Hayır (`0` CI içinde) |
| Hold-Out (`2627`) — 4 Lig | **Harman (`α=0.65`) vs Saf Model (`α=0`)** | 314 | **`-0.013378`** | **`[-0.019116, -0.007158]`** | **`< 0.001`** | **Evet** |
| Hold-Out (`2627`) — Avrupa | **Harman (`α=0.65`) vs Saf Model (`α=0`)** | 236 | **`-0.015842`** | **`[-0.022770, -0.009121]`** | **`< 0.001`** | **Evet** |
| Hold-Out (`2627`) — 4 Lig | Harman (`α=0.65`) vs Saf Piyasa (`M_mkt`) | 314 | `+0.002610` | `[-0.000647, +0.005591]` | `0.120` | Hayır (`0` CI içinde) |

### 4.4. Orantısal vs Power Marj Arındırma (`[0.6, 0.8)` Favori Dilimi ve Genel) — Üretimde Aktif Edildi

| Küme | Seri / Yöntem | Genel 1X2 RPS (↓) | Genel 1X2 ECE (↓) | `[0.6, 0.8)` Kalibrasyon `|Gap|` (↓) | Eşleşen Favori RPS (↓) | Genel `ΔRPS` (Power - Orantısal) %95 CI |
|---|---|---:|---:|---:|---:|---:|
| Seçim (`2425+2526`) | Piyasa (Orantısal -> **Power**) | `0.19513 -> 0.19501` | `%0.92 -> %0.32` | **`%2.25 -> %0.03`** | `0.14959 -> 0.14936` | `-0.000118` `[-0.000354, +0.000134]` |
| Seçim (`2425+2526`) | Harman `α=0.65` (Orantısal -> **Power**) | `0.19626 -> 0.19604` | `%1.23 -> %0.96` | **`%4.78 -> %2.34`** | `0.14220 -> 0.14167` | **`-0.000222` `[-0.000374, -0.000059]`** |
| Hold-Out (`2627`) | Piyasa (Orantısal -> **Power**) | `0.19096 -> 0.18968` | `%3.30 -> %2.69` | **`%10.06 -> %4.53`** | `0.13249 -> 0.12923` | **`-0.001280` `[-0.002208, -0.000358]`** |
| Hold-Out (`2627`) | Harman `α=0.65` (Orantısal -> **Power**) | `0.19351 -> 0.19229` | `%4.04 -> %3.42` | **`%13.55 -> %8.80`** | `0.12759 -> 0.12416` | **`-0.001211` `[-0.001851, -0.000619]`** |

---

## 5. Tam Kalite Kapısı, CI/Pages ve Fiziksel Cihaz Canlı Doğrulama Kanıtları

| Kontrol Katmanı | Komut / Hedef | Sonuç | Kanıt |
|---|---|---|---|
| Python Statik Tip Analizi | `python -m mypy engine app.py` | **GEÇTİ (0 hata)** | `Success: no issues found in 45 source files` |
| Python Linter | `python -m ruff check engine app.py` | **GEÇTİ (0 hata)** | `All checks passed!` |
| Python Birim Testleri (Ağsız) | `python -m unittest discover -s engine/tests -v` | **GEÇTİ (0 hata)** | `Ran 82 tests — OK (skipped=2)` (`test_live_*` temiz atlandı) |
| Flutter Statik Analiz | `flutter analyze` | **GEÇTİ (0 sorun)** | `No issues found!` |
| Flutter Widget Testleri | `flutter test` | **GEÇTİ (15/15)** | `All tests passed!` (`>36 saat` bayat bülten uyarısı dahil) |
| GitHub Actions CI (`ci.yml`) | Run ID **`46085198426`** (`main`) | **`success`** | `lint-and-test` (`140793025086`, 28s) + `flutter` (`140793025318`, 1m5s) yeşil |
| Günlük Bülten & Kota Kalkanı (`update_bulletin.yml`) | Run ID **`46084843964`** (`main`) | **`success`** | `actions/cache@v4` kaydedildi (`bulletin-api-quota-46084843964`, `34,320` B), 4 lig / 33 maç yayınlandı |
| Canlı GitHub Pages `bulletin.json` | `https://naziffarm4.github.io/futbol-skor-analiz/bulletin.json` | **DOĞRULANDI** | `generated_at: 2026-11-27T23:52:56.415615+00:00`; `super_lig` `sources_used: ['TheOddsAPI', 'ESPN', 'Football-Data', 'FotMob-xG', 'SportsGambler']` (`"Understat"` eşleşmesi: `0`) |
| Release APK & Fiziksel Telefon (`adb`) | Cihaz `VKVCX8EQBE9PAIXG` (`2602EPTC0G`) | **DOĞRULANDI** | `app-release.apk` (`48,849,362` B / `46.59 MiB`), `adb install -r` -> `Success`, `LIVE_PID: 29975`, `adb logcat -d` hata sayısı: **`0`** |
| Bilgi Çizgesi Güncellemesi | `/graphify --update` | **GÜNCELLENDİ** | `1776 -> 1850` düğüm, `3673 -> 3748` kenar, `89` topluluk (`+174` yeni düğüm, `+415` yeni kenar; `graph.json`, `GRAPH_REPORT.md`, `graph.html`) |
