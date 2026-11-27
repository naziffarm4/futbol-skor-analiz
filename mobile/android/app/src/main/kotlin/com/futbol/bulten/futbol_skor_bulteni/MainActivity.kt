package com.futbol.bulten.futbol_skor_bulteni

import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "com.futbol.bulten/storage")
            .setMethodCallHandler { call, result ->
                if (call.method == "getFilesDir") result.success(filesDir.absolutePath)
                else result.notImplemented()
            }
    }
}
