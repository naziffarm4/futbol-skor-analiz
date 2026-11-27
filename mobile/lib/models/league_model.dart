import '../config/constants.dart';

class LeagueModel {
  final String id;
  final String name;
  final String country;
  final String flag;
  final String season;
  final List<String> sourcesUsed;
  final int sourcesCount;
  final int sourcesTotal;

  const LeagueModel({
    required this.id,
    required this.name,
    required this.country,
    required this.flag,
    required this.season,
    this.sourcesUsed = const <String>[],
    this.sourcesCount = 0,
    this.sourcesTotal = 5,
  });

  String get tabTitle => '$flag $name';

  static List<String> _parseSources(dynamic raw) {
    if (raw is! List) return const <String>[];
    return raw
        .map((item) => item?.toString().trim() ?? '')
        .where((s) => s.isNotEmpty)
        .toList();
  }

  factory LeagueModel.fromJson(Map<String, dynamic> json, {String flag = '⚽'}) {
    final rawSeason = json['season']?.toString().trim() ?? '';
    final parsedSources = _parseSources(json['sources_used']);
    final rawCount = (json['sources_count'] as num?)?.toInt();
    final rawTotal = (json['sources_total'] as num?)?.toInt();

    return LeagueModel(
      id: (json['id'] ?? '').toString(),
      name: (json['name'] ?? '').toString(),
      country: (json['country'] ?? '').toString(),
      flag: (json['flag'] ?? flag).toString(),
      season: rawSeason.isEmpty ? AppConstants.defaultSeason : rawSeason,
      sourcesUsed: parsedSources,
      sourcesCount:
          rawCount != null ? (rawCount < 0 ? 0 : rawCount) : parsedSources.length,
      sourcesTotal: (rawTotal != null && rawTotal > 0) ? rawTotal : 5,
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'name': name,
        'country': country,
        'flag': flag,
        'season': season,
        'sources_used': sourcesUsed,
        'sources_count': sourcesCount,
        'sources_total': sourcesTotal,
      };
}
