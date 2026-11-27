import 'package:intl/intl.dart';

import '../models/league_model.dart';

class AppConstants {
  const AppConstants._();

  static const String appTitle = '⚽ Futbol Skor & Analiz Bülteni';

  static String computeCurrentSeason([DateTime? date]) {
    final d = date ?? DateTime.now();
    return d.month >= 7 ? '${d.year}-${d.year + 1}' : '${d.year - 1}-${d.year}';
  }

  static String get defaultSeason => computeCurrentSeason();

  static const bool hasCustomApiUrl = bool.hasEnvironment('API_URL');

  static const String apiUrl = String.fromEnvironment(
    'API_URL',
    defaultValue: 'https://naziffarm4.github.io/futbol-skor-analiz/bulletin.json',
  );

  static const String apiBaseUrl = apiUrl;

  static const String statisticalDisclaimer =
      'İstatistiksel analiz amaçlıdır; kesin sonuç garantisi veya bahis tavsiyesi değildir.';

  static List<LeagueModel> get supportedLeagues {
    final season = defaultSeason;
    return <LeagueModel>[
      LeagueModel(
        id: 'super_lig',
        name: 'Süper Lig',
        country: 'Türkiye',
        flag: '🇹🇷',
        season: season,
      ),
      LeagueModel(
        id: 'premier_league',
        name: 'Premier League',
        country: 'İngiltere',
        flag: '🏴󠁧󠁢󠁥󠁮󠁧󠁿',
        season: season,
      ),
      LeagueModel(
        id: 'la_liga',
        name: 'La Liga',
        country: 'İspanya',
        flag: '🇪🇸',
        season: season,
      ),
      LeagueModel(
        id: 'ligue_1',
        name: 'Ligue 1',
        country: 'Fransa',
        flag: '🇫🇷',
        season: season,
      ),
    ];
  }

  static const List<String> _shortMonthsTr = [
    'Oca',
    'Şub',
    'Mar',
    'Nis',
    'May',
    'Haz',
    'Tem',
    'Ağu',
    'Eyl',
    'Eki',
    'Kas',
    'Ara',
  ];

  static String formatShortTimestampTr(DateTime? dateTime) {
    if (dateTime == null) return '';
    final local = dateTime.toLocal();
    final month = _shortMonthsTr[local.month - 1];
    final hour = local.hour.toString().padLeft(2, '0');
    final minute = local.minute.toString().padLeft(2, '0');
    return '${local.day} $month $hour:$minute';
  }

  static String formatMatchDateTime(DateTime dateTime) {
    final local = dateTime.toLocal();
    try {
      return DateFormat('d MMM EEE • HH:mm', 'tr_TR').format(local);
    } catch (_) {
      return DateFormat('dd.MM.yyyy • HH:mm').format(local);
    }
  }

  static String formatDetailDateTime(DateTime dateTime) {
    final local = dateTime.toLocal();
    try {
      return DateFormat('d MMMM yyyy, EEEE • HH:mm', 'tr_TR').format(local);
    } catch (_) {
      return DateFormat('dd.MM.yyyy • HH:mm').format(local);
    }
  }
}
