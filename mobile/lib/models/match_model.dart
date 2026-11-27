import 'package:flutter/material.dart';

import 'analysis_model.dart';
import 'injury_model.dart';
import 'prediction_model.dart';

class TeamInfo {
  final int id;
  final String leagueId;
  final String name;
  final String shortName;
  final String? logoUrl;
  final Color badgeColor;

  const TeamInfo({
    required this.id,
    required this.leagueId,
    required this.name,
    required this.shortName,
    this.logoUrl,
    required this.badgeColor,
  });

  String get initials {
    final trimmed = shortName.trim();
    if (trimmed.isNotEmpty && trimmed.length <= 3) {
      return trimmed.toUpperCase();
    }
    final words = name
        .trim()
        .split(RegExp(r'\s+'))
        .where((w) => w.isNotEmpty)
        .toList();
    if (words.length >= 2) {
      return '${words[0][0]}${words[1][0]}'.toUpperCase();
    }
    if (words.length == 1 && words[0].length >= 2) {
      return words[0].substring(0, 2).toUpperCase();
    }
    return 'FC';
  }

  static Color _colorFromName(String seed) {
    const palette = <Color>[
      Color(0xFFE53935),
      Color(0xFF1E88E5),
      Color(0xFF00ACC1),
      Color(0xFF43A047),
      Color(0xFFFB8C00),
      Color(0xFF8E24AA),
      Color(0xFFD81B60),
      Color(0xFF3949AB),
    ];
    final hash = seed.codeUnits.fold<int>(0, (acc, c) => acc + c * 31);
    return palette[hash.abs() % palette.length];
  }

  factory TeamInfo.fromJson(Map<String, dynamic> json) {
    final name = (json['name'] ?? 'Takım').toString();
    final shortRaw = json['short_name']?.toString().trim();
    return TeamInfo(
      id: (json['id'] as num?)?.toInt() ?? 0,
      leagueId: (json['league_id'] ?? '').toString(),
      name: name,
      shortName: (shortRaw != null && shortRaw.isNotEmpty) ? shortRaw : name,
      logoUrl: json['logo_url']?.toString(),
      badgeColor: _colorFromName(name),
    );
  }
}

class MatchModel {
  final int id;
  final String leagueId;
  final int round;
  final DateTime matchDate;
  final String status;
  final TeamInfo homeTeam;
  final TeamInfo awayTeam;
  final PredictionModel prediction;
  final TeamAnalysisModel analysis;
  final List<InjuryModel> homeInjuries;
  final List<InjuryModel> awayInjuries;

  const MatchModel({
    required this.id,
    required this.leagueId,
    required this.round,
    required this.matchDate,
    this.status = 'SCHEDULED',
    required this.homeTeam,
    required this.awayTeam,
    required this.prediction,
    required this.analysis,
    this.homeInjuries = const [],
    this.awayInjuries = const [],
  });

  int get totalMissingPlayers => homeInjuries.length + awayInjuries.length;

  static Map<String, dynamic> _asMap(dynamic raw) {
    if (raw is Map<String, dynamic>) return raw;
    if (raw is Map) return Map<String, dynamic>.from(raw);
    return const <String, dynamic>{};
  }

  static List<InjuryModel> _parseInjuries(dynamic raw) {
    if (raw is! List) return const <InjuryModel>[];
    final items = <InjuryModel>[];
    for (final entry in raw) {
      if (entry is Map<String, dynamic>) {
        items.add(InjuryModel.fromJson(entry));
      } else if (entry is Map) {
        items.add(InjuryModel.fromJson(Map<String, dynamic>.from(entry)));
      }
    }
    return items;
  }

  factory MatchModel.fromJson(Map<String, dynamic> json) {
    return MatchModel(
      id: (json['id'] as num?)?.toInt() ?? 0,
      leagueId: (json['league_id'] ?? '').toString(),
      round: (json['round'] as num?)?.toInt() ?? 1,
      matchDate: DateTime.tryParse((json['match_date'] ?? '').toString()) ??
          DateTime.fromMillisecondsSinceEpoch(0, isUtc: true),
      status: (json['status'] ?? 'SCHEDULED').toString(),
      homeTeam: TeamInfo.fromJson(_asMap(json['home_team'])),
      awayTeam: TeamInfo.fromJson(_asMap(json['away_team'])),
      prediction: PredictionModel.fromJson(_asMap(json['prediction'])),
      analysis: TeamAnalysisModel.fromJson(
        _asMap(json['team_analysis'] ?? json['analysis']),
      ),
      homeInjuries: _parseInjuries(json['home_injuries']),
      awayInjuries: _parseInjuries(json['away_injuries']),
    );
  }
}
