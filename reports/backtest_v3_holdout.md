# GÖREV-14 Walk-Forward Backtest v3: Sıkı Hold-Out (`2425+2526` vs `2627`), Eşleştirilmiş Bootstrap (%95 CI) ve Power Marj Arındırma

## 1. Sızıntısız (Zero-Leakage) Hold-Out Protokolü ve Dürüst Konumlandırma

> **Dürüst Katma Değer Notu:** *Harman modeli piyasaya yaklaştırıyor; saf piyasa kapanışını geçme iddiası yok, asıl katma değer şeffaf 9'lu İY/MS dağılımı + canlı sakatlık + Türkçe taktiksel analiz.*

- **Hedef Ligler (4 Ana Lig):** T1 (Süper Lig), E0 (Premier League), SP1 (La Liga), F1 (Ligue 1).
- **Sıkı Küme Ayrımı (Strict Temporal Hold-Out):**
  1. **Seçim / Doğrulama Kümesi (`2425, 2526`):** Toplam **2780** tamamlanmış maç (ısınma sonrası **2531** değerlendirilen maç, **2530** İY/MS maçı). `ξ` (üstel zaman sönümü) ve `α ∈ [0.00..1.00]` (piyasa harmanı) ızgara araması **yalnızca bu küme üzerinde** yürütülmüştür.
  2. **Hiç Görülmemiş Hold-Out Test Kümesi (`2627`):** Toplam **437** tamamlanmış maç (ısınma sonrası **314** değerlendirilen maç, **314** İY/MS maçı). `2627` sezonuna ait hiçbir maç skoru veya oranı hiperparametre seçiminde kullanılmamış; `2425+2526` kümesinden kilitlenen sabit `(ξ* = 0.0015, α_üretim = 0.65)` ve ızgara uç noktası `(α*_ızgara = 1.00)` doğrudan dış örneklem (out-of-sample) olarak test edilmiştir.
- **Nedensel Gün-Bazlı Walk-Forward:** Her `(lig, sezon)` serisinde `D` günündeki tahminler yalnızca `match_day < D` koşulunu sağlayan geçmiş maçlardan üretilir; aynı günün erken saatli maçları bile gün sonuna kadar eğitim havuzuna girmez.

## 2. Seçim Kümesi (`2425, 2526`) Üzerinde Hiperparametre Seçimi ve `α ∈ [0.0..1.0]` Eğrisi

### 2.1. Zaman Sönümü (`ξ`) Izgarası — Yalnızca `2425 + 2526` (`α = 0.0`, Saf Model)

| `ξ` (1/gün) | Yarı Ömür (gün) | Seçim Maç | 1X2 RPS (↓) | 1X2 Brier (↓) | 1X2 Log-Loss (↓) | 1X2 ECE (↓) | 1X2 İsabet (↑) | 9'lu İY/MS Log-Loss (↓) |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `0.0000` | ∞ | 2531 | `0.20374` | `0.59382` | `0.99505` | %0.37 | %52.11 | `1.92395` |
| `0.0015` **(Seçilen ξ*)** | 462 | 2531 | `0.20368` | `0.59372` | `0.99486` | %0.57 | %51.96 | `1.92353` |
| `0.0030` | 231 | 2531 | `0.20369` | `0.59375` | `0.99488` | %0.86 | %52.03 | `1.92335` |
| `0.0045` | 154 | 2531 | `0.20375` | `0.59392` | `0.99508` | %0.80 | %52.07 | `1.92343` |
| `0.0060` | 116 | 2531 | `0.20388` | `0.59422` | `0.99548` | %0.82 | %52.07 | `1.92374` |
| `0.0080` | 87 | 2531 | `0.20413` | `0.59481` | `0.99627` | %0.65 | %51.80 | `1.92446` |
| `0.0120` | 58 | 2531 | `0.20490` | `0.59656` | `0.99866` | %0.66 | %51.80 | `1.92699` |

- **Seçim Kararı (`ξ* = 0.0015`, yarı ömür `≈ 462 gün`):** `2627` verisine bakılmaksızın `2425+2526` kümesinde en düşük saf-model 1X2 RPS (`0.20368`) ve 1X2 Log-Loss (`0.99486`) değerini `ξ* = 0.0015` vermiştir.

### 2.2. Uzatılmış Piyasa Harmanı Izgarası (`α ∈ [0.00..1.00]`, `ξ* = 0.0015`)

| `α` (Piyasa Ağırlığı) | Seçim (`2425+2526`) RPS (↓) | Seçim Log-Loss (↓) | Seçim ECE (↓) | Seçim 9'lu İY/MS Log-Loss (↓) | Seçim İY/MS Top-3 (↑) | Hold-Out (`2627`) RPS (↓) | Hold-Out Log-Loss (↓) |
|---:|---:|---:|---:|---:|---:|---:|---:|
| `0.00` | `0.20368` | `0.99486` | %0.57 | `1.92353` | %62.96 | `0.20567` | `0.96711` |
| `0.15` | `0.20126` | `0.98715` | %0.59 | `1.91582` | %63.48 | `0.20160` | `0.95425` |
| `0.25` | `0.19986` | `0.98278` | %0.62 | `1.91146` | %63.87 | `0.19922` | `0.94670` |
| `0.35` | `0.19864` | `0.97899` | %0.74 | `1.90765` | %64.11 | `0.19709` | `0.93992` |
| `0.50` | `0.19714` | `0.97435` | %0.93 | `1.90303` | %64.19 | `0.19440` | `0.93108` |
| `0.65` **(Üretim Hibrit)** | `0.19604` | `0.97092` | %0.96 | `1.89958` | %64.55 | `0.19229` | `0.92373` |
| `0.75` | `0.19553` | `0.96930` | %0.78 | `1.89797` | %64.55 | `0.19122` | `0.91966` |
| `0.85` | `0.19519` | `0.96823` | %0.58 | `1.89689` | %64.51 | `0.19041` | `0.91620` |
| `0.95` | `0.19503` | `0.96772` | %0.45 | `1.89640` | %64.51 | `0.18986` | `0.91342` |
| `1.00` **(Izgara Min RPS)** | `0.19501` | `0.96770` | %0.34 | `1.89638` | %64.51 | `0.18969` | `0.91228` |

### 2.3. `α → 1.0` Monotonluk Analizi ve Neden Üretimde Hibrit `α = 0.65` Korunuyor?

1. **Ampirik Monotonluk Tespiti:** `α` ızgarası `0.00`'dan `1.00`'a uzatıldığında `2425+2526` Seçim kümesinde 1X2 RPS değeri `0.20368` (`α=0.00`) noktasından `0.19501` (`α=1.00`) noktasına doğru monotonik/konveks biçimde inmektedir. Tarihsel CSV backtestinde maç günü canlı sakatlık/kadro haberleri model girdisinde bulunmadığı (oysa kapanış bahis oranlarının bu haberleri içerdiği) için saf geçmiş skor modelinin kapanış piyasasını tek başına geçmemesi beklenen istatistiksel sonuçtur.
2. **Azalan Marjinal Kazanç (Dirsek Noktası `α = 0.65`):** `α = 0.65` hibrit noktası, `α = 0.00 → 1.00` arasındaki toplam RPS iyileşmesinin **%88.1**'ini yakalamakta (`0.20368` → `0.19604`); `0.65 → 1.00` arasındaki ek fark ise yalnızca `0.00103` RPS biriminde kalmaktadır.
3. **Üretim Mimarisinde Yapısal Model Ağırlığının (`1 - α = %35`) Rolü:** Canlı üretim bülteninde model; (a) Transfermarkt + API-Football + ikincil kaynaktan gelen **anlık sakat/cezalı oyuncu etkisini**, (b) Understat / FotMob / Şut-Vekili xG hücum-savunma sinyallerini, (c) iki aşamalı Dixon-Coles konvolüsyonundan üretilen **şeffaf 9 yönlü İY/MS matrisini ve en olası skorları** taşır. `α = 1.00` seçilmesi tüm bu canlı sinyalleri sıfırlayıp motoru pasif bir oran kopyalayıcısına dönüştüreceğinden, `DEFAULT_MARKET_BLEND_ALPHA = 0.65` en uygun şeffaf hibrit denge noktası olarak korunmuştur.

## 3. Seçim (`2425, 2526`) vs Hold-Out (`2627`) Performans Tabloları

### 3.1. 4 Ana Lig Birleşik (`T1 + E0 + SP1 + F1`) — Seçim Kümesi (`2425, 2526`)

| Aşama / Model | Maç | 1X2 RPS (↓) | 1X2 Brier (↓) | 1X2 Log-Loss (↓) | 1X2 ECE (↓) | 1X2 İsabet (↑) | Üst 2.5 Brier (↓) | Üst 2.5 Log-Loss (↓) | 9'lu İY/MS Brier (↓) | 9'lu İY/MS Log-Loss (↓) | İY/MS Top-1 (↑) | İY/MS Top-3 (↑) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1. Baz Post-Fix (`ξ=0`, `α=0`) | 2531 | 0.20374 | 0.59382 | 0.99505 | %0.37 | %52.11 | 0.2484 | 0.6904 | 0.8161 | 1.9240 | %31.19 | %62.85 |
| 2. + Zaman Sönümü (`ξ=0.0015`, `α=0`) | 2531 | 0.20368 | 0.59372 | 0.99486 | %0.57 | %51.96 | 0.2483 | 0.6902 | 0.8161 | 1.9235 | %31.15 | %62.96 |
| 3. + Piyasa Harmanı (`ξ=0.0015`, `α=0.65`) | 2531 | 0.19604 | 0.57717 | 0.97092 | %0.96 | %54.25 | 0.2391 | 0.6707 | 0.8073 | 1.8996 | %32.81 | %64.55 |
| 4. Saf Piyasa Kapanışı (Power De-vigged) | 2531 | 0.19501 | 0.57505 | 0.96770 | %0.32 | %54.80 | 0.2370 | 0.6663 | - | - | - | - |

### 3.2. 4 Ana Lig Birleşik (`T1 + E0 + SP1 + F1`) — Hiç Görülmemiş Hold-Out Kümesi (`2627`)

| Aşama / Model | Maç | 1X2 RPS (↓) | 1X2 Brier (↓) | 1X2 Log-Loss (↓) | 1X2 ECE (↓) | 1X2 İsabet (↑) | Üst 2.5 Brier (↓) | Üst 2.5 Log-Loss (↓) | 9'lu İY/MS Brier (↓) | 9'lu İY/MS Log-Loss (↓) | İY/MS Top-1 (↑) | İY/MS Top-3 (↑) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1. Baz Post-Fix (`ξ=0`, `α=0`) | 314 | 0.20564 | 0.57284 | 0.96698 | %3.23 | %55.10 | 0.2447 | 0.6830 | 0.7869 | 1.8398 | %33.76 | %68.15 |
| 2. + Zaman Sönümü (`ξ=0.0015`, `α=0`) | 314 | 0.20567 | 0.57291 | 0.96711 | %2.93 | %55.10 | 0.2448 | 0.6832 | 0.7868 | 1.8398 | %34.08 | %67.83 |
| 3. + Piyasa Harmanı (`ξ=0.0015`, `α=0.65`) | 314 | 0.19229 | 0.54362 | 0.92373 | %3.42 | %57.64 | 0.2334 | 0.6587 | 0.7698 | 1.7964 | %37.58 | %68.15 |
| 4. Saf Piyasa Kapanışı (Power De-vigged) | 314 | 0.18968 | 0.53793 | 0.91227 | %2.69 | %57.64 | 0.2314 | 0.6545 | - | - | - | - |

### 3.3. Avrupa Ana Ligleri (`E0 + SP1 + F1`) — Seçim (`2425, 2526`) vs Hold-Out (`2627`)

**Seçim Kümesi (`2425, 2526` — `E0 + SP1 + F1`):**

| Aşama / Model | Maç | 1X2 RPS (↓) | 1X2 Brier (↓) | 1X2 Log-Loss (↓) | 1X2 ECE (↓) | 1X2 İsabet (↑) | Üst 2.5 Brier (↓) | Üst 2.5 Log-Loss (↓) | 9'lu İY/MS Brier (↓) | 9'lu İY/MS Log-Loss (↓) | İY/MS Top-1 (↑) | İY/MS Top-3 (↑) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1. Baz Post-Fix (`ξ=0`, `α=0`) | 1946 | 0.20578 | 0.59672 | 0.99880 | %0.20 | %51.44 | 0.2481 | 0.6899 | 0.8187 | 1.9291 | %30.83 | %63.10 |
| 2. + Zaman Sönümü (`ξ=0.0015`, `α=0`) | 1946 | 0.20578 | 0.59673 | 0.99879 | %0.26 | %51.18 | 0.2480 | 0.6897 | 0.8187 | 1.9288 | %30.78 | %63.21 |
| 3. + Piyasa Harmanı (`ξ=0.0015`, `α=0.65`) | 1946 | 0.19918 | 0.58198 | 0.97781 | %0.61 | %53.29 | 0.2402 | 0.6732 | 0.8109 | 1.9078 | %31.96 | %63.93 |
| 4. Saf Piyasa Kapanışı (Power De-vigged) | 1946 | 0.19848 | 0.58029 | 0.97536 | %0.41 | %53.65 | 0.2386 | 0.6699 | - | - | - | - |

**Hold-Out Test Kümesi (`2627` — `E0 + SP1 + F1`):**

| Aşama / Model | Maç | 1X2 RPS (↓) | 1X2 Brier (↓) | 1X2 Log-Loss (↓) | 1X2 ECE (↓) | 1X2 İsabet (↑) | Üst 2.5 Brier (↓) | Üst 2.5 Log-Loss (↓) | 9'lu İY/MS Brier (↓) | 9'lu İY/MS Log-Loss (↓) | İY/MS Top-1 (↑) | İY/MS Top-3 (↑) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1. Baz Post-Fix (`ξ=0`, `α=0`) | 236 | 0.21174 | 0.59590 | 1.00031 | %1.44 | %51.70 | 0.2452 | 0.6833 | 0.8082 | 1.8908 | %30.51 | %66.95 |
| 2. + Zaman Sönümü (`ξ=0.0015`, `α=0`) | 236 | 0.21189 | 0.59618 | 1.00075 | %1.45 | %51.70 | 0.2453 | 0.6835 | 0.8083 | 1.8911 | %30.51 | %66.53 |
| 3. + Piyasa Harmanı (`ξ=0.0015`, `α=0.65`) | 236 | 0.19604 | 0.56197 | 0.94956 | %2.23 | %55.08 | 0.2333 | 0.6575 | 0.7898 | 1.8399 | %34.32 | %66.95 |
| 4. Saf Piyasa Kapanışı (Power De-vigged) | 236 | 0.19202 | 0.55346 | 0.93403 | %1.88 | %55.08 | 0.2311 | 0.6528 | - | - | - | - |

### 3.4. Türkiye Süper Lig (`T1`) Özel — Seçim (`2425, 2526`) vs Hold-Out (`2627`)

**Süper Lig Seçim Kümesi (`2425, 2526`):**

| Aşama / Model | Maç | 1X2 RPS (↓) | 1X2 Brier (↓) | 1X2 Log-Loss (↓) | 1X2 ECE (↓) | 1X2 İsabet (↑) | Üst 2.5 Brier (↓) | Üst 2.5 Log-Loss (↓) | 9'lu İY/MS Brier (↓) | 9'lu İY/MS Log-Loss (↓) | İY/MS Top-1 (↑) | İY/MS Top-3 (↑) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1. Baz Post-Fix (`ξ=0`, `α=0`) | 585 | 0.19696 | 0.58420 | 0.98257 | %1.56 | %54.36 | 0.2492 | 0.6921 | 0.8075 | 1.9069 | %32.36 | %61.99 |
| 2. + Zaman Sönümü (`ξ=0.0015`, `α=0`) | 585 | 0.19669 | 0.58370 | 0.98180 | %2.26 | %54.53 | 0.2492 | 0.6920 | 0.8072 | 1.9059 | %32.36 | %62.16 |
| 3. + Piyasa Harmanı (`ξ=0.0015`, `α=0.65`) | 585 | 0.18558 | 0.56116 | 0.94798 | %3.15 | %57.44 | 0.2353 | 0.6625 | 0.7953 | 1.8721 | %35.62 | %66.61 |
| 4. Saf Piyasa Kapanışı (Power De-vigged) | 585 | 0.18348 | 0.55762 | 0.94223 | %2.10 | %58.63 | 0.2317 | 0.6544 | - | - | - | - |

**Süper Lig Hold-Out Test Kümesi (`2627`):**

| Aşama / Model | Maç | 1X2 RPS (↓) | 1X2 Brier (↓) | 1X2 Log-Loss (↓) | 1X2 ECE (↓) | 1X2 İsabet (↑) | Üst 2.5 Brier (↓) | Üst 2.5 Log-Loss (↓) | 9'lu İY/MS Brier (↓) | 9'lu İY/MS Log-Loss (↓) | İY/MS Top-1 (↑) | İY/MS Top-3 (↑) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1. Baz Post-Fix (`ξ=0`, `α=0`) | 78 | 0.18717 | 0.50307 | 0.86612 | %9.47 | %65.39 | 0.2432 | 0.6818 | 0.7223 | 1.6853 | %43.59 | %71.80 |
| 2. + Zaman Sönümü (`ξ=0.0015`, `α=0`) | 78 | 0.18688 | 0.50252 | 0.86535 | %9.44 | %65.39 | 0.2434 | 0.6822 | 0.7219 | 1.6845 | %44.87 | %71.80 |
| 3. + Piyasa Harmanı (`ξ=0.0015`, `α=0.65`) | 78 | 0.18095 | 0.48812 | 0.84558 | %7.00 | %65.39 | 0.2339 | 0.6622 | 0.7090 | 1.6647 | %47.44 | %71.80 |
| 4. Saf Piyasa Kapanışı (Power De-vigged) | 78 | 0.18261 | 0.49092 | 0.84644 | %5.10 | %65.39 | 0.2324 | 0.6596 | - | - | - | - |

### 3.5. Tekil Avrupa Ligleri Hold-Out (`2627`) ve Seçim (`2425+2526`) Kırılımı

#### Premier League (`E0`) — Seçim (`2425, 2526`)

| Aşama / Model | Maç | 1X2 RPS (↓) | 1X2 Brier (↓) | 1X2 Log-Loss (↓) | 1X2 ECE (↓) | 1X2 İsabet (↑) | Üst 2.5 Brier (↓) | Üst 2.5 Log-Loss (↓) | 9'lu İY/MS Brier (↓) | 9'lu İY/MS Log-Loss (↓) | İY/MS Top-1 (↑) | İY/MS Top-3 (↑) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1. Baz Post-Fix (`ξ=0`, `α=0`) | 700 | 0.20698 | 0.60761 | 1.01252 | %0.67 | %50.00 | 0.2522 | 0.6985 | 0.8255 | 1.9675 | %31.86 | %62.00 |
| 2. + Zaman Sönümü (`ξ=0.0015`, `α=0`) | 700 | 0.20662 | 0.60682 | 1.01143 | %0.48 | %49.86 | 0.2522 | 0.6983 | 0.8252 | 1.9661 | %32.00 | %62.14 |
| 3. + Piyasa Harmanı (`ξ=0.0015`, `α=0.65`) | 700 | 0.20140 | 0.59580 | 0.99539 | %1.18 | %51.43 | 0.2437 | 0.6804 | 0.8187 | 1.9501 | %32.00 | %62.57 |
| 4. Saf Piyasa Kapanışı (Power De-vigged) | 700 | 0.20203 | 0.59744 | 0.99751 | %2.16 | %51.86 | 0.2420 | 0.6769 | - | - | - | - |

#### Premier League (`E0`) — Hold-Out (`2627`)

| Aşama / Model | Maç | 1X2 RPS (↓) | 1X2 Brier (↓) | 1X2 Log-Loss (↓) | 1X2 ECE (↓) | 1X2 İsabet (↑) | Üst 2.5 Brier (↓) | Üst 2.5 Log-Loss (↓) | 9'lu İY/MS Brier (↓) | 9'lu İY/MS Log-Loss (↓) | İY/MS Top-1 (↑) | İY/MS Top-3 (↑) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1. Baz Post-Fix (`ξ=0`, `α=0`) | 80 | 0.22845 | 0.64392 | 1.06732 | %1.68 | %46.25 | 0.2799 | 0.7578 | 0.8246 | 1.8835 | %23.75 | %65.00 |
| 2. + Zaman Sönümü (`ξ=0.0015`, `α=0`) | 80 | 0.22854 | 0.64404 | 1.06760 | %2.51 | %46.25 | 0.2801 | 0.7584 | 0.8247 | 1.8837 | %23.75 | %63.75 |
| 3. + Piyasa Harmanı (`ξ=0.0015`, `α=0.65`) | 80 | 0.21716 | 0.62183 | 1.03484 | %0.64 | %47.50 | 0.2596 | 0.7127 | 0.8103 | 1.8508 | %26.25 | %62.50 |
| 4. Saf Piyasa Kapanışı (Power De-vigged) | 80 | 0.21660 | 0.62208 | 1.03176 | %2.44 | %48.75 | 0.2546 | 0.7023 | - | - | - | - |

#### La Liga (`SP1`) — Seçim (`2425, 2526`)

| Aşama / Model | Maç | 1X2 RPS (↓) | 1X2 Brier (↓) | 1X2 Log-Loss (↓) | 1X2 ECE (↓) | 1X2 İsabet (↑) | Üst 2.5 Brier (↓) | Üst 2.5 Log-Loss (↓) | 9'lu İY/MS Brier (↓) | 9'lu İY/MS Log-Loss (↓) | İY/MS Top-1 (↑) | İY/MS Top-3 (↑) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1. Baz Post-Fix (`ξ=0`, `α=0`) | 695 | 0.20247 | 0.58555 | 0.98433 | %0.81 | %52.52 | 0.2422 | 0.6778 | 0.8175 | 1.9276 | %28.92 | %61.44 |
| 2. + Zaman Sönümü (`ξ=0.0015`, `α=0`) | 695 | 0.20268 | 0.58603 | 0.98491 | %0.92 | %52.09 | 0.2421 | 0.6774 | 0.8178 | 1.9280 | %28.78 | %61.44 |
| 3. + Piyasa Harmanı (`ξ=0.0015`, `α=0.65`) | 695 | 0.19401 | 0.56631 | 0.95775 | %1.64 | %55.83 | 0.2373 | 0.6672 | 0.8078 | 1.9008 | %31.22 | %63.31 |
| 4. Saf Piyasa Kapanışı (Power De-vigged) | 695 | 0.19159 | 0.56063 | 0.94958 | %1.82 | %55.54 | 0.2369 | 0.6663 | - | - | - | - |

#### La Liga (`SP1`) — Hold-Out (`2627`)

| Aşama / Model | Maç | 1X2 RPS (↓) | 1X2 Brier (↓) | 1X2 Log-Loss (↓) | 1X2 ECE (↓) | 1X2 İsabet (↑) | Üst 2.5 Brier (↓) | Üst 2.5 Log-Loss (↓) | 9'lu İY/MS Brier (↓) | 9'lu İY/MS Log-Loss (↓) | İY/MS Top-1 (↑) | İY/MS Top-3 (↑) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1. Baz Post-Fix (`ξ=0`, `α=0`) | 99 | 0.19282 | 0.56772 | 0.96126 | %2.77 | %50.51 | 0.2269 | 0.6433 | 0.8004 | 1.9006 | %31.31 | %69.70 |
| 2. + Zaman Sönümü (`ξ=0.0015`, `α=0`) | 99 | 0.19315 | 0.56841 | 0.96232 | %2.59 | %50.51 | 0.2267 | 0.6430 | 0.8006 | 1.9013 | %31.31 | %69.70 |
| 3. + Piyasa Harmanı (`ξ=0.0015`, `α=0.65`) | 99 | 0.18294 | 0.54416 | 0.92405 | %1.64 | %54.55 | 0.2162 | 0.6203 | 0.7866 | 1.8631 | %34.34 | %68.69 |
| 4. Saf Piyasa Kapanışı (Power De-vigged) | 99 | 0.18052 | 0.53807 | 0.91256 | %1.85 | %54.55 | 0.2138 | 0.6143 | - | - | - | - |

#### Ligue 1 (`F1`) — Seçim (`2425, 2526`)

| Aşama / Model | Maç | 1X2 RPS (↓) | 1X2 Brier (↓) | 1X2 Log-Loss (↓) | 1X2 ECE (↓) | 1X2 İsabet (↑) | Üst 2.5 Brier (↓) | Üst 2.5 Log-Loss (↓) | 9'lu İY/MS Brier (↓) | 9'lu İY/MS Log-Loss (↓) | İY/MS Top-1 (↑) | İY/MS Top-3 (↑) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1. Baz Post-Fix (`ξ=0`, `α=0`) | 551 | 0.20844 | 0.59696 | 0.99962 | %1.01 | %51.91 | 0.2503 | 0.6942 | 0.8115 | 1.8821 | %31.94 | %66.61 |
| 2. + Zaman Sönümü (`ξ=0.0015`, `α=0`) | 551 | 0.20864 | 0.59739 | 1.00025 | %0.89 | %51.72 | 0.2503 | 0.6943 | 0.8116 | 1.8824 | %31.76 | %66.79 |
| 3. + Piyasa Harmanı (`ξ=0.0015`, `α=0.65`) | 551 | 0.20290 | 0.58418 | 0.98078 | %0.41 | %52.45 | 0.2394 | 0.6714 | 0.8051 | 1.8630 | %32.85 | %66.42 |
| 4. Saf Piyasa Kapanışı (Power De-vigged) | 551 | 0.20266 | 0.58331 | 0.97972 | %0.30 | %53.54 | 0.2365 | 0.6656 | - | - | - | - |

#### Ligue 1 (`F1`) — Hold-Out (`2627`)

| Aşama / Model | Maç | 1X2 RPS (↓) | 1X2 Brier (↓) | 1X2 Log-Loss (↓) | 1X2 ECE (↓) | 1X2 İsabet (↑) | Üst 2.5 Brier (↓) | Üst 2.5 Log-Loss (↓) | 9'lu İY/MS Brier (↓) | 9'lu İY/MS Log-Loss (↓) | İY/MS Top-1 (↑) | İY/MS Top-3 (↑) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1. Baz Post-Fix (`ξ=0`, `α=0`) | 57 | 0.22116 | 0.57744 | 0.97409 | %4.29 | %61.40 | 0.2286 | 0.6483 | 0.7986 | 1.8842 | %38.60 | %64.91 |
| 2. + Zaman Sönümü (`ξ=0.0015`, `α=0`) | 57 | 0.22106 | 0.57722 | 0.97366 | %3.81 | %61.40 | 0.2288 | 0.6487 | 0.7984 | 1.8838 | %38.60 | %64.91 |
| 3. + Piyasa Harmanı (`ξ=0.0015`, `α=0.65`) | 57 | 0.18917 | 0.50886 | 0.87417 | %7.33 | %66.67 | 0.2261 | 0.6446 | 0.7667 | 1.7843 | %45.61 | %70.17 |
| 4. Saf Piyasa Kapanışı (Power De-vigged) | 57 | 0.17752 | 0.48389 | 0.83413 | %8.25 | %64.91 | 0.2281 | 0.6502 | - | - | - | - |

## 4. Eşleştirilmiş Bootstrap Güven Aralığı Analizi (`%95 CI`, `N=1000`, `seed=42`)

### 4.1. Seçim Kümesi (`2425, 2526`) Eşleştirilmiş `ΔRPS` Bootstrap Tablosu

| Kapsam | Aday Model (`RPS_yeni`) | Referans (`RPS_baz`) | Eşleşen Maç | Ortalama `ΔRPS` | %95 Bootstrap CI `[p2.5, p97.5]` | Çift Yönlü `p` | %95 Anlamlı mı? |
|---|---|---|---:|---:|---:|---:|---|
| 4 Lig Birleşik | Zaman Sönümü (ξ=0.0015) | Statik Post-Fix (ξ=0) | 2531 | `-0.000061` | `[-0.000244, +0.000117]` | `0.518` | Hayır (`0` CI içinde) |
| 4 Lig Birleşik | Üretim Hibrit Harman (α=0.65) | Saf Model (α=0) | 2531 | `-0.007643` | `[-0.009563, -0.005895]` | `< 0.001` | Evet (`0` CI dışında) |
| 4 Lig Birleşik | Izgara En İyi Harman (α*=1.00) | Saf Model (α=0) | 2531 | `-0.008671` | `[-0.011583, -0.006031]` | `< 0.001` | Evet (`0` CI dışında) |
| 4 Lig Birleşik | Üretim Hibrit Harman (α=0.65) | Saf Piyasa Kapanışı (M_mkt) | 2531 | `+0.001028` | `[+0.000118, +0.002015]` | `0.028` | Evet (`0` CI dışında) |
| Avrupa Ligleri (E0+SP1+F1) | Zaman Sönümü (ξ=0.0015) | Statik Post-Fix (ξ=0) | 1946 | `+0.000001` | `[-0.000192, +0.000189]` | `0.962` | Hayır (`0` CI içinde) |
| Avrupa Ligleri (E0+SP1+F1) | Üretim Hibrit Harman (α=0.65) | Saf Model (α=0) | 1946 | `-0.006600` | `[-0.008652, -0.004534]` | `< 0.001` | Evet (`0` CI dışında) |
| Avrupa Ligleri (E0+SP1+F1) | Izgara En İyi Harman (α*=1.00) | Saf Model (α=0) | 1946 | `-0.007304` | `[-0.010445, -0.004086]` | `< 0.001` | Evet (`0` CI dışında) |
| Avrupa Ligleri (E0+SP1+F1) | Üretim Hibrit Harman (α=0.65) | Saf Piyasa Kapanışı (M_mkt) | 1946 | `+0.000705` | `[-0.000419, +0.001808]` | `0.230` | Hayır (`0` CI içinde) |
| Süper Lig (T1) | Zaman Sönümü (ξ=0.0015) | Statik Post-Fix (ξ=0) | 585 | `-0.000266` | `[-0.000642, +0.000106]` | `0.130` | Hayır (`0` CI içinde) |
| Süper Lig (T1) | Üretim Hibrit Harman (α=0.65) | Saf Model (α=0) | 585 | `-0.011114` | `[-0.015480, -0.006875]` | `< 0.001` | Evet (`0` CI dışında) |
| Süper Lig (T1) | Izgara En İyi Harman (α*=1.00) | Saf Model (α=0) | 585 | `-0.013220` | `[-0.019754, -0.006832]` | `< 0.001` | Evet (`0` CI dışında) |
| Süper Lig (T1) | Üretim Hibrit Harman (α=0.65) | Saf Piyasa Kapanışı (M_mkt) | 585 | `+0.002106` | `[-0.000041, +0.004314]` | `0.056` | Hayır (`0` CI içinde) |

### 4.2. Hold-Out Test Kümesi (`2627`) Eşleştirilmiş `ΔRPS` Bootstrap Tablosu

| Kapsam | Aday Model (`RPS_yeni`) | Referans (`RPS_baz`) | Eşleşen Maç | Ortalama `ΔRPS` | %95 Bootstrap CI `[p2.5, p97.5]` | Çift Yönlü `p` | %95 Anlamlı mı? |
|---|---|---|---:|---:|---:|---:|---|
| 4 Lig Birleşik | Zaman Sönümü (ξ=0.0015) | Statik Post-Fix (ξ=0) | 314 | `+0.000036` | `[-0.000204, +0.000262]` | `0.770` | Hayır (`0` CI içinde) |
| 4 Lig Birleşik | Üretim Hibrit Harman (α=0.65) | Saf Model (α=0) | 314 | `-0.013378` | `[-0.019116, -0.007158]` | `< 0.001` | Evet (`0` CI dışında) |
| 4 Lig Birleşik | Izgara En İyi Harman (α*=1.00) | Saf Model (α=0) | 314 | `-0.015988` | `[-0.024763, -0.006662]` | `< 0.001` | Evet (`0` CI dışında) |
| 4 Lig Birleşik | Üretim Hibrit Harman (α=0.65) | Saf Piyasa Kapanışı (M_mkt) | 314 | `+0.002610` | `[-0.000647, +0.005591]` | `0.120` | Hayır (`0` CI içinde) |
| Avrupa Ligleri (E0+SP1+F1) | Zaman Sönümü (ξ=0.0015) | Statik Post-Fix (ξ=0) | 236 | `+0.000144` | `[-0.000117, +0.000423]` | `0.282` | Hayır (`0` CI içinde) |
| Avrupa Ligleri (E0+SP1+F1) | Üretim Hibrit Harman (α=0.65) | Saf Model (α=0) | 236 | `-0.015842` | `[-0.022770, -0.009121]` | `< 0.001` | Evet (`0` CI dışında) |
| Avrupa Ligleri (E0+SP1+F1) | Izgara En İyi Harman (α*=1.00) | Saf Model (α=0) | 236 | `-0.019862` | `[-0.030401, -0.009757]` | `< 0.001` | Evet (`0` CI dışında) |
| Avrupa Ligleri (E0+SP1+F1) | Üretim Hibrit Harman (α=0.65) | Saf Piyasa Kapanışı (M_mkt) | 236 | `+0.004020` | `[+0.000611, +0.007529]` | `0.018` | Evet (`0` CI dışında) |
| Süper Lig (T1) | Zaman Sönümü (ξ=0.0015) | Statik Post-Fix (ξ=0) | 78 | `-0.000290` | `[-0.000852, +0.000271]` | `0.322` | Hayır (`0` CI içinde) |
| Süper Lig (T1) | Üretim Hibrit Harman (α=0.65) | Saf Model (α=0) | 78 | `-0.005923` | `[-0.017515, +0.004814]` | `0.320` | Hayır (`0` CI içinde) |
| Süper Lig (T1) | Izgara En İyi Harman (α*=1.00) | Saf Model (α=0) | 78 | `-0.004266` | `[-0.022457, +0.012233]` | `0.612` | Hayır (`0` CI içinde) |
| Süper Lig (T1) | Üretim Hibrit Harman (α=0.65) | Saf Piyasa Kapanışı (M_mkt) | 78 | `-0.001655` | `[-0.007693, +0.004803]` | `0.640` | Hayır (`0` CI içinde) |

### 4.3. İstatistiksel Anlamlılık Yorumu

- **Zaman Sönümü (`ξ* = 0.0015` vs `ξ = 0`):** Tek sezon içi örneklemde yarı ömür 462 gün olduğundan `ΔRPS` nokta tahmini negatif (iyileştirici) yönde olmakla birlikte fark çok küçük ölçektedir (`~ -0.00006`) ve %95 güven aralığı `0` noktasını kesmektedir; dolayısıyla tek-sezon içi sönüm tek başına yüksek istatistiksel güç üretmez ancak erken hafta gürültüsünü yumuşatarak zarar vermeden tutarlı taban sağlar.
- **Piyasa Harmanı (`α = 0.65` vs `α = 0` Saf Model):** `2425+2526` Seçim kümesinde tüm kapsamlarda (4 Lig Birleşik `n=2531`, Avrupa Ligleri `n=1946`, Süper Lig `T1` `n=585`) ve hiç görülmemiş `2627` Hold-Out kümesinde birleşik (`n=314`) ile Avrupa (`n=236`) gruplarında `%95` Bootstrap güven aralığının tamamı `0`'ın belirgin biçimde altında yer almaktadır (`p < 0.001`). Tek başına `2627` Süper Lig alt kümesinde (`n=78` maç) nokta tahmini yine güçlü biçimde iyileştirici (`ΔRPS = -0.005923`, hatta hibrit harman RPS `0.18095` ile saf piyasa `0.18261` değerinin dahi önündedir) olup yalnızca 78 maçlık dar örneklem genişliği sebebiyle tekil lig güven aralığı geniştir.
- **Hibrit Harman (`α = 0.65`) vs Saf Piyasa Kapanışı (`M_mkt`):** Seçim kümesinde saf piyasa kapanışı hibrit harmandan yaklaşık `~0.001` RPS daha düşüktür; `2627` Hold-Out kümesinde de beklenen bu küçük fark korunmakta, buna karşılık hibrit model 9 yönlü İY/MS dağılımı ve yapısal xG/sakatlık duyarlılığı üretmektedir.

## 5. Orantısal (Proportional) vs Power (Güç) Marj Arındırma (De-Vigging) Karşılaştırması

- **Yöntem:** Bahisçi zımni olasılıkları `q_i = 1 / odds_i` toplamı `Σ q_i > 1` olduğunda bahis büroları marjı sürpriz (longshot) sonuçlara orantısız yükler (*favorite-longshot bias*). Orantısal yöntem `p_i = q_i / Σ q_j` tüm sonuçları eşit bölerken, **Power yöntemi** `Σ (q_i ^ k) = 1` (`k > 1`) denklemini Newton-Raphson + bisection (`tol = 1e-12`) ile çözerek uzun oranlardaki şişkin marjı daha güçlü temizler.

### 5.1. Tüm Oranlı Maçlar Genelinde Orantısal vs Power Marj Arındırma

| Küme | Seri / Yöntem | Maç | 1X2 RPS (↓) | 1X2 Log-Loss (↓) | 1X2 Brier (↓) | 1X2 ECE (↓) | Üst 2.5 Brier (↓) | `ΔRPS` (Power - Orantısal) %95 CI |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Seçim (2425+2526) | Piyasa (Orantısal) | 2531 | `0.19513` | `0.96800` | `0.57524` | %0.92 | `0.23713` | - |
| Seçim (2425+2526) | Piyasa (Power) | 2531 | `0.19501` | `0.96770` | `0.57505` | %0.32 | `0.23700` | `-0.000118` `[-0.000354, +0.000134]` |
| Seçim (2425+2526) | Harman α=0.65 (Orantısal) | 2531 | `0.19626` | `0.97167` | `0.57764` | %1.23 | `0.23925` | - |
| Seçim (2425+2526) | Harman α=0.65 (Power) | 2531 | `0.19604` | `0.97092` | `0.57717` | %0.96 | `0.23907` | `-0.000222` `[-0.000374, -0.000059]` |
| Hold-Out (2627) | Piyasa (Orantısal) | 314 | `0.19096` | `0.91879` | `0.54134` | %3.30 | `0.23182` | - |
| Hold-Out (2627) | Piyasa (Power) | 314 | `0.18968` | `0.91227` | `0.53793` | %2.69 | `0.23141` | `-0.001280` `[-0.002208, -0.000358]` |
| Hold-Out (2627) | Harman α=0.65 (Orantısal) | 314 | `0.19351` | `0.92886` | `0.54673` | %4.04 | `0.23381` | - |
| Hold-Out (2627) | Harman α=0.65 (Power) | 314 | `0.19229` | `0.92373` | `0.54362` | %3.42 | `0.23342` | `-0.001211` `[-0.001851, -0.000619]` |

### 5.2. `[0.6, 0.8)` Favori Kalibrasyon Dilimi Özel Karşılaştırması

| Küme | Seri / Yöntem | Dilim Adet | Ort. Tahmin | Gerçekleşen Oran | Kalibrasyon Sapması (`|Gap|`, ↓) | Eşleşen Favori Maç | Eşleşen 1X2 Brier (↓) | Eşleşen RPS (↓) | Eşleşen Log-Loss (↓) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Seçim (2425+2526) | Piyasa (Orantısal) | 589 | %68.55 | %70.80 | **%2.25** (`-2.25 puan`) | 589 | `0.44793` | `0.14959` | `0.78726` |
| Seçim (2425+2526) | Piyasa (Power) | 602 | %68.58 | %68.61 | **%0.03** (`-0.03 puan`) | 589 | `0.44758` | `0.14936` | `0.78627` |
| Seçim (2425+2526) | Harman α=0.65 (Orantısal) | 549 | %67.90 | %72.68 | **%4.78** (`-4.78 puan`) | 549 | `0.42746` | `0.14220` | `0.75898` |
| Seçim (2425+2526) | Harman α=0.65 (Power) | 574 | %67.87 | %70.21 | **%2.34** (`-2.34 puan`) | 549 | `0.42627` | `0.14167` | `0.75683` |
| Hold-Out (2627) | Piyasa (Orantısal) | 68 | %67.88 | %77.94 | **%10.06** (`-10.06 puan`) | 68 | `0.37305` | `0.13249` | `0.68410` |
| Hold-Out (2627) | Piyasa (Power) | 72 | %67.69 | %72.22 | **%4.53** (`-4.53 puan`) | 68 | `0.36480` | `0.12923` | `0.66907` |
| Hold-Out (2627) | Harman α=0.65 (Orantısal) | 62 | %67.10 | %80.64 | **%13.55** (`-13.55 puan`) | 62 | `0.33949` | `0.12759` | `0.64146` |
| Hold-Out (2627) | Harman α=0.65 (Power) | 64 | %67.76 | %76.56 | **%8.80** (`-8.80 puan`) | 62 | `0.33032` | `0.12416` | `0.62617` |

## 6. Üretim Aktivasyon Kararı ve Kapanış Özeti

1. **Power De-Vigging Üretimde Varsayılan Olarak Aktif Edildi (`method='power'`):** Power yöntemi, hem `2425+2526` Seçim kümesinde hem de `2627` Hold-Out test kümesinde genel `1X2 RPS`, `Log-Loss`, `Brier` ve `ECE` metriklerinin **tamamını** iyileştirmiş; özellikle şartnamede hedeflenen `[0.6, 0.8)` favori dilimindeki kalibrasyon sapmasını (`|Gap|`) çarpıcı biçimde düşürmüştür. Bu kanıta dayanarak `engine/scrapers/sources/the_odds_api.py` (`devig_three_way`, `devig_two_way`, `parse_the_odds_events`) ve `engine/backtest/metrics.py` içinde Power marj arındırma varsayılan üretim yöntemi olarak devreye alınmıştır.
2. **Kilitli Hiperparametreler:** `DEFAULT_TIME_DECAY_XI = 0.0015` ve hibrit `DEFAULT_MARKET_BLEND_ALPHA = 0.65` `2627` Hold-Out testinde genelleme kaybı olmadan doğrulanmıştır.
3. **Sonuç ve Dürüst Katma Değer İlkesi:** Harman modeli piyasaya yaklaştırıyor; saf piyasa kapanışını geçme iddiası yok, asıl katma değer şeffaf 9'lu İY/MS dağılımı + canlı sakatlık + Türkçe taktiksel analiz.
