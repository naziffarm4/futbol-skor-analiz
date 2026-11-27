import 'package:flutter/material.dart';

import '../config/theme.dart';
import '../models/analysis_model.dart';
import '../models/prediction_model.dart';

class AnalysisSection extends StatelessWidget {
  final String homeTeamName;
  final String awayTeamName;
  final TeamAnalysisModel analysis;
  final PredictionModel? prediction;
  final int? homeMissingCount;
  final int? awayMissingCount;

  const AnalysisSection({
    super.key,
    required this.homeTeamName,
    required this.awayTeamName,
    required this.analysis,
    this.prediction,
    this.homeMissingCount,
    this.awayMissingCount,
  });

  static List<String> splitParagraphs(String raw) {
    final normalized = raw.replaceAll('\r\n', '\n').trim();
    if (normalized.isEmpty) return const <String>[];
    final byBlankLine = normalized
        .split(RegExp(r'\n\s*\n+'))
        .map((p) => p.trim())
        .where((p) => p.isNotEmpty)
        .toList();
    if (byBlankLine.length > 1) return byBlankLine;
    return normalized
        .split('\n')
        .map((p) => p.trim())
        .where((p) => p.isNotEmpty)
        .toList();
  }

  @override
  Widget build(BuildContext context) {
    final homeOff = analysis.homeOffenseRating.round();
    final homeDef = analysis.homeDefenseRating.round();
    final awayOff = analysis.awayOffenseRating.round();
    final awayDef = analysis.awayDefenseRating.round();
    final homePower = ((analysis.homeOffenseRating + analysis.homeDefenseRating) / 2).round();
    final awayPower = ((analysis.awayOffenseRating + analysis.awayDefenseRating) / 2).round();

    final overviewBadges = <_BadgeSpec>[
      if (prediction != null)
        _BadgeSpec(
          label: 'Skor ${prediction!.formattedScore} • ${prediction!.confidenceLabel}',
          color: AppColors.neonGreen,
        ),
      _BadgeSpec(
        label: 'Güç Dengesi $homePower - $awayPower',
        color: AppColors.neonBlue,
      ),
    ];

    final homeBadges = <_BadgeSpec>[
      _BadgeSpec(
        label: 'Hücum $homeOff • Savunma $homeDef',
        color: AppColors.neonBlue,
      ),
      if (homeMissingCount != null)
        _BadgeSpec(
          label: homeMissingCount! > 0
              ? '${homeMissingCount!} Eksik Oyuncu'
              : 'Tam Kadro',
          color: homeMissingCount! > 0
              ? AppColors.coralRed
              : AppColors.neonGreen,
        ),
    ];

    final awayBadges = <_BadgeSpec>[
      _BadgeSpec(
        label: 'Hücum $awayOff • Savunma $awayDef',
        color: AppColors.neonOrange,
      ),
      if (awayMissingCount != null)
        _BadgeSpec(
          label: awayMissingCount! > 0
              ? '${awayMissingCount!} Eksik Oyuncu'
              : 'Tam Kadro',
          color: awayMissingCount! > 0
              ? AppColors.coralRed
              : AppColors.neonGreen,
        ),
    ];

    final htFtBadges = <_BadgeSpec>[
      if (prediction != null)
        _BadgeSpec(
          label: '${prediction!.htScoreDisplay} • ${prediction!.ftScoreDisplay}',
          color: AppColors.neonGreen,
        ),
      if (prediction != null && prediction!.topHtFt.isNotEmpty)
        _BadgeSpec(
          label:
              '${prediction!.topHtFt.first.code} (${prediction!.topHtFt.first.percentText})',
          color: AppColors.neonBlue,
        ),
    ];

    final hasHtFtReasoning = analysis.htFtReasoningText.trim().isNotEmpty;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Padding(
          padding: EdgeInsets.only(bottom: 10),
          child: Row(
            children: [
              Icon(
                Icons.psychology_rounded,
                color: AppColors.neonGreen,
                size: 20,
              ),
              SizedBox(width: 8),
              Expanded(
                child: Text(
                  'Uzman Sistem Analiz Raporu',
                  style: TextStyle(
                    color: AppColors.textPrimary,
                    fontSize: 16,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
            ],
          ),
        ),
        _AnalysisCard(
          icon: Icons.insights_rounded,
          title: 'Neden Bu Skor?',
          subtitleBadge: 'Maçın Genel Senaryosu',
          accentColor: AppColors.neonGreen,
          badges: overviewBadges,
          body: analysis.matchOverviewText,
        ),
        if (hasHtFtReasoning) ...[
          const SizedBox(height: 12),
          _AnalysisCard(
            icon: Icons.timeline_rounded,
            title: 'Kapsamlı Durum Değerlendirmesi & Neden Bu İY/MS?',
            subtitleBadge: prediction != null
                ? 'İY/MS: ${prediction!.htFtPrediction}'
                : 'İY/MS Senaryosu',
            accentColor: AppColors.neonBlue,
            badges: htFtBadges,
            body: analysis.htFtReasoningText,
          ),
        ],
        const SizedBox(height: 12),
        _AnalysisCard(
          icon: Icons.home_work_rounded,
          title: 'Ev Sahibi Durumu',
          subtitleBadge: homeTeamName,
          accentColor: AppColors.neonBlue,
          badges: homeBadges,
          body: analysis.homeAnalysisText,
        ),
        const SizedBox(height: 12),
        _AnalysisCard(
          icon: Icons.flight_takeoff_rounded,
          title: 'Deplasman Durumu',
          subtitleBadge: awayTeamName,
          accentColor: AppColors.neonOrange,
          badges: awayBadges,
          body: analysis.awayAnalysisText,
        ),
      ],
    );
  }
}

class _BadgeSpec {
  final String label;
  final Color color;

  const _BadgeSpec({required this.label, required this.color});
}

class _AnalysisCard extends StatelessWidget {
  final IconData icon;
  final String title;
  final String subtitleBadge;
  final Color accentColor;
  final List<_BadgeSpec> badges;
  final String body;

  const _AnalysisCard({
    required this.icon,
    required this.title,
    required this.subtitleBadge,
    required this.accentColor,
    required this.badges,
    required this.body,
  });

  @override
  Widget build(BuildContext context) {
    final paragraphs = AnalysisSection.splitParagraphs(body);

    return Card(
      child: Container(
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(16),
          border: Border(
            left: BorderSide(color: accentColor, width: 3.5),
          ),
        ),
        padding: const EdgeInsets.all(15),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Padding(
                  padding: const EdgeInsets.only(top: 1.5),
                  child: Icon(icon, color: accentColor, size: 17),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    title,
                    style: TextStyle(
                      color: accentColor,
                      fontSize: 14,
                      fontWeight: FontWeight.w800,
                      letterSpacing: -0.1,
                      height: 1.25,
                    ),
                  ),
                ),
              ],
            ),
            if (subtitleBadge.trim().isNotEmpty || badges.isNotEmpty) ...[
              const SizedBox(height: 10),
              Wrap(
                spacing: 8,
                runSpacing: 6,
                children: [
                  if (subtitleBadge.trim().isNotEmpty)
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 8,
                        vertical: 3.5,
                      ),
                      decoration: BoxDecoration(
                        color: AppColors.cardElevated,
                        borderRadius: BorderRadius.circular(8),
                        border: Border.all(color: AppColors.border),
                      ),
                      child: Text(
                        subtitleBadge,
                        style: const TextStyle(
                          color: AppColors.textPrimary,
                          fontSize: 11.5,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                  for (final badge in badges)
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 9,
                        vertical: 4,
                      ),
                      decoration: BoxDecoration(
                        color: badge.color.withValues(alpha: 0.12),
                        borderRadius: BorderRadius.circular(8),
                        border: Border.all(
                          color: badge.color.withValues(alpha: 0.30),
                        ),
                      ),
                      child: Text(
                        badge.label,
                        style: TextStyle(
                          color: badge.color,
                          fontSize: 11.5,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ),
                ],
              ),
            ],
            const SizedBox(height: 12),
            if (paragraphs.isEmpty)
              const Text(
                'Analiz değerlendirmesi mevcut değil.',
                style: TextStyle(
                  color: AppColors.textSecondary,
                  fontSize: 13.5,
                  height: 1.55,
                ),
              )
            else
              for (var i = 0; i < paragraphs.length; i++) ...[
                if (i > 0) const SizedBox(height: 11),
                if (i == 0)
                  Container(
                    width: double.infinity,
                    padding: const EdgeInsets.symmetric(
                      horizontal: 11,
                      vertical: 9,
                    ),
                    decoration: BoxDecoration(
                      color: AppColors.cardElevated.withValues(alpha: 0.55),
                      borderRadius: BorderRadius.circular(10),
                    ),
                    child: Text(
                      paragraphs[i],
                      style: const TextStyle(
                        color: AppColors.textPrimary,
                        fontSize: 13.6,
                        fontWeight: FontWeight.w600,
                        height: 1.55,
                      ),
                    ),
                  )
                else
                  Text(
                    paragraphs[i],
                    style: TextStyle(
                      color: AppColors.textPrimary.withValues(alpha: 0.88),
                      fontSize: 13.4,
                      fontWeight: FontWeight.w400,
                      height: 1.55,
                    ),
                  ),
              ],
          ],
        ),
      ),
    );
  }
}
