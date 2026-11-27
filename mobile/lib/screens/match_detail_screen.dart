import 'package:flutter/material.dart';

import '../config/constants.dart';
import '../config/theme.dart';
import '../models/league_model.dart';
import '../models/match_model.dart';
import '../widgets/analysis_section.dart';
import '../widgets/data_transparency_banner.dart';
import '../widgets/injuries_list.dart';
import '../widgets/match_card.dart';
import '../widgets/rating_comparison_bar.dart';
import '../widgets/score_probability_bar.dart';

class MatchDetailScreen extends StatelessWidget {
  final MatchModel match;
  final LeagueModel league;
  final String dataSource;
  final List<String> sourcesUsed;
  final int sourcesCount;
  final int sourcesTotal;
  final String? season;
  final DateTime? generatedAt;
  final int playedMatchesCount;
  final int injuriesCount;

  const MatchDetailScreen({
    super.key,
    required this.match,
    required this.league,
    this.dataSource = 'Transfermarkt',
    this.sourcesUsed = const <String>[],
    this.sourcesCount = 0,
    this.sourcesTotal = 5,
    this.season,
    this.generatedAt,
    this.playedMatchesCount = 0,
    this.injuriesCount = 0,
  });

  @override
  Widget build(BuildContext context) {
    final effectiveSources =
        sourcesUsed.isNotEmpty ? sourcesUsed : league.sourcesUsed;
    final effectiveSourcesCount =
        sourcesCount > 0 ? sourcesCount : league.sourcesCount;
    final effectiveSourcesTotal =
        sourcesTotal > 0 ? sourcesTotal : league.sourcesTotal;
    final effectiveInjuries =
        injuriesCount > 0 ? injuriesCount : match.totalMissingPlayers;

    return Scaffold(
      appBar: AppBar(
        title: Text('${league.flag} ${league.name} • ${match.round}. Hafta'),
      ),
      body: SingleChildScrollView(
        key: const ValueKey('match_detail_scroll'),
        padding: const EdgeInsets.fromLTRB(16, 16, 16, 32),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            _HeroMatchBanner(match: match),
            const SizedBox(height: 16),
            MatchOutcomeSummaryCard(prediction: match.prediction),
            const SizedBox(height: 16),
            ScoreProbabilityBar(topScores: match.prediction.topScores),
            if (match.prediction.topHtFt.isNotEmpty ||
                match.prediction.allHtFt.isNotEmpty) ...[
              const SizedBox(height: 16),
              HtFtProbabilityBar(
                topHtFt: match.prediction.topHtFt,
                allHtFt: match.prediction.allHtFt,
                highlightedCode: match.prediction.htFtPrediction,
              ),
            ],
            const SizedBox(height: 18),
            AnalysisSection(
              homeTeamName: match.homeTeam.name,
              awayTeamName: match.awayTeam.name,
              analysis: match.analysis,
              prediction: match.prediction,
              homeMissingCount: match.homeInjuries.length,
              awayMissingCount: match.awayInjuries.length,
            ),
            const SizedBox(height: 18),
            RatingComparisonBar(
              homeTeamName: match.homeTeam.name,
              awayTeamName: match.awayTeam.name,
              analysis: match.analysis,
            ),
            const SizedBox(height: 18),
            InjuriesList(
              homeTeamName: match.homeTeam.name,
              awayTeamName: match.awayTeam.name,
              homeInjuries: match.homeInjuries,
              awayInjuries: match.awayInjuries,
            ),
            const SizedBox(height: 18),
            DataTransparencyBanner(
              key: const ValueKey('detail_transparency_banner'),
              dataSource: dataSource,
              sourcesUsed: effectiveSources,
              sourcesCount: effectiveSourcesCount,
              sourcesTotal: effectiveSourcesTotal,
              season: season ?? league.season,
              generatedAt: generatedAt,
              playedMatchesCount: playedMatchesCount,
              injuriesCount: effectiveInjuries,
              isCard: true,
            ),
          ],
        ),
      ),
    );
  }
}

class _HeroMatchBanner extends StatelessWidget {
  final MatchModel match;

  const _HeroMatchBanner({required this.match});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 18),
      decoration: BoxDecoration(
        gradient: const LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [
            AppColors.cardElevated,
            AppColors.surface,
          ],
        ),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: AppColors.border, width: 1.2),
      ),
      child: Column(
        children: [
          Text(
            AppConstants.formatDetailDateTime(match.matchDate),
            textAlign: TextAlign.center,
            style: const TextStyle(
              color: AppColors.textSecondary,
              fontSize: 12.5,
              fontWeight: FontWeight.w600,
            ),
          ),
          const SizedBox(height: 16),
          Row(
            children: [
              Expanded(
                child: Column(
                  children: [
                    TeamBadge(team: match.homeTeam, size: 52),
                    const SizedBox(height: 8),
                    Text(
                      match.homeTeam.name,
                      textAlign: TextAlign.center,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        color: AppColors.textPrimary,
                        fontSize: 14.5,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                    const SizedBox(height: 2),
                    const Text(
                      'Ev Sahibi',
                      style: TextStyle(
                        color: AppColors.textMuted,
                        fontSize: 11,
                      ),
                    ),
                  ],
                ),
              ),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 8),
                child: Column(
                  children: [
                    const Text(
                      'ANA SKOR TAHMİNİ',
                      style: TextStyle(
                        color: AppColors.neonGreen,
                        fontSize: 9.5,
                        fontWeight: FontWeight.w800,
                        letterSpacing: 0.9,
                      ),
                    ),
                    const SizedBox(height: 6),
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 18,
                        vertical: 10,
                      ),
                      decoration: BoxDecoration(
                        color: AppColors.neonGreen.withValues(alpha: 0.14),
                        borderRadius: BorderRadius.circular(14),
                        border: Border.all(
                          color: AppColors.neonGreen,
                          width: 1.6,
                        ),
                      ),
                      child: Text(
                        match.prediction.formattedScore,
                        style: const TextStyle(
                          color: AppColors.neonGreen,
                          fontSize: 26,
                          fontWeight: FontWeight.w900,
                          letterSpacing: 1.4,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              Expanded(
                child: Column(
                  children: [
                    TeamBadge(team: match.awayTeam, size: 52),
                    const SizedBox(height: 8),
                    Text(
                      match.awayTeam.name,
                      textAlign: TextAlign.center,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        color: AppColors.textPrimary,
                        fontSize: 14.5,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                    const SizedBox(height: 2),
                    const Text(
                      'Deplasman',
                      style: TextStyle(
                        color: AppColors.textMuted,
                        fontSize: 11,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 14),
          Wrap(
            alignment: WrapAlignment.center,
            spacing: 8,
            runSpacing: 8,
            children: [
              _HeroStatPill(
                text: match.prediction.htScoreDisplay,
                color: AppColors.textPrimary,
                borderColor: AppColors.border,
                backgroundColor: AppColors.card,
              ),
              _HeroStatPill(
                text: match.prediction.ftScoreDisplay,
                color: AppColors.neonGreen,
                borderColor: AppColors.neonGreen.withValues(alpha: 0.55),
                backgroundColor: AppColors.neonGreen.withValues(alpha: 0.14),
              ),
              _HeroStatPill(
                text: 'İY/MS: ${match.prediction.htFtPrediction}',
                color: AppColors.neonOrange,
                borderColor: AppColors.neonOrange.withValues(alpha: 0.55),
                backgroundColor: AppColors.neonOrange.withValues(alpha: 0.15),
              ),
              _HeroStatPill(
                text: match.prediction.confidenceLabel,
                color: AppColors.neonBlue,
                borderColor: AppColors.neonBlue.withValues(alpha: 0.45),
                backgroundColor: AppColors.neonBlue.withValues(alpha: 0.15),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _HeroStatPill extends StatelessWidget {
  final String text;
  final Color color;
  final Color borderColor;
  final Color backgroundColor;

  const _HeroStatPill({
    required this.text,
    required this.color,
    required this.borderColor,
    required this.backgroundColor,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: backgroundColor,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: borderColor),
      ),
      child: Text(
        text,
        style: TextStyle(
          color: color,
          fontSize: 11.5,
          fontWeight: FontWeight.w800,
        ),
      ),
    );
  }
}
