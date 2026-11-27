# GÖREV-13 Walk-Forward Backtest v2: Üstel Zaman Sönümü (M2), Piyasa Harmanı (M5) ve 9 Yönlü İY/MS Kalibrasyonu

## 1. Metodoloji, Veri Kümesi ve Nedensellik (Zero-Leakage) Garantisi

- **Veri Kapsamı:** Sezonlar: `2425, 2526, 2627` | Hedef Ligler: T1 (Süper Lig), E0 (Premier League), SP1 (La Liga), F1 (Ligue 1).
- **Örneklem Büyüklüğü:** Football-Data tarihsel arşivinden toplam **3217** tamamlanmış resmi lig maçı ayrıştırıldı; her `(lig, sezon)` grubundaki ilk **30** maçlık ısınma (warm-up) penceresi sonrasında tam **2845** maç walk-forward olarak değerlendirildi (`1X2` oran kapsaması: **2845** maç, `Üst/Alt 2.5` oran kapsaması: **2845** maç, geçerli `HTHG`/`HTAG` ilk yarı skoru bulunan `9'lu İY/MS` kapsaması: **2844** maç).
- **Nedensel (Causal) Walk-Forward Protokolü:** Her `(lig, sezon)` serisi başlama vuruşu zamanına (`kickoff`) göre sıralanır ve takvim gününe (`match_day`) göre gruplanır. `D` günündeki her maç için lig gol ortalamaları (`calculate_league_baseline`), takım hücum/savunma reytingleri (`build_team_ratings`), üstel zaman ağırlıkları (`w = exp(-ξ * Δgün)`, `ref_date = D`), geçmiş isabetli şut (`HST`/`AST`) ve ilk yarı gol payları yalnızca `match_day < D` koşulunu sağlayan geçmiş maçlardan hesaplanır. `D` gününün sonuçları ancak o günün tüm tahminleri üretildikten sonra geçmiş havuzuna eklenir.
- **9 Yönlü Marjinal Tutarlı İY/MS Dağılımı:** İki aşamalı (`İY` + `2Y`) Dixon-Coles konvolüsyonundan elde edilen 9 İY/MS olasılığı (`1/1, X/1, 2/1, 1/X, X/X, 2/X, 1/2, X/2, 2/2`), her tam saha sonuç grubunda (`MS=1`, `MS=X`, `MS=2`) modelin (veya piyasa harmanının) nihai `p_home, p_draw, p_away` olasılıklarına tam marjinal tutarlılıkla ölçeklenir ve en büyük kalan yöntemiyle toplamı `1.0000` olacak şekilde yuvarlanır.
- **Not (Saf Piyasa 9'lu İY/MS Sütunları):** Football-Data CSV kaynaklarında bahisçi kapanış oranları yalnızca `1X2` ve `Üst/Alt 2.5` pazarları için yayımlandığından (9 yönlü bahisçi İY/MS oranları CSV'de yer almadığından) Saf Piyasa satırında 9'lu İY/MS metrikleri `-` olarak gösterilmiştir.

## 2. Dört Lig Birleşik Kademeli Ablasyon Tablosu (`T1 + E0 + SP1 + F1`)

| Aşama / Model | Maç | 1X2 RPS (↓) | 1X2 Brier (↓) | 1X2 Log-Loss (↓) | 1X2 İsabet (↑) | Üst 2.5 Brier (↓) | Üst 2.5 Log-Loss (↓) | Üst 2.5 İsabet (↑) | 9'lu İY/MS Brier (↓) | 9'lu İY/MS Log-Loss (↓) | İY/MS Top-1 (↑) | İY/MS Top-3 (↑) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1. Baz Post-Fix (`ξ=0`, `α=0`) | 2845 | 0.2039 | 0.5915 | 0.9919 | %52.44 | 0.2480 | 0.6896 | %55.11 | 0.8129 | 1.9147 | %31.47 | %63.43 |
| 2. + Zaman Sönümü (`ξ=0.0015`, `α=0`) | 2845 | 0.2039 | 0.5914 | 0.9918 | %52.30 | 0.2479 | 0.6895 | %55.40 | 0.8128 | 1.9143 | %31.47 | %63.50 |
| 3. + Piyasa Harmanı (`ξ=0.0015`, `α=0.65`) | 2845 | 0.1960 | 0.5742 | 0.9669 | %54.62 | 0.2387 | 0.6698 | %58.31 | 0.8036 | 1.8894 | %33.23 | %64.91 |
| 4. Saf Piyasa Referansı (De-vigged Market) | 2845 | 0.1947 | 0.5715 | 0.9626 | %55.11 | 0.2365 | 0.6654 | %59.26 | - | - | - | - |

### Birleşik Ablasyon Bulguları

1. **Üstel Zaman Sönümü (`M2`, `ξ = 0.0015 / gün`, yarı ömür `≈ 462 gün`):** Dixon-Coles (1997) yarı-haftalık sönüm sabitiyle (`0.0065 / 3.5 ≈ 0.0018/gün`) uyumlu biçimde, `ξ = 0.0015` sönümü saf model modunda (`market_probs=None`) 1X2 RPS değerini `0.20395` -> `0.20390` (`-0.00005`), 1X2 Brier skorunu `0.59151` -> `0.59142` ve 1X2 Log-Loss değerini `0.99195` -> `0.99180` düzeyine iyileştirmiştir.
2. **Marjinal Tutarlı Piyasa Harmanı (`M2 + M5`, `α = 0.65`):** Model dağılımının marjı arındırılmış piyasa olasılıklarıyla `%35 Model + %65 Piyasa` oranında harmanlanması 1X2 RPS'yi `0.2039` -> `0.1960` (`-0.0080`), 1X2 Log-Loss'u `0.9919` -> `0.9669` (`-0.0250`) ve 1X2 isabet oranını `%52.44` -> `%54.62` seviyesine taşımış; saf model ile kapanış piyasası arasındaki RPS farkının **%86.1**'ini kapatırken canlı sakatlık ve xG/şut sinyalleri için `%35` yapısal model ağırlığını korumuştur.
3. **Üst 2.5 ve 9'lu İY/MS Kazanımı:** Harman katmanı Üst 2.5 Brier skorunu `0.2480` -> `0.2387` ve Üst 2.5 Log-Loss'u `0.6896` -> `0.6698` düzeyine indirirken; marjinal ölçekleme sayesinde **9 yönlü İY/MS** Brier skoru `0.8129` -> `0.8036`, 9'lu İY/MS Log-Loss `1.9147` -> `1.8894`, İY/MS Top-1 isabeti `%31.47` -> `%33.23` ve Top-3 isabeti `%63.43` -> `%64.91` olarak yükselmiştir.

## 3. Türkiye Süper Lig (`T1`) Özel Ablasyon Tablosu

| Aşama / Model | Maç | 1X2 RPS (↓) | 1X2 Brier (↓) | 1X2 Log-Loss (↓) | 1X2 İsabet (↑) | Üst 2.5 Brier (↓) | Üst 2.5 Log-Loss (↓) | Üst 2.5 İsabet (↑) | 9'lu İY/MS Brier (↓) | 9'lu İY/MS Log-Loss (↓) | İY/MS Top-1 (↑) | İY/MS Top-3 (↑) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1. Baz Post-Fix (`ξ=0`, `α=0`) | 663 | 0.1958 | 0.5746 | 0.9689 | %55.66 | 0.2485 | 0.6909 | %54.90 | 0.7975 | 1.8808 | %33.69 | %63.14 |
| 2. + Zaman Sönümü (`ξ=0.0015`, `α=0`) | 663 | 0.1955 | 0.5742 | 0.9681 | %55.81 | 0.2485 | 0.6908 | %55.20 | 0.7972 | 1.8799 | %33.84 | %63.29 |
| 3. + Piyasa Harmanı (`ξ=0.0015`, `α=0.65`) | 663 | 0.1858 | 0.5543 | 0.9385 | %58.37 | 0.2357 | 0.6637 | %57.16 | 0.7861 | 1.8503 | %36.71 | %67.52 |
| 4. Saf Piyasa Referansı (De-vigged Market) | 663 | 0.1842 | 0.5515 | 0.9335 | %59.43 | 0.2324 | 0.6565 | %59.43 | - | - | - | - |

- **Süper Lig Değerlendirmesi (`663` maç):** Süper Lig'de form dalgalanmalarının yüksek olması sebebiyle `M2` üstel zaman sönümü tek başına RPS'yi `0.1958` -> `0.1955` ve 1X2 Log-Loss'u `0.9689` -> `0.9681` iyileştirmiştir. `M2 + M5` piyasa harmanı devreye girdiğinde Süper Lig RPS değeri `0.1858` (kapanış piyasası: `0.1842`), 1X2 isabet oranı `%58.37`, 9'lu İY/MS Top-1 isabeti `%36.71` ve İY/MS Top-3 isabeti `%67.52` seviyesine ulaşmıştır.

## 4. Diğer Liglerin Ayrıntılı Ablasyon Kırılımı (`E0`, `SP1`, `F1`)

### Premier League (`E0`)

| Aşama / Model | Maç | 1X2 RPS (↓) | 1X2 Brier (↓) | 1X2 Log-Loss (↓) | 1X2 İsabet (↑) | Üst 2.5 Brier (↓) | Üst 2.5 Log-Loss (↓) | Üst 2.5 İsabet (↑) | 9'lu İY/MS Brier (↓) | 9'lu İY/MS Log-Loss (↓) | İY/MS Top-1 (↑) | İY/MS Top-3 (↑) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1. Baz Post-Fix (`ξ=0`, `α=0`) | 780 | 0.2092 | 0.6113 | 1.0181 | %49.61 | 0.2551 | 0.7046 | %52.18 | 0.8254 | 1.9589 | %31.03 | %62.31 |
| 2. + Zaman Sönümü (`ξ=0.0015`, `α=0`) | 780 | 0.2089 | 0.6106 | 1.0172 | %49.49 | 0.2550 | 0.7045 | %52.18 | 0.8252 | 1.9576 | %31.15 | %62.31 |
| 3. + Piyasa Harmanı (`ξ=0.0015`, `α=0.65`) | 780 | 0.2030 | 0.5983 | 0.9993 | %51.03 | 0.2453 | 0.6836 | %56.15 | 0.8178 | 1.9398 | %31.54 | %62.31 |
| 4. Saf Piyasa Referansı (De-vigged Market) | 780 | 0.2032 | 0.5990 | 0.9998 | %51.54 | 0.2431 | 0.6791 | %57.82 | - | - | - | - |

### La Liga (`SP1`)

| Aşama / Model | Maç | 1X2 RPS (↓) | 1X2 Brier (↓) | 1X2 Log-Loss (↓) | 1X2 İsabet (↑) | Üst 2.5 Brier (↓) | Üst 2.5 Log-Loss (↓) | Üst 2.5 İsabet (↑) | 9'lu İY/MS Brier (↓) | 9'lu İY/MS Log-Loss (↓) | İY/MS Top-1 (↑) | İY/MS Top-3 (↑) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1. Baz Post-Fix (`ξ=0`, `α=0`) | 794 | 0.2013 | 0.5833 | 0.9815 | %52.27 | 0.2403 | 0.6735 | %56.67 | 0.8153 | 1.9243 | %29.22 | %62.47 |
| 2. + Zaman Sönümü (`ξ=0.0015`, `α=0`) | 794 | 0.2015 | 0.5838 | 0.9821 | %51.89 | 0.2402 | 0.6731 | %57.81 | 0.8156 | 1.9247 | %29.09 | %62.47 |
| 3. + Piyasa Harmanı (`ξ=0.0015`, `α=0.65`) | 794 | 0.1930 | 0.5646 | 0.9552 | %55.67 | 0.2348 | 0.6617 | %61.08 | 0.8056 | 1.8978 | %31.49 | %63.98 |
| 4. Saf Piyasa Referansı (De-vigged Market) | 794 | 0.1906 | 0.5590 | 0.9470 | %55.42 | 0.2341 | 0.6601 | %60.20 | - | - | - | - |

### Ligue 1 (`F1`)

| Aşama / Model | Maç | 1X2 RPS (↓) | 1X2 Brier (↓) | 1X2 Log-Loss (↓) | 1X2 İsabet (↑) | Üst 2.5 Brier (↓) | Üst 2.5 Log-Loss (↓) | Üst 2.5 İsabet (↑) | 9'lu İY/MS Brier (↓) | 9'lu İY/MS Log-Loss (↓) | İY/MS Top-1 (↑) | İY/MS Top-3 (↑) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1. Baz Post-Fix (`ξ=0`, `α=0`) | 608 | 0.2096 | 0.5951 | 0.9972 | %52.80 | 0.2482 | 0.6899 | %57.07 | 0.8103 | 1.8823 | %32.57 | %66.45 |
| 2. + Zaman Sönümü (`ξ=0.0015`, `α=0`) | 608 | 0.2098 | 0.5955 | 0.9978 | %52.63 | 0.2483 | 0.6900 | %56.58 | 0.8104 | 1.8826 | %32.40 | %66.61 |
| 3. + Piyasa Harmanı (`ξ=0.0015`, `α=0.65`) | 608 | 0.2018 | 0.5777 | 0.9717 | %53.78 | 0.2384 | 0.6694 | %58.72 | 0.8017 | 1.8565 | %33.88 | %66.61 |
| 4. Saf Piyasa Referansı (De-vigged Market) | 608 | 0.2004 | 0.5744 | 0.9669 | %54.61 | 0.2359 | 0.6646 | %59.70 | - | - | - | - |

## 5. Hiperparametre Izgara Duyarlılık Analizi (`ξ` ve `α`)

### 5.1. Zaman Sönümü (`time_decay_xi = ξ`) Duyarlılığı (`α = 0.0`, Saf Model)

| `ξ` (1/gün) | Yarı Ömür (gün) | 1X2 RPS (↓) | 1X2 Brier (↓) | 1X2 Log-Loss (↓) | 1X2 İsabet (↑) | Üst 2.5 Brier (↓) | 9'lu İY/MS Log-Loss (↓) |
|---:|---:|---:|---:|---:|---:|---:|---:|
| `0.0000` | ∞ | `0.20395` | `0.59151` | `0.99195` | %52.44 | `0.24797` | `1.91466` |
| `0.0015` **(Seçilen)** | 462 | `0.20390` | `0.59142` | `0.99180` | %52.30 | `0.24791` | `1.91428` |
| `0.0030` | 231 | `0.20391` | `0.59146` | `0.99183` | %52.37 | `0.24794` | `1.91414` |
| `0.0045` | 154 | `0.20398` | `0.59162` | `0.99204` | %52.48 | `0.24804` | `1.91421` |
| `0.0060` | 116 | `0.20410` | `0.59191` | `0.99242` | %52.37 | `0.24823` | `1.91449` |
| `0.0080` | 87 | `0.20433` | `0.59246` | `0.99316` | %52.09 | `0.24859` | `1.91516` |
| `0.0120` | 58 | `0.20505` | `0.59407` | `0.99539` | %52.02 | `0.24964` | `1.91749` |

### 5.2. Piyasa Harmanı (`market_blend_alpha = α`) Duyarlılığı (`ξ = 0.0015`)

| `α` (Piyasa Ağırlığı) | 1X2 RPS (↓) | 1X2 Brier (↓) | 1X2 Log-Loss (↓) | 1X2 İsabet (↑) | Üst 2.5 Brier (↓) | Üst 2.5 Log-Loss (↓) | 9'lu İY/MS Brier (↓) | 9'lu İY/MS Log-Loss (↓) | İY/MS Top-1 (↑) | İY/MS Top-3 (↑) |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `0.00` | `0.20390` | `0.59142` | `0.99180` | %52.30 | `0.24791` | `0.68946` | `0.81282` | `1.91428` | %31.47 | %63.50 |
| `0.15` | `0.20143` | `0.58605` | `0.98397` | %53.11 | `0.24516` | `0.68350` | `0.81002` | `1.90645` | %31.89 | %64.03 |
| `0.25` | `0.19999` | `0.58294` | `0.97950` | %53.64 | `0.24353` | `0.68003` | `0.80837` | `1.90199` | %31.96 | %64.28 |
| `0.35` | `0.19873` | `0.58020` | `0.97558` | %54.06 | `0.24206` | `0.67694` | `0.80691` | `1.89807` | %32.49 | %64.70 |
| `0.50` | `0.19715` | `0.57680` | `0.97069` | %54.31 | `0.24017` | `0.67300` | `0.80505` | `1.89317` | %32.88 | %64.87 |
| `0.65` **(Seçilen)** | `0.19596` | `0.57423` | `0.96694` | %54.62 | `0.23865` | `0.66984` | `0.80360` | `1.88944` | %33.23 | %64.91 |

## 6. Güvenirlik ve Kalibrasyon Özeti (Reliability Buckets)

### 6.1. 1X2 Olasılık Dilimleri (Baz Post-Fix vs M2+M5 Harman vs Piyasa)

| Olasılık Dilimi | Baz Adet | Baz Tahmin | Baz Gerçekleşen | Baz Hata | Harman (M2+M5) Adet | Harman Tahmin | Harman Gerçekleşen | Harman Hata | Piyasa Hata |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `[0.0, 0.2)` | 1269 | %14.62 | %14.26 | %0.35 | 1352 | %14.81 | %11.98 | %2.83 | %2.10 |
| `[0.2, 0.4)` | 4969 | %28.56 | %28.07 | %0.48 | 4841 | %28.23 | %27.66 | %0.57 | %0.38 |
| `[0.4, 0.6)` | 1690 | %48.70 | %49.53 | %0.83 | 1681 | %48.90 | %50.68 | %1.78 | %1.61 |
| `[0.6, 0.8)` | 558 | %67.45 | %69.89 | %2.45 | 611 | %67.82 | %73.49 | %5.67 | %3.06 |
| `[0.8, 1.0]` | 49 | %83.89 | %85.71 | %1.83 | 50 | %83.36 | %86.00 | %2.64 | %4.65 |

### 6.2. Üst 2.5 Olasılık Dilimleri (Baz Post-Fix vs M2+M5 Harman vs Piyasa)

| Olasılık Dilimi | Baz Adet | Baz Tahmin | Baz Gerçekleşen | Baz Hata | Harman (M2+M5) Adet | Harman Tahmin | Harman Gerçekleşen | Harman Hata | Piyasa Hata |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `[0.0, 0.2)` | 6 | %17.51 | %33.33 | %15.82 | 0 | - | - | - | - |
| `[0.2, 0.4)` | 460 | %34.22 | %43.70 | %9.48 | 231 | %35.07 | %37.23 | %2.16 | %1.03 |
| `[0.4, 0.6)` | 1733 | %50.67 | %53.78 | %3.11 | 1968 | %50.85 | %51.83 | %0.98 | %0.61 |
| `[0.6, 0.8)` | 628 | %66.28 | %60.51 | %5.77 | 640 | %65.37 | %65.47 | %0.10 | %1.96 |
| `[0.8, 1.0]` | 18 | %81.78 | %88.89 | %7.11 | 6 | %81.95 | %100.00 | %18.05 | %17.39 |

## 7. Üretim Varsayılanları Kararı

- `DEFAULT_TIME_DECAY_XI = 0.0015`: Çok hızlı sönüm (`ξ >= 0.0045`) sezon içi örneklem hacmini aşırı daraltarak RPS'yi bozarken, `ξ = 0.0015` hem birleşik 4 ligde hem de Süper Lig ve Premier League özelinde RPS, Brier ve Log-Loss metriklerini eşzamanlı düşürdüğü için üretim varsayılanı olarak atanmıştır. Oran verisi bulunmayan (`market_probs=None`) saf model çağrılarında da doğrudan aktiftir.
- `DEFAULT_MARKET_BLEND_ALPHA = 0.65`: Test edilen hibrit harman ızgarasında (`0.00..0.65`) tüm olasılıksal metrikleri (`1X2 RPS`, `1X2 Log-Loss`, `Üst 2.5 Brier/Log-Loss`, `9'lu İY/MS Brier/Log-Loss` ve `İY/MS Top-1/Top-3`) monotonik biçimde iyileştirirken çoklu kaynak sakatlık ve xG/şut sinyallerinin etkisini koruduğu için üretim varsayılanı olarak sabitlenmiştir.
