# GÖREV-09: %100 Ücretsiz Bulut Yayını (GitHub Actions + GitHub Pages) ve Statik CDN Uyumlu Mobil İstemci

## 1. Amaç ve Kapsam
Hugging Face Docker/Gradio Spaces katmanının ücretli (PRO) plana geçmesi nedeniyle, projenin bulut altyapısını **%100 ücretsiz, kredi kartı istemeyen, uyku modu olmayan ve global CDN hızında çalışan GitHub Actions + GitHub Pages** mimarisine geçirmek:

1. Günde 2 kez otomatik (ve istenildiğinde tek tıkla manuel) çalışarak 4 ligin gerçek Transfermarkt maç/sakatlık verilerini ve Dixon-Coles + taktiksel Türkçe analizlerini üreten **GitHub Actions** iş akışı (`.github/workflows/update_bulletin.yml`) oluşturmak.
2. Çıktıyı statik `bulletin.json` (+ şık durum sayfası `index.html`) olarak **GitHub Pages**'e yayınlamak (`https://<kullanici>.github.io/<repo>/bulletin.json`).
3. Flutter `BulletinApiService` istemcisini hem doğrudan `.json` statik CDN adreslerini (cache-busting `?t=` destekli) hem de klasik `/api/v1/bulletin` FastAPI adreslerini destekleyecek şekilde güncellemek.
4. Depoyu temiz `.gitignore` ile GitHub'a yüklemeye hazır hale getirmek ve 3 adımlı `GITHUB_DEPLOY.md` rehberini hazırlamak (sistemde `gh` CLI oturumu açıksa doğrudan kontrol etmek).

---

## 2. Teknik Şartname ve Alt Ajan (Subagent) Görev Dağılımı

### A. Ön Aşama: Mimari Kontrol (`graphify`)
- `graphify-out/` üzerinden `engine/cli.py`, `engine/bulletin.py` ve `mobile/lib/services/bulletin_api_service.dart` düğüm ilişkilerini sorgula.

### B. Alt Ajan Delegasyonu (Subagents)

#### 🤖 Alt Ajan 1: Backend Export, GitHub Actions & Deploy Hazırlığı (Backend/DevOps Subagent)
- **Hedef Dosyalar:** `engine/cli.py`, `engine/bulletin.py`, `.github/workflows/update_bulletin.yml`, `.gitignore`, `GITHUB_DEPLOY.md`
- **Yapılacaklar:**
  1. **Statik Bülten Dışa Aktarma (`engine/cli.py`):**
     - `python -m engine.cli --export-bulletin <output_path>` argümanını ekle.
     - 4 ligin tamamını (`super_lig`, `premier_league`, `la_liga`, `ligue_1`) canlı çekip `GET /api/v1/bulletin` ile birebir aynı JSON şemasında (`data_source`, `generated_at`, `total_played_matches`, `leagues_meta`, `leagues`) hedef dosyaya atomik olarak yazsın.
     - Eğer tek bir ligde geçici ağ hatası olursa önceki mevcut dosyadan o ligi koruyabilen dayanıklı (resilient) yazım mantığı ekle.
  2. **GitHub Actions İş Akışı (`.github/workflows/update_bulletin.yml`):**
     - Tetikleyiciler: `schedule` (`0 6 * * *` ve `0 16 * * *` UTC — TSİ 09:00 ve 19:00), `workflow_dispatch` (manuel tek tık).
     - İzinler: `contents: read`, `pages: write`, `id-token: write`.
     - Python 3.12 kurar, `engine/requirements.txt` yükler, `python -m engine.cli --export-bulletin dist/bulletin.json` çalıştırır, `dist/bulletin.json` içeriğinde 4 lig ve geçerli maçlar olduğunu doğrular, minimalist bir `dist/index.html` + `dist/.nojekyll` oluşturur ve resmi `actions/upload-pages-artifact@v3` + `actions/deploy-pages@v4` ile GitHub Pages'e yayınlar.
  3. **`.gitignore` ve `GITHUB_DEPLOY.md`:**
     - `.env`, `mobile/build/`, `.dart_tool/`, `__pycache__/`, `*.apk`, `.venv/` vb. gereksiz/gizli dosyaları hariç tutan temiz `.gitignore` oluştur.
     - Kullanıcının GitHub'da tek repo açıp Pages'i aktif etmesi ve ardından `--dart-define=API_URL=https://<kullanici>.github.io/<repo>/bulletin.json` ile final Release APK derlemesi için 3 adımlı, sade `GITHUB_DEPLOY.md` rehberini yaz (eski `HF_DEPLOY.md` içine GitHub Pages'in önerilen ücretsiz yol olduğuna dair yönlendirme notu düş).
     - Sistemde `gh auth status` kontrolü yap; eğer zaten giriş yapılmış bir GitHub CLI oturumu varsa raporda belirt (izinsiz repo açma/push yapma).

#### 🤖 Alt Ajan 2: Flutter Statik CDN İstemci Güncellemesi (Mobile Subagent)
- **Hedef Dosyalar:** `mobile/lib/services/bulletin_api_service.dart`, `mobile/lib/config/constants.dart`
- **Yapılacaklar:**
  1. **Akıllı URL Çözümleme (`BulletinApiService`):**
     - Verilen `API_URL` (veya `apiBaseUrl`) `.json` ile bitiyorsa (örn: `https://<user>.github.io/<repo>/bulletin.json`), sonuna `/api/v1/bulletin` eklemeden doğrudan o URL'ye istek atsın.
     - `.json` ile bitmiyorsa mevcut gibi `/api/v1/bulletin` eklesin.
     - CDN önbelleğini aşmak için isteğe `?_ts=<epoch_ms>` sorgu parametresi ve `Cache-Control: no-cache` başlığı eklesin (böylece kullanıcı ekranı aşağı çektiğinde anında taze veriyi görsün).
  2. **Bulut URL Yapılandırıldığında Yerel Fallback Davranışı:**
     - `--dart-define=API_URL=https://...` verilmişse yalnızca o bulut adresini kullansın, gereksiz yere `127.0.0.1:7860` USB tüneline düşmesin; geliştirme modunda (tanımsızken) mevcut yerel/USB yedek davranışını korusun.

#### 🤖 Alt Ajan 3: QA & Doğrulama Uzmanı (QA Subagent)
- **Yapılacaklar:**
  1. `python -m engine.cli --export-bulletin engine/data/test_export_bulletin.json` (veya mock/birim testi) ile export şemasının `GET /api/v1/bulletin` ile birebir uyumlu olduğunu test et ve geçici test dosyasını temizle.
  2. `python -m unittest discover -s engine/tests -v` ile tüm Python testlerinin (yeni export testi dahil) sıfır hatayla geçtiğini doğrula.
  3. `mobile/test/widget_test.dart` içine statik `.json` URL çözümleme + cache-busting testi ekle; `PUB_CACHE="E:\Users\nazif_acikgoz\AppData\Local\Pub\Cache"` ile `flutter analyze` (0 sorun) ve `flutter test` (tüm testler yeşil) doğrula.
  4. YAML sözdizimi doğrulaması (`.github/workflows/update_bulletin.yml` geçerli YAML olduğunu Python ile kontrol et).

### C. Kapanış (`graphify --update`)
- `/graphify --update` ile bilgi grafiğini güncelle ve tüm kanıtları `tasks/GOREV-09-RAPOR.md` dosyasına kaydet.

---

## 3. Doğrulama Kriteri
1. `.github/workflows/update_bulletin.yml` geçerli YAML ve resmi GitHub Pages dağıtım akışına uygun olmalı.
2. `python -m engine.cli --export-bulletin` komutu ve birim testleri sıfır hatayla geçmeli.
3. `BulletinApiService` hem `https://.../bulletin.json` hem de `http://...:7860` adreslerini testlerle doğrulamalı.
4. `flutter analyze` (0 sorun) ve `flutter test` tamamen yeşil olmalı.
5. `GITHUB_DEPLOY.md` ve `.gitignore` eksiksiz hazır olmalı.
