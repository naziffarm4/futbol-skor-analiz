# GÖREV-07: Sahte (Mock) Veriyi Kökten Silme, Canlı Bülten API'si ve Otomatik Canlı Senkronizasyon (Graphify & Multi-Agent)

## 1. Amaç ve Kapsam
Bu görevin amacı; `graphify` bilgi grafiği ve uzmanlaşmış **alt ajanlar (subagents)** kullanılarak:
1. Kod tabanının güncel mimari ve bağımlılık haritasının `/graphify` ile çıkarılması,
2. Mobil uygulamadaki tüm sahte / temsili (mock) verilerin **tamamen temizlenmesi**,
3. `app.py` backend servisine 4 ligin (Süper Lig, Premier League, La Liga, Ligue 1) bütün maçlarını (~38 maç), gerçek Transfermarkt sakatlıklarını ve Dixon-Coles tahminlerini döndüren canlı bir REST API (`GET /api/v1/bulletin`) eklenmesi,
4. Mobil uygulamanın doğrudan bu canlı API üzerinden otomatik çalışacak şekilde güncellenmesi ve bağlı telefona yüklenmesidir.

---

## 2. Teknik Şartname ve Alt Ajan (Subagent) Görev Dağılımı

### A. Ön Aşama: Mimari Haritalandırma (`graphify`)
- Göreve başlarken `/graphify` çalıştırılmalı; `engine/` ve `mobile/` dizinlerinin bağımlılık grafiği (`graphify-out/`) ve `GRAPH_REPORT.md` oluşturulmalıdır.

### B. Alt Ajan Delegasyonu (Subagents)

#### 🤖 Alt Ajan 1: Backend & Canlı API Uzmanı (Backend Subagent)
- **Görev:**
  1. `app.py` içine `CORSMiddleware` (tüm kökenlere izin verecek şekilde) eklemek.
  2. `GET /api/v1/bulletin` uç noktasını yazmak:
     - 4 ligin sıradaki haftasındaki **tüm gerçek maçlarını** (~38 maç), takımlarını, Dixon-Coles tahminlerini (`Prediction`), Türkçe analiz metinlerini (`TeamAnalysis`) ve Transfermarkt'tan çekilen **tüm gerçek sakat/cezalı oyuncu listelerini** (`Injury`) tekil bir JSON ağacı olarak sunmak.
  3. `engine/data/bulletin_cache.json` önbellek mekanizmasını kurmak; sunucu açıldığında veya ilk istekte 4 ligin gerçek verisini toplayıp diske ve belleğe önbellekleyerek milisaniyelik API yanıtı sağlamak.
  4. `POST /api/v1/sync` ile isteğe bağlı anlık yeniden tarama uç noktası eklemek.

#### 🤖 Alt Ajan 2: Flutter İstemci & Mock Temizleme Uzmanı (Mobile Subagent)
- **Görev:**
  1. `mobile/lib/services/mock_data.dart` dosyasını ve projedeki tüm sahte veri referanslarını **TAMAMEN SİLMEK**.
  2. `mobile/lib/services/bulletin_api_service.dart` canlı HTTP istemcisini yazmak:
     - Uygulama açılışında `GET $apiBaseUrl/api/v1/bulletin` isteği atar.
     - Varsayılan adresler: `--dart-define=API_URL=...` (Hugging Face bulut URL'si) veya `http://10.19.138.89:7860` (yerel Wi-Fi).
     - Sunucuya erişilemezse kullanıcı dostu bir "Sunucuya bağlanılamadı, tekrar dene" ekranı sunar; asla sahte veriye geri dönmez.
  3. `mobile/android/app/src/main/AndroidManifest.xml` içine `android:usesCleartextTraffic="true"` eklemek.
  4. `HomeScreen` ve `MatchDetailScreen` ekranlarını yeni gerçek modeller ve canlı API akışıyla bağlamak.

#### 🤖 Alt Ajan 3: Kalite Güvencesi, Test & Cihaz Kurulum Uzmanı (QA Subagent)
- **Görev:**
  1. `mobile/test/widget_test.dart` test dosyasını mock veriden arındırıp gerçek veri modelleri ve HTTP API ayrıştırmasıyla güncellemek.
  2. `flutter analyze` (0 hata/uyarı) ve `flutter test` (tüm testler yeşil) çalıştırmak.
  3. `flutter build apk --debug` ile uygulamayı derlemek.
  4. `adb install -r mobile/build/app/outputs/flutter-apk/app-debug.apk` ile bağlı fiziksel telefona yüklemek ve uygulamanın canlı başladığını doğrulamak.

### C. Son Aşama: Graf Güncelleme ve Kapanış (`graphify --update`)
- Tüm işlemler tamamlandığında `/graphify --update` ile bilgi grafiğini güncellemek ve tüm bulguları `tasks/GOREV-07-RAPOR.md` dosyasına kaydetmek.

---

## 3. Doğrulama Kriteri
1. `graphify-out/graph.json` ve `GRAPH_REPORT.md` dosyasının üretildiği kanıtlanmalıdır.
2. `GET http://10.19.138.89:7860/api/v1/bulletin` uç noktasının 4 ligin tüm gerçek maçlarını (haftalık ~38 maç) ve gerçek Transfermarkt sakatlıklarını JSON olarak döndürdüğü kanıtlanmalıdır.
3. `mobile/` içinde hiçbir mock maç verisinin kalmadığı (`grep MockData` -> 0 sonuç) doğrulanmalıdır.
4. `flutter analyze` ve `flutter test` sıfır hatayla geçmelidir.
5. Telefonda uygulamanın açılıp 4 ligin tüm gerçek maçlarının listelendiği doğrulanmalıdır.
