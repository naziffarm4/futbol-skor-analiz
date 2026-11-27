# GÖREV-12-REPAIR: Denetim Bulgularının Kapatılması (Mypy Sıfırlama, Soğuk Başlangıç Koruması, Git Geçmişi Temizliği)

## 1. Amaç ve Kapsam
GÖREV-12 bağımsız teknik denetiminde tespit edilen 3 somut açığı kapatmak ve depoyu tamamen temiz, sıfır uyarılı duruma getirmek:

1. **Tam `mypy engine app.py` Sıfırlama:** Test klasörü dahil tüm dosyalarda (40+ dosya) `mypy engine app.py` komutunun **0 hata** vermesini sağlamak:
   - `engine/tests/test_foundation.py:90`: `ModelMetaclass` tip hatasını (`type[DBModel]` veya `cast` / `getattr` olmadan doğru tip daraltmasıyla) gider.
   - `engine/tests/test_scrapers.py:284, 349`: `Tag | None` üzerinde `assert ... is not None` daraltması ekleyerek `union-attr` hatalarını gider.
2. **`app.py` Soğuk Başlangıç Kimlik Doğrulama Düzeltmesi:**
   - `GET /api/v1/bulletin` (`refresh=False`) çağrısında bellek/disk önbelleği boşsa (`cached is None`), kimlik doğrulaması olmadan ağır `run_full_cycle()` tetiklenmesini engelle; bunun yerine HTTP `503 Service Unavailable` (`"Bülten önbelleği henüz hazırlanmadı; zamanlayıcı veya yetkili senkronizasyon bekleniyor."`) döndür.
   - Önbellek üretimi yalnızca arka plan zamanlayıcısı veya `SYNC_API_KEY` ile doğrulanan `POST /sync`, `POST /api/v1/sync`, `GET /api/v1/bulletin?refresh=true` tarafından yapılabilsin.
   - `engine/tests/test_runner.py` içindeki ilgili testi bu güvenli davranışa göre güncelle ve yeni bir testle soğuk başlangıçta kimlik doğrulamasız `GET /api/v1/bulletin` çağrısının `run_full_cycle` tetiklemediğini (HTTP 503 döndüğünü) doğrula.
3. **Public GitHub Geçmişinden `GEMINI.md` ve `CLAUDE.md` Temizliği (Yerel Kopyaları Koruyarak):**
   - Yerel diskteki `GEMINI.md` ve `CLAUDE.md` dosyalarını **ASLA SİLME** (`.gitignore` içinde kalmaya devam edecekler).
   - Git geçmişindeki eski commit'lerde kalan `GEMINI.md` ve `CLAUDE.md` izlerini temizle (en güvenli ve sıfır dış araç gerektiren yol: mevcut temiz çalışma ağacından `git checkout --orphan clean-main`, tüm takip edilen dosyalarla temiz tek kök commit oluşturup `git branch -M clean-main main` ve `git push --force origin main` yap — `.gitignore` sayesinde `GEMINI.md`, `CLAUDE.md`, `.env`, `graphify-out/` kesinlikle dahil olmaz).
   - Ardından `git log --all -- GEMINI.md CLAUDE.md` çıktısının **tamamen boş** olduğunu kanıtla ve `ci.yml` iş akışının GitHub üzerinde yeşil geçtiğini doğrula.

---

## 2. Doğrulama Kriteri
1. `mypy engine app.py` -> `Success: no issues found` (0 hata).
2. `ruff check engine app.py` -> `All checks passed!` (0 hata).
3. `python -m unittest discover -s engine/tests -v` -> Tüm testler OK (0 hata).
4. `git log --all -- GEMINI.md CLAUDE.md` -> Boş çıktı; yerel diskte `Test-Path GEMINI.md` ve `Test-Path CLAUDE.md` -> `True`.
5. GitHub `ci.yml` son koşumu -> `success`.
6. `/graphify --update` ve kanıtlar `tasks/GOREV-12-REPAIR-RAPOR.md` dosyasına kaydedilmeli.
