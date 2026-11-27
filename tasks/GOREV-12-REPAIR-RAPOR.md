# GÖREV-12-REPAIR Denetim Düzeltme ve Doğrulama Raporu

**Tarih:** 2026-11-27  
**Durum:** ✅ TAMAMLANDI (Tam `mypy` Sıfırlama + `GET /api/v1/bulletin` Soğuk Başlangıç Koruması + Git Geçmişinden `GEMINI.md`/`CLAUDE.md` Temizliği + GitHub Actions `ci.yml` Yeşil Geçiş + `/graphify --update`)

---

## 1. Ön Aşama: `graphify` Bağımlılık ve Etki Alanı Kontrolü

Uygulama öncesinde `graphify-out/graph.json` (`1,429` düğüm, `3,276` kenar, `76` topluluk, `EXTRACTED: %90`, `INFERRED: %10`, `AMBIGUOUS: %0`) üzerinde BFS sorguları çalıştırılarak değiştirilecek bileşenlerin tüm çağrıcıları doğrulandı:

- **`app.py` (`get_bulletin`, `require_sync_api_key`, `_execute_sync`, `_daily_scheduler_loop`):** `engine/bulletin.py` (`get_cached_bulletin`, `load_bulletin_from_disk`, `update_bulletin_cache`) ve `engine/runner.py` (`run_full_cycle`) ile doğrudan bağlı olduğu; HTTP test kapsamının `engine/tests/test_runner.py` (`RunnerAndServiceTests`) ve `engine/tests/test_security_api.py` (`SecurityAndObservabilityTests`) üzerinde toplandığı belirlendi.
- **`engine/tests/test_foundation.py` (`FoundationVerificationTests.test_sql_schema_and_pydantic_parity`):** `engine/models/schemas.py` içindeki `DBModel` (`_non_db_fields: ClassVar[tuple[str, ...]]`) alt sınıflarını (`League`, `Team`, `Match`, `Injury`, `Prediction`, `TeamAnalysis`) SQL şemasıyla karşılaştırdığı doğrulandı.
- **`engine/tests/test_scrapers.py` (`BaseScraperTests`):** `BaseScraper.fetch_soup()` üzerinden dönen `BeautifulSoup.select_one(".box")` (`Tag | None`) çağrılarının `L284` ve `L349` satırlarında daraltılmadığı tespit edildi.

---

## 2. Alt Ajan 1: Kod ve Güvenlik Düzeltmeleri

### 2.1. Tam `mypy engine app.py` Sıfırlama (40 Kaynak Dosya, 0 Hata)
- **`engine/tests/test_foundation.py`:**
  - Başlangıç hatası: `ModelMetaclass has no attribute "model_fields"` ve `"_non_db_fields"` (`[attr-defined]`).
  - Çözüm: `engine.models.schemas` modülünden `DBModel` içe aktarıldı ve `model_map: dict[str, type[DBModel]] = { ... }` tip bildirimi eklendi (`cast` veya `getattr` kullanmadan doğrudan sınıf hiyerarşisi üzerinden tip daraltması sağlandı).
- **`engine/tests/test_scrapers.py`:**
  - Başlangıç hatası: `Item "None" of "Tag | None" has no attribute "get_text"` (`[union-attr]`, `L284` ve `L349`).
  - Çözüm: `test_rate_limiting_and_retry_backoff` ve `test_waf_202_switches_to_browser_and_preserves_404` metotlarında `box = soup.select_one(".box")` ve `assert box is not None` daraltması eklendi.

### 2.2. `app.py` Soğuk Başlangıç Kimlik Doğrulama Koruması (`GET /api/v1/bulletin`)
- **Kök Neden:** Önceki akışta `GET /api/v1/bulletin` (`refresh=False`) çağrıldığında bellek/disk önbelleği henüz boşsa (`cached is None`), uç nokta kimlik doğrulaması aramadan `sync_lock` alıp ağır `run_full_cycle()` (5 kaynaklı ağ kazıma + veritabanı yazımı) sürecini tetikliyordu.
- **Uygulanan Düzeltme (`app.py:get_bulletin`):**
  - `not refresh` dalında `cached = get_cached_bulletin()` kontrolü yapılır; önbellek doluysa doğrudan döndürülür, boşsa (`cached is None`) `sync_lock` alınmadan ve `run_full_cycle()` çağrılmadan derhal HTTP `503 Service Unavailable` (`"Bülten önbelleği henüz hazırlanmadı; zamanlayıcı veya yetkili senkronizasyon bekleniyor."`) yükseltilir.
  - Bülten önbelleği üretimi yalnızca arka plan zamanlayıcısı (`_daily_scheduler_loop`) veya `SYNC_API_KEY` ile doğrulanan `POST /sync`, `POST /api/v1/sync` ve `GET /api/v1/bulletin?refresh=true` uç noktaları tarafından gerçekleştirilebilir.
- **Birim ve Güvenlik Testi Güncellemeleri (`engine/tests/test_runner.py`, `engine/tests/test_security_api.py`):**
  - Yeni test `test_bulletin_cold_start_returns_503_without_triggering_cycle`: Önbellek boşken kimlik doğrulamasız `GET /api/v1/bulletin` çağrısının HTTP `503` ve beklenen Türkçe hata mesajını döndürdüğünü, `run_full_cycle` fonksiyonunu **hiç tetiklemediğini** (`assert_not_called()`) ve disk önbelleği oluşturmadığını doğrular.
  - `test_bulletin_auto_generation_cache_and_global_unique_ids`, `test_bulletin_returns_503_when_scrape_produces_zero_matches`, `test_cors_headers_on_bulletin_and_preflight`, `test_cli_export_bulletin_writes_four_league_schema_atomically` ve `test_bulletin_public_read_vs_protected_refresh` testleri yeni soğuk başlangıç güvenlik sözleşmesine göre güncellendi (toplam **62 birim/entegrasyon testi**).

---

## 3. Alt Ajan 2: Git Geçmişi Temizliği, QA ve GitHub Actions `ci.yml` Doğrulaması

### 3.1. Yerel Kopyaları Koruyarak Git Geçmişinden `GEMINI.md` ve `CLAUDE.md` Temizliği
- Yerel diskteki `GEMINI.md` ve `CLAUDE.md` dosyalarına **hiçbir şekilde dokunulmadı** (`.gitignore` içinde kalmaya devam ettiler).
- Temiz çalışma ağacı üzerinden `git checkout --orphan clean-main` ve `git add -A` çalıştırıldı; commit öncesinde sahnelenen indekste `GEMINI.md`, `CLAUDE.md`, `.env` ve `graphify-out/` dosyalarının bulunmadığı doğrulandı.
- Tek temiz kök commit (`88c686f42fca91bd94371448b9ba9de5c97a7eb3`) oluşturularak `git branch -M clean-main main`, `git push --force origin main` ve `git reflog expire --expire=now --all && git gc --prune=now` uygulandı.

### 3.2. Kanıt Çıktıları

| Kontrol Kalemi | Komut | Sonuç |
|---|---|---|
| Mypy Tip Kontrolü (40 dosya) | `mypy engine app.py` | `Success: no issues found in 40 source files` (0 hata) |
| Ruff Lint Kontrolü | `ruff check engine app.py` | `All checks passed!` (0 hata) |
| Python Birim Testleri | `python -m unittest discover -s engine/tests -v` | `Ran 62 tests in 23.615s — OK` (0 hata) |
| Git Geçmişi İz Kontrolü | `git log --all -- GEMINI.md CLAUDE.md` | Tamamen boş çıktı (`0` satır) |
| Git İndeks Kontrolü | `git ls-files GEMINI.md CLAUDE.md` | Tamamen boş çıktı |
| Yerel Disk Dosya Varlığı | `Test-Path GEMINI.md; Test-Path CLAUDE.md` | `True` / `True` |
| GitHub Actions `ci.yml` | `gh run view 46057248034` | `status: completed`, `conclusion: success` (`lint-and-test`, 44s) |

- **Kök Commit SHA:** `88c686f42fca91bd94371448b9ba9de5c97a7eb3`
- **GitHub Actions CI Run:** `https://github.com/naziffarm4/futbol-skor-analiz/actions/runs/46057248034` (`Ruff` ✅, `Mypy` ✅, `Unit Tests` ✅)

---

## 4. Kapanış: `/graphify --update` Özeti

- **Kapsam:** `7` değişen/yeni dosya (`app.py`, `engine/tests/test_foundation.py`, `engine/tests/test_runner.py`, `engine/tests/test_scrapers.py`, `engine/tests/test_security_api.py`, `tasks/GOREV-12-REPAIR.md`, `tasks/GOREV-12-REPAIR-RAPOR.md`).
- **Grafik Boyutu:** `1,445` düğüm · `3,056` kenar · `82` topluluk (`EXTRACTED: %91`, `INFERRED: %9`, `AMBIGUOUS: %0`).
- **Fark (`graph_diff`):** `+19` yeni düğüm, `+43` yeni kenar; yeni topluluk `#55` `"GÖREV-12-REPAIR Audit Remediation"` ve 2 yeni hiper-kenar (`gorev_12_repair_audit_remediation_pillars`, `bulletin_cold_start_security_boundary`) üretildi.
- **Sağlık Kontrolü:** Kayıp veya kopuk uç nokta kenarı `0` (`missing_endpoint_edges: 0`, `dangling_endpoint_edges: 0`; kod tabanındaki özyinelemeli yardımcılardan kaynaklı `2` adet `self_loop_edges`).
- **Çıktılar:** `graphify-out/graph.json`, `graphify-out/GRAPH_REPORT.md`, `graphify-out/graph.html`.

