# GÖREV-13-REPAIR: CI Yedek Fikstür Kaynağında Ligue 1 Hafta Gruplama Düzeltmesi — Kapanış Raporu

**Tarih:** 2026-11-28  
**Onarım Commit:** `7cd25d5` (`fix(gorev-13-repair): group upcoming weekend fixtures into single next_round across fallback sources`)  
**CI İş Akışı (`ci.yml`):** Run `46077230903` — `success`  
**Canlı Bülten Yayını (`update_bulletin.yml`):** Run `46077232678` — `success` (43 sn)  
**Canlı Yayın URL:** `https://naziffarm4.github.io/futbol-skor-analiz/bulletin.json` (`generated_at: 2026-11-27T22:32:49.874093+00:00`)

---

## 1. Kök Neden Tespiti (3 Katmanlı Zincirleme Kök Neden)

GitHub Actions veri merkezi IP'sinde Transfermarkt `HTTP 202` (AWS WAF challenge) ve API-Football ücretsiz plan sezon kısıtı döndüğünde `IngestionPipeline._synthesize_fallback_fixtures()` devreye girmektedir. Yapılan canlı ve statik analizde Ligue 1'in yalnızca `1` maç üretmesine yol açan **üç birleşik kök neden** kesin olarak tespit edilmiştir:

1. **Katman 1 — The Odds API Ligue 1 Spor Anahtarı Hatası (`engine/config.py:115`):**
   - `THE_ODDS_API_SPORT_KEYS[LeagueId.LIGUE_1]` değeri `"soccer_france_ligue_1"` olarak tanımlıydı; oysa The Odds API v4 `/v4/sports` uç noktasındaki resmi aktif anahtar **`"soccer_france_ligue_one"`**'dır.
   - Bu nedenle `super_lig` (`8` maç), `premier_league` (`19–20` maç) ve `la_liga` (`21–22` maç) yaklaşan fikstürleri `TheOddsAPI` üzerinden kurtarılırken, `ligue_1` **`HTTP 404: Unknown sport`** hatası alarak yalnızca ESPN yedeğine kalmaktaydı.

2. **Katman 2 — ESPN Tek Günlük Varsayılan Scoreboard Kısa-Devresi + Tireli Tarih Aralığında `HTTP 400` (`engine/scrapers/sources/espn.py` & `engine/scrapers/pipeline.py`):**
   - `ESPNAdapter.fetch_league()` parametresiz `/scoreboard` uç noktasını çağırmaktadır; bu uç nokta yalnızca aktif günün maçlarını (Cuma günü sadece Cuma açılış maçı olan `Brest vs Paris FC` — **1 maç**) döndürmektedir.
   - `pipeline.py` içindeki eski `has_espn_sched = any(fx.status != "FINISHED" for fx in espn_data.fixtures)` kontrolü, Cuma günkü bu tek maçı görünce `True` dönerek `_fetch_espn_upcoming_window()` çağrısını **tamamen atlamaktaydı**; Cumartesi (5 maç) ve Pazar (3 maç) fikstürleri hiç çekilmiyordu.
   - Üstelik `_fetch_espn_upcoming_window()` çağrılsa dahi gönderdiği `?dates=YYYYMMDD-YYYYMMDD` (tireli tarih aralığı) parametresi ESPN Soccer `/scoreboard` API'si tarafından **`HTTP 400 Bad Request`** ile reddedilmekteydi (ESPN yalnızca tekil `?dates=YYYYMMDD` sorgusunu kabul etmektedir).

3. **Katman 3 — Yaklaşan Maçların `<= 4 Gün` Hafta Kümesi ve Takım Kadrosu Tekilleştirmesi (`engine/scrapers/pipeline.py` & `engine/scrapers/fixtures.py`):**
   - Yalnızca `team_sched_counts` sayacına dayalı eski hafta ataması, Cuma akşamı maçını tamamlamış iki takımın bir sonraki hafta sonu (6–7 gün sonraki) maçını mevcut haftaya sızdırabilme riski taşıyordu.
   - Ayrıca `TeamAliasResolver` üzerinde puan durumu kadrosu (`standings`) tam yüklenmeden `resolve_key()` çalıştırıldığında `"Le Havre AC"` ve `"Le Mans FC"` gibi ortak kelimeli (`"le"`) kulüpler çakışarak aynı günde sahte takım tekrarı üretip haftayı bölebiliyordu; `Amed SFK` / `Amed SK`, `Deportivo` / `Deportivo La Coruña` ve `Racing Santander` / `Real Racing Club de Santander` yazımları da çapraz kaynakta çift kayda açık durumdaydı.

---

## 2. Uygulanan Düzeltmeler

| Dosya | Yapılan Değişiklik |
|---|---|
| `engine/config.py`, `docs/veri-kaynaklari.md` | `THE_ODDS_API_SPORT_KEYS[LeagueId.LIGUE_1]` değeri `"soccer_france_ligue_one"` olarak düzeltildi (`HTTP 404` giderildi, 17 yaklaşan Ligue 1 maçı ve konsensüs piyasa oranları aktifleşti). |
| `engine/scrapers/sources/espn.py` | `ESPNLeagueData.calendar_dates` alanı ve `parse_espn_calendar_dates()` eklendi; ilk `/scoreboard` yanıtındaki `leagues[0]["calendar"]` içinden sezonun gerçek maç günleri (`YYYY-MM-DD`) ayrıştırıldı. |
| `engine/scrapers/pipeline.py` | 1) `_fetch_espn_upcoming_window()` tireli aralık yerine `calendar_dates` içindeki gerçek maç günlerini tekil `?dates=YYYYMMDD` ile sorgulayacak şekilde güncellendi ve ESPN'deki planlanmış maç sayısı tam hafta eşiğinin altındaysa (`< expected_per_round`) Cuma günü 1 maç olsa bile çalışması sağlandı.<br>2) `group_upcoming_into_rounds()` eklendi: yaklaşan `SCHEDULED` maçlar `<= 4` günlük hafta kümesi (`max_cluster_span_days=4`, `max_day_gap_days=3`), küme içi takım ayrıklığı ve son 2 günde o haftanın açılış maçını tamamlamış takımlar (`recent_fin_teams`) dikkate alınarak tek `next_round` altında toplandı.<br>3) Resmi lig kadrosu (`_register_roster_team`) ile ikincil kaynak takma ad eşleştirmesi (`_register_name`) ayrıştırıldı; bitmiş maçların (`seen_finished`) önbellekten tekrar `SCHEDULED` olarak eklenmesi engellendi. |
| `engine/scrapers/fusion.py` | `amed sfk`, `deportivo la coruna`, `real racing club de santander`, `le mans fc` ve `es troyes ac` varyantları `_ALIAS_GROUPS` sözlüğüne eklendi. |
| `engine/scrapers/fixtures.py`, `engine/predictors/service.py`, `engine/predictors/__init__.py` | `select_next_round()` ortak fonksiyon olarak `engine/scrapers/fixtures.py` içine taşındı (ertelenmiş kısmi geçmiş hafta kalıntısı korumasıyla güçlendirildi), `LeagueFixturesData.next_round` ve `engine.predictors` bu tek ortak fonksiyona bağlandı. |
| `engine/tests/test_official_apis_and_archive.py` | `test_ligue1_friday_plus_eight_weekend_matches_grouped_into_single_next_round` deterministik regresyon birim testi eklendi (Transfermarkt HTTP 202 + API-Football kısıtlı + ESPN varsayılan scoreboard'da 1 Cuma maçı + `dates=YYYYMMDD-YYYYMMDD` için HTTP 400 + Cumartesi 5 / Pazar 3 maç + ertesi hafta 3 maç senaryosunda `next_round=12` altında tam **9 maç** gruplandığını ve 9'lu İY/MS toplamlarının `1.0000` olduğunu doğrular). |

---

## 3. Yerel Doğrulama Sonuçları

- `python -m mypy engine app.py` -> **`Success: no issues found in 45 source files`** (0 hata)
- `python -m ruff check engine app.py` -> **`All checks passed!`** (0 hata)
- `python -m unittest discover -s engine/tests -v` -> **`Ran 78 tests in 19.833s — OK`** (0 hata)

---

## 4. Canlı Yayın (`bulletin.json`) Kanıt Tablosu

`update_bulletin.yml` (Run `46077232678`) tamamlandıktan sonra canlı `https://naziffarm4.github.io/futbol-skor-analiz/bulletin.json` (`generated_at: 2026-11-27T22:32:49.874093+00:00`) üzerinden doğrulanan değerler:

*(Not: Yayın `2026-11-27 22:32 UTC` itibarıyla üretildiğinden Cuma akşamı oynanıp tamamlanan açılış maçları — Ligue 1'de `Brest vs Paris FC`, Premier League'de `Nottingham Forest vs Chelsea`, La Liga'da `Levante vs Racing Santander`, Süper Lig'de `Alanyaspor vs Konyaspor` ve `Çaykur Rizespor vs Kasımpaşa` — `FINISHED` olarak `played_matches_count` toplamına geçmiş, hafta sonunun kalan tüm `SCHEDULED` maçları eksiksiz olarak tek `next_round` bülteninde toplanmıştır.)*

| Lig (`id`) | `next_round` | Oynanmış Maç (`played`) | Bültendeki Planlanmış Maç (`matches_count`) | Aktif Kaynaklar (`sources_used`) | 9'lu İY/MS Toplam (`min` / `max`) | Maks. İY/MS Sapması | Maks. 1X2 Sapması |
|---|---:|---:|---:|---|---:|---:|---:|
| `super_lig` | 14 | 110 | **7** (28–30 Kas tam kalan hafta) | `TheOddsAPI, ESPN, Football-Data, Understat, SportsGambler` | `1.000000` / `1.000000` | `0.00000000` | `0.00000000` |
| `premier_league` | 13 | 111 | **9** (28–29 Kas tam kalan hafta) | `TheOddsAPI, ESPN, Football-Data, Understat, SportsGambler` | `1.000000` / `1.000000` | `0.00000000` | `0.00000000` |
| `la_liga` | 15 | 130 | **9** (28–30 Kas tam kalan hafta) | `TheOddsAPI, ESPN, Football-Data, Understat, SportsGambler` | `1.000000` / `1.000000` | `0.00000000` | `0.00000000` |
| `ligue_1` | 13 | 100 | **8** (28–29 Kas tam kalan hafta) | `TheOddsAPI, ESPN, Football-Data, Understat, SportsGambler` | `1.000000` / `1.000000` | `0.00000000` | `0.00000000` |

### Canlı `ligue_1` Hafta Sonu Maç Listesi (`matches_count = 8`)
1. `2026-11-28T16:15:00+00:00` — `Angers vs Lens` (`ht_ft: 2/2`, 9'lu İY/MS toplam = `1.0000`)
2. `2026-11-28T19:45:00+00:00` — `Paris Saint-Germain vs Lorient` (`ht_ft: 1/1`, 9'lu İY/MS toplam = `1.0000`)
3. `2026-11-28T19:45:00+00:00` — `Nice vs Troyes` (`ht_ft: 1/1`, 9'lu İY/MS toplam = `1.0000`)
4. `2026-11-28T19:45:00+00:00` — `Le Mans vs Lille` (`ht_ft: 2/2`, 9'lu İY/MS toplam = `1.0000`)
5. `2026-11-28T19:45:00+00:00` — `Le Havre AC vs Strasbourg` (`ht_ft: 1/1`, 9'lu İY/MS toplam = `1.0000`)
6. `2026-11-29T14:00:00+00:00` — `AJ Auxerre vs Marseille` (`ht_ft: 2/2`, 9'lu İY/MS toplam = `1.0000`)
7. `2026-11-29T16:15:00+00:00` — `Toulouse vs Stade Rennais` (`ht_ft: 1/1`, 9'lu İY/MS toplam = `1.0000`)
8. `2026-11-29T19:45:00+00:00` — `Lyon vs AS Monaco` (`ht_ft: X/X`, 9'lu İY/MS toplam = `1.0000`)
