import 'package:flutter/material.dart';

import '../config/theme.dart';
import '../models/injury_model.dart';

class InjuriesList extends StatelessWidget {
  final String homeTeamName;
  final String awayTeamName;
  final List<InjuryModel> homeInjuries;
  final List<InjuryModel> awayInjuries;

  const InjuriesList({
    super.key,
    required this.homeTeamName,
    required this.awayTeamName,
    required this.homeInjuries,
    required this.awayInjuries,
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
                  Icons.medical_services_rounded,
                  color: AppColors.coralRed,
                  size: 20,
                ),
                SizedBox(width: 8),
                Expanded(
                  child: Text(
                    'Sakatlık & Ceza Listesi',
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
            _TeamInjuriesBlock(
              teamTitle: '🏠 $homeTeamName',
              injuries: homeInjuries,
            ),
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 14),
              child: Divider(height: 1),
            ),
            _TeamInjuriesBlock(
              teamTitle: '✈️ $awayTeamName',
              injuries: awayInjuries,
            ),
          ],
        ),
      ),
    );
  }
}

class _TeamInjuriesBlock extends StatelessWidget {
  final String teamTitle;
  final List<InjuryModel> injuries;

  const _TeamInjuriesBlock({
    required this.teamTitle,
    required this.injuries,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Expanded(
              child: Text(
                teamTitle,
                style: const TextStyle(
                  color: AppColors.textPrimary,
                  fontSize: 14,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
              decoration: BoxDecoration(
                color: AppColors.cardElevated,
                borderRadius: BorderRadius.circular(10),
              ),
              child: Text(
                '${injuries.length} Eksik',
                style: const TextStyle(
                  color: AppColors.textSecondary,
                  fontSize: 11,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
          ],
        ),
        const SizedBox(height: 10),
        if (injuries.isEmpty)
          const Text(
            'Kadroda kayıtlı sakat veya cezalı oyuncu bulunmuyor.',
            style: TextStyle(
              color: AppColors.textSecondary,
              fontSize: 13,
            ),
          )
        else
          for (var i = 0; i < injuries.length; i++) ...[
            if (i > 0) const SizedBox(height: 8),
            _InjuryTile(injury: injuries[i]),
          ],
      ],
    );
  }
}

class _InjuryTile extends StatelessWidget {
  final InjuryModel injury;

  const _InjuryTile({required this.injury});

  Color _positionColor(PlayerPosition pos) {
    switch (pos) {
      case PlayerPosition.gk:
        return AppColors.neonOrange;
      case PlayerPosition.def:
        return AppColors.neonBlue;
      case PlayerPosition.mid:
        return AppColors.neonGreen;
      case PlayerPosition.fw:
        return AppColors.coralRed;
    }
  }

  Color _impactColor(ImpactLevel impact) {
    switch (impact) {
      case ImpactLevel.high:
        return AppColors.coralRed;
      case ImpactLevel.medium:
        return AppColors.neonOrange;
      case ImpactLevel.low:
        return AppColors.neutralBar;
    }
  }

  @override
  Widget build(BuildContext context) {
    final posColor = _positionColor(injury.position);
    final impColor = _impactColor(injury.impactLevel);

    return Container(
      padding: const EdgeInsets.all(11),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
                decoration: BoxDecoration(
                  color: posColor.withValues(alpha: 0.16),
                  borderRadius: BorderRadius.circular(6),
                  border: Border.all(color: posColor.withValues(alpha: 0.5)),
                ),
                child: Text(
                  injury.position.code,
                  style: TextStyle(
                    color: posColor,
                    fontSize: 11,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ),
              const SizedBox(width: 7),
              Expanded(
                child: Text(
                  injury.playerName,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    color: AppColors.textPrimary,
                    fontSize: 13.5,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
              if (injury.verifiedByMultipleSources) ...[
                const SizedBox(width: 6),
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 6,
                    vertical: 2.5,
                  ),
                  decoration: BoxDecoration(
                    color: AppColors.neonGreen.withValues(alpha: 0.14),
                    borderRadius: BorderRadius.circular(6),
                    border: Border.all(
                      color: AppColors.neonGreen.withValues(alpha: 0.45),
                    ),
                  ),
                  child: const Text(
                    '✓ Onaylı',
                    style: TextStyle(
                      color: AppColors.neonGreen,
                      fontSize: 10,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                ),
              ],
              const SizedBox(width: 6),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
                decoration: BoxDecoration(
                  color: impColor.withValues(alpha: 0.16),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Text(
                  injury.impactLevel.code,
                  style: TextStyle(
                    color: impColor,
                    fontSize: 10.5,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Wrap(
            spacing: 8,
            runSpacing: 4,
            alignment: WrapAlignment.spaceBetween,
            children: [
              Text(
                injury.reason,
                style: const TextStyle(
                  color: AppColors.textSecondary,
                  fontSize: 12,
                ),
              ),
              Text(
                'Dönüş: ${injury.formattedReturnDate}',
                style: const TextStyle(
                  color: AppColors.textMuted,
                  fontSize: 11.5,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
