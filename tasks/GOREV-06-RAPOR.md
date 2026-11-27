# GÖREV-06 Teknik Uygulama ve Doğrulama Raporu

**Görev:** Flutter Android APK Derleme, Optimizasyon ve Fiziksel Cihaz Kurulumu  
**Tarih:** 2026-11-26  
**Durum:** Tamamlandı ve Fiziksel Cihazda Doğrulandı (`app-debug.apk` üretildi, `adb install -r` -> `Success`, `PID 6646` çalışıyor)

---

## 1. Güncellenen ve Üretilen Dosyalar

`tasks/GOREV-06-APK-DERLEME-VE-CIHAZ-KURULUMU.md` teknik şartnamesi kapsamında aşağıdaki dosyalar güncellendi ve üretildi:

```text
E:\apk\futbol\
├── mobile\
│   ├── android\app\src\main\AndroidManifest.xml          # INTERNET, ACCESS_NETWORK_STATE izinleri ve "Futbol Analiz" etiketi
│   └── build\app\outputs\flutter-apk\app-debug.apk       # Derlenen Android Debug APK paketi (154,11 MB)
└── tasks\
    ├── GOREV-06-APK-DERLEME-VE-CIHAZ-KURULUMU.md
    └── GOREV-06-RAPOR.md                                 # Bu teknik doğrulama raporu
```

---

## 2. Teknik Uygulama Detayları

### 2.1. Android Manifest Yapılandırması (`mobile/android/app/src/main/AndroidManifest.xml`)
- Ağ üzerinden canlı Supabase veritabanına ve yazı tipi servislerine erişebilmesi için `<manifest>` kök düğümüne aşağıdaki izinler eklendi:
  - `<uses-permission android:name="android.permission.INTERNET"/>`
  - `<uses-permission android:name="android.permission.ACCESS_NETWORK_STATE"/>`
- Uygulamanın cihaz ana ekranındaki adı `android:label="futbol_skor_bulteni"` değerinden `android:label="Futbol Analiz"` değerine güncellendi.

### 2.2. APK Derleme Süreci (`flutter build apk --debug`)
- **Ortam Değişkeni:** Windows Türkçe kullanıcı dizini (`C:\Users\NAZİF AÇIKGÖZ`) kaynaklı Dart Native Assets / Pub önbellek kod sayfası sorunlarını engellemek üzere:
  ```powershell
  $env:PUB_CACHE = "E:\Users\nazif_acikgoz\AppData\Local\Pub\Cache"
  ```
- **Derleme Komutu:**
  ```powershell
  E:\Users\nazif_acikgoz\AppData\Local\develop\flutter\bin\flutter.bat build apk --debug
  ```
- **Çıktı Özeti:**
  - `Running Gradle task 'assembleDebug'... 1017,1s`
  - `√ Built build\app\outputs\flutter-apk\app-debug.apk` (`exit code 0`)

### 2.3. Derlenen APK Kanıt Bilgileri
| Özellik | Değer |
|---|---|
| **Tam Dosya Yolu** | `E:\apk\futbol\mobile\build\app\outputs\flutter-apk\app-debug.apk` |
| **Paket Kimliği (`applicationId`)** | `com.futbol.bulten.futbol_skor_bulteni` |
| **Sürüm (`versionName` / `versionCode`)** | `1.0.0` (`versionCode=1`, `minSdk=24`, `targetSdk=36`) |
| **Dosya Boyutu** | `161.596.861 bayt` (`154,11 MB`) |
| **Üretim Zaman Damgası** | `26.11.2026 20:01:45` |
| **SHA-256 Özeti** | `B8FCDA8BE371A0454118784197F28D9F893DC09E21A6961BE5633D3A0207AE1D` |

---

## 3. Fiziksel Cihaz Kurulumu ve Çalışma Zamanı Doğrulaması

### 3.1. Bağlı Cihaz Tespiti (`adb devices -l`)
```text
List of devices attached
VKVCX8EQBE9PAIXG       device product:warhol_global model:2602EPTC0G device:warhol transport_id:1
```

### 3.2. APK Kurulumu (`adb install -r`)
```text
Performing Streamed Install
Success
```
- Cihaz üzerindeki kurulu paket yolu:
  `package:/data/app/~~Al6AsMJf2fPE55Atl3ACpA==/com.futbol.bulten.futbol_skor_bulteni--ysItsNUNDbxiUr70WTWag==/base.apk`

### 3.3. İzin ve Başlatma (Smoke Test) Doğrulaması
- `adb shell dumpsys package com.futbol.bulten.futbol_skor_bulteni` çıktısı:
  - `android.permission.INTERNET: granted=true`
  - `android.permission.ACCESS_NETWORK_STATE: granted=true`
- `adb shell am start -n com.futbol.bulten.futbol_skor_bulteni/.MainActivity` ile uygulama fiziksel cihazda başlatıldı ve aktif süreç kimliği (`PID 6646`) doğrulandı.

---

## 4. Karşılaşılan Durumlar ve Çözümler

1. **İlk Gradle Derlemesinin Uzun Sürmesi (`1017,1s` / ~16,9 dk):**
   - **Sebep:** Projenin Android modülünde ilk kez APK derlendiği için Gradle 9.3.1 dağıtımı, Android SDK Build-Tools/Platform 36 ve NDK bileşenleri ilk kez indirildi ve önbelleklendi.
   - **Çözüm:** `java` süreçlerinin CPU/bellek kullanımı ve `mobile/build` altındaki anlık dosya üretimi kontrol edilerek sağlıklı ilerlediği doğrulandı; süreç kesilmeden tamamlanması beklendi. Önbellek oluştuğu için sonraki derlemeler çok daha kısa sürecektir.
2. **Türkçe Kullanıcı Profili (`PUB_CACHE`) Önlemi:**
   - **Sebep:** Windows kullanıcı klasöründeki Türkçe karakterlerin Dart paket yollarını bozması.
   - **Çözüm:** Derleme öncesinde `$env:PUB_CACHE = "E:\Users\nazif_acikgoz\AppData\Local\Pub\Cache"` tanımlanarak hatasız paket çözümü sağlandı.
