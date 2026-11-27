import 'dart:convert';

class ScoreOption {
  final String score;
  final double probability;

  const ScoreOption({
    required this.score,
    required this.probability,
  });

  String get formattedScore {
    final parts = score.split('-');
    if (parts.length == 2) {
      return '${parts[0].trim()} - ${parts[1].trim()}';
    }
    return score;
  }

  /// Hem 0.0-1.0 hem de 0-100 ölçeğindeki olasılıkları yüzdeye (0-100) normalize eder.
  double get percentage => probability <= 1.0 ? probability * 100.0 : probability;

  String get formattedPercentage => '%${percentage.toStringAsFixed(1)}';

  factory ScoreOption.fromJson(Map<String, dynamic> json) {
    return ScoreOption(
      score: (json['score'] ?? '0-0').toString(),
      probability: (json['prob'] as num?)?.toDouble() ?? 0.0,
    );
  }
}

class HtFtOption {
  final String code;
  final String label;
  final double prob;

  const HtFtOption({
    required this.code,
    required this.label,
    required this.prob,
  });

  double get percentage => prob <= 1.0 ? prob * 100.0 : prob;

  String get percentText => '%${percentage.toStringAsFixed(1)}';

  static String _partLabelTr(String raw) {
    switch (raw.trim().toUpperCase()) {
      case '1':
        return 'Ev';
      case '2':
        return 'Deplasman';
      default:
        return 'Beraberlik';
    }
  }

  static String defaultLabelForCode(String code) {
    final parts = code.split('/');
    if (parts.length == 2) {
      return '${_partLabelTr(parts[0])} / ${_partLabelTr(parts[1])}';
    }
    return code;
  }

  factory HtFtOption.fromJson(Map<String, dynamic> json) {
    final rawCode = (json['code'] ?? 'X/X').toString().trim();
    final effectiveCode = rawCode.isEmpty ? 'X/X' : rawCode;
    final rawLabel = (json['label'] ?? '').toString().trim();
    return HtFtOption(
      code: effectiveCode,
      label: rawLabel.isEmpty ? defaultLabelForCode(effectiveCode) : rawLabel,
      prob: (json['prob'] as num?)?.toDouble() ?? 0.0,
    );
  }
}

class PredictionModel {
  final int id;
  final int matchId;
  final int predictedHtHomeScore;
  final int predictedHtAwayScore;
  final int predictedHomeScore;
  final int predictedAwayScore;
  final String htFtPrediction;
  final double confidenceRate;
  final List<ScoreOption> topScores;
  final List<HtFtOption> topHtFt;

  PredictionModel({
    required this.id,
    required this.matchId,
    this.predictedHtHomeScore = 0,
    this.predictedHtAwayScore = 0,
    required this.predictedHomeScore,
    required this.predictedAwayScore,
    String? htFtPrediction,
    required this.confidenceRate,
    required this.topScores,
    this.topHtFt = const <HtFtOption>[],
  }) : htFtPrediction =
            (htFtPrediction != null && htFtPrediction.trim().isNotEmpty)
                ? htFtPrediction.trim()
                : deriveHtFtCode(
                    predictedHtHomeScore,
                    predictedHtAwayScore,
                    predictedHomeScore,
                    predictedAwayScore,
                  );

  static String _outcomeCode(int home, int away) {
    if (home > away) return '1';
    if (home < away) return '2';
    return 'X';
  }

  static String deriveHtFtCode(
    int htHome,
    int htAway,
    int ftHome,
    int ftAway,
  ) {
    return '${_outcomeCode(htHome, htAway)}/${_outcomeCode(ftHome, ftAway)}';
  }

  String get formattedScore => '$predictedHomeScore - $predictedAwayScore';

  String get htScoreDisplay =>
      'İY $predictedHtHomeScore - $predictedHtAwayScore';

  String get ftScoreDisplay => 'MS $predictedHomeScore - $predictedAwayScore';

  String get compactHtFtBadge =>
      'İY $predictedHtHomeScore-$predictedHtAwayScore • İY/MS: $htFtPrediction';

  int get confidencePercentage {
    final normalized =
        confidenceRate <= 1.0 ? confidenceRate * 100.0 : confidenceRate;
    return normalized.round().clamp(0, 100);
  }

  String get confidenceLabel => 'Model Netliği: %$confidencePercentage';

  static List<T> _parseJsonList<T>(
    dynamic raw,
    T Function(Map<String, dynamic>) mapper,
  ) {
    final items = <T>[];
    dynamic source = raw;
    if (source is String && source.trim().isNotEmpty) {
      try {
        source = jsonDecode(source);
      } catch (_) {
        return items;
      }
    }
    if (source is List) {
      for (final item in source) {
        if (item is Map<String, dynamic>) {
          items.add(mapper(item));
        } else if (item is Map) {
          items.add(mapper(Map<String, dynamic>.from(item)));
        }
      }
    }
    return items;
  }

  factory PredictionModel.fromJson(Map<String, dynamic> json) {
    final parsedScores = _parseJsonList<ScoreOption>(
      json['top_scores_json'] ?? json['top_scores'],
      ScoreOption.fromJson,
    );
    final parsedHtFt = _parseJsonList<HtFtOption>(
      json['top_ht_ft_json'] ?? json['top_ht_ft'],
      HtFtOption.fromJson,
    );

    final htHome = (json['predicted_ht_home_score'] as num?)?.toInt() ?? 0;
    final htAway = (json['predicted_ht_away_score'] as num?)?.toInt() ?? 0;
    final ftHome = (json['predicted_home_score'] as num?)?.toInt() ?? 0;
    final ftAway = (json['predicted_away_score'] as num?)?.toInt() ?? 0;
    final rawHtFt = json['ht_ft_prediction']?.toString().trim() ?? '';

    return PredictionModel(
      id: (json['id'] as num?)?.toInt() ?? 0,
      matchId: (json['match_id'] as num?)?.toInt() ?? 0,
      predictedHtHomeScore: htHome,
      predictedHtAwayScore: htAway,
      predictedHomeScore: ftHome,
      predictedAwayScore: ftAway,
      htFtPrediction: rawHtFt.isEmpty
          ? deriveHtFtCode(htHome, htAway, ftHome, ftAway)
          : rawHtFt,
      confidenceRate: (json['confidence_rate'] as num?)?.toDouble() ?? 0.0,
      topScores: parsedScores.take(3).toList(),
      topHtFt: parsedHtFt.take(3).toList(),
    );
  }
}
