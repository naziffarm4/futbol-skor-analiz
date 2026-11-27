# GÖREV-10: GitHub Pages Canlı Bulut Yayını ve Bulut Bağlantılı Final Release APK

## 1. Amaç ve Kapsam
Bu final görevin amacı; sistemde aktif olan `gh` CLI oturumu (`naziffarm4`) üzerinden:
1. `futbol-skor-analiz` adlı public GitHub deposunu oluşturmak ve temiz proje kodunu (`.gitignore` kurallarına uyarak, hiçbir `.env` veya gizli anahtar içermeden) yüklemek,
2. GitHub Pages'i `build_type: workflow` (GitHub Actions) modunda aktif edip `.github/workflows/update_bulletin.yml` iş akışını tetiklemek ve canlı `https://naziffarm4.github.io/futbol-skor-analiz/bulletin.json` adresinin HTTP 200 ile 4 ligin gerçek verisini döndürdüğünü doğrulamak,
3. Flutter mobil uygulamasını `--dart-define=API_URL=https://naziffarm4.github.io/futbol-skor-analiz/bulletin.json` parametresiyle **Final Release APK (`android-arm64`)** olarak derleyip bağlı fiziksel telefona yüklemek ve **USB tüneli olmadan** (doğrudan internet üzerinden) canlı açıldığını kanıtlamaktır.

---

## 2. Teknik Şartname ve Alt Ajan (Subagent) Görev Dağılımı

### A. Ön Aşama: Güvenlik & Temizlik Kontrolü (`graphify`)
- `git status` ve `.gitignore` kontrolü ile `.env`, gizli anahtar, `mobile/build/` veya büyük geçici dosyaların kesinlikle commit edilmeyeceğini doğrula.

### B. Alt Ajan Delegasyonu (Subagents)

#### 🤖 Alt Ajan 1: GitHub Repo & Pages Yayın Uzmanı (DevOps Subagent)
1. `gh auth status` ile `naziffarm4` oturumunu doğrula.
2. `git init -b main` (eğer repo henüz başlatılmamışsa), `.gitignore` kontrolü, ilk temiz commit.
3. `gh repo create naziffarm4/futbol-skor-analiz --public --source=. --remote=origin --push` ile depoyu oluştur ve kodu gönder (eğer repo zaten varsa mevcut remote'a push et).
4. GitHub API (`gh api -X POST repos/naziffarm4/futbol-skor-analiz/pages -f build_type=workflow` veya `PUT`) ile GitHub Pages kaynağını **GitHub Actions** olarak etkinleştir.
5. `gh workflow run update_bulletin.yml` ile ilk otomatik bülten üretimini başlat ve `gh run watch` ile iş akışının yeşil (`completed / success`) bitmesini bekle.
6. `https://naziffarm4.github.io/futbol-skor-analiz/bulletin.json` adresine HTTP GET atarak HTTP 200, `data_source: "Transfermarkt"`, 4 lig ve tüm gerçek maç/sakatlıkların canlı yayında olduğunu doğrula.

#### 🤖 Alt Ajan 2: Final Release APK & Fiziksel Cihaz Doğrulama Uzmanı (Mobile/QA Subagent)
1. Canlı URL (`https://naziffarm4.github.io/futbol-skor-analiz/bulletin.json`) doğrulandıktan sonra `mobile/` dizininde:
   - `$env:PUB_CACHE="E:\Users\nazif_acikgoz\AppData\Local\Pub\Cache"`
   - `flutter build apk --release --target-platform android-arm64 --dart-define=API_URL=https://naziffarm4.github.io/futbol-skor-analiz/bulletin.json`
2. Önceki USB tünelini temizle (`adb reverse --remove-all`), böylece uygulamanın yerel bilgisayara değil **gerçekten buluttaki GitHub Pages CDN'ine** bağlandığını kanıtla!
3. `adb install -r mobile/build/app/outputs/flutter-apk/app-release.apk` ile telefona yükle, uygulamayı başlat ve `adb logcat` üzerinde sıfır hata ile canlı bültenin açıldığını doğrula.

### C. Kapanış (`graphify --update`)
- `/graphify --update` çalıştır ve canlı URL, GitHub Actions run linki, APK boyutu/SHA-256 ve telefon doğrulama kanıtlarını `tasks/GOREV-10-RAPOR.md` dosyasına kaydet.

---

## 3. Doğrulama Kriteri
1. `https://naziffarm4.github.io/futbol-skor-analiz/bulletin.json` -> HTTP 200 OK ve 4 ligin eksiksiz gerçek verisi.
2. `https://naziffarm4.github.io/futbol-skor-analiz/` -> Koyu tema canlı durum sayfası HTTP 200 OK.
3. `adb reverse --remove-all` sonrasında fiziksel telefonda uygulama doğrudan buluttan veriyi çekip 0 hata ile açılmalı.
4. `tasks/GOREV-10-RAPOR.md` eksiksiz kaydedilmeli.
