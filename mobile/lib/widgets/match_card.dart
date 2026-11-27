import 'package:flutter/material.dart';

import '../config/constants.dart';
import '../config/theme.dart';
import '../models/match_model.dart';

class TeamBadge extends StatelessWidget {
  final TeamInfo team;
  final double size;

  const TeamBadge({
    super.key,
    required this.team,
    this.size = 42,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [
            team.badgeColor,
            team.badgeColor.withValues(alpha: 0.65),
          ],
        ),
        border: Border.all(
          color: Colors.white.withValues(alpha: 0.18),
          width: 1.5,
        ),
        boxShadow: [
          BoxShadow(
            color: team.badgeColor.withValues(alpha: 0.32),
            blurRadius: 10,
            offset: const Offset(0, 3),
          ),
        ],
      ),
      alignment: Alignment.center,
      child: Text(
        team.initials,
        style: TextStyle(
          color: Colors.white,
          fontWeight: FontWeight.w800,
          fontSize: size * 0.32,
          letterSpacing: 0.4,
        ),
      ),
    );
  }
}

class MatchCard extends StatelessWidget {
  final MatchModel match;
  final VoidCallback onTap;

  const MatchCard({
    super.key,
    required this.match,
    required this.onTap,
  });

  Color _confidenceColor(int percent) {
    if (percent >= 68) return AppColors.neonGreen;
    if (percent >= 60) return AppColors.neonBlue;
    return AppColors.neonOrange;
  }

  @override
  Widget build(BuildContext context) {
    final confidence = match.prediction.confidencePercentage;
    final confColor = _confidenceColor(confidence);
    final missingCount = match.totalMissingPlayers;

    return Card(
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        key: ValueKey('match_card_${match.id}'),
        onTap: onTap,
        borderRadius: BorderRadius.circular(16),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              // Üst bilgi satırı: Hafta + Tarih/Saat
              Row(
                children: [
                  Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 8,
                      vertical: 3,
                    ),
                    decoration: BoxDecoration(
                      color: AppColors.cardElevated,
                      borderRadius: BorderRadius.circular(6),
                    ),
                    child: Text(
                      '${match.round}. Hafta',
                      style: const TextStyle(
                        color: AppColors.textSecondary,
                        fontSize: 11,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.end,
                      children: [
                        const Icon(
                          Icons.schedule_rounded,
                          size: 14,
                          color: AppColors.textSecondary,
                        ),
                        const SizedBox(width: 4),
                        Flexible(
                          child: Text(
                            AppConstants.formatMatchDateTime(match.matchDate),
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(
                              color: AppColors.textSecondary,
                              fontSize: 12,
                              fontWeight: FontWeight.w500,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 16),

              // Orta satır: Ev Sahibi - Neon Skor Kutusu - Deplasman
              Row(
                children: [
                  Expanded(
                    child: Column(
                      children: [
                        TeamBadge(team: match.homeTeam),
                        const SizedBox(height: 8),
                        Text(
                          match.homeTeam.name,
                          textAlign: TextAlign.center,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            color: AppColors.textPrimary,
                            fontSize: 14,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(width: 10),
                  Column(
                    children: [
                      const Text(
                        'TAHMİN',
                        style: TextStyle(
                          color: AppColors.neonGreen,
                          fontSize: 10,
                          fontWeight: FontWeight.w800,
                          letterSpacing: 1.1,
                        ),
                      ),
                      const SizedBox(height: 4),
                      Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 16,
                          vertical: 10,
                        ),
                        decoration: BoxDecoration(
                          color: AppColors.neonGreen.withValues(alpha: 0.12),
                          borderRadius: BorderRadius.circular(12),
                          border: Border.all(
                            color: AppColors.neonGreen.withValues(alpha: 0.55),
                            width: 1.4,
                          ),
                        ),
                        child: Text(
                          match.prediction.formattedScore,
                          style: const TextStyle(
                            color: AppColors.neonGreen,
                            fontSize: 22,
                            fontWeight: FontWeight.w900,
                            letterSpacing: 1.2,
                          ),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Column(
                      children: [
                        TeamBadge(team: match.awayTeam),
                        const SizedBox(height: 8),
                        Text(
                          match.awayTeam.name,
                          textAlign: TextAlign.center,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            color: AppColors.textPrimary,
                            fontSize: 14,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 10),
              Center(
                child: Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 10,
                    vertical: 4,
                  ),
                  decoration: BoxDecoration(
                    color: AppColors.neonBlue.withValues(alpha: 0.12),
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(
                      color: AppColors.neonBlue.withValues(alpha: 0.42),
                    ),
                  ),
                  child: Text(
                    match.prediction.compactHtFtBadge,
                    textAlign: TextAlign.center,
                    style: const TextStyle(
                      color: AppColors.neonBlue,
                      fontSize: 11.5,
                      fontWeight: FontWeight.w800,
                      letterSpacing: 0.2,
                    ),
                  ),
                ),
              ),
              const SizedBox(height: 14),
              const Divider(height: 1),
              const SizedBox(height: 12),

              // Alt rozetler: Model netliği, Eksikler rozeti ve Detay oku
              Row(
                children: [
                  Expanded(
                    child: Wrap(
                      spacing: 8,
                      runSpacing: 6,
                      crossAxisAlignment: WrapCrossAlignment.center,
                      children: [
                        Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 10,
                            vertical: 5,
                          ),
                          decoration: BoxDecoration(
                            color: confColor.withValues(alpha: 0.14),
                            borderRadius: BorderRadius.circular(20),
                            border: Border.all(
                              color: confColor.withValues(alpha: 0.45),
                            ),
                          ),
                          child: Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Icon(
                                Icons.verified_rounded,
                                size: 14,
                                color: confColor,
                              ),
                              const SizedBox(width: 5),
                              Flexible(
                                child: Text(
                                  match.prediction.confidenceLabel,
                                  softWrap: true,
                                  style: TextStyle(
                                    color: confColor,
                                    fontSize: 12,
                                    fontWeight: FontWeight.w700,
                                  ),
                                ),
                              ),
                            ],
                          ),
                        ),
                        Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 10,
                            vertical: 5,
                          ),
                          decoration: BoxDecoration(
                            color: missingCount > 0
                                ? AppColors.neonOrange.withValues(alpha: 0.14)
                                : AppColors.cardElevated,
                            borderRadius: BorderRadius.circular(20),
                            border: Border.all(
                              color: missingCount > 0
                                  ? AppColors.neonOrange.withValues(alpha: 0.45)
                                  : AppColors.border,
                            ),
                          ),
                          child: Text(
                            missingCount > 0
                                ? '🚨 $missingCount Eksik'
                                : '✅ Tam Kadro',
                            style: TextStyle(
                              color: missingCount > 0
                                  ? AppColors.neonOrange
                                  : AppColors.textSecondary,
                              fontSize: 12,
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(width: 6),
                  const Icon(
                    Icons.chevron_right_rounded,
                    size: 20,
                    color: AppColors.neonBlue,
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}
