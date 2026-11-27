# GÖREV-05: Flutter Mobil Uygulaması (Karanlık Tema, 4 Lig Sekmesi, Skor Tahmin Kartları ve Analiz Paneli)

## 1. Amaç ve Kapsam
Bu görevin amacı; Türkiye Süper Ligi, İngiltere Premier League, İspanya La Liga ve Fransa Ligue 1 için otonom olarak üretilen skor tahminlerini, takım analiz raporlarını ve sakatlık/ceza durumlarını modern, yüksek performanslı ve akıcı bir **Flutter (Dart)** mobil uygulaması olarak geliştirmektir.

Kullanıcı tercihleri doğrultusunda:
- **Tasarım:** Modern, koyu tema (Dark Theme - FotMob/SofaScore stili lacivert/füme zemin, neon yeşil/turuncu/mavi vurgular).
- **Odak:** Sadece maç skoru tahminleri (en olası skor, alternatif ilk 3 skor ve güven oranı).
- **Analizler:** Takımlar hakkında üretilen uzman analiz metinleri ve kuvvet göstergeleri.
- **Sakatlıklar:** Her iki takımın eksik oyuncu listesi, mevkileri, nedenleri ve takıma etki dereceleri.
- **Bağlantı & Dayanıklılık:** Supabase istemcisi üzerinden canlı veri çekme, bağlantı/anahtar henüz tanımlı değilken dahi uygulamanın tam çalışmasını sağlayan zengin çevrimdışı (offline fallback/mock) veri desteği.

---

## 2. Teknik Şartname

### A. Proje Konumu ve Bağımlılıklar (`mobile/`)
Proje `e:\apk\futbol\mobile\` dizininde konumlandırılmalıdır:
- Sistemdeki Flutter SDK yolu: `E:\Users\nazif_acikgoz\AppData\Local\develop\flutter\bin\flutter`
- Bağımlılıklar (`mobile/pubspec.yaml`):
  - `flutter: sdk: flutter`
  - `supabase_flutter: ^2.8.0` (Supabase PostgreSQL ve REST istemcisi)
  - `google_fonts: ^6.2.0` (Modern tipografi: Inter / Poppins)
  - `intl: ^0.20.0` (Tarih ve saat formatlama)

### B. Mimari ve Dizin Yapısı (`mobile/lib/`)
```text
e:\apk\futbol\mobile\
├── pubspec.yaml
├── lib\
│   ├── main.dart                      # Uygulama giriş noktası, koyu tema yapılandırması
│   ├── config\
│   │   ├── theme.dart                 # Renk paleti, koyu tema, kart stilleri, tipografi
│   │   └── constants.dart             # 4 lig tanımları, bayraklar, varsayılan ayarlar
│   ├── models\
│   │   ├── league_model.dart          # Lig veri modeli
│   │   ├── match_model.dart           # Maç ve takım modeli
│   │   ├── prediction_model.dart      # Skor tahmini ve Top 3 skorlar
│   │   ├── analysis_model.dart        # Takım analiz metinleri ve reytingler
│   │   └── injury_model.dart          # Sakat ve cezalı oyuncu modeli
│   ├── services\
│   │   ├── supabase_service.dart      # Supabase veri çekme ve hata yönetimi
│   │   └── mock_data.dart             # Canlı bağlantı olmadığında 4 lig için zengin demo verisi
│   ├── screens\
│   │   ├── home_screen.dart           # 4 lig sekmeli bülten ana ekranı
│   │   └── match_detail_screen.dart   # Maç detayı, skor dağılımı, analiz ve sakatlık paneli
│   └── widgets\
│       ├── match_card.dart            # Bülten maç kartı (skor rozeti, güven oranı, sakatlık rozeti)
│       ├── score_probability_bar.dart # En olası ilk 3 skorun yatay ilerleme çubuğu
│       ├── rating_comparison_bar.dart # Hücum ve savunma güç karşılaştırma çubukları
│       ├── analysis_section.dart      # Maç özeti, ev sahibi ve deplasman analiz kartları
│       └── injuries_list.dart         # Mevki ve etki derecesi rozetli sakatlar listesi
└── test\
    └── widget_test.dart               # Kapsamlı UI ve veri model testleri
```

### C. Ekran ve Bileşen Detayları

1. **Ana Ekran (`HomeScreen`):**
   - Üst Bar: "⚽ Futbol Skor & Analiz Bülteni" başlığı, anlık yenileme butonu (`RefreshIndicator`).
   - **4 Lig Sekmesi (`TabBar`):**
     - 🇹🇷 Süper Lig
     - 🏴󠁧󠁢󠁥󠁮󠁧󠁿 Premier League
     - 🇪🇸 La Liga
     - 🇫🇷 Ligue 1
   - **Haftanın Maçları Kartları (`MatchCard`):**
     - Ev sahibi ve deplasman takımlarının adları ve renkli logoları/rozetleri.
     - Maç günü ve başlama saati.
     - **Bültenin Skor Tahmini:** Büyük puntoyla neon vurgulu skor kutusu (Örn: `2 - 1`).
     - **Güven Rozeti:** Örn: `%68 Güven`.
     - **Eksikler Rozeti:** Örn: `🚨 3 Eksik`.
     - Tıklandığında `MatchDetailScreen` ekranına akıcı geçiş.

2. **Maç Detay Ekranı (`MatchDetailScreen`):**
   - **Hero Banner:** Takım isimleri, maç tarihi, bültenin ana skoru ve güven skoru.
   - **Skor Olasılık Dağılımı (Top 3 Skorlar):**
     - 1. Skor: Örn. `2 - 1` (%16.8) [Yeşil ilerleme çubuğu]
     - 2. Skor: Örn. `1 - 1` (%14.2) [Mavi ilerleme çubuğu]
     - 3. Skor: Örn. `2 - 0` (%11.5) [Gri ilerleme çubuğu]
   - **Uzman Sistem Analiz Raporu:**
     - 📌 *Genel Maç Akışı:* Tempo, gol beklentisi ve derbi/denge durumu.
     - 🏠 *Ev Sahibi Analizi:* Form, iç saha üretkenliği ve eksiklerin hücuma/savunmaya net etkisi.
     - ✈️ *Deplasman Analizi:* Dış saha direnci, gol yememe performansı ve eksiklerin zaafiyetleri.
   - **Karşılaştırmalı Kuvvet Göstergeleri:**
     - Ev Sahibi Hücum vs Deplasman Savunma (0 - 100 puan)
     - Ev Sahibi Savunma vs Deplasman Hücum (0 - 100 puan)
   - **Sakatlık & Ceza Listesi:**
     - İki takımın ayrı sekmeleri veya blokları halinde:
     - Oyuncunun adı, mevkisi (`GK`, `DEF`, `MID`, `FW` renkli rozet), sakatlık nedeni, tahmini dönüş tarihi ve etki derecesi (`HIGH`, `MEDIUM`, `LOW`).

---

## 3. Doğrulama ve Test Kriteri
- Flutter projesi oluşturulmalı ve `pub get` bağımlılıkları yüklenmelidir.
- `flutter analyze` veya `dart analyze` ile statik kod analizi çalıştırılmalı ve sıfır hata/uyarı elde edilmelidir.
- `flutter test` ile `test/widget_test.dart` çalıştırılmalı:
  - 4 lig sekmesinin hatasız render edildiği,
  - Maç kartlarının bülten skorlarıyla listelendiği,
  - Maç kartına tıklandığında detay ekranına geçildiği,
  - Skor olasılık çubuklarının, analiz metinlerinin ve sakatlık listelerinin eksiksiz görüntülendiği doğrulanmalıdır.
- Tüm süreç ve test sonuçları `tasks/GOREV-05-RAPOR.md` dosyasına kaydedilmelidir.
