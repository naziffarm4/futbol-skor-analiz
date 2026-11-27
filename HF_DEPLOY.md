# Hugging Face Spaces Bulut Dağıtım Rehberi (HF_DEPLOY)

> **ÖNEMLİ DUYURU — ÜCRETSİZ ALTERNATİF ÖNERİSİ (`GITHUB_DEPLOY.md`):**
> Hugging Face Docker Spaces altyapısının belirli katmanlarda ücretli / **PRO** plan gerektirmesi nedeniyle, bu proje için önerilen birincil dağıtım yöntemi **%100 ücretsiz, kredi kartı istemeyen, uyku modu (sleep/cold-start) bulunmayan GitHub Actions + GitHub Pages CDN** mimarisidir. Kurulum için doğrudan **[`GITHUB_DEPLOY.md`](./GITHUB_DEPLOY.md)** rehberini takip edin.

Bu rehber, **Futbol Skor ve Analiz Motoru** FastAPI arka uç servisini Hugging Face Spaces üzerinde yayınlamak ve Flutter mobil uygulamasını canlı bulut adresine bağlamak için gereken 3 adımı içerir.

---

## Adım 1: Hugging Face Space Oluşturma

1. [https://huggingface.co/new-space](https://huggingface.co/new-space) adresine gidin ve hesabınızla giriş yapın.
2. **Space name** alanına kısa bir ad verin (ör. `futbol-analiz-api`).
3. **Select the Space SDK** bölümünden **Docker** seçeneğini işaretleyin (şablon olarak **Blank** seçebilirsiniz).
4. **Space hardware** bölümünde ücretsiz katman olan **CPU basic (2 vCPU · 16 GB · FREE)** donanımını seçin.
5. Görünürlüğü **Public** olarak bırakın (mobil uygulamanın kimlik doğrulama başlığı olmadan doğrudan `/api/v1/bulletin` uç noktasına erişebilmesi için önerilir) ve **Create Space** düğmesine tıklayın.

> **Teknik Uyumluluk Notu:** Depodaki `Dockerfile`, Hugging Face Spaces Docker SDK standartlarına uygun şekilde `UID 1000` (`user`) yetkisiyle çalışır, `/app/engine/data` önbellek dizinine yazma iznine sahiptir ve `7860` portunu dışarı açar. `README.md` başlığındaki YAML bloğu (`sdk: docker`, `app_port: 7860`) hazır yapılandırılmıştır.

---

## Adım 2: Ortam Değişkenleri (Secrets / Variables) ve Kod Yükleme

### 2.1. Secrets ve Variables Tanımlama

Space sayfasında **Settings -> Variables and secrets** bölümüne giderek aşağıdaki değerleri ekleyin:

**New secret (Gizli Anahtarlar - İsteğe Bağlı Kalıcı Veritabanı İçin):**
- `SUPABASE_URL`: Supabase proje URL adresiniz (ör. `https://xxxx.supabase.co`). Tanımlanmazsa servis yerel bellek + disk önbelleği (`bulletin_cache.json`) modunda kesintisiz çalışmaya devam eder.
- `SUPABASE_KEY`: Supabase `anon` / `public` anahtarınız.
- `SUPABASE_SERVICE_ROLE_KEY`: Yazma (`upsert`) işlemleri için Supabase `service_role` anahtarınız.
- `SYNC_API_KEY`: Manuel senkronizasyon uç noktaları (`POST /sync`, `POST /api/v1/sync`, `GET /api/v1/bulletin?refresh=true`) için zorunlu gizli anahtar (`X-API-Key` veya `Authorization: Bearer <token>`).

**New variable (Çalışma Zamanı Ayarları):**
- `SCHEDULER_ENABLED`: `true` (günlük otonom Transfermarkt veri çekme ve tahmin döngüsünü etkinleştirir).
- `SYNC_INTERVAL_HOURS`: `24` (tam senkronizasyon döngüsü aralığı, saat cinsinden).
- `STARTUP_SYNC_DELAY_SECONDS`: `5` (konteyner açılışından kaç saniye sonra ilk arka plan senkronizasyonunun başlayacağı).
- `DEFAULT_SEASON`: *(isteğe bağlı — boş bırakıldığında her yıl Temmuz itibarıyla otomatik dinamik `YIL-(YIL+1)` sezonu hesaplanır)*.
- `HTTP_TIMEOUT_SECONDS`: `30` (veri kaynakları HTTP istek zaman aşımı süresi).

### 2.2. Kaynak Kodun Yüklenmesi

Sadece arka uç dosyalarını (`app.py`, `Dockerfile`, `README.md`, `engine/`) Space deposuna gönderin (`mobile/` klasörünü göndermenize gerek yoktur):

```bash
git init
git remote add space https://huggingface.co/spaces/<kullanici>-adi/<space>-adi
git add Dockerfile README.md app.py engine/
git commit -m "Deploy Futbol Skor ve Analiz Motoru backend"
git push --force space main
```

Push işleminden sonra Hugging Face Spaces konteyneri otomatik olarak derler (**Building**) ve birkaç dakika içinde **Running** durumuna geçirir.

---

## Adım 3: Canlı Doğrulama ve Mobil Uygulamayı Derleme

### 3.1. Canlı Servis Kontrolü

Space adresiniz `https://<kullanici>-<space>.hf.space` biçimindedir (Hugging Face kullanıcı adınız ve Space adınız küçük harflerle, tire ile birleştirilir). Tarayıcıdan veya terminalden doğrulayın:

```bash
# 1. Sağlık kontrolü
curl -s https://<kullanici>-<space>.hf.space/health

# 2. Güncel haftalık bülten ve veri şeffaflığı alanları (data_source, total_played_matches)
curl -s https://<kullanici>-<space>.hf.space/api/v1/bulletin

# 3. İsteğe bağlı manuel yenileme tetikleme (SYNC_API_KEY gerektirir)
curl -s -X POST -H "X-API-Key: $SYNC_API_KEY" https://<kullanici>-<space>.hf.space/api/v1/sync
```

### 3.2. Flutter Mobil Uygulamasını Canlı API ile Çalıştırma ve Derleme

`mobile/` dizininde `--dart-define=API_URL=...` parametresiyle canlı Hugging Face Space adresini vererek uygulamayı çalıştırın veya APK paketini üretin:

```bash
cd mobile

# Geliştirme / bağlı fiziksel cihazda canlı API ile çalıştırma
flutter run --dart-define=API_URL=https://<kullanici>-<space>.hf.space

# Yayın (Release) APK derlemesi
flutter build apk --release --dart-define=API_URL=https://<kullanici>-<space>.hf.space
```
