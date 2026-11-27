import 'package:flutter/material.dart';

import '../config/theme.dart';
import '../models/prediction_model.dart';

class ScoreProbabilityBar extends StatelessWidget {
  final List<ScoreOption> topScores;

  const ScoreProbabilityBar({
    super.key,
    required this.topScores,
  });

  Color _barColorForIndex(int index) {
    switch (index) {
      case 0:
        return AppColors.neonGreen;
      case 1:
        return AppColors.neonBlue;
      default:
        return AppColors.neutralBar;
    }
  }

  @override
  Widget build(BuildContext context) {
    final items = topScores.take(3).toList();
    final maxPercent = items.isEmpty
        ? 25.0
        : items
            .map((e) => e.percentage)
            .reduce((a, b) => a > b ? a : b)
            .clamp(10.0, 100.0);

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Row(
              children: [
                Icon(
                  Icons.stacked_bar_chart_rounded,
                  color: AppColors.neonGreen,
                  size: 20,
                ),
                SizedBox(width: 8),
                Expanded(
                  child: Text(
                    'Skor Olasılık Dağılımı (Top 3)',
                    style: TextStyle(
                      color: AppColors.textPrimary,
                      fontSize: 16,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 14),
            for (var i = 0; i < items.length; i++) ...[
              if (i > 0) const SizedBox(height: 12),
              _ScoreRow(
                rank: i + 1,
                option: items[i],
                barColor: _barColorForIndex(i),
                fillFactor:
                    (items[i].percentage / (maxPercent * 1.15)).clamp(0.08, 1.0),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _ScoreRow extends StatelessWidget {
  final int rank;
  final ScoreOption option;
  final Color barColor;
  final double fillFactor;

  const _ScoreRow({
    required this.rank,
    required this.option,
    required this.barColor,
    required this.fillFactor,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Container(
              width: 24,
              height: 24,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                color: barColor.withValues(alpha: 0.16),
                borderRadius: BorderRadius.circular(6),
              ),
              child: Text(
                '$rank.',
                style: TextStyle(
                  color: barColor,
                  fontSize: 12,
                  fontWeight: FontWeight.w800,
                ),
              ),
            ),
            const SizedBox(width: 10),
            Text(
              option.formattedScore,
              style: const TextStyle(
                color: AppColors.textPrimary,
                fontSize: 15,
                fontWeight: FontWeight.w800,
              ),
            ),
            const Spacer(),
            Text(
              option.formattedPercentage,
              style: TextStyle(
                color: barColor,
                fontSize: 14,
                fontWeight: FontWeight.w700,
              ),
            ),
          ],
        ),
        const SizedBox(height: 6),
        ClipRRect(
          borderRadius: BorderRadius.circular(6),
          child: LinearProgressIndicator(
            value: fillFactor,
            minHeight: 8,
            backgroundColor: AppColors.cardElevated,
            valueColor: AlwaysStoppedAnimation<Color>(barColor),
          ),
        ),
      ],
    );
  }
}

class HtFtProbabilityBar extends StatelessWidget {
  final List<HtFtOption> topHtFt;

  const HtFtProbabilityBar({
    super.key,
    required this.topHtFt,
  });

  Color _barColorForIndex(int index) {
    switch (index) {
      case 0:
        return AppColors.neonGreen;
      case 1:
        return AppColors.neonBlue;
      default:
        return AppColors.neonOrange;
    }
  }

  @override
  Widget build(BuildContext context) {
    final items = topHtFt.take(3).toList();
    final maxPercent = items.isEmpty
        ? 25.0
        : items
            .map((e) => e.percentage)
            .reduce((a, b) => a > b ? a : b)
            .clamp(10.0, 100.0);

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Row(
              children: [
                Icon(
                  Icons.timeline_rounded,
                  color: AppColors.neonBlue,
                  size: 20,
                ),
                SizedBox(width: 8),
                Expanded(
                  child: Text(
                    'En Olası 3 İY/MS Senaryosu',
                    style: TextStyle(
                      color: AppColors.textPrimary,
                      fontSize: 16,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 14),
            for (var i = 0; i < items.length; i++) ...[
              if (i > 0) const SizedBox(height: 12),
              _HtFtRow(
                option: items[i],
                barColor: _barColorForIndex(i),
                fillFactor:
                    (items[i].percentage / (maxPercent * 1.15)).clamp(0.08, 1.0),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _HtFtRow extends StatelessWidget {
  final HtFtOption option;
  final Color barColor;
  final double fillFactor;

  const _HtFtRow({
    required this.option,
    required this.barColor,
    required this.fillFactor,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3.5),
              decoration: BoxDecoration(
                color: barColor.withValues(alpha: 0.16),
                borderRadius: BorderRadius.circular(6),
                border: Border.all(color: barColor.withValues(alpha: 0.45)),
              ),
              child: Text(
                option.code,
                style: TextStyle(
                  color: barColor,
                  fontSize: 12.5,
                  fontWeight: FontWeight.w800,
                ),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                option.label,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  color: AppColors.textPrimary,
                  fontSize: 13.5,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
            const SizedBox(width: 8),
            Text(
              option.percentText,
              style: TextStyle(
                color: barColor,
                fontSize: 13.5,
                fontWeight: FontWeight.w800,
              ),
            ),
          ],
        ),
        const SizedBox(height: 6),
        ClipRRect(
          borderRadius: BorderRadius.circular(6),
          child: LinearProgressIndicator(
            value: fillFactor,
            minHeight: 8,
            backgroundColor: AppColors.cardElevated,
            valueColor: AlwaysStoppedAnimation<Color>(barColor),
          ),
        ),
      ],
    );
  }
}
