import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

class AppColors {
  const AppColors._();

  // Lacivert / füme zemin katmanları (FotMob / SofaScore stili)
  static const Color background = Color(0xFF0B1120);
  static const Color surface = Color(0xFF121B2E);
  static const Color card = Color(0xFF18243C);
  static const Color cardElevated = Color(0xFF1F2F4D);
  static const Color border = Color(0xFF2A3C61);

  // Neon vurgu renkleri
  static const Color neonGreen = Color(0xFF00E676);
  static const Color neonOrange = Color(0xFFFF9100);
  static const Color neonBlue = Color(0xFF00B0FF);
  static const Color coralRed = Color(0xFFFF5252);
  static const Color neutralBar = Color(0xFF64748B);

  // Tipografi renkleri
  static const Color textPrimary = Color(0xFFF8FAFC);
  static const Color textSecondary = Color(0xFF94A3B8);
  static const Color textMuted = Color(0xFF64748B);
}

class AppTheme {
  const AppTheme._();

  static ThemeData get darkTheme {
    final base = ThemeData(
      useMaterial3: true,
      brightness: Brightness.dark,
      scaffoldBackgroundColor: AppColors.background,
      colorScheme: const ColorScheme.dark(
        primary: AppColors.neonGreen,
        secondary: AppColors.neonBlue,
        tertiary: AppColors.neonOrange,
        surface: AppColors.surface,
        error: AppColors.coralRed,
        onPrimary: Color(0xFF04130B),
        onSecondary: Color(0xFF041524),
        onSurface: AppColors.textPrimary,
      ),
    );

    final textTheme = GoogleFonts.interTextTheme(base.textTheme).apply(
      bodyColor: AppColors.textPrimary,
      displayColor: AppColors.textPrimary,
    );

    return base.copyWith(
      textTheme: textTheme,
      appBarTheme: AppBarTheme(
        backgroundColor: AppColors.surface,
        foregroundColor: AppColors.textPrimary,
        elevation: 0,
        centerTitle: false,
        surfaceTintColor: Colors.transparent,
        titleTextStyle: textTheme.titleLarge?.copyWith(
          fontWeight: FontWeight.w700,
          color: AppColors.textPrimary,
          letterSpacing: -0.3,
        ),
      ),
      cardTheme: CardThemeData(
        color: AppColors.card,
        elevation: 0,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(16),
          side: const BorderSide(color: AppColors.border, width: 1),
        ),
      ),
      tabBarTheme: TabBarThemeData(
        labelColor: AppColors.neonGreen,
        unselectedLabelColor: AppColors.textSecondary,
        indicatorColor: AppColors.neonGreen,
        dividerColor: AppColors.border,
        labelStyle: textTheme.labelLarge?.copyWith(
          fontWeight: FontWeight.w700,
        ),
        unselectedLabelStyle: textTheme.labelLarge?.copyWith(
          fontWeight: FontWeight.w500,
        ),
      ),
      dividerColor: AppColors.border,
    );
  }
}
