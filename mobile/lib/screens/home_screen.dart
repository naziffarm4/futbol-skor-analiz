import 'package:flutter/material.dart';

import '../config/constants.dart';
import '../config/theme.dart';
import '../models/league_model.dart';
import '../models/match_model.dart';
import '../services/bulletin_api_service.dart';
import '../widgets/data_transparency_banner.dart';
import '../widgets/match_card.dart';
import 'match_detail_screen.dart';

class HomeScreen extends StatefulWidget {
  final BulletinApiService? service;

  const HomeScreen({super.key, this.service});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  late final BulletinApiService _service;
  BulletinData? _bulletin;
  bool _isLoading = true;
  bool _hasError = false;

  @override
  void initState() {
    super.initState();
    _service = widget.service ?? BulletinApiService();
    _loadBulletin();
  }

  Future<void> _loadBulletin() async {
    setState(() {
      _isLoading = true;
      _hasError = false;
    });

    try {
      final data = await _service.fetchBulletin();
      if (!mounted) return;
      setState(() {
        _bulletin = data;
        _isLoading = false;
        _hasError = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _bulletin = null;
        _isLoading = false;
        _hasError = true;
      });
    }
  }

  void _openMatchDetail(
    MatchModel match,
    LeagueModel league,
    BulletinData bulletin,
  ) {
    final resolvedLeague = bulletin.effectiveLeague(league);
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => MatchDetailScreen(
          match: match,
          league: resolvedLeague,
          dataSource: bulletin.dataSource,
          sourcesUsed: resolvedLeague.sourcesUsed,
          sourcesCount: resolvedLeague.sourcesCount,
          sourcesTotal: resolvedLeague.sourcesTotal,
          season: resolvedLeague.season,
          generatedAt: bulletin.generatedAt,
          playedMatchesCount: bulletin.effectivePlayedMatches(league.id),
          injuriesCount: bulletin.effectiveInjuriesCount(league.id),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final leagues = AppConstants.supportedLeagues;
    final bulletin = _bulletin;

    return DefaultTabController(
      length: leagues.length,
      child: Scaffold(
        appBar: AppBar(
          title: const Text(
            AppConstants.appTitle,
            overflow: TextOverflow.ellipsis,
          ),
          actions: [
            if (bulletin != null && !_hasError)
              Center(
                child: Container(
                  margin: const EdgeInsets.only(right: 4),
                  padding: const EdgeInsets.symmetric(
                    horizontal: 8,
                    vertical: 4,
                  ),
                  decoration: BoxDecoration(
                    color: (bulletin.isOfflineCache
                            ? AppColors.neonOrange
                            : AppColors.neonGreen)
                        .withValues(alpha: 0.14),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Text(
                    bulletin.isOfflineCache ? 'Çevrimdışı' : 'Canlı',
                    style: TextStyle(
                      color: bulletin.isOfflineCache
                          ? AppColors.neonOrange
                          : AppColors.neonGreen,
                      fontSize: 11,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
              ),
            IconButton(
              tooltip: 'Bülteni Yenile',
              onPressed: _isLoading ? null : _loadBulletin,
              icon: _isLoading
                  ? const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: AppColors.neonGreen,
                      ),
                    )
                  : const Icon(Icons.refresh_rounded),
            ),
          ],
          bottom: TabBar(
            isScrollable: true,
            tabAlignment: TabAlignment.start,
            padding: const EdgeInsets.symmetric(horizontal: 8),
            tabs: [
              for (final league in leagues)
                Tab(
                  key: ValueKey('league_tab_${league.id}'),
                  text: league.tabTitle,
                ),
            ],
          ),
        ),
        body: _buildBody(leagues, bulletin),
      ),
    );
  }

  Widget _buildBody(List<LeagueModel> leagues, BulletinData? bulletin) {
    if (_isLoading && bulletin == null) {
      return const Center(
        child: Padding(
          padding: EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              CircularProgressIndicator(color: AppColors.neonGreen),
              SizedBox(height: 16),
              Text(
                'Canlı bülten yükleniyor...',
                textAlign: TextAlign.center,
                style: TextStyle(
                  color: AppColors.textSecondary,
                  fontSize: 14,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
          ),
        ),
      );
    }

    if (_hasError || bulletin == null) {
      return Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Container(
            padding: const EdgeInsets.all(24),
            decoration: BoxDecoration(
              color: AppColors.card,
              borderRadius: BorderRadius.circular(18),
              border: Border.all(color: AppColors.border),
            ),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(
                  Icons.cloud_off_rounded,
                  size: 48,
                  color: AppColors.coralRed,
                ),
                const SizedBox(height: 14),
                const Text(
                  'Sunucuya bağlanılamadı, tekrar dene',
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    color: AppColors.textPrimary,
                    fontSize: 16,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                const SizedBox(height: 18),
                FilledButton.icon(
                  key: const ValueKey('retry_bulletin_button'),
                  onPressed: _loadBulletin,
                  icon: const Icon(Icons.refresh_rounded, size: 18),
                  label: const Text('Tekrar Dene'),
                ),
              ],
            ),
          ),
        ),
      );
    }

    final tabView = TabBarView(
      children: [
        for (final league in leagues)
          Builder(
            builder: (_) {
              final resolvedLeague = bulletin.effectiveLeague(league);
              return _LeagueMatchesList(
                league: resolvedLeague,
                matches: bulletin.matchesByLeague[league.id] ?? const [],
                dataSource: bulletin.dataSource,
                sourcesUsed: resolvedLeague.sourcesUsed,
                sourcesCount: resolvedLeague.sourcesCount,
                sourcesTotal: resolvedLeague.sourcesTotal,
                season: resolvedLeague.season,
                generatedAt: bulletin.generatedAt,
                playedMatchesCount: bulletin.effectivePlayedMatches(league.id),
                injuriesCount: bulletin.effectiveInjuriesCount(league.id),
                onRefresh: _loadBulletin,
                onTapMatch: (match) =>
                    _openMatchDetail(match, resolvedLeague, bulletin),
              );
            },
          ),
      ],
    );

    if (!bulletin.isOfflineCache) {
      return tabView;
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _OfflineCacheBanner(
          formattedTimestamp: bulletin.formattedGeneratedAt,
          isLoading: _isLoading,
          onRetry: _loadBulletin,
        ),
        Expanded(child: tabView),
      ],
    );
  }
}

class _OfflineCacheBanner extends StatelessWidget {
  final String formattedTimestamp;
  final bool isLoading;
  final VoidCallback onRetry;

  const _OfflineCacheBanner({
    required this.formattedTimestamp,
    required this.isLoading,
    required this.onRetry,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      key: const ValueKey('offline_cache_banner'),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
      decoration: BoxDecoration(
        color: AppColors.neonOrange.withValues(alpha: 0.14),
        border: Border(
          bottom: BorderSide(
            color: AppColors.neonOrange.withValues(alpha: 0.45),
          ),
        ),
      ),
      child: Row(
        children: [
          const Icon(
            Icons.offline_pin_rounded,
            size: 17,
            color: AppColors.neonOrange,
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              'Çevrimdışı Önbellek • Son güncelleme: $formattedTimestamp',
              style: const TextStyle(
                color: AppColors.neonOrange,
                fontSize: 12,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
          const SizedBox(width: 8),
          TextButton.icon(
            key: const ValueKey('offline_retry_button'),
            onPressed: isLoading ? null : onRetry,
            style: TextButton.styleFrom(
              foregroundColor: AppColors.neonOrange,
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
              minimumSize: Size.zero,
              tapTargetSize: MaterialTapTargetSize.shrinkWrap,
              backgroundColor: AppColors.neonOrange.withValues(alpha: 0.15),
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(8),
                side: BorderSide(
                  color: AppColors.neonOrange.withValues(alpha: 0.45),
                ),
              ),
            ),
            icon: const Icon(Icons.refresh_rounded, size: 14),
            label: const Text(
              'Yenile',
              style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w800),
            ),
          ),
        ],
      ),
    );
  }
}

class _LeagueMatchesList extends StatelessWidget {
  final LeagueModel league;
  final List<MatchModel> matches;
  final String dataSource;
  final List<String> sourcesUsed;
  final int sourcesCount;
  final int sourcesTotal;
  final String season;
  final DateTime? generatedAt;
  final int playedMatchesCount;
  final int injuriesCount;
  final Future<void> Function() onRefresh;
  final ValueChanged<MatchModel> onTapMatch;

  const _LeagueMatchesList({
    required this.league,
    required this.matches,
    required this.dataSource,
    required this.sourcesUsed,
    required this.sourcesCount,
    required this.sourcesTotal,
    required this.season,
    required this.generatedAt,
    required this.playedMatchesCount,
    required this.injuriesCount,
    required this.onRefresh,
    required this.onTapMatch,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        DataTransparencyBanner(
          key: ValueKey('home_transparency_banner_${league.id}'),
          dataSource: dataSource,
          sourcesUsed: sourcesUsed,
          sourcesCount: sourcesCount,
          sourcesTotal: sourcesTotal,
          season: season,
          generatedAt: generatedAt,
          playedMatchesCount: playedMatchesCount,
          injuriesCount: injuriesCount,
        ),
        Expanded(
          child: RefreshIndicator(
            color: AppColors.neonGreen,
            backgroundColor: AppColors.card,
            onRefresh: onRefresh,
            child: matches.isEmpty
                ? ListView(
                    physics: const AlwaysScrollableScrollPhysics(),
                    padding: const EdgeInsets.all(24),
                    children: [
                      const SizedBox(height: 60),
                      const Icon(
                        Icons.sports_soccer_rounded,
                        size: 48,
                        color: AppColors.textMuted,
                      ),
                      const SizedBox(height: 12),
                      Text(
                        '${league.name} için bu hafta bülten maçı bulunamadı.',
                        textAlign: TextAlign.center,
                        style: const TextStyle(color: AppColors.textSecondary),
                      ),
                    ],
                  )
                : ListView.separated(
                    physics: const AlwaysScrollableScrollPhysics(),
                    padding: const EdgeInsets.fromLTRB(16, 14, 16, 28),
                    itemCount: matches.length,
                    separatorBuilder: (_, _) => const SizedBox(height: 14),
                    itemBuilder: (context, index) {
                      final match = matches[index];
                      return MatchCard(
                        match: match,
                        onTap: () => onTapMatch(match),
                      );
                    },
                  ),
          ),
        ),
      ],
    );
  }
}
