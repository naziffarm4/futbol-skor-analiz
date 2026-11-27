import 'package:flutter/material.dart';

import '../config/theme.dart';
import '../models/analysis_model.dart';

class RatingComparisonBar extends StatelessWidget {
  final String homeTeamName;
  final String awayTeamName;
  final TeamAnalysisModel analysis;

  const RatingComparisonBar({
    super.key,
    required this.homeTeamName,
    required this.awayTeamName,
    required this.analysis,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Row(
              children: [
                Icon(
                  Icons.speed_rounded,
                  color: AppColors.neonBlue,
                  size: 20,
                ),
                SizedBox(width: 8),
                Expanded(
                  child: Text(
                    'Karşılaştırmalı Kuvvet Göstergeleri',
                    style: TextStyle(
                      color: AppColors.textPrimary,
                      fontSize: 16,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 16),
            _DualComparisonMetric(
              title: 'Ev Sahibi Hücum vs Deplasman Savunma',
              leftLabel: '$homeTeamName Hücum',
              rightLabel: '$awayTeamName Savunma',
              leftScore: analysis.homeOffenseRating,
              rightScore: analysis.awayDefenseRating,
              leftColor: AppColors.neonGreen,
              rightColor: AppColors.neonBlue,
            ),
            const SizedBox(height: 18),
            _DualComparisonMetric(
              title: 'Ev Sahibi Savunma vs Deplasman Hücum',
              leftLabel: '$homeTeamName Savunma',
              rightLabel: '$awayTeamName Hücum',
              leftScore: analysis.homeDefenseRating,
              rightScore: analysis.awayOffenseRating,
              leftColor: AppColors.neonGreen,
              rightColor: AppColors.neonOrange,
            ),
          ],
        ),
      ),
    );
  }
}

class _DualComparisonMetric extends StatelessWidget {
  final String title;
  final String leftLabel;
  final String rightLabel;
  final double leftScore;
  final double rightScore;
  final Color leftColor;
  final Color rightColor;

  const _DualComparisonMetric({
    required this.title,
    required this.leftLabel,
    required this.rightLabel,
    required this.leftScore,
    required this.rightScore,
    required this.leftColor,
    required this.rightColor,
  });

  @override
  Widget build(BuildContext context) {
    final leftClamped = leftScore.clamp(0.0, 100.0);
    final rightClamped = rightScore.clamp(0.0, 100.0);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          title,
          style: const TextStyle(
            color: AppColors.textSecondary,
            fontSize: 12,
            fontWeight: FontWeight.w600,
          ),
        ),
        const SizedBox(height: 8),
        Row(
          children: [
            Text(
              leftClamped.round().toString(),
              style: TextStyle(
                color: leftColor,
                fontSize: 15,
                fontWeight: FontWeight.w800,
              ),
            ),
            const SizedBox(width: 6),
            Expanded(
              child: Text(
                leftLabel,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  color: AppColors.textPrimary,
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
            Expanded(
              child: Text(
                rightLabel,
                textAlign: TextAlign.right,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  color: AppColors.textPrimary,
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
            const SizedBox(width: 6),
            Text(
              rightClamped.round().toString(),
              style: TextStyle(
                color: rightColor,
                fontSize: 15,
                fontWeight: FontWeight.w800,
              ),
            ),
          ],
        ),
        const SizedBox(height: 8),
        Row(
          children: [
            Expanded(
              child: ClipRRect(
                borderRadius: BorderRadius.circular(5),
                child: LinearProgressIndicator(
                  value: leftClamped / 100.0,
                  minHeight: 8,
                  backgroundColor: AppColors.cardElevated,
                  valueColor: AlwaysStoppedAnimation<Color>(leftColor),
                ),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: ClipRRect(
                borderRadius: BorderRadius.circular(5),
                child: LinearProgressIndicator(
                  value: rightClamped / 100.0,
                  minHeight: 8,
                  backgroundColor: AppColors.cardElevated,
                  valueColor: AlwaysStoppedAnimation<Color>(rightColor),
                ),
              ),
            ),
          ],
        ),
      ],
    );
  }
}
