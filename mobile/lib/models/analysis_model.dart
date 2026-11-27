class TeamAnalysisModel {
  final int id;
  final int matchId;
  final String matchOverviewText;
  final String htFtReasoningText;
  final String homeAnalysisText;
  final String awayAnalysisText;
  final double homeOffenseRating;
  final double homeDefenseRating;
  final double awayOffenseRating;
  final double awayDefenseRating;

  const TeamAnalysisModel({
    required this.id,
    required this.matchId,
    required this.matchOverviewText,
    this.htFtReasoningText = '',
    required this.homeAnalysisText,
    required this.awayAnalysisText,
    required this.homeOffenseRating,
    required this.homeDefenseRating,
    required this.awayOffenseRating,
    required this.awayDefenseRating,
  });

  factory TeamAnalysisModel.fromJson(Map<String, dynamic> json) {
    double clampRating(dynamic value) {
      final raw = (value as num?)?.toDouble() ?? 50.0;
      return raw.clamp(0.0, 100.0);
    }

    return TeamAnalysisModel(
      id: (json['id'] as num?)?.toInt() ?? 0,
      matchId: (json['match_id'] as num?)?.toInt() ?? 0,
      matchOverviewText: (json['match_overview_text'] ?? '').toString(),
      htFtReasoningText: (json['ht_ft_reasoning_text'] ?? '').toString(),
      homeAnalysisText: (json['home_analysis_text'] ?? '').toString(),
      awayAnalysisText: (json['away_analysis_text'] ?? '').toString(),
      homeOffenseRating: clampRating(json['home_offense_rating']),
      homeDefenseRating: clampRating(json['home_defense_rating']),
      awayOffenseRating: clampRating(json['away_offense_rating']),
      awayDefenseRating: clampRating(json['away_defense_rating']),
    );
  }
}
