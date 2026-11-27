# GÖREV-08: Anlamlı & Okunabilir Maç Analizi, Veri Kaynağı Şeffaflığı, Bulut Dağıtım Hazırlığı ve Release APK

## 1. Amaç ve Kapsam
Bu görevin amacı; önceki görevde tamamen gerçek verilere geçirilen sistemin:
1. Maç ve takım analiz metinlerini teknik/robotik istatistik ifadelerinden arındırıp **futbolseverin tek bakışta anlayacağı, ikna edici, taktiksel ve gerekçeli açıklamalara** dönüştürmek,
2. Kullanıcının verilerin gerçekliğini ve güncelliğini ekranda doğrudan görebilmesi için **veri kaynağı, son güncelleme zamanı ve analiz edilen maç sayısı** şeffaflık bilgilerini eklemek,
3. Uygulamayı 154 MB'lık debug APK yerine hafif ve yüksek performanslı **arm64 Release APK** (~20-25 MB) olarak derleyip bağlı telefona kurmak,
4. Hugging Face Spaces ücretsiz bulut yayını için tek adımda kullanılabilir dağıtım doğrulaması ve rehberi hazırlamaktır.

---

## 2. Teknik Şartname ve Alt Ajan (Subagent) Görev Dağılımı

### A. Ön Aşama: Mimari Kontrol (`graphify`)
- Göreve başlamadan önce `graphify-out/` bilgi grafiğini sorgula (`analyst.py`, `bulletin.py`, `analysis_section.dart`, `match_detail_screen.dart` ilişkilerini doğrula).

### B. Alt Ajan Delegasyonu (Subagents)

#### 🤖 Alt Ajan 1: Spor Analiz Motoru & Veri Şeffaflığı Uzmanı (Backend Subagent)
- **Hedef Dosyalar:** `engine/predictors/analyst.py`, `engine/bulletin.py`, `app.py`, `engine/tests/test_predictors.py`
- **Yapılacaklar:**
  1. **`analyst.py` Yeniden Tasarımı (Doğal, Gerekçeli ve Taktiksel Dil):**
     - Ağır matematik jargonunu (*"katsayısını aşağı çekiyor"*, *"Dixon-Coles 0-5 dağılımı"* vb.) sade, akıcı ve ikna edici spor analisti Türkçesine çevir.
     - **`match_overview_text`:**
       - İlk cümlede doğrudan **"Neden bu skor öne çıktı?"** sorusunu net yanıtla (iki takımın gol üretkenliği, savunma dengesi, iç/dış saha üstünlüğü).
       - Maçın beklenen senaryosunu ve temposunu anlat (kontrollü oyun mu, yüksek tempolu karşılıklı gol mü, tek taraflı baskı mı?).
       - Kırılma noktasını somutlaştır (form farkı, kilit eksik veya iç saha baskısı).
     - **`home_analysis_text` ve `away_analysis_text`:**
       - Son 5 maç performansı, atılan/yenilen gol ortalamaları ve gol yememe (clean sheet) karnesini doğal dille anlat.
       - Sakat/cezalı oyuncuların **mevkiye özel taktiksel etkisini** yaz (Örn: Kaleci/stoper eksiği -> *"savunma yerleşimi ve duran toplarda risk"*; orta saha eksiği -> *"oyun kurulumu ve top kazanmada düşüş"*; forvet eksiği -> *"ceza sahası bitiriciliğinde güç kaybı"*).
       - Tekrara düşen kalıp cümleler yerine maçın profiline göre değişen (güçlü favori, dengeli maç, gollü düello, savunma savaşı) zengin şablonlar kullan.
  2. **Veri Şeffaflığı Metadatası (`engine/bulletin.py` & `app.py`):**
     - `GET /api/v1/bulletin` yanıtına kök düzeyinde `data_source: "Transfermarkt"`, `generated_at`, ve her lig için `played_matches_count` (analizin kaç gerçek lig maçına dayandığı) bilgisini ekle.
     - Güncel `engine/data/bulletin_cache.json` önbelleğini yeni zenginleştirilmiş analiz metinleriyle yeniden üret ve canlı sunucuyu tazele.
  3. **Hugging Face Spaces Dağıtım Hazırlığı (`HF_DEPLOY.md`):**
     - `Dockerfile` ve `app.py` yapılandırmasının Hugging Face Spaces (Port 7860, UID 1000) ile %100 uyumlu olduğunu doğrula ve kullanıcının tek seferde ücretsiz buluta çıkabilmesi için net, 3 adımlı `HF_DEPLOY.md` rehberini oluştur.

#### 🤖 Alt Ajan 2: Flutter Arayüz & Şeffaflık Uzmanı (Mobile Subagent)
- **Hedef Dosyalar:** `mobile/lib/models/`, `mobile/lib/services/bulletin_api_service.dart`, `mobile/lib/screens/home_screen.dart`, `mobile/lib/screens/match_detail_screen.dart`, `mobile/lib/widgets/analysis_section.dart`
- **Yapılacaklar:**
  1. **Veri Kaynağı & Güncelleme Şeffaflık Bandı:**
     - `HomeScreen` üst kısmında ve `MatchDetailScreen` altında verinin nereden ve ne zaman çekildiğini açıkça göster (Örn: `Kaynak: Transfermarkt • Güncelleme: 26 Kas 21:15 • 108 gerçek maç analizi`).
  2. **Okunabilir Analiz Kartları (`AnalysisSection`):**
     - Uzun tek blok metin yerine görsel hiyerarşisi yüksek, rahat okunan paragraf aralığı, vurgu başlıkları (*"Neden Bu Skor?"*, *"Ev Sahibi Durumu"*, *"Deplasman Durumu"*) ve gerekirse öne çıkan metrik özet rozetleri (örn. *"Son 5 Maç"*, *"Eksik Etkisi"*) ile okunabilirliği artır.
  3. **Dar Ekran (360x800) Taşma Kontrolü:**
     - Yeni bilgi rozetlerinin hiçbir ekran boyutunda `RenderFlex overflow` üretmediğini garanti et.

#### 🤖 Alt Ajan 3: QA, Release APK & Cihaz Kurulum Uzmanı (QA Subagent)
- **Yapılacaklar:**
  1. Python test paketini (`python -m unittest discover -s engine/tests -v`) çalıştır ve yeni analiz motoru + şeffaflık alanları için testleri doğrula.
  2. `PUB_CACHE="E:\Users\nazif_acikgoz\AppData\Local\Pub\Cache"` ile `flutter analyze` (0 sorun) ve `flutter test` (tüm testler yeşil) çalıştır.
  3. Hafif ve hızlı **Release APK** derle:
     `flutter build apk --release --target-platform android-arm64`
     (Boyutun debug APK'daki 154 MB'dan ~20-30 MB bandına düştüğünü raporla).
  4. Bağlı telefona (`adb devices`) `adb install -r mobile/build/app/outputs/flutter-apk/app-release.apk` ile yükle (`adb reverse tcp:7860 tcp:7860` aktifken uygulamayı başlat ve logcat hatasız açıldığını doğrula).

### C. Kapanış (`graphify --update`)
- `/graphify --update` ile bilgi grafiğini güncelle ve tüm kanıtları (örnek 2 gerçek maçın yeni analiz metinleri dahil) `tasks/GOREV-08-RAPOR.md` dosyasına kaydet.

---

## 3. Doğrulama Kriteri
1. Yeni üretilen analiz metinlerinden en az 2 gerçek maç örneği `tasks/GOREV-08-RAPOR.md` içinde yer almalı; metinlerin akıcı, gerekçeli ve taktiksel olduğu kanıtlanmalıdır.
2. `GET /api/v1/bulletin` yanıtında `data_source` ve lig bazlı `played_matches_count` alanları doğrulanmalıdır.
3. Python tüm testleri + `flutter analyze` (0 sorun) + `flutter test` geçmelidir.
4. `app-release.apk` başarıyla derlenip bağlı telefona kurulmalı ve sıfır hatayla çalışmalıdır.
