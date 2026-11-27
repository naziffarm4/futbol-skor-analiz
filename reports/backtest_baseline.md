# GÖREV-12 Walk-Forward Backtest ve Kalibrasyon Referans Raporu

## 1. Metodoloji ve Sıfır Sızıntı (Zero-Leakage) Protokolü

- **Kapsam:** Sezonlar: `2425, 2526, 2627` | Ligler: T1 (Süper Lig), E0 (Premier League), SP1 (La Liga), F1 (Ligue 1).
- **Veri Hacmi:** Toplam **3217** tamamlanmış maç ayrıştırıldı; her lig-sezon grubunda ilk **30** maçlık ısınma (warm-up) penceresi sonrasında **2845** maç walk-forward olarak değerlendirildi (oran verisi bulunan alt küme: **2845** maç 1X2, **2845** maç Üst/Alt 2.5).
- **Sıfır Gelecek Sızıntısı Garantisi:** Maçlar `(lig, sezon)` bazında kesin kronolojik sıraya dizilir ve takvim gününe (`match_day`) göre gruplanır. `D` günündeki her maç yalnızca `kickoff_date < D` koşulunu sağlayan geçmiş maçlardan çıkan `LeagueBaseline` (`avg_home_goals`, `avg_away_goals`), takım hücum/savunma katsayıları (`build_team_ratings`), geçmiş isabetli şut (`HST`/`AST`) ve İY/MS gol payları kullanılarak tahmin edilir. `D` gününün sonuçları ancak o günün tüm tahminleri üretildikten sonra geçmiş havuzuna eklenir.
- **Değerlendirilen Modeller:**
  1. **Post-Fix (Yeni Ölçek, `max_goals=10`):** `λ = avg_home_goals * home_attack * away_defense`, `μ = avg_away_goals * away_attack * home_defense`, `0..10` Dixon-Coles matrisi (`ρ = -0.10`).
  2. **Pre-Fix (Eski Ölçek, `max_goals=5`):** Eski formül `λ = home_attack * away_defense * home_advantage`, `μ = away_attack * home_defense` (lig gol ortalaması çarpanı eksik, `0..5` matris).
  3. **Lig Ortalaması Sabit Baz:** Yalnızca `D` gününden önceki lig `avg_home_goals` ve `avg_away_goals` değerleriyle (`attack=1.0, defense=1.0`) çalışan sabit referans model.
  4. **Piyasa (De-vigged Kapanış Oranları):** `PSCH/PSCD/PSCA` (Pinnacle kapanış) öncelikli, yoksa `B365CH` / `AvgCH` kapanış ve açılış yedekli bahisçi oranlarından marjın oransal (`p_i = (1/odd_i) / Σ(1/odd_j)`) temizlenmesiyle elde edilen referans.
- **Metrik Formülleri:**
  - **RPS (Ranked Probability Score — Birincil Metrik):** `0.5 * ((p_H - o_H)^2 + ((p_H + p_D) - (o_H + o_D))^2)` (düşük daha iyi).
  - **Çok Sınıflı Brier Skoru:** `(p_H - o_H)^2 + (p_D - o_D)^2 + (p_A - o_A)^2` (düşük daha iyi).
  - **Log-Loss (Çapraz Entropi):** `-ln(max(1e-15, p_gerçek))` (düşük daha iyi).

## 2. Dört Lig Toplu Karşılaştırma Tablosu (Pre-Fix vs Post-Fix vs Baz vs Piyasa)

| Model / Referans | Maç | RPS (↓) | Brier 1X2 (↓) | Log-Loss 1X2 (↓) | 1X2 İsabet (↑) | Tahmin λ+μ | Gerçek Gol | Tahmin Üst 2.5 | Gerçek Üst 2.5 | Üst 2.5 Sapma | Üst 2.5 Brier (↓) | Üst 2.5 Log-Loss (↓) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Post-Fix (Yeni Ölçek, max=10) | 2845 | 0.2039 | 0.5915 | 0.9919 | %52.44 | 2.772 | 2.816 | %51.58 | %53.81 | -2.23 puan | 0.2480 | 0.6896 |
| Pre-Fix (Eski Ölçek, max=5) | 2845 | 0.2052 | 0.5970 | 0.9998 | %51.49 | 2.245 | 2.816 | %38.37 | %53.81 | -15.44 puan | 0.2710 | 0.7400 |
| Lig Ortalaması Sabit Baz | 2845 | 0.2306 | 0.6471 | 1.0702 | %44.64 | 2.784 | 2.816 | %52.58 | %53.81 | -1.23 puan | 0.2496 | 0.6923 |
| Piyasa (De-vigged Kapanış) | 2845 | 0.1947 | 0.5715 | 0.9626 | %55.11 | - | 2.816 | %53.59 | %53.81 | -0.23 puan | 0.2365 | 0.6654 |

### Düzeltme Öncesi -> Sonrası Doğrudan Etki Özeti

- **Toplam Beklenen Gol Ölçeği (`λ + μ`):** Pre-Fix modelde maç başı ortalama `2.245` gol tahmin edilirken gerçekleşen ortalama `2.816` goldü (**%-20.29** sistematik eksik tahmin). Post-Fix modelde ortalama beklenen gol `2.772` seviyesine gelerek gerçekleşen ortalamaya **%-1.58** bağıl farkla oturdu.
- **Üst 2.5 Gol Kalibrasyonu:** Pre-Fix modelde ortalama Üst 2.5 tahmini `%38.37` iken gerçekleşen oran `%53.81` (sapma: `-15.44 puan`). Post-Fix modelde ortalama Üst 2.5 tahmini `%51.58` (sapma: `-2.23 puan`), Üst 2.5 Brier skoru `-0.0230` ve Üst 2.5 Log-Loss `-0.0504` değişti.
- **1X2 Sıralı Olasılık Kalitesi:** Post-Fix model Pre-Fix modele göre RPS'de `-0.0012`, 1X2 Brier skorunda `-0.0055` ve 1X2 Log-Loss'ta `-0.0079` fark üretti; ayrıca sabit lig ortalaması baz modelini RPS'de `-0.0266` geride bıraktı.

## 3. Türkiye Süper Lig (`T1`) Özel Bölümü

| Model / Referans | Maç | RPS (↓) | Brier 1X2 (↓) | Log-Loss 1X2 (↓) | 1X2 İsabet (↑) | Tahmin λ+μ | Gerçek Gol | Tahmin Üst 2.5 | Gerçek Üst 2.5 | Üst 2.5 Sapma | Üst 2.5 Brier (↓) | Üst 2.5 Log-Loss (↓) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Post-Fix (Yeni Ölçek, max=10) | 663 | 0.1958 | 0.5746 | 0.9689 | %55.66 | 2.731 | 2.849 | %50.59 | %55.35 | -4.76 puan | 0.2485 | 0.6909 |
| Pre-Fix (Eski Ölçek, max=5) | 663 | 0.1979 | 0.5824 | 0.9787 | %53.24 | 2.174 | 2.849 | %36.59 | %55.35 | -18.77 puan | 0.2794 | 0.7592 |
| Lig Ortalaması Sabit Baz | 663 | 0.2291 | 0.6434 | 1.0652 | %44.95 | 2.745 | 2.849 | %51.65 | %55.35 | -3.70 puan | 0.2486 | 0.6904 |
| Piyasa (De-vigged Kapanış) | 663 | 0.1842 | 0.5515 | 0.9335 | %59.43 | - | 2.849 | %54.59 | %55.35 | -0.76 puan | 0.2324 | 0.6565 |

- **Süper Lig Bulguları:** Değerlendirilen **663** Süper Lig maçında gerçekleşen gol ortalaması `2.849` ve gerçekleşen Üst 2.5 oranı `%55.35` oldu. Pre-Fix model Süper Lig'de maç başı yalnızca `2.174` gol ve `%36.59` Üst 2.5 öngörerek `-18.77 puan` sistematik sapma üretirken, Post-Fix model `2.731` beklenen gol ve `%50.59` Üst 2.5 tahminiyle sapmayı `-4.76 puan` düzeyine indirdi (RPS: `0.1979` -> `0.1958`, kapanış piyasası RPS: `0.1842`).

## 4. Diğer Hedef Liglerin Ayrıntılı Kırılımı (`E0`, `SP1`, `F1`)

### Premier League (`E0`)

| Model / Referans | Maç | RPS (↓) | Brier 1X2 (↓) | Log-Loss 1X2 (↓) | 1X2 İsabet (↑) | Tahmin λ+μ | Gerçek Gol | Tahmin Üst 2.5 | Gerçek Üst 2.5 | Üst 2.5 Sapma | Üst 2.5 Brier (↓) | Üst 2.5 Log-Loss (↓) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Post-Fix (Yeni Ölçek, max=10) | 780 | 0.2092 | 0.6113 | 1.0182 | %49.61 | 2.825 | 2.842 | %52.98 | %55.51 | -2.53 puan | 0.2551 | 0.7046 |
| Pre-Fix (Eski Ölçek, max=5) | 780 | 0.2100 | 0.6155 | 1.0243 | %49.23 | 2.177 | 2.842 | %36.74 | %55.51 | -18.77 puan | 0.2871 | 0.7745 |
| Lig Ortalaması Sabit Baz | 780 | 0.2314 | 0.6560 | 1.0825 | %41.15 | 2.835 | 2.842 | %53.83 | %55.51 | -1.68 puan | 0.2490 | 0.6913 |
| Piyasa (De-vigged Kapanış) | 780 | 0.2032 | 0.5990 | 0.9998 | %51.54 | - | 2.842 | %56.39 | %55.51 | +0.87 puan | 0.2431 | 0.6791 |

### La Liga (`SP1`)

| Model / Referans | Maç | RPS (↓) | Brier 1X2 (↓) | Log-Loss 1X2 (↓) | 1X2 İsabet (↑) | Tahmin λ+μ | Gerçek Gol | Tahmin Üst 2.5 | Gerçek Üst 2.5 | Üst 2.5 Sapma | Üst 2.5 Brier (↓) | Üst 2.5 Log-Loss (↓) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Post-Fix (Yeni Ölçek, max=10) | 794 | 0.2013 | 0.5833 | 0.9815 | %52.27 | 2.644 | 2.700 | %48.43 | %50.25 | -1.82 puan | 0.2403 | 0.6735 |
| Pre-Fix (Eski Ölçek, max=5) | 794 | 0.2021 | 0.5867 | 0.9865 | %50.88 | 2.327 | 2.700 | %40.33 | %50.25 | -9.92 puan | 0.2490 | 0.6931 |
| Lig Ortalaması Sabit Baz | 794 | 0.2283 | 0.6428 | 1.0647 | %46.47 | 2.659 | 2.700 | %49.56 | %50.25 | -0.69 puan | 0.2506 | 0.6945 |
| Piyasa (De-vigged Kapanış) | 794 | 0.1906 | 0.5590 | 0.9470 | %55.42 | - | 2.700 | %48.97 | %50.25 | -1.28 puan | 0.2341 | 0.6601 |

### Ligue 1 (`F1`)

| Model / Referans | Maç | RPS (↓) | Brier 1X2 (↓) | Log-Loss 1X2 (↓) | 1X2 İsabet (↑) | Tahmin λ+μ | Gerçek Gol | Tahmin Üst 2.5 | Gerçek Üst 2.5 | Üst 2.5 Sapma | Üst 2.5 Brier (↓) | Üst 2.5 Log-Loss (↓) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Post-Fix (Yeni Ölçek, max=10) | 608 | 0.2096 | 0.5951 | 0.9972 | %52.80 | 2.915 | 2.898 | %54.99 | %54.61 | +0.38 puan | 0.2482 | 0.6899 |
| Pre-Fix (Eski Ölçek, max=5) | 608 | 0.2109 | 0.6026 | 1.0087 | %53.29 | 2.301 | 2.898 | %39.84 | %54.61 | -14.76 puan | 0.2699 | 0.7360 |
| Lig Ortalaması Sabit Baz | 608 | 0.2341 | 0.6454 | 1.0670 | %46.38 | 2.925 | 2.898 | %55.94 | %54.61 | +1.34 puan | 0.2499 | 0.6931 |
| Piyasa (De-vigged Kapanış) | 608 | 0.2004 | 0.5744 | 0.9669 | %54.61 | - | 2.898 | %54.93 | %54.61 | +0.32 puan | 0.2359 | 0.6646 |

## 5. Güvenirlik Dilimleri (Calibration Buckets)

### 5.1. 1X2 Olasılık Dilimleri (3 Sonuç x Maç Sayısı)

| Olasılık Dilimi | Post-Fix Adet | Post-Fix Tahmin | Post-Fix Gerçekleşen | Post-Fix Mutlak Hata | Pre-Fix Adet | Pre-Fix Tahmin | Pre-Fix Gerçekleşen | Pre-Fix Mutlak Hata | Piyasa Mutlak Hata |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `[0.0, 0.2)` | 1269 | %14.62 | %14.26 | %0.35 | 1093 | %14.84 | %14.18 | %0.66 | %2.10 |
| `[0.2, 0.4)` | 4969 | %28.56 | %28.07 | %0.48 | 5433 | %30.21 | %28.53 | %1.68 | %0.38 |
| `[0.4, 0.6)` | 1690 | %48.70 | %49.53 | %0.83 | 1621 | %48.14 | %52.56 | %4.42 | %1.61 |
| `[0.6, 0.8)` | 558 | %67.45 | %69.89 | %2.45 | 376 | %66.75 | %73.94 | %7.19 | %3.06 |
| `[0.8, 1.0]` | 49 | %83.89 | %85.71 | %1.83 | 12 | %84.48 | %83.33 | %1.15 | %4.65 |

### 5.2. Üst 2.5 Olasılık Dilimleri

| Olasılık Dilimi | Post-Fix Adet | Post-Fix Tahmin | Post-Fix Gerçekleşen | Post-Fix Mutlak Hata | Pre-Fix Adet | Pre-Fix Tahmin | Pre-Fix Gerçekleşen | Pre-Fix Mutlak Hata | Piyasa Mutlak Hata |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `[0.0, 0.2)` | 6 | %17.51 | %33.33 | %15.82 | 60 | %17.57 | %51.67 | %34.10 | - |
| `[0.2, 0.4)` | 460 | %34.22 | %43.70 | %9.48 | 1612 | %32.09 | %49.75 | %17.66 | %1.03 |
| `[0.4, 0.6)` | 1733 | %50.67 | %53.78 | %3.11 | 1109 | %47.09 | %58.70 | %11.62 | %0.61 |
| `[0.6, 0.8)` | 628 | %66.28 | %60.51 | %5.77 | 64 | %65.14 | %73.44 | %8.30 | %1.96 |
| `[0.8, 1.0]` | 18 | %81.78 | %88.89 | %7.11 | 0 | - | - | - | %17.39 |

## 6. Teknik Yorum, Kalan Farklar ve Faz 2 Yol Haritası

1. **Ölçek Hatasının Giderilmesi Doğrulandı:** Pre-Fix modelde `ratings.py` içinde lig ortalamasına bölünerek boyutsuz `~1.0` etrafında normalize edilen katsayıların `poisson.py` tarafında `avg_home_goals` ve `avg_away_goals` ile çarpılmaması, toplam gol beklentisinde yaklaşık `-%15` ila `-%20` ve Üst 2.5 olasılıklarında `~15 puan` sistematik eksik tahmine yol açıyordu. Post-Fix model bu yapısal hatayı ortadan kaldırarak hem toplam gol ölçeğini hem de Üst 2.5 Brier ve Log-Loss metriklerini belirgin biçimde iyileştirdi.
2. **1X2 Sıralaması vs Gol Hacmi Ayrımı:** Pre-Fix modelde ev sahibi gol beklentisi `home_advantage (~1.26)` ile çarpılıp deplasman golü `1.0` ölçeğinde bırakıldığı için `λ / μ` oranı kısmen korunuyor, ancak `λ + μ` toplamı bastırılıyordu. Post-Fix düzeltmesi 1X2 RPS/Brier/Log-Loss/İsabet metriklerinin tamamını iyileştirirken beraberlik/gollü maç dengesini gerçek Poisson ölçeğine taşıdı ve `max_goals=10` ile yüksek skorlu karşılaşmalardaki kuyruk kırpılmasını sonlandırdı.
3. **Piyasa Kapanış Oranlarıyla Kalan Mesafe:** Kapanış oranları alt kümesinde Post-Fix RPS `0.2039` iken marjı temizlenmiş kapanış piyasası RPS `0.1947` seviyesindedir (`+0.0093` fark). Tarihsel CSV walk-forward koşusunda anlık maç günü sakatlık/kadrolar, teknik direktör değişimleri, fikstür sıkışıklığı (Avrupa kupası yorgunluğu) ve zaman-ağırlıklı üstel form çürümesi (exponential time-decay) henüz yer almadığından piyasanın birkaç binde puan önde olması beklenen ve sağlıklı bir referans sonucudur.
4. **Faz 2 Öncelikleri:** (a) Oynanmış maçlarda üstel zaman sönümlemesi (`exp(-ξ * Δgün)`) ve sezonlar arası Elo/önsel taşınım (carry-over prior) eklenmesi, (b) `ρ` ve çekme ağırlığının (`prior_weight`) walk-forward RPS üzerinde optimize edilmesi, (c) maç başı gerçek Understat xG serilerinin tarihsel backtest katmanına bağlanması.
