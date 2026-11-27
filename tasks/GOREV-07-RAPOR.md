# GÖREV-07 Teknik Uygulama ve Doğrulama Raporu

**Görev:** Sahte (Mock) Veriyi Kökten Silme, Canlı Bülten API'si ve Otomatik Canlı Senkronizasyon (`Graphify` & `Multi-Agent`)  
**Tarih:** 2026-11-26  
**Durum:** Tamamlandı ve Fiziksel Cihazda Canlı Doğrulandı (`Python: 29/29 test OK`, `Flutter: analyze 0 hata / test 5/5 OK`, `ADB Install: Success`)

---

## 1. Ön Aşama: Mimari Haritalandırma (`/graphify`)

Görevin başlangıcında tüm kod tabanı (`engine/`, `mobile/`, `tasks/`) üzerinde `/graphify` tam boru hattı (AST yapısal çıkarım + 3 paralel semantik alt ajan) çalıştırıldı:
- **Üretilen Dosyalar:** `graphify-out/graph.json`, `graphify-out/GRAPH_REPORT.md`, `graphify-out/graph.html`, `graphify-out/manifest.json`
- **İlk Graf Metrikleri:** `817 düğüm`, `1.696 kenar`, `50 küme (community)` (`%88 EXTRACTED`, `%12 INFERRED`, `%0 AMBIGUOUS`)
- **Merkezi Soyutlamalar (God Nodes):** `LeagueId` (51 kenar), `Injury` (34), `IngestionPipeline` (31), `Match` (30), `BaseScraper` (30), `PredictionService` (26), `Team` (25), `InjuriesScraper` (23), `MatchStatus` (21), `run_full_cycle()` (21).
- **Mimari Tespit:** Silinecek olan `MockData` katmanı bilgi grafiğinde izole `Community 35 ("Legacy Flutter MockData Layer")` olarak haritalandı.

---

## 2. Alt Ajan (Subagent) Uygulama Özeti

### 2.1. Alt Ajan 1: Backend & Canlı API Uzmanı (`app.py`, `engine/bulletin.py`)
- **`CORSMiddleware`:** `app.py` içerisine tüm kökenlere izin veren (`allow_origins=["*"]`, `allow_methods=["*"]`, `allow_headers=["*"]`, `allow_credentials=False`) CORS katmanı eklendi.
- **Canlı Bülten Ağacı ve Önbellek (`engine/bulletin.py` & `engine/data/bulletin_cache.json`):**
  - `CycleResult` çıktısını tekil JSON ağacına dönüştüren `build_bulletin_payload()` yazıldı.
  - Supabase devrede değilken lig bazlı `1`'den başlayan yerel ID çakışmalarını önlemek üzere 4 lig genelinde **global benzersiz pozitif tam sayı ID ataması** (`match.id == prediction.match_id == team_analysis.match_id: 1..38`, `injury.id: 1..231`) uygulandı.
  - `engine/data/bulletin_cache.json` (`280.766 bayt`) için geçici dosya + `os.replace` atomik yazım ve bellek içi (`_memory_cache`) milisaniyelik önbellek katmanı kuruldu; sunucu açılışında (`lifespan`) disk önbelleği otomatik belleğe alındı.
- **Yeni Uç Noktalar:**
  - `GET /api/v1/bulletin`: Bellek -> disk -> çift kontrollü `sync_lock` altında canlı üretim (`?refresh=true` destekli) ve veri üretilemediğinde HTTP `503` koruması.
  - `POST /api/v1/sync`: İsteğe bağlı tek lig (`?league=...`) veya 4 lig anlık yeniden tarama, önbellek güncelleme ve eşzamanlı çalışmada HTTP `409 Conflict` koruması (`POST /sync` geriye dönük korundu).
- **Canlı Bülten Verisi (`bulletin_cache.json` & `http://10.19.138.89:7860/api/v1/bulletin`):**
  - **Toplam Gerçek Maç (`total_matches`):** `38`
  - **Toplam Gerçek Sakat/Cezalı (`total_injuries`):** `231`
  - **Lig Bazlı Dağılım:**
    - `super_lig` (Süper Lig — 13. Hafta): **9 maç**, **68 sakat/cezalı**
    - `premier_league` (Premier League — 12. Hafta): **10 maç**, **45 sakat/cezalı**
    - `la_liga` (La Liga — 14. Hafta): **10 maç**, **69 sakat/cezalı**
    - `ligue_1` (Ligue 1 — 12. Hafta): **9 maç**, **49 sakat/cezalı**

### 2.2. Alt Ajan 2: Flutter İstemci & Mock Temizleme Uzmanı (`mobile/lib/`)
- **Sahte Verinin Kökten Silinmesi:**
  - `mobile/lib/services/mock_data.dart` ve `mobile/lib/services/supabase_service.dart` dosyaları tamamen silindi.
  - `mobile/lib/` ve `mobile/test/` genelinde `MockData` / `mock_data` referans sayısı: **0**.
- **Canlı API İstemcisi (`mobile/lib/services/bulletin_api_service.dart`):**
  - `AppConstants.apiUrl` varsayılanı `http://10.19.138.89:7860/api/v1/bulletin` olarak tanımlandı ve `--dart-define=API_URL=...` (hem kök bulut URL'si hem tam uç nokta URL'si için `resolveBulletinUri()`) desteği eklendi.
  - Türkçe karakter bütünlüğü için `utf8.decode(response.bodyBytes)` çözümlemesi ve `MatchModel.fromJson` fabrika kurucusu eklendi.
  - Yerel Wi-Fi güvenlik duvarı/hotspot kısıtlamalarında bağlı USB `adb reverse` (`127.0.0.1:7860`) tünelini otomatik deneyen taşıma yedeği eklendi; sunucu kapalı/erişilemez olduğunda **asla sahte veriye dönmez**.
- **Hata Ekranı ve Cleartext HTTP İzni:**
  - `HomeScreen` sunucuya erişemediğinde `"Sunucuya bağlanılamadı, tekrar dene"` mesajını ve `Tekrar Dene` (`ValueKey('retry_bulletin_button')`) butonunu gösterir.
  - `mobile/android/app/src/main/AndroidManifest.xml` içerisindeki `<application>` etiketine `android:usesCleartextTraffic="true"` eklendi.

### 2.3. Alt Ajan 3: QA, Test & Fiziksel Cihaz Kurulum Uzmanı (`mobile/test/`, APK, ADB)
- **`mobile/test/widget_test.dart`:** Mock veriden tamamen arındırılarak gerçek `engine/data/bulletin_cache.json` önbellek verisi ve `package:http/testing.dart` (`MockClient`) ile 5 kapsamlı birim/widget testi yazıldı (model ayrıştırma, 38 maç + sakatlık doğrulaması, HTTP 500 / ağ hatasında `"Sunucuya bağlanılamadı, tekrar dene"` ekranı ve yeniden deneme kurtarması, 4 lig sekmesi + `MatchDetailScreen` bileşenleri, `360x800` dar ekran taşmasızlık testi).
- **Analiz, Test ve APK Derleme (`$env:PUB_CACHE="E:\Users\nazif_acikgoz\AppData\Local\Pub\Cache"`):**
  - `flutter analyze`: **`No issues found!`** (`0` hata, `0` uyarı)
  - `flutter test`: **`00:03 +5: All tests passed!`** (`5/5` test yeşil)
  - `flutter build apk --debug`: `mobile/build/app/outputs/flutter-apk/app-debug.apk` başarıyla üretildi.
- **Fiziksel Telefona Kurulum ve Canlı Çalışma Kanıtı (`VKVCX8EQBE9PAIXG` / `Xiaomi 2602EPTC0G`):**
  - `adb install -r mobile/build/app/outputs/flutter-apk/app-debug.apk` -> `Performing Streamed Install -> Success`
  - `adb shell am start -W -n com.futbol.bulten.futbol_skor_bulteni/.MainActivity` -> `Status: ok`, `LaunchState: COLD`, `TotalTime: 1136 ms`
  - `uiautomator dump` ekran doğrulaması: Üst barda **`Canlı`** rozeti, 4 lig sekmesi (`🇹🇷 Süper Lig`, `🏴󠁧󠁢󠁥󠁮󠁧󠁿 Premier League`, `🇪🇸 La Liga`, `🇫🇷 Ligue 1`) ve gerçek maç kartları (`Çaykur Rizespor 0 - 0 Kasımpaşa • %66 Güven • 🚨 9 Eksik`, `Alanyaspor 0 - 0 Konyaspor • %77 Güven • 🚨 2 Eksik`, `Samsunspor 1 - 1 Gençlerbirliği SK • %57 Güven • 🚨 5 Eksik`, `Gaziantep FK 0 - 1 Amed SK • %76 Güven • 🚨 11 Eksik`) canlı olarak görüntülendi.
  - `adb logcat -d -s flutter:E AndroidRuntime:E`: **0 çalışma zamanı hatası**.

---

## 3. Karşılaşılan Hatalar / Engeller ve Uygulanan Çözümler

1. **La Liga'da Geçmiş Haftadan İleri Tarihe Ertelenmiş Tekil Maçın Sıradaki Haftayı Gölgelemesi:**
   - **Kök Neden:** Canlı Transfermarkt verisinde La Liga 8. haftadan 9 Aralık'a ertelenmiş 1 adet `SCHEDULED` maç (`Rayo Vallecano - Athletic Bilbao`) bulunduğu için saf `min(m.round)` seçimi 9–13. haftalar oynanmış olmasına rağmen 14. hafta (10 maç) yerine 8. haftayı (1 maç) seçiyordu.
   - **Çözüm:** `select_next_round(finished_matches, scheduled_matches)` algoritması eklenerek kendisinden sonraki haftalarda maç oynanmış eski erteleme haftaları atlandı ve 4 ligde tam **38 gerçek maç** üretildi.
2. **Fiziksel Telefon Hotspot + Windows Güvenlik Duvarı LAN Engeli:**
   - **Kök Neden:** Bilgisayar telefonun erişim noktasına (`Public` Wi-Fi profili) bağlıyken Windows Güvenlik Duvarı üzerinde `C:\Python313\python.exe` için `Block` kuralı bulunması ve telefonda hücresel veri açıkken Android `netd`'nin `10.0.0.0/8` CGNAT trafiğini `ap0` yerine hücresel tabloya yönlendirmesi.
   - **Çözüm:** `adb reverse tcp:7860 tcp:7860` USB tüneli aktif edildi ve `BulletinApiService` içine birincil `http://10.19.138.89:7860/api/v1/bulletin` adresinin yanında yerel USB tüneli (`http://127.0.0.1:7860/api/v1/bulletin`) yedek taşıma yolu eklendi; böylece standart `flutter build apk --debug` çıktısı hem Wi-Fi LAN açıkken hem de USB bağlıyken kesintisiz canlı veri çeker hale getirildi.

---

## 4. Kapanış: Bilgi Grafiği Güncellemesi (`/graphify --update`)

Tüm değişiklikler tamamlandıktan sonra `/graphify --update` artımlı güncellemesi çalıştırıldı:
- Silinen `mock_data.dart` ve `supabase_service.dart` dosyalarına ait `31` düğüm bilgi grafiğinden budandı (`Pruned 31 node(s)`), değişen 14 kod dosyasından `173` düğüm yenilendi.
- **Graf Fark Özeti (`graph_diff`):** `+110 yeni düğüm`, `+205 yeni kenar`, `-52 silinen düğüm`, `-201 silinen kenar`.
- **Nihai Graf Boyutu:** `875 düğüm`, `1.700 kenar` (`graphify-out/graph.json`, `graphify-out/GRAPH_REPORT.md` ve `graphify-out/graph.html` güncellendi).

---

## 5. Doğrulama Kriterleri Kontrol Tablosu

| # | Doğrulama Kriteri | Sonuç | Kanıt |
|---|---|---|---|
| 1 | `graphify-out/graph.json` ve `GRAPH_REPORT.md` üretimi + `--update` | ✅ Başarılı | İlk: `817` düğüm / `1.696` kenar; `--update` sonrası: `875` düğüm / `1.700` kenar |
| 2 | `GET http://10.19.138.89:7860/api/v1/bulletin` 4 lig gerçek maç & sakatlık | ✅ Başarılı | `HTTP 200 OK`, `CORS: *`, `total_matches: 38`, `total_injuries: 231` |
| 3 | `mobile/` içinde sıfır mock veri (`grep MockData` -> 0 sonuç) | ✅ Başarılı | `mock_data.dart` silindi; `mobile/lib` ve `mobile/test` taraması `0` eşleşme |
| 4 | `flutter analyze` ve `flutter test` sıfır hata | ✅ Başarılı | `flutter analyze`: `No issues found!`; `flutter test`: `5/5 passed!`; `unittest`: `29/29 OK` |
| 5 | Fiziksel telefonda kurulum ve 4 ligin gerçek maçlarının listelenmesi | ✅ Başarılı | `VKVCX8EQBE9PAIXG` cihazında `Canlı` rozeti, 4 lig sekmesi ve gerçek maç kartları doğrulandı |
