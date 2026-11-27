import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:intl/date_symbol_data_local.dart';

import 'package:futbol_skor_bulteni/config/constants.dart';
import 'package:futbol_skor_bulteni/config/theme.dart';
import 'package:futbol_skor_bulteni/main.dart';
import 'package:futbol_skor_bulteni/models/analysis_model.dart';
import 'package:futbol_skor_bulteni/models/injury_model.dart';
import 'package:futbol_skor_bulteni/models/league_model.dart';
import 'package:futbol_skor_bulteni/models/match_model.dart';
import 'package:futbol_skor_bulteni/models/prediction_model.dart';
import 'package:futbol_skor_bulteni/screens/match_detail_screen.dart';
import 'package:futbol_skor_bulteni/services/bulletin_api_service.dart';
import 'package:futbol_skor_bulteni/widgets/analysis_section.dart';
import 'package:futbol_skor_bulteni/widgets/data_transparency_banner.dart';
import 'package:futbol_skor_bulteni/widgets/injuries_list.dart';
import 'package:futbol_skor_bulteni/widgets/match_card.dart';
import 'package:futbol_skor_bulteni/widgets/rating_comparison_bar.dart';
import 'package:futbol_skor_bulteni/widgets/score_probability_bar.dart';

String _loadRealBulletinJson() {
  final relative = File('../engine/data/bulletin_cache.json');
  if (relative.existsSync()) {
    return relative.readAsStringSync(encoding: utf8);
  }
  return File('E:/apk/futbol/engine/data/bulletin_cache.json')
      .readAsStringSync(encoding: utf8);
}

BulletinApiService _createSuccessService(List<int> bodyBytes) {
  final client = MockClient((_) async {
    return http.Response.bytes(
      bodyBytes,
      200,
      headers: const {'content-type': 'application/json; charset=utf-8'},
    );
  });
  return BulletinApiService(client: client);
}

void main() {
  late String realBulletinRaw;
  late List<int> realBulletinBytes;
  late Map<String, dynamic> realBulletinMap;

  setUpAll(() async {
    GoogleFonts.config.allowRuntimeFetching = false;
    await initializeDateFormatting('tr_TR', null);
    realBulletinRaw = _loadRealBulletinJson();
    realBulletinBytes = utf8.encode(realBulletinRaw);
    realBulletinMap = Map<String, dynamic>.from(
      jsonDecode(realBulletinRaw) as Map,
    );
  });

  group('Canlı Bülten Modelleri ve HTTP Servis Testleri', () {
    test(
      'Test 1: PredictionModel, TeamAnalysisModel, InjuryModel, MatchModel.fromJson ve resolveBulletinUri',
      () {
        final leagues = realBulletinMap['leagues'] as List<dynamic>;
        final firstLeague = Map<String, dynamic>.from(leagues.first as Map);
        final firstMatchRaw = Map<String, dynamic>.from(
          (firstLeague['matches'] as List<dynamic>).first as Map,
        );

        final prediction = PredictionModel.fromJson(
          Map<String, dynamic>.from(firstMatchRaw['prediction'] as Map),
        );
        expect(prediction.formattedScore, contains(' - '));
        expect(prediction.htScoreDisplay, startsWith('İY '));
        expect(prediction.ftScoreDisplay, startsWith('MS '));
        expect(prediction.htFtPrediction, contains('/'));
        expect(prediction.confidencePercentage, inInclusiveRange(1, 100));
        expect(
          prediction.confidenceLabel,
          'Model Netliği: %${prediction.confidencePercentage}',
        );
        expect(prediction.confidenceLabel.contains('Güven'), isFalse);
        expect(prediction.topScores.length, 3);

        final analysis = TeamAnalysisModel.fromJson(
          Map<String, dynamic>.from(firstMatchRaw['team_analysis'] as Map),
        );
        expect(analysis.matchOverviewText, isNotEmpty);
        expect(analysis.homeOffenseRating, greaterThan(0));
        expect(analysis.awayDefenseRating, greaterThan(0));

        final homeInjuriesRaw = firstMatchRaw['home_injuries'] as List<dynamic>;
        if (homeInjuriesRaw.isNotEmpty) {
          final injury = InjuryModel.fromJson(
            Map<String, dynamic>.from(homeInjuriesRaw.first as Map),
          );
          expect(injury.playerName, isNotEmpty);
          expect(PlayerPosition.values, contains(injury.position));
          expect(ImpactLevel.values, contains(injury.impactLevel));
          expect(injury.formattedReturnDate, isNotEmpty);
        }

        final match = MatchModel.fromJson(firstMatchRaw);
        expect(match.id, greaterThan(0));
        expect(match.leagueId, (firstLeague['id'] ?? 'super_lig').toString());
        expect(
          match.homeTeam.name,
          (firstMatchRaw['home_team'] as Map)['name'],
        );
        expect(
          match.awayTeam.name,
          (firstMatchRaw['away_team'] as Map)['name'],
        );
        expect(
          match.totalMissingPlayers,
          match.homeInjuries.length + match.awayInjuries.length,
        );

        expect(
          AppConstants.apiUrl,
          'https://naziffarm4.github.io/futbol-skor-analiz/bulletin.json',
        );
        expect(
          AppConstants.apiBaseUrl,
          'https://naziffarm4.github.io/futbol-skor-analiz/bulletin.json',
        );

        final service = BulletinApiService();
        expect(service.allowsUsbFallback, isFalse);
        expect(
          service.resolveBulletinUri(null, 1700000000000).toString(),
          'https://naziffarm4.github.io/futbol-skor-analiz/bulletin.json?_ts=1700000000000',
        );
        expect(
          service.resolveBulletinUri('https://example.hf.space').toString(),
          'https://example.hf.space/api/v1/bulletin',
        );
        expect(
          service.resolveBulletinUri('https://example.hf.space/').toString(),
          'https://example.hf.space/api/v1/bulletin',
        );
        expect(
          service
              .resolveBulletinUri('http://127.0.0.1:7860/api/v1/bulletin')
              .toString(),
          'http://127.0.0.1:7860/api/v1/bulletin',
        );
      },
    );

    test(
      'Test 2: Gerçek bulletin_cache.json ile fetchBulletin 4 lig, maçları ve sakatlıkları ayrıştırır',
      () async {
        final service = _createSuccessService(realBulletinBytes);
        final bulletin = await service.fetchBulletin();

        expect(bulletin.totalMatches, greaterThan(0));
        expect(bulletin.totalInjuries, greaterThan(0));

        const expectedLeagueIds = <String>[
          'super_lig',
          'premier_league',
          'la_liga',
          'ligue_1',
        ];
        var parsedMatchesCount = 0;
        var parsedInjuriesCount = 0;

        for (final leagueId in expectedLeagueIds) {
          final matches = bulletin.matchesByLeague[leagueId];
          expect(matches, isNotNull);
          expect(matches, isNotEmpty);
          parsedMatchesCount += matches!.length;
          for (final m in matches) {
            parsedInjuriesCount += m.totalMissingPlayers;
          }
        }

        final rawMap = jsonDecode(realBulletinRaw) as Map<String, dynamic>;
        expect(parsedMatchesCount, rawMap['total_matches']);
        expect(bulletin.totalInjuries, rawMap['total_injuries']);
        expect(parsedInjuriesCount, greaterThan(0));
      },
    );

    test(
      'Test 8: GÖREV-09 statik .json ve klasik FastAPI URL çözümleme ile CDN önbellek kırma (_ts)',
      () {
        final service = BulletinApiService(
          apiUrl: 'https://user.github.io/futbol/bulletin.json',
        );
        expect(service.allowsUsbFallback, isFalse);

        final explicitTsUri = service.resolveBulletinUri(
          'https://user.github.io/futbol/bulletin.json',
          1700000000000,
        );
        expect(explicitTsUri.path, '/futbol/bulletin.json');
        expect(explicitTsUri.queryParameters['_ts'], '1700000000000');
        expect(
          explicitTsUri.toString(),
          'https://user.github.io/futbol/bulletin.json?_ts=1700000000000',
        );

        final mergedQueryUri = service.resolveBulletinUri(
          'https://user.github.io/futbol/bulletin.json/?env=prod',
          1700000000000,
        );
        expect(mergedQueryUri.path, '/futbol/bulletin.json');
        expect(mergedQueryUri.queryParameters['env'], 'prod');
        expect(mergedQueryUri.queryParameters['_ts'], '1700000000000');

        final autoTsUri = service.resolveBulletinUri(
          'https://user.github.io/futbol/bulletin.json',
        );
        expect(autoTsUri.path, '/futbol/bulletin.json');
        final parsedAutoTs =
            int.tryParse(autoTsUri.queryParameters['_ts'] ?? '');
        expect(parsedAutoTs, isNotNull);
        expect(parsedAutoTs, greaterThan(0));

        expect(
          service.resolveBulletinUri('https://example.hf.space').toString(),
          'https://example.hf.space/api/v1/bulletin',
        );
      },
    );

    test(
      'Test 9: GÖREV-09 GitHub Pages statik .json fetchBulletin başlıkları, ayrıştırma ve USB yedek devre dışılığı',
      () async {
        const cloudJsonUrl = 'https://user.github.io/futbol/bulletin.json';
        final capturedRequests = <http.Request>[];

        final okClient = MockClient((request) async {
          capturedRequests.add(request);
          return http.Response.bytes(
            realBulletinBytes,
            200,
            headers: const {'content-type': 'application/json; charset=utf-8'},
          );
        });

        final okService = BulletinApiService(
          client: okClient,
          apiUrl: cloudJsonUrl,
        );
        expect(okService.allowsUsbFallback, isFalse);

        final bulletin = await okService.fetchBulletin();
        expect(capturedRequests, hasLength(1));
        final req = capturedRequests.single;
        expect(req.url.scheme, 'https');
        expect(req.url.host, 'user.github.io');
        expect(req.url.path, '/futbol/bulletin.json');
        expect(
          int.tryParse(req.url.queryParameters['_ts'] ?? ''),
          greaterThan(0),
        );
        expect(req.headers['Cache-Control'], 'no-cache');
        expect(req.headers['Accept'], 'application/json');
        expect(bulletin.totalMatches, realBulletinMap['total_matches']);
        expect(bulletin.matchesByLeague['super_lig'], isNotEmpty);
        expect(bulletin.matchesByLeague['ligue_1'], isNotEmpty);

        final failedUris = <Uri>[];
        final failingClient = MockClient((request) async {
          failedUris.add(request.url);
          throw const SocketException('GitHub Pages CDN erişim hatası');
        });
        final failingService = BulletinApiService(
          client: failingClient,
          apiUrl: cloudJsonUrl,
        );
        expect(failingService.allowsUsbFallback, isFalse);

        await expectLater(
          failingService.fetchBulletin(),
          throwsA(isA<BulletinApiException>()),
        );
        expect(failedUris, hasLength(1));
        expect(failedUris.single.host, 'user.github.io');
        expect(failedUris.any((u) => u.host == '127.0.0.1'), isFalse);
      },
    );

    test(
      'Test 10: GÖREV-11 Dinamik sezon hesaplama (Haziran -> önceki sezon, Temmuz -> yeni sezon)',
      () {
        expect(
          AppConstants.computeCurrentSeason(DateTime(2026, 6, 30)),
          '2025-2026',
        );
        expect(
          AppConstants.computeCurrentSeason(DateTime(2025, 1, 15)),
          '2024-2025',
        );
        expect(
          AppConstants.computeCurrentSeason(DateTime(2026, 7, 1)),
          '2026-2027',
        );
        expect(
          AppConstants.computeCurrentSeason(DateTime(2027, 11, 20)),
          '2027-2028',
        );
        expect(AppConstants.defaultSeason, AppConstants.computeCurrentSeason());

        final leagueWithoutSeason = LeagueModel.fromJson(const {
          'id': 'super_lig',
          'name': 'Süper Lig',
          'country': 'Türkiye',
        });
        expect(leagueWithoutSeason.season, AppConstants.defaultSeason);
      },
    );

    test(
      'Test 11: GÖREV-11 5 kaynak füzyonu, İY/MS olasılıkları ve çoklu kaynaklı sakatlık ayrıştırma',
      () {
        final season = AppConstants.defaultSeason;
        const fiveSources = <String>[
          'ESPN',
          'Football-Data',
          'Understat',
          'Transfermarkt',
          'SportsGambler',
        ];

        final v2Payload = <String, dynamic>{
          'data_source':
              '5 Kaynak Füzyonu (ESPN, Football-Data, Understat, Transfermarkt, SportsGambler)',
          'sources_used': fiveSources,
          'sources_count': 5,
          'sources_total': 5,
          'source_diagnostics': <String, dynamic>{
            'ESPN': <String, dynamic>{'status': 'ok'},
            'Transfermarkt': <String, dynamic>{'status': 'ok'},
          },
          'generated_at': '2026-11-27T18:00:00Z',
          'season': season,
          'total_matches': 1,
          'total_injuries': 55,
          'total_played_matches': 450,
          'leagues': <Map<String, dynamic>>[
            <String, dynamic>{
              'id': 'super_lig',
              'name': 'Süper Lig',
              'country': 'Turkey',
              'season': season,
              'played_matches_count': 117,
              'injuries_count': 55,
              'sources_used': fiveSources,
              'sources_count': 5,
              'sources_total': 5,
              'matches': <Map<String, dynamic>>[
                <String, dynamic>{
                  'id': 101,
                  'league_id': 'super_lig',
                  'round': 14,
                  'match_date': '2026-11-29T16:00:00Z',
                  'home_team': <String, dynamic>{
                    'id': 1,
                    'name': 'Galatasaray',
                    'short_name': 'GS',
                  },
                  'away_team': <String, dynamic>{
                    'id': 2,
                    'name': 'Eyüpspor',
                    'short_name': 'EYP',
                  },
                  'prediction': <String, dynamic>{
                    'id': 1,
                    'match_id': 101,
                    'predicted_ht_home_score': 1,
                    'predicted_ht_away_score': 0,
                    'predicted_home_score': 2,
                    'predicted_away_score': 1,
                    'ht_ft_prediction': '1/1',
                    'confidence_rate': 64.5,
                    'top_scores_json': <Map<String, dynamic>>[
                      <String, dynamic>{'score': '2-1', 'prob': 0.145},
                      <String, dynamic>{'score': '1-0', 'prob': 0.118},
                      <String, dynamic>{'score': '2-0', 'prob': 0.102},
                    ],
                    'top_ht_ft_json': <Map<String, dynamic>>[
                      <String, dynamic>{
                        'code': '1/1',
                        'label': 'Ev / Ev',
                        'prob': 0.342,
                      },
                      <String, dynamic>{
                        'code': 'X/1',
                        'label': 'Beraberlik / Ev',
                        'prob': 0.198,
                      },
                      <String, dynamic>{
                        'code': 'X/X',
                        'label': 'Beraberlik / Beraberlik',
                        'prob': 0.141,
                      },
                    ],
                  },
                  'team_analysis': <String, dynamic>{
                    'id': 1,
                    'match_id': 101,
                    'match_overview_text': 'Ev sahibi üstün.',
                    'ht_ft_reasoning_text':
                        'İlk yarı önde başlangıç ve ikinci yarı skor koruma senaryosu öne çıkıyor.',
                    'home_analysis_text': 'Ev sahibi iç saha baskısı yüksek.',
                    'away_analysis_text': 'Deplasman geçiş arıyor.',
                    'home_offense_rating': 74.2,
                    'home_defense_rating': 68.5,
                    'away_offense_rating': 61.0,
                    'away_defense_rating': 58.3,
                  },
                  'home_injuries': <Map<String, dynamic>>[
                    <String, dynamic>{
                      'id': 10,
                      'team_id': 1,
                      'player_name': 'Mauro Icardi',
                      'position': 'FW',
                      'reason': 'Çapraz bağ yırtığı',
                      'return_date': '2027-03-01',
                      'impact_level': 'HIGH',
                      'verified_by_multiple_sources': true,
                      'sources': <String>['Transfermarkt', 'SportsGambler'],
                    },
                  ],
                  'away_injuries': const <dynamic>[],
                },
              ],
            },
          ],
        };

        final bulletin = BulletinData.fromJson(v2Payload);
        expect(bulletin.sourcesUsed, fiveSources);
        expect(bulletin.sourcesCount, 5);
        expect(bulletin.sourcesTotal, 5);
        expect(bulletin.sourceDiagnostics, contains('ESPN'));

        final league = bulletin.leaguesById['super_lig']!;
        expect(league.sourcesUsed, fiveSources);
        expect(league.sourcesCount, 5);
        expect(league.sourcesTotal, 5);
        expect(bulletin.effectiveInjuriesCount('super_lig'), 55);

        final match = bulletin.matchesByLeague['super_lig']!.single;
        expect(match.prediction.predictedHtHomeScore, 1);
        expect(match.prediction.predictedHtAwayScore, 0);
        expect(match.prediction.htFtPrediction, '1/1');
        expect(match.prediction.htScoreDisplay, 'İY 1 - 0');
        expect(match.prediction.ftScoreDisplay, 'MS 2 - 1');
        expect(match.prediction.compactHtFtBadge, 'İY 1-0 • İY/MS: 1/1');
        expect(match.prediction.topHtFt, hasLength(3));
        expect(match.prediction.topHtFt.first.code, '1/1');
        expect(match.prediction.topHtFt.first.label, 'Ev / Ev');
        expect(match.prediction.topHtFt.first.percentText, '%34.2');
        expect(
          match.analysis.htFtReasoningText,
          contains('İlk yarı önde başlangıç'),
        );
        expect(match.homeInjuries.single.verifiedByMultipleSources, isTrue);
        expect(
          match.homeInjuries.single.sources,
          equals(<String>['Transfermarkt', 'SportsGambler']),
        );

        // ht_ft_prediction eksik olduğunda İY ve MS skorlarından otomatik türetme kontrolü
        final fallbackPred = PredictionModel.fromJson(const {
          'predicted_ht_home_score': 0,
          'predicted_ht_away_score': 0,
          'predicted_home_score': 2,
          'predicted_away_score': 1,
        });
        expect(fallbackPred.htFtPrediction, 'X/1');
      },
    );
  });

  group('Canlı Bülten UI, Hata Yönetimi ve Duyarlılık Testleri', () {
    testWidgets(
      'Test 3: HTTP 500 veya ağ hatasında sahte veri göstermez, yeniden denemede canlı veriyi yükler',
      (WidgetTester tester) async {
        var attempt = 0;
        final client = MockClient((_) async {
          attempt++;
          if (attempt == 1) {
            return http.Response('Internal Server Error', 500);
          }
          if (attempt == 2) {
            throw const SocketException('Bağlantı reddedildi');
          }
          return http.Response.bytes(
            realBulletinBytes,
            200,
            headers: const {'content-type': 'application/json; charset=utf-8'},
          );
        });

        final service = BulletinApiService(client: client);

        final firstLeague =
            (realBulletinMap['leagues'] as List<dynamic>).first as Map;
        final firstMatch =
            (firstLeague['matches'] as List<dynamic>).first as Map;
        final expectedHomeName =
            (firstMatch['home_team'] as Map)['name'].toString();
        final expectedAwayName =
            (firstMatch['away_team'] as Map)['name'].toString();

        await tester.pumpWidget(FutbolBulteniApp(service: service));
        await tester.pumpAndSettle();

        expect(
          find.text('Sunucuya bağlanılamadı, tekrar dene'),
          findsOneWidget,
        );
        expect(
          find.byKey(const ValueKey('retry_bulletin_button')),
          findsOneWidget,
        );
        expect(find.byType(MatchCard), findsNothing);
        expect(find.text('Canlı'), findsNothing);

        await tester.tap(find.byKey(const ValueKey('retry_bulletin_button')));
        await tester.pumpAndSettle();
        expect(
          find.text('Sunucuya bağlanılamadı, tekrar dene'),
          findsOneWidget,
        );
        expect(find.byType(MatchCard), findsNothing);

        await tester.tap(find.byKey(const ValueKey('retry_bulletin_button')));
        await tester.pumpAndSettle();
        expect(
          find.text('Sunucuya bağlanılamadı, tekrar dene'),
          findsNothing,
        );
        expect(find.text('Canlı'), findsOneWidget);
        expect(find.byType(MatchCard), findsWidgets);
        expect(find.text(expectedHomeName), findsWidgets);
        expect(find.text(expectedAwayName), findsWidgets);
      },
    );

    testWidgets(
      'Test 4: 4 lig sekmesi geçişleri ve MatchDetailScreen tüm analiz/sakatlık bileşenleriyle açılır',
      (WidgetTester tester) async {
        final service = _createSuccessService(realBulletinBytes);
        final bulletin = await service.fetchBulletin();

        await tester.pumpWidget(FutbolBulteniApp(service: service));
        await tester.pumpAndSettle();

        expect(find.text(AppConstants.appTitle), findsOneWidget);
        expect(find.text('Canlı'), findsOneWidget);

        for (final league in AppConstants.supportedLeagues) {
          final tabFinder = find.byKey(ValueKey('league_tab_${league.id}'));
          await tester.ensureVisible(tabFinder);
          await tester.tap(tabFinder);
          await tester.pumpAndSettle();

          final firstMatch = bulletin.matchesByLeague[league.id]!.first;
          expect(find.byType(MatchCard), findsWidgets);
          expect(find.text(firstMatch.homeTeam.name), findsWidgets);
          expect(find.text(firstMatch.awayTeam.name), findsWidgets);
        }

        final superLigTab = find.byKey(
          const ValueKey('league_tab_super_lig'),
        );
        await tester.ensureVisible(superLigTab);
        await tester.tap(superLigTab);
        await tester.pumpAndSettle();

        final firstSuperLigMatch = bulletin.matchesByLeague['super_lig']!.first;
        await tester.tap(
          find.byKey(ValueKey('match_card_${firstSuperLigMatch.id}')),
        );
        await tester.pumpAndSettle();

        expect(find.byType(MatchDetailScreen), findsOneWidget);
        expect(find.text('ANA SKOR TAHMİNİ'), findsOneWidget);
        expect(find.byType(ScoreProbabilityBar), findsOneWidget);
        expect(find.byType(AnalysisSection), findsOneWidget);

        final detailScroll = find.byKey(const ValueKey('match_detail_scroll'));
        await tester.drag(detailScroll, const Offset(0, -500));
        await tester.pumpAndSettle();
        expect(find.byType(RatingComparisonBar), findsOneWidget);

        await tester.drag(detailScroll, const Offset(0, -600));
        await tester.pumpAndSettle();
        expect(find.byType(InjuriesList), findsOneWidget);
        if (firstSuperLigMatch.homeInjuries.isNotEmpty) {
          expect(
            find.text(firstSuperLigMatch.homeInjuries.first.playerName),
            findsOneWidget,
          );
        }
      },
    );

    testWidgets(
      'Test 5: Dar telefon ekranında (360x800) ana ekran ve detay ekranı taşma olmadan render edilir',
      (WidgetTester tester) async {
        tester.view.physicalSize = const Size(360, 800);
        tester.view.devicePixelRatio = 1.0;
        addTearDown(() {
          tester.view.resetPhysicalSize();
          tester.view.resetDevicePixelRatio();
        });

        final service = _createSuccessService(realBulletinBytes);
        final bulletin = await service.fetchBulletin();
        final firstMatch = bulletin.matchesByLeague['super_lig']!.first;

        await tester.pumpWidget(FutbolBulteniApp(service: service));
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
        expect(find.byType(MatchCard), findsWidgets);
        expect(find.textContaining('Model Netliği: %'), findsWidgets);
        expect(
          find.text(
            'İstatistiksel analiz amaçlıdır; kesin sonuç garantisi veya bahis tavsiyesi değildir.',
          ),
          findsOneWidget,
        );

        await tester.tap(find.byKey(ValueKey('match_card_${firstMatch.id}')));
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
        expect(find.byType(MatchDetailScreen), findsOneWidget);
        expect(find.byType(ScoreProbabilityBar), findsOneWidget);
        expect(find.textContaining('Model Netliği: %'), findsWidgets);
        expect(
          find.text(
            'İstatistiksel analiz amaçlıdır; kesin sonuç garantisi veya bahis tavsiyesi değildir.',
          ),
          findsOneWidget,
        );

        final detailScroll = find.byKey(const ValueKey('match_detail_scroll'));
        await tester.drag(detailScroll, const Offset(0, -700));
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
        expect(find.byType(InjuriesList), findsOneWidget);
      },
    );

    test(
      'Test 6: GÖREV-08 BulletinData yeni JSON alanları, eski JSON varsayılanları ve paragraf ayrıştırma',
      () {
        final season = AppConstants.defaultSeason;
        final legacyPayload = <String, dynamic>{
          'generated_at': '2026-11-26T18:15:00Z',
          'season': season,
          'leagues': <Map<String, dynamic>>[
            <String, dynamic>{
              'id': 'super_lig',
              'matches': <dynamic>[],
            },
          ],
        };
        final legacyData = BulletinData.fromJson(legacyPayload);
        expect(legacyData.dataSource, 'Transfermarkt');
        expect(legacyData.sourcesUsed, equals(<String>['Transfermarkt']));
        expect(legacyData.sourcesCount, 1);
        expect(legacyData.sourcesTotal, 5);
        expect(legacyData.totalPlayedMatches, 0);
        expect(legacyData.playedMatchesByLeague['super_lig'], 0);
        expect(legacyData.effectivePlayedMatches('super_lig'), 0);

        final contractPayload = <String, dynamic>{
          'data_source': 'Transfermarkt',
          'generated_at': '2026-11-26T18:15:00Z',
          'season': season,
          'leagues': <Map<String, dynamic>>[
            <String, dynamic>{
              'id': 'super_lig',
              'played_matches_count': 108,
              'matches': <dynamic>[],
            },
            <String, dynamic>{
              'id': 'premier_league',
              'played_matches_count': 120,
              'matches': <dynamic>[],
            },
          ],
        };
        final contractData = BulletinData.fromJson(contractPayload);
        expect(contractData.dataSource, 'Transfermarkt');
        expect(contractData.playedMatchesByLeague['super_lig'], 108);
        expect(contractData.playedMatchesByLeague['premier_league'], 120);
        expect(contractData.totalPlayedMatches, 228);
        expect(contractData.effectivePlayedMatches('super_lig'), 108);
        expect(contractData.effectivePlayedMatches('la_liga'), 228);

        final localSample = DateTime(2026, 11, 26, 21, 15);
        expect(
          AppConstants.formatShortTimestampTr(localSample),
          '26 Kas 21:15',
        );

        final paragraphs = AnalysisSection.splitParagraphs(
          'İlk paragraf taktik özeti.\n\nİkinci paragraf kadro ve form detayı.',
        );
        expect(paragraphs, hasLength(2));
        expect(
          AnalysisSection.splitParagraphs('Tek paragraf metni.'),
          hasLength(1),
        );
      },
    );

    testWidgets(
      'Test 7: 360x800 dar ekranda 5/5 Kaynak Doğruladı, İY/MS rozeti, En Olası 3 İY/MS, Neden Bu İY/MS ve Onaylı rozeti sıfır taşma ile görünür',
      (WidgetTester tester) async {
        tester.view.physicalSize = const Size(360, 800);
        tester.view.devicePixelRatio = 1.0;
        addTearDown(() {
          tester.view.resetPhysicalSize();
          tester.view.resetDevicePixelRatio();
        });

        final season = AppConstants.defaultSeason;
        const fiveSources = <String>[
          'ESPN',
          'Football-Data',
          'Understat',
          'Transfermarkt',
          'SportsGambler',
        ];

        final enrichedMap = jsonDecode(realBulletinRaw) as Map<String, dynamic>;
        enrichedMap['data_source'] =
            '5 Kaynak Füzyonu (ESPN, Football-Data, Understat, Transfermarkt, SportsGambler)';
        enrichedMap['sources_used'] = fiveSources;
        enrichedMap['sources_count'] = 5;
        enrichedMap['sources_total'] = 5;
        enrichedMap['generated_at'] = '2026-11-27T18:15:00Z';
        enrichedMap['season'] = season;
        enrichedMap['total_played_matches'] = 450;

        final leagues = enrichedMap['leagues'] as List<dynamic>;
        for (var i = 0; i < leagues.length; i++) {
          final league = leagues[i] as Map<String, dynamic>;
          league['season'] = season;
          league['played_matches_count'] = i == 0 ? 117 : 114;
          league['injuries_count'] = i == 0 ? 55 : 42;
          league['sources_used'] = fiveSources;
          league['sources_count'] = 5;
          league['sources_total'] = 5;
        }

        final firstLeagueMatches =
            (leagues.first as Map<String, dynamic>)['matches'] as List<dynamic>;
        final firstMatchMap = firstLeagueMatches.first as Map<String, dynamic>;
        final firstMatchId = (firstMatchMap['id'] as num).toInt();

        final predictionMap =
            firstMatchMap['prediction'] as Map<String, dynamic>;
        predictionMap['predicted_ht_home_score'] = 1;
        predictionMap['predicted_ht_away_score'] = 0;
        predictionMap['predicted_home_score'] = 2;
        predictionMap['predicted_away_score'] = 1;
        predictionMap['ht_ft_prediction'] = '1/1';
        predictionMap['confidence_rate'] = 64.5;
        predictionMap['top_ht_ft_json'] = <Map<String, dynamic>>[
          <String, dynamic>{'code': '1/1', 'label': 'Ev / Ev', 'prob': 0.342},
          <String, dynamic>{
            'code': 'X/1',
            'label': 'Beraberlik / Ev',
            'prob': 0.198,
          },
          <String, dynamic>{
            'code': 'X/X',
            'label': 'Beraberlik / Beraberlik',
            'prob': 0.141,
          },
        ];

        final teamAnalysis =
            firstMatchMap['team_analysis'] as Map<String, dynamic>;
        teamAnalysis['match_overview_text'] =
            'Poisson dağılımı ve saha içi güç dengesi ev sahibini bir adım öne çıkarıyor.\n\nSon haftalardaki gol beklentisi ve geçiş hücumu verimliliği bu skoru destekliyor.';
        teamAnalysis['ht_ft_reasoning_text'] =
            'Ev sahibi ilk 45 dakikada yüksek ön alan baskısıyla erken gol bulma eğiliminde.\n\nİkinci yarıda ise topa sahip olma üstünlüğüyle 1/1 senaryosunu koruma olasılığı yüksek.';
        teamAnalysis['home_analysis_text'] =
            'Ev sahibi iç sahada yüksek baskı ve kenar ortalarıyla pozisyon üretiyor.\n\nSavunma hattındaki yerleşim disiplini rakibe az net şans tanıyor.';
        teamAnalysis['away_analysis_text'] =
            'Deplasman ekibi hızlı hücumlarla skora tutunmayı hedefliyor.\n\nEksik oyuncular orta saha direncini kısmen sınırlayabilir.';

        firstMatchMap['home_injuries'] = <Map<String, dynamic>>[
          <String, dynamic>{
            'id': 10,
            'team_id': 1,
            'player_name': 'Mauro Emanuel Icardi Rivero',
            'position': 'FW',
            'reason': 'Çapraz bağ yırtığı',
            'return_date': '2027-03-01',
            'impact_level': 'HIGH',
            'verified_by_multiple_sources': true,
            'sources': <String>['Transfermarkt', 'SportsGambler'],
          },
        ];

        final enrichedBytes = utf8.encode(jsonEncode(enrichedMap));
        final service = _createSuccessService(enrichedBytes);

        await tester.pumpWidget(FutbolBulteniApp(service: service));
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);

        // HomeScreen 5/5 Kaynak Doğruladı + aktif kaynaklar + kompakt İY/MS rozeti
        expect(find.byType(DataTransparencyBanner), findsOneWidget);
        expect(find.text('5/5 Kaynak Doğruladı'), findsOneWidget);
        expect(
          find.textContaining(
            'ESPN, Football-Data, Understat, Transfermarkt, SportsGambler',
          ),
          findsOneWidget,
        );
        expect(find.text('Sezon: $season'), findsOneWidget);
        expect(find.text('117 gerçek maç analizi'), findsOneWidget);
        expect(find.text('55 eksik kaydı'), findsOneWidget);
        expect(find.textContaining('Güncelleme:'), findsOneWidget);
        expect(find.text('İY 1-0 • İY/MS: 1/1'), findsOneWidget);
        expect(find.text('Model Netliği: %65'), findsWidgets);
        expect(
          find.text(AppConstants.statisticalDisclaimer),
          findsOneWidget,
        );

        // Detay ekranına geçiş (360x800)
        await tester.tap(find.byKey(ValueKey('match_card_$firstMatchId')));
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);

        // Hero kartında İY, MS ve İY/MS rozetleri + En Olası 3 İY/MS kartı
        expect(find.text('İY 1 - 0'), findsOneWidget);
        expect(find.text('MS 2 - 1'), findsOneWidget);
        expect(find.text('İY/MS: 1/1'), findsWidgets);
        expect(find.text('Model Netliği: %65'), findsWidgets);
        expect(find.byType(HtFtProbabilityBar), findsOneWidget);
        expect(find.text('En Olası 3 İY/MS Senaryosu'), findsOneWidget);
        expect(find.text('Ev / Ev'), findsOneWidget);
        expect(find.text('%34.2'), findsOneWidget);
        expect(find.text('Beraberlik / Ev'), findsOneWidget);
        expect(find.text('%19.8'), findsOneWidget);

        // Analiz kartlarına kaydırma
        final detailScroll = find.byKey(const ValueKey('match_detail_scroll'));
        await tester.drag(detailScroll, const Offset(0, -450));
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);

        expect(find.text('Neden Bu Skor?'), findsOneWidget);
        expect(
          find.text('Kapsamlı Durum Değerlendirmesi & Neden Bu İY/MS?'),
          findsOneWidget,
        );
        expect(
          find.textContaining('Ev sahibi ilk 45 dakikada yüksek ön alan'),
          findsOneWidget,
        );

        // Sakatlıklar ve en alttaki şeffaflık kartına kaydırma
        await tester.drag(detailScroll, const Offset(0, -1300));
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);

        expect(find.text('✓ Onaylı'), findsOneWidget);
        expect(
          find.byKey(const ValueKey('detail_transparency_banner')),
          findsOneWidget,
        );
        expect(find.text('5/5 Kaynak Doğruladı'), findsOneWidget);
        expect(
          find.text(AppConstants.statisticalDisclaimer),
          findsOneWidget,
        );
      },
    );

    test(
      'Test 12: GÖREV-13 PredictionModel 9 senaryolu all_ht_ft_json, 1X2/Üst-Alt/KG harmanı ve eski JSON yedekleme uyumluluğu',
      () {
        final fullPred = PredictionModel.fromJson(const <String, dynamic>{
          'id': 1,
          'match_id': 1,
          'predicted_home_score': 2,
          'predicted_away_score': 1,
          'predicted_ht_home_score': 1,
          'predicted_ht_away_score': 0,
          'ht_ft_prediction': '1/1',
          'top_ht_ft_json': <Map<String, dynamic>>[
            <String, dynamic>{'code': '1/1', 'label': 'Ev / Ev', 'prob': 0.362},
            <String, dynamic>{
              'code': 'X/1',
              'label': 'Beraberlik / Ev',
              'prob': 0.184,
            },
            <String, dynamic>{
              'code': 'X/X',
              'label': 'Beraberlik / Beraberlik',
              'prob': 0.141,
            },
          ],
          'all_ht_ft_json': <Map<String, dynamic>>[
            <String, dynamic>{'code': '1/1', 'label': 'Ev / Ev', 'prob': 0.362},
            <String, dynamic>{
              'code': 'X/1',
              'label': 'Beraberlik / Ev',
              'prob': 0.184,
            },
            <String, dynamic>{
              'code': 'X/X',
              'label': 'Beraberlik / Beraberlik',
              'prob': 0.141,
            },
            <String, dynamic>{
              'code': '2/2',
              'label': 'Dep / Dep',
              'prob': 0.095,
            },
            <String, dynamic>{
              'code': '1/X',
              'label': 'Ev / Beraberlik',
              'prob': 0.068,
            },
            <String, dynamic>{
              'code': 'X/2',
              'label': 'Beraberlik / Dep',
              'prob': 0.062,
            },
            <String, dynamic>{
              'code': '2/X',
              'label': 'Dep / Beraberlik',
              'prob': 0.041,
            },
            <String, dynamic>{
              'code': '2/1',
              'label': 'Dep / Ev',
              'prob': 0.026,
            },
            <String, dynamic>{
              'code': '1/2',
              'label': 'Ev / Dep',
              'prob': 0.021,
            },
          ],
          'p_home': 0.572,
          'p_draw': 0.250,
          'p_away': 0.178,
          'p_over25': 0.585,
          'p_under25': 0.415,
          'p_btts_yes': 0.542,
          'p_btts_no': 0.458,
          'market_blended': true,
          'confidence_rate': 0.42,
          'top_scores_json': <Map<String, dynamic>>[
            <String, dynamic>{'score': '2-1', 'prob': 0.142},
            <String, dynamic>{'score': '1-0', 'prob': 0.118},
            <String, dynamic>{'score': '1-1', 'prob': 0.109},
          ],
        });

        expect(fullPred.allHtFt, hasLength(9));
        for (final code in PredictionModel.canonicalHtFtCodes) {
          final opt = fullPred.htFtProbFor(code);
          expect(opt.code, code);
          expect(opt.prob, greaterThan(0.0));
        }
        expect(fullPred.bestHtFt.code, '1/1');
        expect(fullPred.bestHtFt.percentText, '%36.2');
        expect(fullPred.htFtOptionFor('2/1').percentText, '%2.6');
        expect(fullPred.htFtOptionFor('1/2').percentText, '%2.1');
        expect(fullPred.pHomeText, '%57.2');
        expect(fullPred.pDrawText, '%25.0');
        expect(fullPred.pAwayText, '%17.8');
        expect(fullPred.pOver25Text, '%58.5');
        expect(fullPred.pUnder25Text, '%41.5');
        expect(fullPred.pBttsYesText, '%54.2');
        expect(fullPred.pBttsNoText, '%45.8');
        expect(fullPred.marketBlended, isTrue);
        expect(fullPred.bestHtFtBadge, 'İY/MS 1/1 %36');
        expect(fullPred.compactProbSummary, 'İY/MS 1/1 %36 • 1:%57 X:%25 2:%18');

        // Eski önbellek JSON (all_ht_ft_json ve p_home/p_over25/p_btts_yes eksik)
        final legacyPred = PredictionModel.fromJson(const <String, dynamic>{
          'id': 9,
          'match_id': 99,
          'predicted_ht_home_score': 1,
          'predicted_ht_away_score': 0,
          'predicted_home_score': 2,
          'predicted_away_score': 0,
          'confidence_rate': 0.51,
        });

        expect(legacyPred.allHtFt, hasLength(9));
        for (final code in PredictionModel.canonicalHtFtCodes) {
          expect(legacyPred.htFtProbFor(code).prob, greaterThan(0.0));
        }
        expect(legacyPred.pHome, greaterThan(legacyPred.pAway));
        expect(legacyPred.pHomeShort, isNot('%0'));
        expect(legacyPred.pDrawShort, isNot('%0'));
        expect(legacyPred.pAwayShort, isNot('%0'));
        expect(
          (legacyPred.pHome + legacyPred.pDraw + legacyPred.pAway),
          closeTo(1.0, 1e-6),
        );
        expect(
          (legacyPred.pOver25 + legacyPred.pUnder25),
          closeTo(1.0, 1e-6),
        );
        expect(
          (legacyPred.pBttsYes + legacyPred.pBttsNo),
          closeTo(1.0, 1e-6),
        );
        expect(legacyPred.marketBlended, isFalse);

        // cacheFilePath enjeksiyonu ve varsayılan systemTemp yedeklemesi kontrolü
        final customCacheService = BulletinApiService(
          cacheFilePath: '${Directory.systemTemp.path}/custom_bulten_test.json',
        );
        expect(customCacheService.isOfflineCacheEnabled, isTrue);
      },
    );

    testWidgets(
      'Test 13: 360x800 ekranda MatchCard 1/X/2 + İY/MS yüzdelerini ve MatchDetailScreen Olasılık Özeti + 3x3 İY/MS matrisini taşmasız çizer',
      (WidgetTester tester) async {
        tester.view.physicalSize = const Size(360, 800);
        tester.view.devicePixelRatio = 1.0;
        addTearDown(() {
          tester.view.resetPhysicalSize();
          tester.view.resetDevicePixelRatio();
        });

        final payload = jsonDecode(realBulletinRaw) as Map<String, dynamic>;
        final firstLeague =
            (payload['leagues'] as List<dynamic>).first as Map<String, dynamic>;
        final firstMatch = (firstLeague['matches'] as List<dynamic>).first
            as Map<String, dynamic>;
        final firstMatchId = (firstMatch['id'] as num).toInt();
        firstMatch['prediction'] = <String, dynamic>{
          'id': 1,
          'match_id': firstMatchId,
          'predicted_home_score': 2,
          'predicted_away_score': 1,
          'predicted_ht_home_score': 1,
          'predicted_ht_away_score': 0,
          'ht_ft_prediction': '1/1',
          'top_ht_ft_json': <Map<String, dynamic>>[
            <String, dynamic>{'code': '1/1', 'label': 'Ev / Ev', 'prob': 0.362},
            <String, dynamic>{
              'code': 'X/1',
              'label': 'Beraberlik / Ev',
              'prob': 0.184,
            },
            <String, dynamic>{
              'code': 'X/X',
              'label': 'Beraberlik / Beraberlik',
              'prob': 0.141,
            },
          ],
          'all_ht_ft_json': <Map<String, dynamic>>[
            <String, dynamic>{'code': '1/1', 'label': 'Ev / Ev', 'prob': 0.362},
            <String, dynamic>{
              'code': 'X/1',
              'label': 'Beraberlik / Ev',
              'prob': 0.184,
            },
            <String, dynamic>{
              'code': 'X/X',
              'label': 'Beraberlik / Beraberlik',
              'prob': 0.141,
            },
            <String, dynamic>{
              'code': '2/2',
              'label': 'Dep / Dep',
              'prob': 0.095,
            },
            <String, dynamic>{
              'code': '1/X',
              'label': 'Ev / Beraberlik',
              'prob': 0.068,
            },
            <String, dynamic>{
              'code': 'X/2',
              'label': 'Beraberlik / Dep',
              'prob': 0.062,
            },
            <String, dynamic>{
              'code': '2/X',
              'label': 'Dep / Beraberlik',
              'prob': 0.041,
            },
            <String, dynamic>{
              'code': '2/1',
              'label': 'Dep / Ev',
              'prob': 0.026,
            },
            <String, dynamic>{
              'code': '1/2',
              'label': 'Ev / Dep',
              'prob': 0.021,
            },
          ],
          'p_home': 0.572,
          'p_draw': 0.250,
          'p_away': 0.178,
          'p_over25': 0.585,
          'p_under25': 0.415,
          'p_btts_yes': 0.542,
          'p_btts_no': 0.458,
          'market_blended': true,
          'confidence_rate': 0.42,
          'top_scores_json': <Map<String, dynamic>>[
            <String, dynamic>{'score': '2-1', 'prob': 0.142},
            <String, dynamic>{'score': '1-0', 'prob': 0.118},
            <String, dynamic>{'score': '1-1', 'prob': 0.109},
          ],
        };
        (firstMatch['team_analysis']
                as Map<String, dynamic>)['ht_ft_reasoning_text'] =
            'İlk yarı baskısı ve ikinci yarı denge kontrolü 1/1 olasılığını destekliyor.';

        final service = _createSuccessService(utf8.encode(jsonEncode(payload)));
        await tester.pumpWidget(FutbolBulteniApp(service: service));
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);

        // MatchCard 1/X/2 + en olası İY/MS yüzdesi kontrolü
        expect(find.text('İY/MS 1/1 %36'), findsWidgets);
        expect(find.text('1:%57'), findsWidgets);
        expect(find.text('X:%25'), findsWidgets);
        expect(find.text('2:%18'), findsWidgets);

        await tester.tap(find.byKey(ValueKey('match_card_$firstMatchId')));
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);

        // Olasılık Özeti Paneli (1X2 + 2.5 Üst/Alt + KG Var/Yok + Piyasa Harmanı)
        expect(find.byType(MatchOutcomeSummaryCard), findsOneWidget);
        expect(find.text('Piyasa + Poisson Harmanı'), findsOneWidget);
        expect(find.text('%57.2'), findsOneWidget);
        expect(find.text('%25.0'), findsOneWidget);
        expect(find.text('%17.8'), findsOneWidget);
        expect(find.text('2.5 Üst'), findsOneWidget);
        expect(find.text('%58.5'), findsOneWidget);
        expect(find.text('2.5 Alt'), findsOneWidget);
        expect(find.text('%41.5'), findsOneWidget);
        expect(find.text('KG Var'), findsOneWidget);
        expect(find.text('%54.2'), findsOneWidget);
        expect(find.text('KG Yok'), findsOneWidget);
        expect(find.text('%45.8'), findsOneWidget);

        // 3x3 İY/MS Tam Matris (tüm 9 hücre + satır/sütun başlıkları)
        expect(
          find.text('İlk Yarı / Maç Sonucu Tam Yüzdelik Matrisi (3×3)'),
          findsOneWidget,
        );
        for (final code in PredictionModel.canonicalHtFtCodes) {
          expect(find.byKey(ValueKey('ht_ft_cell_$code')), findsOneWidget);
          expect(find.textContaining(code), findsWidgets);
        }
        expect(find.textContaining('%2.6'), findsOneWidget);
        expect(find.textContaining('%2.1'), findsOneWidget);

        // Tüm taktik analiz kartlarının korunması ve 360x800 kaydırmada sıfır taşma
        final detailScroll = find.byKey(const ValueKey('match_detail_scroll'));
        await tester.drag(detailScroll, const Offset(0, -700));
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
        expect(find.text('Neden Bu Skor?'), findsOneWidget);
        expect(
          find.text('Kapsamlı Durum Değerlendirmesi & Neden Bu İY/MS?'),
          findsOneWidget,
        );
        expect(find.text('Ev Sahibi Durumu'), findsOneWidget);
        expect(find.text('Deplasman Durumu'), findsOneWidget);

        await tester.drag(detailScroll, const Offset(0, -900));
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
        expect(find.byType(RatingComparisonBar), findsOneWidget);
        expect(find.byType(InjuriesList), findsOneWidget);
      },
    );

    testWidgets(
      'Test 14: BulletinApiService başarılı bülteni diske kaydeder ve ağ kesildiğinde HomeScreen Çevrimdışı Önbellek bandıyla açılır',
      (WidgetTester tester) async {
        tester.view.physicalSize = const Size(360, 800);
        tester.view.devicePixelRatio = 1.0;
        final tempDir = Directory.systemTemp.createTempSync(
          'futbol_offline_cache_test_',
        );
        const storageChannel = MethodChannel('com.futbol.bulten/storage');
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
            .setMockMethodCallHandler(storageChannel, (call) async {
          if (call.method == 'getFilesDir') {
            return tempDir.path;
          }
          return null;
        });

        addTearDown(() {
          tester.view.resetPhysicalSize();
          tester.view.resetDevicePixelRatio();
          TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
              .setMockMethodCallHandler(storageChannel, null);
          if (tempDir.existsSync()) {
            tempDir.deleteSync(recursive: true);
          }
        });

        // 1. Canlı HTTP 200 yanıtı yerel önbellek dosyasına kaydedilir
        var shouldFail = false;
        final client = MockClient((_) async {
          if (shouldFail) {
            throw const SocketException('İnternet bağlantısı yok');
          }
          return http.Response.bytes(
            realBulletinBytes,
            200,
            headers: const {'content-type': 'application/json; charset=utf-8'},
          );
        });

        final service = BulletinApiService(
          client: client,
          enableOfflineCache: true,
        );
        final liveData = await service.fetchBulletin();
        expect(liveData.isOfflineCache, isFalse);

        final savedCacheFile = File(
          '${tempDir.path}/${BulletinApiService.defaultCacheFileName}',
        );
        expect(savedCacheFile.existsSync(), isTrue);
        expect(savedCacheFile.readAsStringSync(), isNotEmpty);

        // 2. Ağ kesildiğinde hata ekranı yerine önbellekteki bülten ve Çevrimdışı Önbellek bandı gösterilir
        shouldFail = true;
        await tester.pumpWidget(FutbolBulteniApp(service: service));
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);

        expect(
          find.byKey(const ValueKey('offline_cache_banner')),
          findsOneWidget,
        );
        expect(
          find.textContaining('Çevrimdışı Önbellek • Son güncelleme:'),
          findsOneWidget,
        );
        expect(find.text('Çevrimdışı'), findsOneWidget);
        expect(find.byType(MatchCard), findsWidgets);
        expect(
          find.text('Sunucuya bağlanılamadı, tekrar dene'),
          findsNothing,
        );

        // 3. Ağ geri geldiğinde Yenile butonu canlı bültene geçirir
        shouldFail = false;
        await tester.tap(find.byKey(const ValueKey('offline_retry_button')));
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
        expect(
          find.byKey(const ValueKey('offline_cache_banner')),
          findsNothing,
        );
        expect(find.text('Canlı'), findsOneWidget);
      },
    );

    testWidgets(
      'Test 15: GÖREV-14 DataTransparencyBanner bayat bülten (>36 saat) turuncu uyarısı, <=36 saat gizliliği ve FotMob-xG / ShotProxy-xG kaynakları',
      (WidgetTester tester) async {
        tester.view.physicalSize = const Size(360, 800);
        tester.view.devicePixelRatio = 1.0;
        addTearDown(() {
          tester.view.resetPhysicalSize();
          tester.view.resetDevicePixelRatio();
        });

        // Geçersiz/boş ISO-8601 güvenli ayrıştırma kontrolü
        expect(BulletinData.parseGeneratedAt(null), isNull);
        expect(BulletinData.parseGeneratedAt(''), isNull);
        expect(BulletinData.parseGeneratedAt('gecersiz-tarih'), isNull);
        final parsedUtc =
            BulletinData.parseGeneratedAt('2026-11-26T21:00:00+03:00');
        expect(parsedUtc, DateTime.utc(2026, 11, 26, 18, 0));

        final fixedNow = DateTime.utc(2026, 11, 28, 18, 0);
        const superLigSources = <String>[
          'ESPN',
          'API-Football',
          'FotMob-xG',
          'ShotProxy-xG',
          'Transfermarkt',
          'SportsGambler',
        ];

        // 1. Güncel bülten (4 saat önce <= 36 saat): uyarı gösterilmez
        await tester.pumpWidget(
          MaterialApp(
            theme: AppTheme.darkTheme,
            home: Scaffold(
              body: DataTransparencyBanner(
                sourcesUsed: superLigSources,
                sourcesCount: 5,
                sourcesTotal: 5,
                generatedAt: fixedNow.subtract(const Duration(hours: 4)),
                now: fixedNow,
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
        expect(
          find.byKey(const ValueKey('stale_bulletin_warning')),
          findsNothing,
        );
        expect(find.textContaining('Bülten güncel değil'), findsNothing);
        expect(find.textContaining('FotMob-xG'), findsOneWidget);
        expect(find.textContaining('ShotProxy-xG'), findsOneWidget);

        // 2. Tam sınır (36 saat 0 dk) ve null generatedAt: uyarı gösterilmez
        await tester.pumpWidget(
          MaterialApp(
            theme: AppTheme.darkTheme,
            home: Scaffold(
              body: Column(
                children: [
                  DataTransparencyBanner(
                    generatedAt: fixedNow.subtract(const Duration(hours: 36)),
                    now: fixedNow,
                  ),
                  DataTransparencyBanner(
                    generatedAt: null,
                    now: fixedNow,
                  ),
                ],
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
        expect(find.textContaining('Bülten güncel değil'), findsNothing);

        // 3. Bayat bülten (48 saat önce > 36 saat): turuncu kutu, ikon ve metin gösterilir
        await tester.pumpWidget(
          MaterialApp(
            theme: AppTheme.darkTheme,
            home: Scaffold(
              body: DataTransparencyBanner(
                sourcesUsed: superLigSources,
                sourcesCount: 5,
                sourcesTotal: 5,
                generatedAt: fixedNow.subtract(const Duration(hours: 48)),
                now: fixedNow,
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);

        final warningBoxFinder = find.byKey(
          const ValueKey('stale_bulletin_warning'),
        );
        expect(warningBoxFinder, findsOneWidget);
        expect(
          find.text('Bülten güncel değil (48 saat önce)'),
          findsOneWidget,
        );

        final warningContainer = tester.widget<Container>(warningBoxFinder);
        final boxDecoration = warningContainer.decoration! as BoxDecoration;
        expect(
          boxDecoration.border,
          Border.all(color: AppColors.neonOrange.withValues(alpha: 0.45)),
        );

        final warningIcon = tester.widget<Icon>(
          find.descendant(
            of: warningBoxFinder,
            matching: find.byIcon(Icons.warning_amber_rounded),
          ),
        );
        expect(warningIcon.color, AppColors.neonOrange);

        final warningText = tester.widget<Text>(
          find.text('Bülten güncel değil (48 saat önce)'),
        );
        expect(warningText.style?.color, AppColors.neonOrange);

        // 4. Sınır üstü (36 saat 1 dk > 36 saat): uyarı tetiklenir
        await tester.pumpWidget(
          MaterialApp(
            theme: AppTheme.darkTheme,
            home: Scaffold(
              body: DataTransparencyBanner(
                generatedAt: fixedNow.subtract(
                  const Duration(hours: 36, minutes: 1),
                ),
                now: fixedNow,
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
        expect(
          find.text('Bülten güncel değil (36 saat önce)'),
          findsOneWidget,
        );
      },
    );
  });
}
