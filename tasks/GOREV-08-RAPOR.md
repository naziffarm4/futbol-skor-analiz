# GÖREV-08 RAPORU: Anlamlı & Okunabilir Maç Analizi, Veri Kaynağı Şeffaflığı, Bulut Dağıtım Hazırlığı ve Release APK

**Tarih:** 2026-11-26  
**Durum:** ✅ TAMAMLANDI (Tüm Doğrulama Kriterleri Karşılandı)

---

## 1. Ön Aşama: `graphify` Mimari ve Bağımlılık Analizi

Geliştirmeye başlamadan önce `graphify-out/graph.json` (875 düğüm) üzerinde `mcp__graphify__query_graph` ve `mcp__graphify__get_neighbors` sorguları çalıştırılarak uçtan uca etki alanı doğrulandı:

- **Backend Analiz & Bülten Zinciri:**
  - `engine/predictors/analyst.py:generate_match_analysis_texts()` → `TeamRatingProfile` ve `PoissonPredictionResult` verilerini alıp `MatchAnalysisTexts` üretir; `engine/predictors/service.py:run_prediction_pipeline()` ve `engine/tests/test_predictors.py:test_analyst_text_generation()` tarafından çağrılır.
  - `engine/bulletin.py:build_bulletin_payload()` ve `update_bulletin_cache()` → `CycleResult` çıktısını benzersiz ID garantili JSON ağacına dönüştürüp `engine/data/bulletin_cache.json` önbelleğine yazar; `app.py:/api/v1/bulletin` ve `/sync` uç noktaları tarafından sunulur.
- **Mobil Veri & Arayüz Zinciri:**
  - `mobile/lib/services/bulletin_api_service.dart:BulletinData.fromJson()` → `mobile/lib/screens/home_screen.dart` (`_HomeScreenState`, `_LeagueMatchesList`) → `mobile/lib/screens/match_detail_screen.dart` (`MatchDetailScreen`) → `mobile/lib/widgets/analysis_section.dart` (`AnalysisSection`, `_AnalysisCard`).

---

## 2. Alt Ajan 1 — Spor Analiz Motoru, Veri Şeffaflığı ve Bulut Dağıtımı (Backend)

### 2.1. `engine/predictors/analyst.py` Yeniden Tasarımı
- **Matematik Jargonunun Temizlenmesi:** Metinlerdeki *"Dixon-Coles"*, *"Poisson"*, *"0-5 dağılımı"*, *"olasılık matrisi"*, *"katsayısını aşağı çekiyor"*, *"λ"*, *"logaritmik"* ve *"/100 reyting"* gibi tüm teknik model terimleri kaldırılarak doğal, ikna edici spor analisti Türkçesine geçildi.
- **İki Paragraflı (`\n\n`) Yapı ve Maç Profili Çeşitliliği:**
  - **`match_overview_text`:**
    1. *1. Paragraf ("Neden Bu Skor?"):* İlk cümlede doğrudan tahmini skoru (`predicted_home_score - predicted_away_score`) vererek gol üretkenliği, savunma disiplini, iç/dış saha ortalamaları ve gol yememe (clean sheet) alışkanlığı üzerinden somut gerekçesini açıklar; alternatif yakın skor ihtimallerini belirtir.
    2. *2. Paragraf (Maç Senaryosu, Tempo ve Kırılma Noktası):* Maçın profiline göre (**güçlü favori / tek taraflı baskı**, **gollü düello / karşılıklı açık oyun**, **dengeli taktik mücadelesi**, **düşük tempolu savunma savaşı** + **derbi atmosferi**) beklenen oyun temposunu ve maçın kırılma noktasını anlatır.
  - **`home_analysis_text` ve `away_analysis_text`:**
    1. *1. Paragraf (Form ve Saha Karnesi):* Son 5 maç bilançosu, puan ritmi, iç/dış saha maç başı gol ortalamaları ve gol yememe performansı takım kimliğine (üretken hücumcu, disiplinli savunmacı, dengeli, istikrarsız/formsuz) göre çeşitlenen cümlelerle aktarılır.
    2. *2. Paragraf (Mevkiye Özel Sakatlık/Eksik Etkisi):* Tekilleştirilmiş oyuncu adları ve sakatlık/ceza nedenleriyle birlikte mevkiye özel taktiksel etkiler yorumlanır:
       - **Kaleci / Savunma (`GK` / `DEF`):** Kale güvenliği, savunma yerleşimi, hava topları ve duran top savunmasında risk.
       - **Orta Saha (`MID`):** Merkezde oyun kurulumu, pas bağlantısı ve top kazanma direncinde düşüş.
       - **Hücum (`FW`):** Ceza sahası bitiriciliği, ön alan presi ve hücum derinliğinde güç kaybı.
       - **Tam Kadro:** Eksik bulunmadığında ideal 11 istikrarının ve hamle çeşitliliğinin sağladığı taktiksel avantaj vurgulanır.

### 2.2. Veri Şeffaflığı Metadatası (`engine/bulletin.py` & `app.py`)
Canlı `GET http://127.0.0.1:7860/api/v1/bulletin` ve `engine/data/bulletin_cache.json` doğrulaması:
- `data_source`: `"Transfermarkt"`
- `generated_at`: `"2026-11-26T18:44:21.636242+00:00"`
- `season`: `"2026-2027"`
- `total_matches`: `38` (sıradaki hafta maçları)
- `total_injuries`: `234` (güncel sakat/cezalı/eksik kayıtları)
- `total_played_matches`: `446` (analize temel oluşturan gerçek oynanmış lig maçları toplamı)

| Lig ID | Lig Adı | Sıradaki Hafta | Analiz Edilen Gerçek Maç (`played_matches_count`) | Bülten Maçı (`matches_count`) | Eksik Oyuncu (`injuries_count`) |
|---|---|---:|---:|---:|---:|
| `super_lig` | Süper Lig | 13 | **108** | 9 | 68 |
| `premier_league` | Premier League | 12 | **110** | 10 | 45 |
| `la_liga` | La Liga | 14 | **129** | 10 | 69 |
| `ligue_1` | Ligue 1 | 12 | **99** | 9 | 52 |

### 2.3. Hugging Face Spaces Bulut Dağıtım Hazırlığı (`Dockerfile` & `HF_DEPLOY.md`)
- `Dockerfile` içinde Port `7860`, non-root `UID 1000` (`user`) ve `/app/engine/data` önbellek dizini yazma izinleri doğrulandı/güvenceye alındı.
- Kök dizinde 3 adımlı (`1. Space Oluşturma`, `2. Ortam Değişkenleri ve Kod Yükleme`, `3. Canlı Doğrulama & --dart-define=API_URL=... ile Mobil Derleme`) **`HF_DEPLOY.md`** rehberi oluşturuldu.

---

## 3. Gerçek Maçlardan Yeni Üretilen Analiz Metin Örnekleri

### Örnek 1: Fenerbahçe SK - Erzurumspor FK (Süper Lig, 13. Hafta — Tahmini Skor: `2-0`, Güçlü Favori Profili)

- **`match_overview_text`:**
  > Ligde 13. hafta mücadelesinde Fenerbahçe SK - Erzurumspor FK karşılaşmasında 2-0 skoru, ev sahibinin taraftarı önündeki gol üretkenliği ve gol yememe disiplininin konuk ekibin dış saha hücum direncine ağır basması sayesinde öne çıkıyor. Fenerbahçe SK iç sahada maç başına 3.40 gol üretip kalesinde 1.20 gol görürken toplam 6 maçta kalesini gole kapattı; Erzurumspor FK ise deplasmanda 0.83 gol ortalaması yakalayıp 1.67 gol yedi ve sezon genelinde 4 kez gol yemeden sahadan ayrıldı. Maç içi kırılmalara bağlı olarak 1-0 ve 1-1 sonuçları da öne çıkan diğer güçlü skor ihtimalleri arasında yer alıyor.
  >
  > Oyun senaryosunda saha içi güç üstünlüğünü elinde bulunduran Fenerbahçe SK ekibinin topa hükmederek oyunu rakip yarı alana yıkması, Erzurumspor FK tarafının ise derinde bekleyip hızlı çıkışlarla nefes araması bekleniyor; karşılaşmanın yüksek tempolu ve tek taraflı baskı sekanslarıyla ilerlemesi öngörülüyor. Maçın kırılma noktasını, Fenerbahçe SK cephesinde Amara Diouf başta olmak üzere hücum hattındaki önemli eksiklerin oyun dengesinde yaratacağı boşluk belirleyecek.

- **`home_analysis_text`:**
  > Üretken hücum kimliğiyle öne çıkan ve son 5 lig maçında 2 galibiyet, 1 beraberlik ve 2 yenilgiyle 7 puan toplayan Fenerbahçe SK, rakip ceza sahasında çoğalma becerisiyle dikkat çekiyor. Taraftarı önünde çıktığı 5 iç saha maçında 3 galibiyet, 0 beraberlik ve 2 yenilgi alan ekip, maç başına 3.40 gol üretirken kalesinde 1.20 gol gördü. Genel toplamda 12 maçın 6 tanesinde, iç sahada ise 2 karşılaşmada kalesini gole kapatmayı başardı.
  >
  > Kadroda ilk 11 kurgusunu doğrudan etkileyen 2 kilit ismin de aralarında bulunduğu Amara Diouf (hücum - Oynama izni yok), Jayden Oosterwolde (savunma - Kısmi kas kopması), Marco Asensio (orta saha - Kıkırdak hasarı) ve 1 diğer isim eksikleri, Fenerbahçe SK adına savunma yerleşimi, hava topları ve duran top güvenliğinde dikkat çeken bir risk doğuruyor, merkezde oyun kurulumu, pas bağlantısı ve top kazanma direncinde düşüşe yol açıyor ve ceza sahası bitiriciliği, ön alan presi ve hücum derinliğinde güç kaybı beraberinde getiriyor. Teknik ekibin iç sahada bu boşlukları takım boyunu kısaltarak ve yardımlaşmayı artırarak kapatması gerekecek.

- **`away_analysis_text`:**
  > Oyunun iki yönünü dengeli oynamaya gayret eden ve son 5 lig maçında 2 galibiyet, 0 beraberlik ve 3 yenilgiyle 6 puan toplayan Erzurumspor FK, puan ritmini koruyarak üst sıralara tutunma mücadelesi veriyor. Bu sezon çıktığı 6 deplasman sınavında 1 galibiyet, 2 beraberlik ve 3 yenilgi elde eden konuk ekip, dış sahada maç başına 0.83 gol bulup kalesinde 1.67 gol gördü. Ligdeki 12 maçın 4 tanesinde gol yemeyen Erzurumspor FK, deplasmanda da 1 kez kalesini gole kapatarak dirençli bir görüntü çizdi.
  >
  > Kadroda ilk 11 kurgusunu doğrudan etkileyen 1 kilit ismin de aralarında bulunduğu Şerefhan Sağlık (kaleci - Oynama izni yok), Festy Ebosele (orta saha - Uyluk gerilmesi), Orhan Ovacıklı (orta saha - Kasık sakatlığı) eksikleri, Erzurumspor FK adına kale güvenliği, savunma arkası zamanlaması ve duran top savunmasında belirgin risk oluşturuyor; aynı zamanda merkezde oyun kurulumu, pas bağlantısı ve top kazanma direncinde düşüşe yol açıyor. Deplasmanda bu eksikleri telafi edebilmek için bloklar arası yardımlaşmanın üst seviyede tutulması şart.

---

### Örnek 2: Real Madrid - Deportivo Alavés (La Liga, 14. Hafta — Tahmini Skor: `2-0`, Seri Yakalamış Lider Profili)

- **`match_overview_text`:**
  > Ligde 14. hafta mücadelesinde Real Madrid - Deportivo Alavés karşılaşmasında 2-0 skoru, ev sahibinin taraftarı önündeki gol üretkenliği ve gol yememe disiplininin konuk ekibin dış saha hücum direncine ağır basması sayesinde öne çıkıyor. Real Madrid iç sahada maç başına 3.17 gol üretip kalesinde 0.67 gol görürken toplam 4 maçta kalesini gole kapattı; Deportivo Alavés ise deplasmanda 0.67 gol ortalaması yakalayıp 1.83 gol yedi ve sezon genelinde 4 kez gol yemeden sahadan ayrıldı. Maç içi kırılmalara bağlı olarak 1-0 ve 3-0 sonuçları da öne çıkan diğer güçlü skor ihtimalleri arasında yer alıyor.
  >
  > Oyun senaryosunda saha içi güç üstünlüğünü elinde bulunduran Real Madrid ekibinin topa hükmederek oyunu rakip yarı alana yıkması, Deportivo Alavés tarafının ise derinde bekleyip hızlı çıkışlarla nefes araması bekleniyor; karşılaşmanın orta-yüksek tempolu ve tek taraflı baskı sekanslarıyla ilerlemesi öngörülüyor. Maçın kırılma noktasını, Real Madrid cephesinde Raúl Asencio başta olmak üzere savunma hattındaki önemli eksiklerin oyun dengesinde yaratacağı boşluk belirleyecek.

- **`home_analysis_text`:**
  > Üretken hücum kimliğiyle öne çıkan ve son 5 lig maçında 5 galibiyet, 0 beraberlik ve 0 yenilgiyle 15 puan toplayan Real Madrid, rakip ceza sahasında çoğalma becerisiyle dikkat çekiyor. Taraftarı önünde çıktığı 6 iç saha maçında 6 galibiyet, 0 beraberlik ve 0 yenilgi alan ekip, maç başına 3.17 gol üretirken kalesinde 0.67 gol gördü. Genel toplamda 13 maçın 4 tanesinde, iç sahada ise 2 karşılaşmada kalesini gole kapatmayı başardı.
  >
  > Kadroda ilk 11 kurgusunu doğrudan etkileyen 2 kilit ismin de aralarında bulunduğu Raúl Asencio (savunma - Stres kırığı), Rodrygo (hücum - Çapraz bağ yırtığı), Endrick (hücum - Kas yaralanması) ve 1 diğer isim eksikleri, Real Madrid adına savunma yerleşimi, hava topları ve duran top güvenliğinde dikkat çeken bir risk doğuruyor; aynı zamanda ceza sahası bitiriciliği, ön alan presi ve hücum derinliğinde güç kaybı beraberinde getiriyor. Teknik ekibin iç sahada bu boşlukları takım boyunu kısaltarak ve yardımlaşmayı artırarak kapatması gerekecek.

- **`away_analysis_text`:**
  > Son haftalarda istediği istikrarı yakalamakta zorlanan ve son 5 lig maçında 1 galibiyet, 2 beraberlik ve 2 yenilgiyle 5 puan toplayan Deportivo Alavés, özellikle geçiş savunmasındaki dalgalanmaları gidermeye çalışıyor. Bu sezon çıktığı 6 deplasman sınavında 0 galibiyet, 3 beraberlik ve 3 yenilgi elde eden konuk ekip, dış sahada maç başına 0.67 gol bulup kalesinde 1.83 gol gördü. Ligdeki 13 maçın 4 tanesinde gol yemeyen Deportivo Alavés, deplasmanda da 2 kez kalesini gole kapatarak dirençli bir görüntü çizdi.
  >
  > Kadroda ilk 11 kurgusunu doğrudan etkileyen 2 kilit ismin de aralarında bulunduğu Facundo Garcés (savunma - Çapraz bağlarda kısmi yırtık), Mikel Rodriguez (orta saha - Çapraz bağlarda kısmi yırtık), Abde Rebbach (hücum - kadro dışı / cezalı) eksikleri, Deportivo Alavés adına savunma yerleşimi, hava topları ve duran top güvenliğinde dikkat çeken bir risk doğuruyor, merkezde oyun kurulumu, pas bağlantısı ve top kazanma direncinde düşüşe yol açıyor ve ceza sahası bitiriciliği, ön alan presi ve hücum derinliğinde güç kaybı beraberinde getiriyor. Deplasmanda bu eksikleri telafi edebilmek için bloklar arası yardımlaşmanın üst seviyede tutulması şart.

---

### Örnek 3: Alanyaspor - Konyaspor (Süper Lig, 13. Hafta — Tahmini Skor: `0-0`, Savunma Savaşı & Tam Kadro Karşılaştırması)

- **`match_overview_text`:**
  > Ligde 13. hafta mücadelesinde Alanyaspor ile Konyaspor arasındaki randevuda 0-0 skoru, iki takımın da savunma güvenliğini ön planda tutan yapısı, kalelerini gole kapatma alışkanlığı ve son haftalardaki kontrollü hücum temposu nedeniyle öne çıkıyor. Alanyaspor iç sahada maç başına 0.80 gol üretip kalesinde 1.20 gol görürken toplam 3 maçta kalesini gole kapattı; Konyaspor ise deplasmanda 0.40 gol ortalaması yakalayıp 1.40 gol yedi ve sezon genelinde 4 kez gol yemeden sahadan ayrıldı. Maç içi kırılmalara bağlı olarak 1-0 ve 1-1 sonuçları da öne çıkan diğer güçlü skor ihtimalleri arasında yer alıyor.
  >
  > Savunma bloklarının hatlar arası mesafeyi daraltacağı, düşük tempolu ve sabır gerektiren sert bir savunma savaşı bekleniyor. Açık oyunda boşluk bulmanın zorlaşacağı bu düzende duran toplar ve ikinci top kazanımları skoru tayin edecek ana silahlar olacak. Maçın kırılma noktasını, Konyaspor kadrosunda Adil Demirbağ öncülüğündeki savunma eksikleri nedeniyle konuk ekibin baskı altında vereceği reaksiyon belirleyecek.

- **`home_analysis_text` (Tam Kadro Avantajı Örneği):**
  > Son haftalarda istediği istikrarı yakalamakta zorlanan ve son 5 lig maçında 0 galibiyet, 0 beraberlik ve 5 yenilgiyle 0 puan toplayan Alanyaspor, özellikle geçiş savunmasındaki dalgalanmaları gidermeye çalışıyor. Taraftarı önünde çıktığı 5 iç saha maçında 1 galibiyet, 2 beraberlik ve 2 yenilgi alan ekip, maç başına 0.80 gol üretirken kalesinde 1.20 gol gördü. Genel toplamda 12 maçın 3 tanesinde, iç sahada ise 2 karşılaşmada kalesini gole kapatmayı başardı.
  >
  > Kadro cephesinde Alanyaspor adına kayıtlı sakat veya cezalı oyuncu bulunmuyor. Teknik heyetin ideal kadro istikrarını koruyarak tam kadro sahaya çıkacak olması, taraftarı önünde hem başlangıç baskısında hem de ikinci yarıdaki hamle çeşitliliğinde önemli bir taktiksel avantaj sağlıyor.

---

## 4. Alt Ajan 2 — Mobil Arayüz & Şeffaflık İyileştirmeleri (Flutter)

1. **`BulletinData` ve Tarih Biçimlendirici (`bulletin_api_service.dart`, `constants.dart`):**
   - `BulletinData` modeline `dataSource`, `totalPlayedMatches`, `playedMatchesByLeague` ve `effectivePlayedMatches(leagueId)` eklendi.
   - Harici paket gerektirmeyen `AppConstants.formatShortTimestampTr` (`26 Kas 21:44`) metodu eklendi.
2. **Veri Şeffaflık Bandı (`DataTransparencyBanner`):**
   - `HomeScreen` lig listelerinin en üstüne ve `MatchDetailScreen` sayfa sonuna `Kaynak: Transfermarkt • Güncelleme: 26 Kas 21:44 • 108 gerçek maç analizi` şeffaflık bandı eklendi.
3. **Okunabilir Analiz Kartları (`AnalysisSection`):**
   - Kart başlıkları **"Neden Bu Skor?"** (`Maç Senaryosu` rozetiyle), **"Ev Sahibi Durumu"** ve **"Deplasman Durumu"** olarak yenilendi.
   - `AnalysisSection.splitParagraphs` ile `\n\n` paragrafları ayrıştırıldı; ilk paragrafa vurgu kutusu, paragraflar arasına `11px` boşluk ve `1.55` satır yüksekliği uygulandı.
   - `Skor X - Y • %Z Güven`, `Güç Dengesi X - Y`, `Hücum XX • Savunma YY` ve `X Eksik Oyuncu` / `Tam Kadro` metrik özet rozetleri eklendi.
4. **Dar Ekran (`360x800`) Taşmasızlık Garantisi:**
   - Sabit `Row` yerine `Wrap` ve esnek kapsayıcılar kullanıldı; `360x800` widget testinde sıfır `RenderFlex overflow` doğrulandı.

---

## 5. Alt Ajan 3 — QA, Release APK Derleme ve Fiziksel Cihaz Doğrulaması

### 5.1. Karşılaşılan Hatalar ve Çözümleri
1. **Türkçe Sıra Sayısı Cümle Bölme Hatası (`test_predictors.py`):** `"Ligde 5. hafta..."` ifadesi düz noktadan bölündüğünde ilk cümle kesiliyordu; regex `re.split(r"(?<!\d)\.\s+", ...)` olarak güncellendi.
2. **Çift Uç Noktadan Gelen Oyuncu Tekrarı (`analyst.py`):** Transfermarkt'ta hem sakat hem oynama izni olmayan oyuncunun iki kez listelenmesi `_prioritize_injuries` içinde isim bazlı tekilleştirme ile giderildi.
3. **Dinamik Sakatlık Sayısı Test Güncellemesi (`widget_test.dart`):** Canlı önbellek yenilendiğinde toplam eksik sayısı `231`'den `234`'e çıktığı için `Test 2` içindeki sabit sayı beklentisi `bulletin_cache.json` içindeki `total_injuries` / `total_matches` alanlarıyla dinamik eşleşecek şekilde düzeltildi.

### 5.2. Test ve Statik Analiz Sonuçları
- **Python Birim Testleri (`python -m unittest discover -s engine/tests -v`):** `Ran 30 tests in 4.063s — OK` (**30/30 başarılı**)
- **Flutter Statik Analiz (`flutter analyze`):** `No issues found! (ran in 7.1s)` (**0 sorun**)
- **Flutter Birim & Widget Testleri (`flutter test`):** `00:04 +7: All tests passed!` (**7/7 başarılı**, `360x800` dar ekran testi dahil)

### 5.3. Release APK Boyut Karşılaştırması ve Fiziksel Telefon (`adb`) Kanıtları
- **Derleme Komutu:** `flutter build apk --release --target-platform android-arm64`
- **APK Boyut Kazanımı:**
  - Önceki Debug APK (`app-debug.apk`): **154.07 MiB** (`161,557,886` bayt)
  - Yeni arm64 Release APK (`app-release.apk`): **16.28 MiB** (`17,065,972` bayt)
  - **Küçülme Oranı:** **%89.44 azalma** (`137.79 MiB` kazanç)
- **Fiziksel Cihaz Kurulumu ve Canlı Doğrulama:**
  - **Cihaz:** `VKVCX8EQBE9PAIXG` (`model:2602EPTC0G`, `device:warhol`)
  - **Tünel:** `adb reverse tcp:7860 tcp:7860` (`UsbFfs tcp:7860 tcp:7860`)
  - **Kurulum:** `adb install -r mobile/build/app/outputs/flutter-apk/app-release.apk` → `Success`
  - **Ekran Doğrulaması (`uiautomator`):** `HomeScreen` üzerinde `Canlı` rozeti, `Kaynak: Transfermarkt | Güncelleme: 26 Kas 21:44 | 108 gerçek maç analizi` bandı ve 4 lig sekmesi; `MatchDetailScreen` üzerinde `Neden Bu Skor?`, `Ev Sahibi Durumu`, `Deplasman Durumu`, metrik rozetler ve çok paragraflı analiz metinleri gerçek cihaz ekranında doğrulandı.
  - **`adb logcat -d` Sonucu:** Impeller (Vulkan) aktif; `FATAL EXCEPTION`: **0**, `E/AndroidRuntime`: **0**, `E/flutter`: **0**, `RenderFlex overflowed`: **0**.

---

## 6. Kapanış: `graphify --update` Bilgi Grafiği Güncellemesi

- Artımlı tarama ile değişen `16` dosya (`12` kaynak kod/test/önbellek, `4` doküman: `HF_DEPLOY.md`, `GOREV-07-RAPOR.md`, `GOREV-08-ANALIZ-ZENGINLESTIRME-VE-RELEASE.md`, `GOREV-08-RAPOR.md`) yeniden çıkarılarak mevcut graf ile birleştirildi (`build_merge`).
- **Güncel Graf İstatistikleri (`graphify-out/`):**
  - **Toplam:** `947` düğüm (`+83` yeni, `-11` eski), `1750` kenar (`+138` yeni, `-88` eski), `45` topluluk (`%91 EXTRACTED`, `%9 INFERRED`, `%0 AMBIGUOUS`, sıfır döngüsel bağımlılık / sıfır kopuk kenar).
  - **Öne Çıkan Yeni Topluluklar:** `Community 2: Tactical Turkish Match Analyst Engine`, `Community 11: HF Spaces Deploy & Task Reports`, `Community 14: Multi-Paragraph AnalysisSection Widget`, `Community 30: DataTransparencyBanner & Detail Cards`.
  - **Çıktılar:** `graphify-out/graph.json`, `graphify-out/GRAPH_REPORT.md`, `graphify-out/graph.html`.

