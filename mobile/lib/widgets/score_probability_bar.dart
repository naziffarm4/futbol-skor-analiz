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

class MatchOutcomeSummaryCard extends StatelessWidget {
  final PredictionModel prediction;

  const MatchOutcomeSummaryCard({
    super.key,
    required this.prediction,
  });

  @override
  Widget build(BuildContext context) {
    final flexHome = (prediction.pHome * 1000).round().clamp(1, 1000);
    final flexDraw = (prediction.pDraw * 1000).round().clamp(1, 1000);
    final flexAway = (prediction.pAway * 1000).round().clamp(1, 1000);

    return Card(
      key: const ValueKey('match_outcome_summary_card'),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(
                  Icons.pie_chart_rounded,
                  color: AppColors.neonGreen,
                  size: 20,
                ),
                const SizedBox(width: 8),
                const Expanded(
                  child: Text(
                    'Olasılık Özeti (1X2 • 2.5 • KG)',
                    style: TextStyle(
                      color: AppColors.textPrimary,
                      fontSize: 15.5,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
              ],
            ),
            if (prediction.marketBlended) ...[
              const SizedBox(height: 8),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
                decoration: BoxDecoration(
                  color: AppColors.neonBlue.withValues(alpha: 0.14),
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(
                    color: AppColors.neonBlue.withValues(alpha: 0.45),
                  ),
                ),
                child: const Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(
                      Icons.auto_graph_rounded,
                      size: 13,
                      color: AppColors.neonBlue,
                    ),
                    SizedBox(width: 5),
                    Flexible(
                      child: Text(
                        'Piyasa + Poisson Harmanı',
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(
                          color: AppColors.neonBlue,
                          fontSize: 11,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ],
            const SizedBox(height: 14),
            Row(
              children: [
                Expanded(
                  child: _OutcomeSegmentLabel(
                    title: 'MS 1',
                    value: prediction.pHomeText,
                    color: AppColors.neonGreen,
                    align: CrossAxisAlignment.start,
                  ),
                ),
                Expanded(
                  child: _OutcomeSegmentLabel(
                    title: 'MS X',
                    value: prediction.pDrawText,
                    color: AppColors.neonBlue,
                    align: CrossAxisAlignment.center,
                  ),
                ),
                Expanded(
                  child: _OutcomeSegmentLabel(
                    title: 'MS 2',
                    value: prediction.pAwayText,
                    color: AppColors.neonOrange,
                    align: CrossAxisAlignment.end,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            ClipRRect(
              borderRadius: BorderRadius.circular(8),
              child: SizedBox(
                height: 10,
                child: Row(
                  children: [
                    Expanded(
                      flex: flexHome,
                      child: Container(color: AppColors.neonGreen),
                    ),
                    const SizedBox(width: 2),
                    Expanded(
                      flex: flexDraw,
                      child: Container(color: AppColors.neonBlue),
                    ),
                    const SizedBox(width: 2),
                    Expanded(
                      flex: flexAway,
                      child: Container(color: AppColors.neonOrange),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 14),
            Row(
              children: [
                Expanded(
                  child: _BinaryMarketTile(
                    primaryLabel: '2.5 Üst',
                    primaryValue: prediction.pOver25Text,
                    secondaryLabel: '2.5 Alt',
                    secondaryValue: prediction.pUnder25Text,
                    primaryRatio: prediction.pOver25,
                    accentColor: AppColors.neonGreen,
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: _BinaryMarketTile(
                    primaryLabel: 'KG Var',
                    primaryValue: prediction.pBttsYesText,
                    secondaryLabel: 'KG Yok',
                    secondaryValue: prediction.pBttsNoText,
                    primaryRatio: prediction.pBttsYes,
                    accentColor: AppColors.neonBlue,
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _OutcomeSegmentLabel extends StatelessWidget {
  final String title;
  final String value;
  final Color color;
  final CrossAxisAlignment align;

  const _OutcomeSegmentLabel({
    required this.title,
    required this.value,
    required this.color,
    required this.align,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: align,
      children: [
        FittedBox(
          fit: BoxFit.scaleDown,
          child: Text(
            title,
            style: const TextStyle(
              color: AppColors.textSecondary,
              fontSize: 11.5,
              fontWeight: FontWeight.w700,
            ),
          ),
        ),
        const SizedBox(height: 2),
        FittedBox(
          fit: BoxFit.scaleDown,
          child: Text(
            value,
            style: TextStyle(
              color: color,
              fontSize: 14,
              fontWeight: FontWeight.w900,
            ),
          ),
        ),
      ],
    );
  }
}

class _BinaryMarketTile extends StatelessWidget {
  final String primaryLabel;
  final String primaryValue;
  final String secondaryLabel;
  final String secondaryValue;
  final double primaryRatio;
  final Color accentColor;

  const _BinaryMarketTile({
    required this.primaryLabel,
    required this.primaryValue,
    required this.secondaryLabel,
    required this.secondaryValue,
    required this.primaryRatio,
    required this.accentColor,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: AppColors.cardElevated.withValues(alpha: 0.65),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  primaryLabel,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    color: AppColors.textPrimary,
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
              const SizedBox(width: 4),
              Text(
                primaryValue,
                style: TextStyle(
                  color: accentColor,
                  fontSize: 12.5,
                  fontWeight: FontWeight.w800,
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          ClipRRect(
            borderRadius: BorderRadius.circular(5),
            child: LinearProgressIndicator(
              value: primaryRatio.clamp(0.0, 1.0),
              minHeight: 6,
              backgroundColor: AppColors.surface,
              valueColor: AlwaysStoppedAnimation<Color>(accentColor),
            ),
          ),
          const SizedBox(height: 6),
          Row(
            children: [
              Expanded(
                child: Text(
                  secondaryLabel,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    color: AppColors.textSecondary,
                    fontSize: 11.5,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
              const SizedBox(width: 4),
              Text(
                secondaryValue,
                style: const TextStyle(
                  color: AppColors.textSecondary,
                  fontSize: 11.5,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class HtFtProbabilityBar extends StatelessWidget {
  final List<HtFtOption> topHtFt;
  final List<HtFtOption> allHtFt;
  final String highlightedCode;

  const HtFtProbabilityBar({
    super.key,
    required this.topHtFt,
    this.allHtFt = const <HtFtOption>[],
    this.highlightedCode = '',
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

  HtFtOption _cellFor(String code, Map<String, HtFtOption> byCode) {
    return byCode[code] ??
        HtFtOption(
          code: code,
          label: HtFtOption.defaultLabelForCode(code),
          prob: 0.0,
        );
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

    final byCode = <String, HtFtOption>{
      for (final item in topHtFt) HtFtOption.normalizeCode(item.code): item,
      for (final item in allHtFt) HtFtOption.normalizeCode(item.code): item,
    };
    final effectiveHighlight = highlightedCode.trim().isNotEmpty
        ? HtFtOption.normalizeCode(highlightedCode)
        : (items.isNotEmpty ? HtFtOption.normalizeCode(items.first.code) : '');

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
            if (allHtFt.isNotEmpty) ...[
              const SizedBox(height: 16),
              const Divider(height: 1),
              const SizedBox(height: 14),
              const Text(
                'İlk Yarı / Maç Sonucu Tam Yüzdelik Matrisi (3×3)',
                style: TextStyle(
                  color: AppColors.textSecondary,
                  fontSize: 12.5,
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(height: 10),
              Row(
                children: [
                  const SizedBox(
                    width: 36,
                    child: Text(
                      'İY\\MS',
                      style: TextStyle(
                        color: AppColors.textMuted,
                        fontSize: 10,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                  ),
                  for (final ft in const <String>['1', 'X', '2']) ...[
                    const SizedBox(width: 6),
                    Expanded(
                      child: Center(
                        child: Text(
                          'MS $ft',
                          style: const TextStyle(
                            color: AppColors.textSecondary,
                            fontSize: 11,
                            fontWeight: FontWeight.w800,
                          ),
                        ),
                      ),
                    ),
                  ],
                ],
              ),
              const SizedBox(height: 6),
              for (final ht in const <String>['1', 'X', '2']) ...[
                if (ht != '1') const SizedBox(height: 6),
                Row(
                  children: [
                    SizedBox(
                      width: 36,
                      child: Text(
                        'İY $ht',
                        style: const TextStyle(
                          color: AppColors.textSecondary,
                          fontSize: 11,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                    ),
                    for (final ft in const <String>['1', 'X', '2']) ...[
                      const SizedBox(width: 6),
                      Expanded(
                        child: _HtFtMatrixCell(
                          option: _cellFor('$ht/$ft', byCode),
                          isHighlighted: '$ht/$ft' == effectiveHighlight,
                        ),
                      ),
                    ],
                  ],
                ),
              ],
            ],
          ],
        ),
      ),
    );
  }
}

class _HtFtMatrixCell extends StatelessWidget {
  final HtFtOption option;
  final bool isHighlighted;

  const _HtFtMatrixCell({
    required this.option,
    required this.isHighlighted,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      key: ValueKey('ht_ft_cell_${option.code}'),
      padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 7),
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: isHighlighted
            ? AppColors.neonGreen.withValues(alpha: 0.16)
            : AppColors.cardElevated.withValues(alpha: 0.72),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(
          color: isHighlighted ? AppColors.neonGreen : AppColors.border,
          width: isHighlighted ? 1.5 : 1.0,
        ),
        boxShadow: isHighlighted
            ? [
                BoxShadow(
                  color: AppColors.neonGreen.withValues(alpha: 0.22),
                  blurRadius: 8,
                ),
              ]
            : null,
      ),
      child: FittedBox(
        fit: BoxFit.scaleDown,
        child: Text.rich(
          TextSpan(
            children: [
              TextSpan(
                text: '${option.code}\n',
                style: TextStyle(
                  color: isHighlighted
                      ? AppColors.neonGreen
                      : AppColors.textSecondary,
                  fontSize: 11,
                  fontWeight: FontWeight.w700,
                  height: 1.2,
                ),
              ),
              TextSpan(
                text: option.percentText,
                style: TextStyle(
                  color: isHighlighted
                      ? AppColors.neonGreen
                      : AppColors.textPrimary,
                  fontSize: 13,
                  fontWeight: FontWeight.w900,
                  height: 1.25,
                ),
              ),
            ],
          ),
          textAlign: TextAlign.center,
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
