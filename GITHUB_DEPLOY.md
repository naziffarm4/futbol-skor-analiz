# GitHub Actions + GitHub Pages Ücretsiz Bulut Yayın Rehberi (GITHUB_DEPLOY)

Bu rehber, **Futbol Skor ve Analiz Motoru** haftalık bültenini **%100 ücretsiz, kredi kartı istemeyen, uyku modu (cold-start) olmayan ve küresel CDN hızında çalışan GitHub Actions + GitHub Pages** altyapısıyla yayınlamak ve Flutter mobil uygulamasını bu canlı adrese bağlamak için gereken **3 adımı** içerir.

---

## Adım 1: Ücretsiz Public GitHub Deposu Açma ve Projeyi Yükleme

1. [https://github.com/new](https://github.com/new) adresinden yeni bir depo oluşturun (ör. `futbol-bulten`).
2. GitHub Pages'in ücretsiz planda çalışabilmesi için depo görünürlüğünü **Public** olarak seçin (**Add a README file** seçeneğini işaretlemeden boş oluşturun).
3. Proje kök dizininde (`E:\apk\futbol`) terminali açıp projeyi GitHub'a gönderin:

```bash
git init
git branch -M main
git add .
git commit -m "Initial commit: Futbol Skor ve Analiz Bulteni"
git remote add origin https://github.com/<kullanici>/<repo>.git
git push -u origin main
```

> **Güvenlik Notu:** Kök dizindeki `.gitignore` dosyası `.env` gizli anahtarlarını, `*.apk` paketlerini, `mobile/build/` ve yerel önbellek dosyalarını otomatik olarak dışarıda bırakır.

---

## Adım 2: GitHub Pages Aktivasyonu ve İlk Canlı Yayını Tetikleme

1. GitHub deponuzda **Settings -> Pages** menüsüne gidin.
2. **Build and deployment -> Source** açılır menüsünden **GitHub Actions** seçeneğini işaretleyin.
3. Üst menüden **Actions -> Update Football Bulletin** iş akışına girin ve sağdaki **Run workflow -> Run workflow** düğmesine tıklayarak ilk yayını başlatın.
4. İş akışı yaklaşık 1-2 dakika içinde 4 ligin (Süper Lig, Premier League, La Liga, Ligue 1) canlı Transfermarkt verilerini çekip Dixon-Coles skor tahminlerini üretir ve yayınlar:
   - **Canlı Durum Sayfası:** `https://<kullanici>.github.io/<repo>/`
   - **Mobil Uygulama JSON CDN Adresi:** `https://<kullanici>.github.io/<repo>/bulletin.json`

> **Otonom Güncelleme:** `.github/workflows/update_bulletin.yml` iş akışı her gün **TSİ 09:00 (`06:00 UTC`)** ve **TSİ 19:00 (`16:00 UTC`)** saatlerinde otomatik çalışarak `bulletin.json` dosyasını yeniler. Geçici bir ağ hatasında önceki yayındaki lig verilerini korur.

---

## Adım 3: Flutter Mobil Uygulamasını Bağlama ve Release APK Derleme

Canlı `bulletin.json` adresinizi `--dart-define=API_URL=...` parametresiyle vererek uygulamayı çalıştırın veya telefonunuza kuruluma hazır imzalı/release APK üretin:

```bash
cd mobile

# Geliştirme modunda canlı GitHub Pages CDN verisiyle çalıştırma
flutter run --dart-define=API_URL=https://<kullanici>.github.io/<repo>/bulletin.json

# Dağıtıma hazır final Release APK derlemesi
flutter build apk --release --dart-define=API_URL=https://<kullanici>.github.io/<repo>/bulletin.json
```

Derlenen APK dosyası `mobile/build/app/outputs/flutter-apk/app-release.apk` yolunda oluşturulur.
