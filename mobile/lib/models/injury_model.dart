enum PlayerPosition {
  gk('GK', 'Kaleci'),
  def('DEF', 'Defans'),
  mid('MID', 'Orta Saha'),
  fw('FW', 'Forvet');

  final String code;
  final String labelTr;
  const PlayerPosition(this.code, this.labelTr);

  static PlayerPosition fromCode(String? raw) {
    final normalized = (raw ?? '').trim().toUpperCase();
    for (final item in PlayerPosition.values) {
      if (item.code == normalized) return item;
    }
    return PlayerPosition.mid;
  }
}

enum ImpactLevel {
  high('HIGH', 'Yüksek Etki'),
  medium('MEDIUM', 'Orta Etki'),
  low('LOW', 'Düşük Etki');

  final String code;
  final String labelTr;
  const ImpactLevel(this.code, this.labelTr);

  static ImpactLevel fromCode(String? raw) {
    final normalized = (raw ?? '').trim().toUpperCase();
    for (final item in ImpactLevel.values) {
      if (item.code == normalized) return item;
    }
    return ImpactLevel.medium;
  }
}

class InjuryModel {
  final int id;
  final int teamId;
  final String playerName;
  final PlayerPosition position;
  final String reason;
  final String? returnDate;
  final ImpactLevel impactLevel;
  final bool verifiedByMultipleSources;
  final List<String> sources;

  const InjuryModel({
    required this.id,
    required this.teamId,
    required this.playerName,
    required this.position,
    required this.reason,
    this.returnDate,
    required this.impactLevel,
    this.verifiedByMultipleSources = false,
    this.sources = const <String>[],
  });

  String get formattedReturnDate {
    final value = returnDate?.trim();
    if (value == null || value.isEmpty) return 'Belirsiz';
    return value;
  }

  static List<String> _parseSources(dynamic raw) {
    if (raw is! List) return const <String>[];
    return raw
        .map((item) => item?.toString().trim() ?? '')
        .where((s) => s.isNotEmpty)
        .toList();
  }

  factory InjuryModel.fromJson(Map<String, dynamic> json) {
    final parsedSources = _parseSources(json['sources']);
    final rawVerified = json['verified_by_multiple_sources'];
    final verified = rawVerified is bool
        ? rawVerified
        : parsedSources.length >= 2;

    return InjuryModel(
      id: (json['id'] as num?)?.toInt() ?? 0,
      teamId: (json['team_id'] as num?)?.toInt() ?? 0,
      playerName: (json['player_name'] ?? '').toString(),
      position: PlayerPosition.fromCode(json['position']?.toString()),
      reason: (json['reason'] ?? 'Sakatlık').toString(),
      returnDate: json['return_date']?.toString(),
      impactLevel: ImpactLevel.fromCode(json['impact_level']?.toString()),
      verifiedByMultipleSources: verified,
      sources: parsedSources,
    );
  }
}
