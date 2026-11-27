import 'dart:convert';
import 'dart:io';

import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;

import '../config/constants.dart';
import '../models/league_model.dart';
import '../models/match_model.dart';

class BulletinApiException implements Exception {
  final String message;
  final int? statusCode;

  const BulletinApiException(this.message, {this.statusCode});

  @override
  String toString() => statusCode != null
      ? 'BulletinApiException($statusCode): $message'
      : 'BulletinApiException: $message';
}

class BulletinData {
  final DateTime? generatedAt;
  final String season;
  final String dataSource;
  final List<String> sourcesUsed;
  final int sourcesCount;
  final int sourcesTotal;
  final Map<String, dynamic> sourceDiagnostics;
  final int totalMatches;
  final int totalInjuries;
  final int totalPlayedMatches;
  final Map<String, int> playedMatchesByLeague;
  final Map<String, int> injuriesByLeague;
  final Map<String, LeagueModel> leaguesById;
  final Map<String, List<MatchModel>> matchesByLeague;
  final bool isOfflineCache;

  const BulletinData({
    required this.generatedAt,
    required this.season,
    this.dataSource = 'Transfermarkt',
    this.sourcesUsed = const <String>[],
    this.sourcesCount = 1,
    this.sourcesTotal = 5,
    this.sourceDiagnostics = const <String, dynamic>{},
    required this.totalMatches,
    required this.totalInjuries,
    this.totalPlayedMatches = 0,
    this.playedMatchesByLeague = const <String, int>{},
    this.injuriesByLeague = const <String, int>{},
    this.leaguesById = const <String, LeagueModel>{},
    required this.matchesByLeague,
    this.isOfflineCache = false,
  });

  String get formattedGeneratedAt {
    final formatted = AppConstants.formatShortTimestampTr(generatedAt);
    return formatted.isNotEmpty ? formatted : 'Bilinmiyor';
  }

  int effectivePlayedMatches(String leagueId) {
    final leagueCount = playedMatchesByLeague[leagueId] ?? 0;
    return leagueCount > 0 ? leagueCount : totalPlayedMatches;
  }

  int effectiveInjuriesCount(String leagueId) {
    final leagueCount = injuriesByLeague[leagueId] ?? 0;
    return leagueCount > 0 ? leagueCount : totalInjuries;
  }

  LeagueModel effectiveLeague(LeagueModel base) {
    final parsed = leaguesById[base.id];
    if (parsed == null) {
      return LeagueModel(
        id: base.id,
        name: base.name,
        country: base.country,
        flag: base.flag,
        season: season,
        sourcesUsed: sourcesUsed,
        sourcesCount: sourcesCount,
        sourcesTotal: sourcesTotal,
      );
    }
    return LeagueModel(
      id: base.id,
      name: base.name,
      country: base.country,
      flag: base.flag,
      season: parsed.season.isNotEmpty ? parsed.season : season,
      sourcesUsed:
          parsed.sourcesUsed.isNotEmpty ? parsed.sourcesUsed : sourcesUsed,
      sourcesCount:
          parsed.sourcesCount > 0 ? parsed.sourcesCount : sourcesCount,
      sourcesTotal:
          parsed.sourcesTotal > 0 ? parsed.sourcesTotal : sourcesTotal,
    );
  }

  static int _parseNonNegativeInt(dynamic value) {
    if (value is num) {
      final parsed = value.toInt();
      return parsed < 0 ? 0 : parsed;
    }
    if (value is String) {
      final parsed = int.tryParse(value.trim()) ?? 0;
      return parsed < 0 ? 0 : parsed;
    }
    return 0;
  }

  static List<String> _parseStringList(dynamic raw) {
    if (raw is! List) return const <String>[];
    return raw
        .map((item) => item?.toString().trim() ?? '')
        .where((s) => s.isNotEmpty)
        .toList();
  }

  factory BulletinData.fromJson(
    Map<String, dynamic> json, {
    bool isOfflineCache = false,
  }) {
    final rawLeagues = json['leagues'];
    if (rawLeagues is! List) {
      throw const BulletinApiException(
        'Sunucudan beklenen "leagues" veri yapısı alınamadı.',
      );
    }

    final supported = AppConstants.supportedLeagues;
    final defaultFlags = <String, String>{
      for (final l in supported) l.id: l.flag,
    };
    final grouped = <String, List<MatchModel>>{
      for (final league in supported) league.id: <MatchModel>[],
    };
    final playedByLeague = <String, int>{
      for (final league in supported) league.id: 0,
    };
    final injuriesByLeague = <String, int>{
      for (final league in supported) league.id: 0,
    };
    final parsedLeaguesById = <String, LeagueModel>{};

    final rawSource = json['data_source']?.toString().trim() ?? '';
    final effectiveDataSource = rawSource.isEmpty ? 'Transfermarkt' : rawSource;
    final rawSeason = json['season']?.toString().trim() ?? '';
    final effectiveSeason =
        rawSeason.isEmpty ? AppConstants.defaultSeason : rawSeason;

    final hasExplicitSources = json['sources_used'] is List;
    final parsedRootSources = hasExplicitSources
        ? _parseStringList(json['sources_used'])
        : <String>[effectiveDataSource];
    final rawSourcesCount = json['sources_count'];
    final effectiveSourcesCount = rawSourcesCount != null
        ? _parseNonNegativeInt(rawSourcesCount)
        : parsedRootSources.length;
    final rawSourcesTotal = json['sources_total'];
    final parsedSourcesTotal = rawSourcesTotal != null
        ? _parseNonNegativeInt(rawSourcesTotal)
        : 5;
    final effectiveSourcesTotal =
        parsedSourcesTotal > 0 ? parsedSourcesTotal : 5;
    final rawDiagnostics = json['source_diagnostics'];
    final parsedDiagnostics = rawDiagnostics is Map
        ? Map<String, dynamic>.from(rawDiagnostics)
        : const <String, dynamic>{};

    var computedMatches = 0;
    var computedInjuries = 0;
    var computedPlayedMatches = 0;

    for (final rawLeague in rawLeagues) {
      if (rawLeague is! Map) continue;
      final leagueMap = Map<String, dynamic>.from(rawLeague);
      final leagueId = (leagueMap['id'] ?? '').toString();
      if (leagueId.isNotEmpty) {
        final parsedLeague = LeagueModel.fromJson(
          <String, dynamic>{
            'season': effectiveSeason,
            ...leagueMap,
          },
          flag: defaultFlags[leagueId] ?? '⚽',
        );
        parsedLeaguesById[leagueId] = parsedLeague;
      }

      final leaguePlayed = _parseNonNegativeInt(
        leagueMap['played_matches_count'],
      );
      if (leagueId.isNotEmpty) {
        playedByLeague[leagueId] = leaguePlayed;
      }
      computedPlayedMatches += leaguePlayed;

      var leagueInjuriesCount = _parseNonNegativeInt(
        leagueMap['injuries_count'],
      );
      if (leagueInjuriesCount == 0 && leagueMap['injuries'] is List) {
        leagueInjuriesCount = (leagueMap['injuries'] as List).length;
      }

      var leagueMatchInjuries = 0;
      final rawMatches = leagueMap['matches'];
      if (rawMatches is List) {
        final bucket = grouped.putIfAbsent(leagueId, () => <MatchModel>[]);
        for (final rawMatch in rawMatches) {
          if (rawMatch is! Map) continue;
          final matchMap = Map<String, dynamic>.from(rawMatch);
          if ((matchMap['league_id'] ?? '').toString().isEmpty &&
              leagueId.isNotEmpty) {
            matchMap['league_id'] = leagueId;
          }
          final match = MatchModel.fromJson(matchMap);
          bucket.add(match);
          computedMatches++;
          leagueMatchInjuries += match.totalMissingPlayers;
        }
      }

      final resolvedLeagueInjuries =
          leagueInjuriesCount > 0 ? leagueInjuriesCount : leagueMatchInjuries;
      if (leagueId.isNotEmpty) {
        injuriesByLeague[leagueId] = resolvedLeagueInjuries;
      }
      computedInjuries += resolvedLeagueInjuries;
    }

    final rootPlayedRaw = json['total_played_matches'];
    final rootPlayed = _parseNonNegativeInt(rootPlayedRaw);

    return BulletinData(
      generatedAt: DateTime.tryParse((json['generated_at'] ?? '').toString()),
      season: effectiveSeason,
      dataSource: effectiveDataSource,
      sourcesUsed: parsedRootSources,
      sourcesCount: effectiveSourcesCount,
      sourcesTotal: effectiveSourcesTotal,
      sourceDiagnostics: parsedDiagnostics,
      totalMatches: (json['total_matches'] as num?)?.toInt() ?? computedMatches,
      totalInjuries:
          (json['total_injuries'] as num?)?.toInt() ?? computedInjuries,
      totalPlayedMatches:
          (rootPlayedRaw != null && rootPlayed > 0)
              ? rootPlayed
              : computedPlayedMatches,
      playedMatchesByLeague: playedByLeague,
      injuriesByLeague: injuriesByLeague,
      leaguesById: parsedLeaguesById,
      matchesByLeague: grouped,
      isOfflineCache: isOfflineCache,
    );
  }
}

class BulletinApiService {
  static const String _bulletinEndpoint = '/api/v1/bulletin';
  static const String _usbReverseFallbackUrl =
      'http://127.0.0.1:7860/api/v1/bulletin';
  static const MethodChannel _storageChannel =
      MethodChannel('com.futbol.bulten/storage');
  static const String defaultCacheFileName = 'futbol_bulletin_cache.json';
  static const Map<String, String> _requestHeaders = <String, String>{
    'Accept': 'application/json',
    'Cache-Control': 'no-cache',
  };

  final http.Client _client;
  final String _apiUrl;
  final String? _cacheFilePath;
  final bool _enableOfflineCache;
  final bool _allowUsbFallback;
  final Duration timeout;

  BulletinApiService({
    http.Client? client,
    String? apiUrl,
    String? cacheFilePath,
    bool? enableOfflineCache,
    this.timeout = const Duration(seconds: 15),
  })  : _client = client ?? http.Client(),
        _apiUrl = apiUrl ?? AppConstants.apiUrl,
        _cacheFilePath = cacheFilePath,
        // shortcut: MockClient kullanan mevcut izolasyon testlerinin birbirini etkilememesi için client enjekte edildiğinde önbellek yalnızca cacheFilePath veya enableOfflineCache ile açılır.
        _enableOfflineCache =
            enableOfflineCache ?? (cacheFilePath != null || client == null),
        _allowUsbFallback = _shouldAllowUsbFallback(
          client: client,
          apiUrl: apiUrl,
        );

  bool get allowsUsbFallback => _allowUsbFallback;
  bool get isOfflineCacheEnabled => _enableOfflineCache;

  Future<File> resolveCacheFile() async {
    final explicit = _cacheFilePath?.trim();
    if (explicit != null && explicit.isNotEmpty) {
      return File(explicit);
    }
    try {
      final dir = await _storageChannel.invokeMethod<String>('getFilesDir');
      if (dir != null && dir.trim().isNotEmpty) {
        return File('${dir.trim()}/$defaultCacheFileName');
      }
    } catch (_) {
      // MissingPluginException veya binding başlatılmamış test ortamı
    }
    return File('${Directory.systemTemp.path}/$defaultCacheFileName');
  }

  Future<void> _writeCacheAtomically(String rawBody) async {
    if (!_enableOfflineCache) return;
    File? target;
    try {
      target = await resolveCacheFile();
      target.parent.createSync(recursive: true);
      final tmp = File('${target.path}.tmp');
      tmp.writeAsStringSync(rawBody, encoding: utf8, flush: true);
      tmp.renameSync(target.path);
    } catch (_) {
      if (target != null) {
        try {
          target.writeAsStringSync(rawBody, encoding: utf8, flush: true);
        } catch (_) {}
      }
    }
  }

  Future<BulletinData?> _readCachedBulletin() async {
    if (!_enableOfflineCache) return null;
    try {
      final file = await resolveCacheFile();
      if (!file.existsSync()) return null;
      final raw = file.readAsStringSync(encoding: utf8);
      if (raw.trim().isEmpty) return null;
      final decoded = jsonDecode(raw);
      if (decoded is! Map) return null;
      return BulletinData.fromJson(
        Map<String, dynamic>.from(decoded),
        isOfflineCache: true,
      );
    } catch (_) {
      return null;
    }
  }

  static bool _shouldAllowUsbFallback({
    required http.Client? client,
    required String? apiUrl,
  }) {
    if (AppConstants.hasCustomApiUrl || client != null || apiUrl != null) {
      return false;
    }
    final defaultUrl = AppConstants.apiUrl.trim().toLowerCase();
    if (defaultUrl.startsWith('https://') || defaultUrl.endsWith('.json')) {
      return false;
    }
    return defaultUrl.startsWith('http://');
  }

  Uri resolveBulletinUri([String? raw, int? cacheBusterMs]) {
    final candidate = (raw ?? _apiUrl).trim();
    final effective = candidate.isEmpty ? AppConstants.apiUrl.trim() : candidate;
    final parsed = Uri.tryParse(effective);
    final scheme = parsed?.scheme.toLowerCase() ?? '';
    if (parsed == null ||
        !parsed.hasScheme ||
        (scheme != 'http' && scheme != 'https') ||
        parsed.host.isEmpty) {
      throw BulletinApiException('Geçersiz API adresi: $effective');
    }

    final cleanPath = parsed.path.replaceAll(RegExp(r'/+$'), '');
    final isStaticJson = cleanPath.toLowerCase().endsWith('.json');
    final targetPath = isStaticJson || cleanPath.endsWith(_bulletinEndpoint)
        ? cleanPath
        : '$cleanPath$_bulletinEndpoint';

    if (isStaticJson || cacheBusterMs != null) {
      final ts =
          (cacheBusterMs ?? DateTime.now().millisecondsSinceEpoch).toString();
      return parsed.replace(
        path: targetPath,
        queryParameters: <String, String>{
          ...parsed.queryParameters,
          '_ts': ts,
        },
      );
    }

    return parsed.replace(path: targetPath);
  }

  Future<BulletinData> fetchBulletin() async {
    final uri = resolveBulletinUri(
      null,
      DateTime.now().millisecondsSinceEpoch,
    );
    http.Response response;
    try {
      final primaryTimeout =
          _allowUsbFallback ? const Duration(seconds: 3) : timeout;
      response = await _client
          .get(uri, headers: _requestHeaders)
          .timeout(primaryTimeout);
    } catch (error) {
      if (!_allowUsbFallback) {
        final cached = await _readCachedBulletin();
        if (cached != null) return cached;
        if (error is BulletinApiException) rethrow;
        throw BulletinApiException('Sunucuya ulaşılamadı: $error');
      }
      // shortcut: Yerel HTTP geliştirme sunucusuna erişilemezse USB adb reverse (127.0.0.1:7860) tünelini dener; HTTPS/statik JSON üretimde devre dışıdır.
      try {
        response = await _client
            .get(
              Uri.parse(_usbReverseFallbackUrl),
              headers: _requestHeaders,
            )
            .timeout(timeout);
      } catch (_) {
        final cached = await _readCachedBulletin();
        if (cached != null) return cached;
        if (error is BulletinApiException) rethrow;
        throw BulletinApiException('Sunucuya ulaşılamadı: $error');
      }
    }

    if (response.statusCode != 200) {
      final cached = await _readCachedBulletin();
      if (cached != null) return cached;
      throw BulletinApiException(
        'Sunucu hatası (HTTP ${response.statusCode})',
        statusCode: response.statusCode,
      );
    }

    final String bodyText;
    final dynamic decodedJson;
    try {
      bodyText = utf8.decode(response.bodyBytes);
      decodedJson = jsonDecode(bodyText);
    } catch (error) {
      final cached = await _readCachedBulletin();
      if (cached != null) return cached;
      throw BulletinApiException('Bülten JSON verisi çözümlenemedi: $error');
    }

    if (decodedJson is! Map) {
      final cached = await _readCachedBulletin();
      if (cached != null) return cached;
      throw const BulletinApiException(
        'Bülten yanıtı geçerli bir JSON nesnesi değil.',
      );
    }

    final BulletinData parsed;
    try {
      parsed = BulletinData.fromJson(
        Map<String, dynamic>.from(decodedJson),
        isOfflineCache: false,
      );
    } catch (error) {
      final cached = await _readCachedBulletin();
      if (cached != null) return cached;
      rethrow;
    }

    await _writeCacheAtomically(bodyText);
    return parsed;
  }
}
