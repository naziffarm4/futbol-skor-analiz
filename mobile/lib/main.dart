import 'package:flutter/material.dart';
import 'package:intl/date_symbol_data_local.dart';

import 'config/constants.dart';
import 'config/theme.dart';
import 'screens/home_screen.dart';
import 'services/bulletin_api_service.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await initializeDateFormatting('tr_TR', null);
  runApp(const FutbolBulteniApp());
}

class FutbolBulteniApp extends StatelessWidget {
  final BulletinApiService? service;

  const FutbolBulteniApp({super.key, this.service});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: AppConstants.appTitle,
      debugShowCheckedModeBanner: false,
      theme: AppTheme.darkTheme,
      darkTheme: AppTheme.darkTheme,
      themeMode: ThemeMode.dark,
      home: HomeScreen(service: service),
    );
  }
}
