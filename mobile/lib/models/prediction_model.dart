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

  String get roundedPercentText => '%${percentage.round()}';

  static String normalizeCode(String raw) {
    final cleaned = raw.trim().toUpperCase();
    if (cleaned.isEmpty) return 'X/X';
    final parts = cleaned.split('/');
    if (parts.length == 2) {
      String normPart(String p) {
        final t = p.trim();
        if (t == '1' || t == '2') return t;
        return 'X';
      }

      return '${normPart(parts[0])}/${normPart(parts[1])}';
    }
    return cleaned;
  }

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
    final effectiveCode = normalizeCode((json['code'] ?? 'X/X').toString());
    final rawLabel = (json['label'] ?? '').toString().trim();
    return HtFtOption(
      code: effectiveCode,
      label: rawLabel.isEmpty ? defaultLabelForCode(effectiveCode) : rawLabel,
      prob: (json['prob'] as num?)?.toDouble() ?? 0.0,
    );
  }
}

class PredictionModel {
  static const List<String> canonicalHtFtCodes = <String>[
    '1/1',
    'X/1',
    '2/1',
    '1/X',
    'X/X',
    '2/X',
    '1/2',
    'X/2',
    '2/2',
  ];

  static const Map<String, double> _priorWeights = <String, double>{
    '1/1': 2.0,
    'X/1': 1.5,
    '2/1': 0.6,
    '1/X': 1.5,
    'X/X': 2.0,
    '2/X': 1.5,
    '1/2': 0.6,
    'X/2': 1.5,
    '2/2': 2.0,
  };

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
  final List<HtFtOption> allHtFt;
  final double pHome;
  final double pDraw;
  final double pAway;
  final double pOver25;
  final double pUnder25;
  final double pBttsYes;
  final double pBttsNo;
  final bool marketBlended;

  factory PredictionModel({
    required int id,
    required int matchId,
    int predictedHtHomeScore = 0,
    int predictedHtAwayScore = 0,
    required int predictedHomeScore,
    required int predictedAwayScore,
    String? htFtPrediction,
    required double confidenceRate,
    required List<ScoreOption> topScores,
    List<HtFtOption> topHtFt = const <HtFtOption>[],
    List<HtFtOption> allHtFt = const <HtFtOption>[],
    double? pHome,
    double? pDraw,
    double? pAway,
    double? pOver25,
    double? pUnder25,
    double? pBttsYes,
    double? pBttsNo,
    bool marketBlended = false,
  }) {
    final resolvedHtFt =
        (htFtPrediction != null && htFtPrediction.trim().isNotEmpty)
            ? HtFtOption.normalizeCode(htFtPrediction)
            : deriveHtFtCode(
                predictedHtHomeScore,
                predictedHtAwayScore,
                predictedHomeScore,
                predictedAwayScore,
              );
    final completeAllHtFt = _buildCompleteHtFt(
      rawAllHtFt: allHtFt,
      rawTopHtFt: topHtFt,
      htFtCode: resolvedHtFt,
      ftHome: predictedHomeScore,
      ftAway: predictedAwayScore,
      rawPHome: pHome,
      rawPDraw: pDraw,
      rawPAway: pAway,
    );
    final probs1X2 = _resolve1X2(pHome, pDraw, pAway, completeAllHtFt);
    final probsOu = _resolveBinaryPair(
      pOver25,
      pUnder25,
      _heuristicOver25(predictedHomeScore, predictedAwayScore),
    );
    final probsBtts = _resolveBinaryPair(
      pBttsYes,
      pBttsNo,
      _heuristicBttsYes(predictedHomeScore, predictedAwayScore),
    );
    return PredictionModel._(
      id: id,
      matchId: matchId,
      predictedHtHomeScore: predictedHtHomeScore,
      predictedHtAwayScore: predictedHtAwayScore,
      predictedHomeScore: predictedHomeScore,
      predictedAwayScore: predictedAwayScore,
      htFtPrediction: resolvedHtFt,
      confidenceRate: confidenceRate,
      topScores: List<ScoreOption>.unmodifiable(topScores),
      topHtFt: _resolveTopHtFt(
        rawTopHtFt: topHtFt,
        completeAllHtFt: completeAllHtFt,
      ),
      allHtFt: completeAllHtFt,
      pHome: probs1X2.$1,
      pDraw: probs1X2.$2,
      pAway: probs1X2.$3,
      pOver25: probsOu.$1,
      pUnder25: probsOu.$2,
      pBttsYes: probsBtts.$1,
      pBttsNo: probsBtts.$2,
      marketBlended: marketBlended,
    );
  }

  const PredictionModel._({
    required this.id,
    required this.matchId,
    required this.predictedHtHomeScore,
    required this.predictedHtAwayScore,
    required this.predictedHomeScore,
    required this.predictedAwayScore,
    required this.htFtPrediction,
    required this.confidenceRate,
    required this.topScores,
    required this.topHtFt,
    required this.allHtFt,
    required this.pHome,
    required this.pDraw,
    required this.pAway,
    required this.pOver25,
    required this.pUnder25,
    required this.pBttsYes,
    required this.pBttsNo,
    required this.marketBlended,
  });

  static double _normalizeUnitProb(num? raw) {
    if (raw == null) return 0.0;
    final v = raw.toDouble();
    if (v.isNaN || v.isInfinite || v <= 0.0) return 0.0;
    return (v > 1.0 ? v / 100.0 : v).clamp(0.0, 1.0);
  }

  static (double, double, double) _scoreHeuristic1X2(int ftHome, int ftAway) {
    if (ftHome > ftAway) {
      final diff = (ftHome - ftAway).clamp(1, 3);
      final h = (0.46 + 0.07 * diff).clamp(0.48, 0.68);
      final d = (0.28 - 0.03 * diff).clamp(0.18, 0.26);
      return (h, d, (1.0 - h - d).clamp(0.08, 0.34));
    }
    if (ftHome < ftAway) {
      final diff = (ftAway - ftHome).clamp(1, 3);
      final a = (0.46 + 0.07 * diff).clamp(0.48, 0.68);
      final d = (0.28 - 0.03 * diff).clamp(0.18, 0.26);
      return ((1.0 - a - d).clamp(0.08, 0.34), d, a);
    }
    return (0.34, 0.36, 0.30);
  }

  static double _heuristicOver25(int ftHome, int ftAway) {
    final goals = ftHome + ftAway;
    if (goals >= 4) return 0.68;
    if (goals == 3) return 0.58;
    if (goals == 2) return 0.44;
    if (goals == 1) return 0.34;
    return 0.26;
  }

  static double _heuristicBttsYes(int ftHome, int ftAway) {
    if (ftHome >= 1 && ftAway >= 1) {
      return (ftHome + ftAway >= 4) ? 0.64 : 0.56;
    }
    return (ftHome + ftAway >= 2) ? 0.42 : 0.35;
  }

  static (double, double) _resolveBinaryPair(
    double? primaryRaw,
    double? complementRaw,
    double heuristicPrimary,
  ) {
    final hasPrimary = primaryRaw != null;
    final hasComplement = complementRaw != null;
    final p = _normalizeUnitProb(primaryRaw);
    final c = _normalizeUnitProb(complementRaw);

    if (hasPrimary && hasComplement && (p + c) > 0.001) {
      final sum = p + c;
      return (p / sum, c / sum);
    }
    if (hasPrimary && p > 0.0) {
      return (p, (1.0 - p).clamp(0.0, 1.0));
    }
    if (hasComplement && c > 0.0) {
      return ((1.0 - c).clamp(0.0, 1.0), c);
    }
    final fallback = heuristicPrimary.clamp(0.0, 1.0);
    return (fallback, (1.0 - fallback).clamp(0.0, 1.0));
  }

  static List<HtFtOption> _buildCompleteHtFt({
    required List<HtFtOption> rawAllHtFt,
    required List<HtFtOption> rawTopHtFt,
    required String htFtCode,
    required int ftHome,
    required int ftAway,
    required double? rawPHome,
    required double? rawPDraw,
    required double? rawPAway,
  }) {
    final byCode = <String, HtFtOption>{};
    for (final item in rawTopHtFt) {
      final code = HtFtOption.normalizeCode(item.code);
      if (canonicalHtFtCodes.contains(code)) {
        byCode[code] = HtFtOption(
          code: code,
          label: item.label.trim().isEmpty
              ? HtFtOption.defaultLabelForCode(code)
              : item.label,
          prob: _normalizeUnitProb(item.prob),
        );
      }
    }
    for (final item in rawAllHtFt) {
      final code = HtFtOption.normalizeCode(item.code);
      if (canonicalHtFtCodes.contains(code)) {
        byCode[code] = HtFtOption(
          code: code,
          label: item.label.trim().isEmpty
              ? HtFtOption.defaultLabelForCode(code)
              : item.label,
          prob: _normalizeUnitProb(item.prob),
        );
      }
    }

    if (byCode.isEmpty) {
      final h = _normalizeUnitProb(rawPHome);
      final d = _normalizeUnitProb(rawPDraw);
      final a = _normalizeUnitProb(rawPAway);
      final (ft1, ftX, ft2) = (h + d + a) > 0.001
          ? (h / (h + d + a), d / (h + d + a), a / (h + d + a))
          : _scoreHeuristic1X2(ftHome, ftAway);

      final ftProbs = <String, double>{'1': ft1, 'X': ftX, '2': ft2};
      for (final ft in const <String>['1', 'X', '2']) {
        final colTotal = ftProbs[ft]!;
        final weights = <String, double>{
          for (final ht in const <String>['1', 'X', '2'])
            '$ht/$ft': ('$ht/$ft' == htFtCode)
                ? 3.2
                : (_priorWeights['$ht/$ft'] ?? 1.0),
        };
        final weightSum = weights.values.fold<double>(0.0, (s, w) => s + w);
        for (final entry in weights.entries) {
          byCode[entry.key] = HtFtOption(
            code: entry.key,
            label: HtFtOption.defaultLabelForCode(entry.key),
            prob: colTotal * (entry.value / weightSum),
          );
        }
      }
    } else if (byCode.length < canonicalHtFtCodes.length) {
      final knownSum =
          byCode.values.fold<double>(0.0, (sum, item) => sum + item.prob);
      final remaining = (1.0 - knownSum).clamp(0.0, 1.0);
      final missingCodes = canonicalHtFtCodes
          .where((code) => !byCode.containsKey(code))
          .toList();
      final totalWeight = missingCodes.fold<double>(
        0.0,
        (sum, code) => sum + (_priorWeights[code] ?? 1.0),
      );
      for (final code in missingCodes) {
        final share = totalWeight > 0
            ? remaining * ((_priorWeights[code] ?? 1.0) / totalWeight)
            : 0.0;
        byCode[code] = HtFtOption(
          code: code,
          label: HtFtOption.defaultLabelForCode(code),
          prob: share,
        );
      }
    }

    final result = <HtFtOption>[
      for (final code in canonicalHtFtCodes) byCode[code]!,
    ]..sort((a, b) => b.prob.compareTo(a.prob));
    return List<HtFtOption>.unmodifiable(result);
  }

  static List<HtFtOption> _resolveTopHtFt({
    required List<HtFtOption> rawTopHtFt,
    required List<HtFtOption> completeAllHtFt,
  }) {
    if (rawTopHtFt.isNotEmpty) {
      return List<HtFtOption>.unmodifiable(rawTopHtFt.take(3));
    }
    return List<HtFtOption>.unmodifiable(completeAllHtFt.take(3));
  }

  static (double, double, double) _resolve1X2(
    double? rawPHome,
    double? rawPDraw,
    double? rawPAway,
    List<HtFtOption> completeAllHtFt,
  ) {
    final h = _normalizeUnitProb(rawPHome);
    final d = _normalizeUnitProb(rawPDraw);
    final a = _normalizeUnitProb(rawPAway);
    final sum = h + d + a;
    if (sum > 0.001) {
      return (h / sum, d / sum, a / sum);
    }

    var ftHomeSum = 0.0;
    var ftDrawSum = 0.0;
    var ftAwaySum = 0.0;
    for (final item in completeAllHtFt) {
      if (item.code.endsWith('/1')) {
        ftHomeSum += item.prob;
      } else if (item.code.endsWith('/X')) {
        ftDrawSum += item.prob;
      } else if (item.code.endsWith('/2')) {
        ftAwaySum += item.prob;
      }
    }
    final derivedSum = ftHomeSum + ftDrawSum + ftAwaySum;
    if (derivedSum > 0.001) {
      return (
        ftHomeSum / derivedSum,
        ftDrawSum / derivedSum,
        ftAwaySum / derivedSum,
      );
    }
    return (0.34, 0.33, 0.33);
  }

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

  static String formatPercent1(double unitProb) {
    final pct = unitProb <= 1.0 ? unitProb * 100.0 : unitProb;
    return '%${pct.toStringAsFixed(1)}';
  }

  static String formatPercentInt(double unitProb) {
    final pct = unitProb <= 1.0 ? unitProb * 100.0 : unitProb;
    return '%${pct.round()}';
  }

  HtFtOption get bestHtFt {
    if (allHtFt.isEmpty) {
      return HtFtOption(
        code: htFtPrediction,
        label: HtFtOption.defaultLabelForCode(htFtPrediction),
        prob: 0.0,
      );
    }
    return allHtFt.reduce((a, b) => a.prob >= b.prob ? a : b);
  }

  HtFtOption htFtOptionFor(String code) {
    final normalized = HtFtOption.normalizeCode(code);
    for (final item in allHtFt) {
      if (item.code == normalized) return item;
    }
    return HtFtOption(
      code: normalized,
      label: HtFtOption.defaultLabelForCode(normalized),
      prob: 0.0,
    );
  }

  HtFtOption htFtProbFor(String code) => htFtOptionFor(code);

  String get formattedScore => '$predictedHomeScore - $predictedAwayScore';

  String get htScoreDisplay =>
      'İY $predictedHtHomeScore - $predictedHtAwayScore';

  String get ftScoreDisplay => 'MS $predictedHomeScore - $predictedAwayScore';

  String get compactHtFtBadge =>
      'İY $predictedHtHomeScore-$predictedHtAwayScore • İY/MS: $htFtPrediction';

  String get pHomeText => formatPercent1(pHome);
  String get pDrawText => formatPercent1(pDraw);
  String get pAwayText => formatPercent1(pAway);

  String get pHomeShort => formatPercentInt(pHome);
  String get pDrawShort => formatPercentInt(pDraw);
  String get pAwayShort => formatPercentInt(pAway);

  String get pOver25Text => formatPercent1(pOver25);
  String get pUnder25Text => formatPercent1(pUnder25);
  String get pBttsYesText => formatPercent1(pBttsYes);
  String get pBttsNoText => formatPercent1(pBttsNo);

  String get bestHtFtBadge =>
      'İY/MS ${bestHtFt.code} ${bestHtFt.roundedPercentText}';

  String get compactProbSummary =>
      '$bestHtFtBadge • 1:$pHomeShort X:$pDrawShort 2:$pAwayShort';

  int get confidencePercentage {
    final normalized =
        confidenceRate <= 1.0 ? confidenceRate * 100.0 : confidenceRate;
    return normalized.round().clamp(0, 100);
  }

  String get confidenceLabel => 'Model Netliği: %$confidencePercentage';

  static bool _parseBool(dynamic value) {
    if (value is bool) return value;
    if (value is num) return value != 0;
    if (value is String) return value.trim().toLowerCase() == 'true';
    return false;
  }

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
    final parsedAllHtFt = _parseJsonList<HtFtOption>(
      json['all_ht_ft_json'] ?? json['all_ht_ft'],
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
      allHtFt: parsedAllHtFt,
      pHome: (json['p_home'] as num?)?.toDouble(),
      pDraw: (json['p_draw'] as num?)?.toDouble(),
      pAway: (json['p_away'] as num?)?.toDouble(),
      pOver25: (json['p_over25'] as num?)?.toDouble(),
      pUnder25: (json['p_under25'] as num?)?.toDouble(),
      pBttsYes: (json['p_btts_yes'] as num?)?.toDouble(),
      pBttsNo: (json['p_btts_no'] as num?)?.toDouble(),
      marketBlended: _parseBool(json['market_blended']),
    );
  }
}
