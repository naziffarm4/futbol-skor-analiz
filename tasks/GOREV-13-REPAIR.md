# GÖREV-13-REPAIR: CI Yedek Fikstür Kaynağında Ligue 1 (1 Maç) Hafta Gruplama Düzeltmesi

## 1. Sorun (Bağımsız Denetim Bulgusu)
Canlı `https://naziffarm4.github.io/futbol-skor-analiz/bulletin.json` üzerinde yapılan bağımsız denetimde:
- `super_lig`: 7 maç, `premier_league`: 10 maç, `la_liga`: 10 maç,
- **`ligue_1`: yalnızca `1` maç** döndüğü tespit edildi.

Kök neden: GitHub Actions veri merkezi IP'sinde Transfermarkt HTTP 202 döndüğünde devreye giren yedek fikstür kaynağı (ESPN / OpenFootball / The Odds API) aynı hafta sonunun Cuma maçını (1 maç) Cumartesi–Pazar maçlarından ayrı bir `round` bloğuna atadığı veya tarih penceresini eksik birleştirdiği için `select_next_round()` yalnızca 1 maçlık bloğu seçmektedir.

---

## 2. Teknik Şartname
1. **Kök Neden Tespiti & Düzeltme (`engine/scrapers/pipeline.py`, `engine/scrapers/sources/espn.py`, `engine/scrapers/fixtures.py`):**
   - Yedek fikstür akışında (ESPN 21 günlük pencere + OpenFootball + The Odds API yaklaşan maçlar) aynı hafta sonu/hafta kümesine (birbirine <= 4 gün mesafedeki ardışık fikstür kümesi) ait tüm `SCHEDULED` maçların tek bir sıradaki hafta (`next_round`) altında doğru gruplanmasını sağla.
   - `ligue_1`, `super_lig`, `premier_league` ve `la_liga` için yaklaşan hafta sonundaki tüm planlanmış maçların (kısmi 1-2 maçlık parçalanma olmadan) eksiksiz bültene girdiğini garanti et.
2. **Regresyon Birim Testi:**
   - Yedek fikstür kaynağından 1 Cuma maçı + 8 Cumartesi/Pazar maçı geldiğinde hepsinin sıradaki tek hafta bülteninde toplandığını kanıtlayan deterministik birim testi ekle.
3. **Doğrulama & Canlı Yayın:**
   - `python -m mypy engine app.py` (0 hata), `python -m ruff check engine app.py` (0 hata), `python -m unittest discover -s engine/tests -v` (0 hata).
   - Değişikliği `naziffarm4/futbol-skor-analiz` reposuna push et, `gh workflow run update_bulletin.yml` çalıştır ve canlı `https://naziffarm4.github.io/futbol-skor-analiz/bulletin.json` üzerinde 4 ligin tamamının maç sayılarını (`ligue_1` dahil tam hafta) ve 0 matematik sapmasını doğrula.
   - `/graphify --update` ve kanıtları `tasks/GOREV-13-REPAIR-RAPOR.md` dosyasına kaydet.
