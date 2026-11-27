# GÖREV-06: Flutter Android APK Derleme, Optimizasyon ve Cihaz Kurulumu

## 1. Amaç ve Kapsam
Bu görevin amacı; `mobile/` dizininde başarıyla geliştirilen ve testleri geçen Flutter mobil uygulamasını:
1. Android platformu için internet erişim izinleri (`android.permission.INTERNET`) ve uygulama etiketiyle yapılandırmak,
2. Android APK paketini (`app-debug.apk` veya `app-release.apk`) derlemek,
3. ADB üzerinden bağlı fiziksel telefona yüklemek (`adb install`), cihaz bağlı değilse hazır APK dosyasını sunarak kurulum adımlarını tamamlamaktır.

---

## 2. Teknik Şartname

### A. Android Yapılandırması (`mobile/android/app/src/main/AndroidManifest.xml`)
- `<uses-permission android:name="android.permission.INTERNET"/>` izninin varlığı kontrol edilmeli ve yoksa eklenmelidir.
- `<uses-permission android:name="android.permission.ACCESS_NETWORK_STATE"/>` eklenmelidir.
- `android:label="Futbol Analiz"` olarak ayarlanmalıdır.

### B. APK Derleme Adımları
- Ortam gereksinimi: Türkçe karakterli Windows kullanıcı profili hatasını önlemek için:
  `$env:PUB_CACHE = "E:\Users\nazif_acikgoz\AppData\Local\Pub\Cache"`
- Flutter binary: `E:\Users\nazif_acikgoz\AppData\Local\develop\flutter\bin\flutter`
- Derleme komutu:
  `flutter build apk --debug`
  *(Not: Debug APK, fiziksel telefonda doğrudan çalışır, ek imzalama anahtarı gerektirmez ve çok hızlı derlenir).*
- Derlenen APK yolu: `mobile/build/app/outputs/flutter-apk/app-debug.apk`.

### C. Cihaza Kurulum ve Doğrulama
- `adb devices` çalıştırılarak bağlı Android cihaz kontrol edilir.
- Cihaz bağlı ve yetkilendirilmişse:
  `adb install -r mobile/build/app/outputs/flutter-apk/app-debug.apk`
- Cihaz bağlı değilse veya yetkilendirilmemişse:
  Kullanıcıya telefonunda **Geliştirici Seçenekleri -> USB Hata Ayıklama (USB Debugging)** özelliğini açması hatırlatılmalı ve derlenen APK'nın tam dosya yolu verilmelidir.

---

## 3. Doğrulama ve Raporlama Kriteri
- Derlemenin başarılı olduğu (`app-debug.apk` dosya boyutu ve zaman damgası) kanıtlanmalıdır.
- Cihaz durumu ve yükleme sonucu `tasks/GOREV-06-RAPOR.md` dosyasına kaydedilmelidir.
