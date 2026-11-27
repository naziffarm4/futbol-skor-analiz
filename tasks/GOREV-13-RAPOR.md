# GÖREV-13 (Faz 2) Teknik Doğrulama ve Kapanış Raporu

**Tarih:** 2026-11-28  
**Depo:** `naziffarm4/futbol-skor-analiz` (`main`)  
**Kapsam:** Resmi Ücretsiz API Omurgası (`API-Football` + `The Odds API`), `QuotaBudgetTracker`, WAF Atlatma Kaldırımı, Snapshot Arşivleme, Üstel Zaman Sönümü (`M2`), Marjinal Tutarlı Piyasa Harmanı (`M5`), 9 Yönlü Yüzdelik İY/MS Olasılık Motoru, Mobil 3×3 İY/MS Matrisi & Çevrimdışı Önbellek

---

## 1. Güvenli Anahtar Yönetimi ve Sıfır Sızıntı Kanıtı

1. **Yerel ve Bulut Gizli Anahtar Tanımı:**
   - `API_FOOTBALL_KEY` ve `THE_ODDS_API_KEY` yalnızca `.gitignore` kapsamındaki yerel `.env` dosyasına tanımlanmış ve `gh secret set` aracılığıyla `naziffarm4/futbol-skor-analiz` GitHub Repository Secrets deposuna şifreli olarak yüklenmiştir.
   - `.env.example` dosyasına yalnızca boş yer tutucular (`API_FOOTBALL_KEY=`, `THE_ODDS_API_KEY=`) eklenmiştir.
2. **Çalışma Zamanı ve Log Sızıntısı Koruması:**
   - `engine/config.py` içindeki `Settings` veri sınıfında her iki anahtar `field(default="", repr=False)` ile gizlenmiştir.
   - `engine/scrapers/sources/api_football.py` içinde `redact_secret()` ve `httpx` / `httpcore` standart logger'larına takılan `_SecretRedactingLogFilter` ile `?apiKey=***REDACTED***` maskelemesi zorunlu kılınmıştır.
   - Disk önbelleği (`engine/data/api_cache/`) gizli anahtar içermeyen SHA-256 karma anahtarlarıyla saklanmaktadır.
3. **Sıfır Anahtar Sızıntısı Denetimi (`git grep`):**
   - Hem takip edilen (`git grep` & `git grep --cached`) hem de çalışma ağacındaki tüm git-görünür dosyalar (`git ls-files --cached --others --exclude-standard` — 179 dosya) gerçek gizli değerlere karşı taranmış ve **0 eşleşme (`leaks: []`)** doğrulanmıştır.

---

## 2. Faz 0 Canlı API Doğrulaması, Kota Kalkanı ve WAF Temizliği

Faz 0 kapsamında toplam yalnızca **4 HTTP çağrısı** harcanarak iki resmi API'nin yanıt şeması ve kota başlıkları canlı doğrulanmış, ayrıntılar `docs/veri-kaynaklari.md` içinde belgelenmiştir:

| Çağrı | Uç Nokta (Maskelenmiş) | HTTP | Kalan Kota Başlıkları | Canlı Doğrulama Özeti |
|---|---|---|---|---|
| **1** | `GET https://v3.football.api-sports.io/fixtures?league=203&season=2025` | `200 OK` | Kota düşmedi | `errors.plan`: *"Free plans do not have access to this season, try from 2022 to 2024."* (`ApiFootballAdapter` bu kısıtı HTTP 200 gövdesinde yakalar ve gereksiz `/injuries` çağrısını atlar) |
| **2** | `GET https://v3.football.api-sports.io/fixtures?league=203&season=2024` | `200 OK` | `x-ratelimit-requests-remaining: 99/100` | **342 Süper Lig maçı** (`score.halftime`, `score.fulltime`, `Regular Season - N`) |
| **3** | `GET https://v3.football.api-sports.io/injuries?league=203&season=2024` | `200 OK` | `x-ratelimit-requests-remaining: 98/100` | **1.750 sakatlık/eksik kaydı** (`player.name`, `player.type`, `player.reason`) |
| **4** | `GET https://api.the-odds-api.com/v4/sports/soccer_turkey_super_league/odds?regions=eu&markets=h2h,totals&oddsFormat=decimal&apiKey=***REDACTED***` | `200 OK` | `x-requests-remaining: 498`, `x-requests-used: 2` | **8 yaklaşan Süper Lig maçı**, maç başına **20–21 Avrupa bahis bürosu** konsensüs oranı |

- **`QuotaBudgetTracker` (`engine/scrapers/sources/api_football.py`):** 6 saatlik TTL disk önbelleği + `remaining < 15` koruma kalkanı ile tekrarlı çalışmalarda sıfır kredi tüketimi ve kota aşımı koruması sağlanmıştır.
- **Sıfır WAF/Bot Atlatma (`engine/scrapers/base.py`):** Playwright `AutomationControlled` gizleme, `HeadlessChrome/` UA değiştirme ve `aws-waf-token` bekleme döngüleri tamamen silinmiştir; `.github/workflows/update_bulletin.yml` içinden Playwright kurulumu kaldırılmış, veri merkezi IP'lerinde Transfermarkt HTTP `202` döndürdüğünde `IngestionPipeline` kesintisiz biçimde `TheOddsAPI + ESPN (21 günlük takvim) + Football-Data + Understat + SportsGambler/TheSportsDB` zinciriyle çalışacak hale getirilmiştir.
- **Veri Arşivi (`engine/archive.py`):** Her bülten ihracında `data/snapshots/snapshot_<YYYYMMDDTHHMMSSZ>.json` altına kota durumu, piyasa oran sayısı, sakatlık özeti ve maç başı 9'lu İY/MS + 1X2/Üst2.5/KG olasılıkları kaydedilmektedir.

---

## 3. Walk-Forward Backtest v2 Sonuçları (`reports/backtest_v2.md`)

`T1` (Süper Lig), `E0` (Premier League), `SP1` (La Liga) ve `F1` (Ligue 1) liglerinde 30 maçlık ısınma penceresi sonrasında tam **2.845 gerçek maç** (nedensel walk-forward, sıfır gelecek sızıntısı) üzerinde adım adım ablasyon ölçülmüştür:

### 3.1. Dört Lig Birleşik Ablasyon Tablosu (`2.845` Maç)

| Aşama / Model | Maç | 1X2 RPS (↓) | 1X2 Brier (↓) | 1X2 Log-Loss (↓) | 1X2 İsabet (↑) | Üst 2.5 Brier (↓) | Üst 2.5 Log-Loss (↓) | Üst 2.5 İsabet (↑) | 9'lu İY/MS Brier (↓) | 9'lu İY/MS Log-Loss (↓) | İY/MS Top-1 (↑) | İY/MS Top-3 (↑) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **1. Baz Post-Fix (`ξ=0`, `α=0`)** | 2845 | 0.2039 | 0.5915 | 0.9919 | %52.44 | 0.2480 | 0.6896 | %55.11 | 0.8129 | 1.9147 | %31.47 | %63.43 |
| **2. + Zaman Sönümü (`ξ=0.0015`, `α=0`)** | 2845 | 0.2039 | 0.5914 | 0.9918 | %52.30 | 0.2479 | 0.6895 | %55.40 | 0.8128 | 1.9143 | %31.47 | %63.50 |
| **3. + Piyasa Harmanı (`ξ=0.0015`, `α=0.65`)** | 2845 | **0.1960** | **0.5742** | **0.9669** | **%54.62** | **0.2387** | **0.6698** | **%58.31** | **0.8036** | **1.8894** | **%33.23** | **%64.91** |
| **4. Saf Piyasa Referansı (De-vigged)** | 2845 | 0.1947 | 0.5715 | 0.9626 | %55.11 | 0.2365 | 0.6654 | %59.26 | - | - | - | - |

*5 ondalık hassasiyette saf model M2 kazanımı: 1X2 RPS `0.20395 -> 0.20390`, Brier `0.59151 -> 0.59142`, Log-Loss `0.99195 -> 0.99180`. Premier League (`E0`, 780 maç) alt kümesinde M2+M5 hibrit model (`0.2030` RPS, `0.9993` Log-Loss) saf kapanış piyasasını (`0.2032` RPS, `0.9998` Log-Loss) doğrudan geride bırakmıştır.*

### 3.2. Türkiye Süper Lig (`T1`) Özel Ablasyon Tablosu (`663` Maç)

| Aşama / Model | Maç | 1X2 RPS (↓) | 1X2 Brier (↓) | 1X2 Log-Loss (↓) | 1X2 İsabet (↑) | Üst 2.5 Brier (↓) | Üst 2.5 Log-Loss (↓) | 9'lu İY/MS Brier (↓) | 9'lu İY/MS Log-Loss (↓) | İY/MS Top-1 (↑) | İY/MS Top-3 (↑) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **1. Baz Post-Fix (`ξ=0`, `α=0`)** | 663 | 0.1958 | 0.5746 | 0.9689 | %55.66 | 0.2485 | 0.6909 | 0.7975 | 1.8808 | %33.69 | %63.14 |
| **2. + Zaman Sönümü (`ξ=0.0015`, `α=0`)** | 663 | 0.1955 | 0.5742 | 0.9681 | %55.81 | 0.2485 | 0.6908 | 0.7972 | 1.8799 | %33.84 | %63.29 |
| **3. + Piyasa Harmanı (`ξ=0.0015`, `α=0.65`)** | 663 | **0.1858** | **0.5543** | **0.9385** | **%58.37** | **0.2357** | **0.6637** | **0.7861** | **1.8503** | **%36.71** | **%67.52** |
| **4. Saf Piyasa Referansı (De-vigged)** | 663 | 0.1842 | 0.5515 | 0.9335 | %59.43 | 0.2324 | 0.6565 | - | - | - | - |

- **Seçilen Üretim Varsayılanları:** `DEFAULT_TIME_DECAY_XI = 0.0015` ve `DEFAULT_MARKET_BLEND_ALPHA = 0.65`.
- **Marjinal Tutarlı 9'lu İY/MS Dağılımı:** `all_ht_ft_json` içindeki 9 senaryonun (`1/1, X/1, 2/1, 1/X, X/X, 2/X, 1/2, X/2, 2/2`) toplamı tam `1.0000` olup `sum(MS==1) == p_home`, `sum(MS==X) == p_draw`, `sum(MS==2) == p_away` eşitliğini dördüncü ondalığa kadar sağlamaktadır.

---

## 4. Mobil Uygulama, Kalite Kapısı, Canlı Yayın ve Fiziksel Telefon Doğrulaması

1. **Mobil Arayüz & Çevrimdışı Önbellek (`mobile/`):**
   - `MatchCard`: Kompakt en olası İY/MS yüzdesi (`İY/MS 1/1 %37`) ve `1 / X / 2` yüzde rozetleri (`1:%52  X:%26  2:%22`).
   - `MatchDetailScreen`: `MatchOutcomeSummaryCard` (`MS 1 / MS X / MS 2` yatay çubuğu + `2.5 Üst / Alt` + `KG Var / Yok` + `"Piyasa + Poisson Harmanı"` rozeti) ve 9 senaryonun tamamını gösteren **3×3 Tam Yüzdelik Matrisi** (`360×800` dar ekranda sıfır taşma).
   - **Çevrimdışı Önbellek:** Ek üçüncü parti bağımlılık eklemeden `MainActivity.kt` `com.futbol.bulten/storage` (`filesDir`) + atomik yerel JSON kaydı ile ağ kesintisinde `"Çevrimdışı Önbellek • Son güncelleme: ..."` bandı ve yenileme aksiyonu eklendi.
2. **Statik Analiz ve Test Kapıları:**
   - `python -m mypy engine app.py`: **0 hata** (`Success: no issues found in 45 source files`)
   - `python -m ruff check engine app.py`: **0 hata** (`All checks passed!`)
   - `python -m unittest discover -s engine/tests -v`: **77/77 test OK**
   - `flutter analyze`: **0 sorun** (`No issues found!`)
   - `flutter test`: **14/14 widget & servis testi OK**
3. **GitHub Actions & Canlı `bulletin.json` Kanıtı:**
   - `Update Football Bulletin` (`46066599966`): **`success`** (45 sn, sıfır Playwright/WAF atlatma ile)
   - `CI` (`46066922525`): **`success`**
   - Canlı `https://naziffarm4.github.io/futbol-skor-analiz/bulletin.json`: HTTP `200`, `sources_used: ['TheOddsAPI', 'ESPN', 'Football-Data', 'Understat', 'SportsGambler']`, `28` haftalık maç (`14` maçta canlı `TheOddsAPI` harmanı aktif), tüm 28 maçta `len(all_ht_ft_json) == 9` ve olasılık toplamı `1.0000` (ör. `Samsunspor vs Genclerbirligi`: `p_home=0.5245, p_draw=0.2596, p_away=0.2159`, `1/1=0.3725, X/X=0.1663, X/1=0.1365, 2/2=0.1110, X/2=0.0886, 1/X=0.0562, 2/X=0.0371, 1/2=0.0163, 2/1=0.0155`).
4. **Fiziksel Telefon Canlı Doğrulaması (`VKVCX8EQBE9PAIXG`):**
   - `flutter build apk --release --target-platform android-arm64` ile `app-release.apk` (`17.263.024` bayt) derlendi.
   - `adb reverse --remove-all` ile aktif USB tüneli olmadığı doğrulanarak `adb install -r` kuruldu ve soğuk başlangıç (`289 ms`, `PID 27861`, Impeller Vulkan) yapıldı.
   - `uiautomator dump` ve `adb logcat` kontrolünde uygulamanın USB tüneli olmadan doğrudan GitHub Pages CDN üzerinden canlı bülteni (`TheOddsAPI` kaynakları + `İY/MS 1/1 %37` + `1:%52 X:%26 2:%22`) ekrana çizdiği ve **0 `AndroidRuntime` / Flutter hatası** ürettiği kanıtlandı.
