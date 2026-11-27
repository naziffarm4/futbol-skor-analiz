import 'package:flutter/material.dart';

import '../config/constants.dart';
import '../config/theme.dart';

class DataTransparencyBanner extends StatelessWidget {
  final String dataSource;
  final List<String> sourcesUsed;
  final int sourcesCount;
  final int sourcesTotal;
  final String? season;
  final DateTime? generatedAt;
  final int playedMatchesCount;
  final int injuriesCount;
  final bool isCard;

  const DataTransparencyBanner({
    super.key,
    this.dataSource = 'Transfermarkt',
    this.sourcesUsed = const <String>[],
    this.sourcesCount = 0,
    this.sourcesTotal = 5,
    this.season,
    this.generatedAt,
    this.playedMatchesCount = 0,
    this.injuriesCount = 0,
    this.isCard = false,
  });

  @override
  Widget build(BuildContext context) {
    final effectiveSource =
        dataSource.trim().isEmpty ? 'Transfermarkt' : dataSource.trim();
    final cleanedSources = sourcesUsed
        .map((s) => s.trim())
        .where((s) => s.isNotEmpty)
        .toList();
    final effectiveTotal = sourcesTotal > 0 ? sourcesTotal : 5;
    final effectiveCount = sourcesCount > 0
        ? sourcesCount
        : (cleanedSources.isNotEmpty ? cleanedSources.length : 1);
    final effectiveSeason = (season != null && season!.trim().isNotEmpty)
        ? season!.trim()
        : AppConstants.defaultSeason;
    final formattedTime = AppConstants.formatShortTimestampTr(generatedAt);

    final sourcesLabel = cleanedSources.length > 1
        ? 'Kaynaklar: ${cleanedSources.join(', ')}'
        : 'Kaynak: ${cleanedSources.isNotEmpty ? cleanedSources.first : effectiveSource}';

    return Container(
      width: double.infinity,
      padding: isCard
          ? const EdgeInsets.symmetric(horizontal: 14, vertical: 12)
          : const EdgeInsets.symmetric(horizontal: 14, vertical: 9),
      decoration: isCard
          ? BoxDecoration(
              color: AppColors.surface,
              borderRadius: BorderRadius.circular(14),
              border: Border.all(color: AppColors.border),
            )
          : const BoxDecoration(
              color: AppColors.surface,
              border: Border(
                bottom: BorderSide(color: AppColors.border),
              ),
            ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Wrap(
            spacing: 6,
            runSpacing: 6,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              Container(
                padding: const EdgeInsets.symmetric(
                  horizontal: 8,
                  vertical: 3.5,
                ),
                decoration: BoxDecoration(
                  color: AppColors.neonGreen.withValues(alpha: 0.14),
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(
                    color: AppColors.neonGreen.withValues(alpha: 0.42),
                  ),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(
                      Icons.verified_rounded,
                      size: 13.5,
                      color: AppColors.neonGreen,
                    ),
                    const SizedBox(width: 4),
                    Text(
                      '$effectiveCount/$effectiveTotal Kaynak Doğruladı',
                      style: const TextStyle(
                        color: AppColors.neonGreen,
                        fontSize: 11.5,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                  ],
                ),
              ),
              _TransparencyPill(
                text: 'Sezon: $effectiveSeason',
                accentColor: AppColors.neonBlue,
              ),
              if (playedMatchesCount > 0)
                _TransparencyPill(
                  text: '$playedMatchesCount gerçek maç analizi',
                  accentColor: AppColors.neonOrange,
                ),
              if (injuriesCount > 0)
                _TransparencyPill(
                  text: '$injuriesCount eksik kaydı',
                  accentColor: AppColors.coralRed,
                ),
              if (formattedTime.isNotEmpty)
                _TransparencyPill(
                  text: 'Güncelleme: $formattedTime',
                  accentColor: AppColors.neonBlue,
                ),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            sourcesLabel,
            style: const TextStyle(
              color: AppColors.textSecondary,
              fontSize: 11,
              fontWeight: FontWeight.w600,
              height: 1.3,
            ),
          ),
          const SizedBox(height: 6),
          const Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Padding(
                padding: EdgeInsets.only(top: 1.5),
                child: Icon(
                  Icons.info_outline_rounded,
                  size: 13,
                  color: AppColors.textMuted,
                ),
              ),
              SizedBox(width: 5),
              Expanded(
                child: Text(
                  AppConstants.statisticalDisclaimer,
                  softWrap: true,
                  style: TextStyle(
                    color: AppColors.textMuted,
                    fontSize: 10.5,
                    fontWeight: FontWeight.w500,
                    height: 1.3,
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _TransparencyPill extends StatelessWidget {
  final String text;
  final Color accentColor;

  const _TransparencyPill({
    required this.text,
    required this.accentColor,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3.5),
      decoration: BoxDecoration(
        color: accentColor.withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: accentColor.withValues(alpha: 0.26)),
      ),
      child: Text(
        text,
        style: const TextStyle(
          color: AppColors.textPrimary,
          fontSize: 11,
          fontWeight: FontWeight.w600,
        ),
      ),
    );
  }
}
