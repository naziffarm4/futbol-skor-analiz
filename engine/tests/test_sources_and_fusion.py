"""GÖREV-11 dinamik sezon, 5 bağımsız veri kaynağı adaptörü ve çoklu kaynak füzyon testleri."""

from __future__ import annotations

import json
import os
import unittest
from datetime import UTC, date, datetime
from unittest.mock import patch

import httpx

from engine.config import (
    PROJECT_ROOT,
    LeagueId,
    Settings,
    get_current_season,
    get_football_data_season_code,
    get_season_start_year,
)
from engine.models.schemas import (
    ImpactLevel,
    Injury,
    Match,
    MatchStatus,
    PlayerPosition,
    Team,
)
from engine.scrapers.base import BaseScraper, ScraperError
from engine.scrapers.fixtures import FixturesScraper
from engine.scrapers.fusion import (
    TeamAliasResolver,
    compute_damped_first_half_share,
    cross_validate_injuries,
    cross_validate_match_scores,
)
from engine.scrapers.injuries import InjuriesScraper
from engine.scrapers.pipeline import IngestionPipeline
from engine.scrapers.sources import (
    ESPNAdapter,
    FootballDataAdapter,
    SecondaryCheckAdapter,
    SecondaryInjuryRecord,
    UnderstatAdapter,
    derive_xg_from_shots,
    parse_football_data_csv,
    parse_sportsgambler_html,
    parse_understat_teams_data,
)
from engine.tests.test_scrapers import MOCK_FIXTURES_HTML, MOCK_INJURIES_HTML

MOCK_ESPN_SCOREBOARD = {
    "events": [
        {
            "id": "401001",
            "date": "2026-11-20T20:00Z",
            "status": {"type": {"name": "STATUS_FINAL", "completed": True}},
            "competitions": [
                {
                    "competitors": [
                        {
                            "homeAway": "home",
                            "score": "3",
                            "team": {"id": "101", "displayName": "Galatasaray", "shortDisplayName": "GAL"},
                            "statistics": [
                                {"name": "totalShots", "displayValue": "18"},
                                {"name": "shotsOnTarget", "displayValue": "8"},
                                {"name": "wonCorners", "displayValue": "7"},
                            ],
                        },
                        {
                            "homeAway": "away",
                            "score": "1",
                            "team": {"id": "102", "displayName": "Beşiktaş", "shortDisplayName": "BJK"},
                            "statistics": [
                                {"name": "totalShots", "displayValue": "9"},
                                {"name": "shotsOnTarget", "displayValue": "3"},
                                {"name": "wonCorners", "displayValue": "4"},
                            ],
                        },
                    ],
                    "details": [
                        {"scoringPlay": True, "clock": {"displayValue": "24'"}, "team": {"id": "101"}},
                        {"scoringPlay": True, "clock": {"displayValue": "45'+2'"}, "team": {"id": "101"}},
                        {"scoringPlay": True, "clock": {"displayValue": "68'"}, "team": {"id": "102"}},
                        {"yellowCard": True, "clock": {"displayValue": "55'"}, "team": {"id": "102"}},
                    ],
                    "odds": [
                        {
                            "moneyline": {
                                "home": {"close": {"odds": "-140"}},
                                "draw": {"close": {"odds": "+260"}},
                                "away": {"close": {"odds": "+340"}},
                            }
                        }
                    ],
                }
            ],
        }
    ]
}

MOCK_ESPN_STANDINGS = {
    "children": [
        {
            "standings": {
                "entries": [
                    {
                        "team": {"displayName": "Galatasaray", "shortDisplayName": "Galatasaray"},
                        "stats": [
                            {"name": "rank", "value": 1},
                            {"name": "points", "value": 31},
                            {"name": "gamesPlayed", "value": 12},
                            {"name": "pointsFor", "value": 29},
                            {"name": "pointsAgainst", "value": 16},
                            {"name": "pointDifferential", "value": 13},
                        ],
                    },
                    {
                        "team": {"displayName": "Fenerbahce", "shortDisplayName": "Fenerbahce"},
                        "stats": [
                            {"name": "rank", "value": 2},
                            {"name": "points", "value": 27},
                            {"name": "gamesPlayed", "value": 12},
                            {"name": "pointsFor", "value": 26},
                            {"name": "pointsAgainst", "value": 11},
                            {"name": "pointDifferential", "value": 15},
                        ],
                    },
                ]
            }
        }
    ]
}

MOCK_FD_CSV = """Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HTHG,HTAG,HTR,HS,AS,HST,AST,HC,AC,HY,AY,HR,AR,B365H,B365D,B365A
T1,20/11/2026,Galatasaray,Besiktas,3,1,H,2,0,H,18,9,8,3,7,4,2,3,0,0,1.72,3.80,4.50
T1,21/11/2026,Fenerbahce,Trabzonspor,2,0,H,1,0,H,15,8,6,2,6,3,1,2,0,1,1.65,3.90,5.00
"""

MOCK_SPORTSGAMBLER_HTML = """
<!doctype html>
<html><body>
  <div class="injuries-block">
    <h3 class="team-name">Galatasaray</h3>
    <table><tbody>
      <tr><td>Mauro Icardi</td><td>Knee Injury</td><td>Mid Dec</td></tr>
    </tbody></table>
  </div>
  <div class="injuries-block">
    <h3 class="team-name">Fenerbahce</h3>
    <table><tbody>
      <tr><td>Fred</td><td>Suspended</td><td>Late Nov</td></tr>
    </tbody></table>
  </div>
</body></html>
"""


class DynamicSeasonTests(unittest.TestCase):
    def test_season_rollover_boundary_june_vs_july(self) -> None:
        self.assertEqual(get_current_season(date(2027, 6, 30)), "2026-2027")
        self.assertEqual(get_current_season(date(2027, 7, 1)), "2027-2028")
        self.assertEqual(get_current_season(date(2026, 1, 15)), "2025-2026")
        self.assertEqual(get_current_season(date(2026, 7, 1)), "2026-2027")

    def test_season_helpers_and_settings_dynamic_env(self) -> None:
        self.assertEqual(get_season_start_year("2026-2027"), 2026)
        self.assertEqual(get_season_start_year(today=date(2027, 7, 1)), 2027)
        self.assertEqual(get_football_data_season_code("2026-2027"), "2627")
        self.assertEqual(get_football_data_season_code("2027-2028"), "2728")
        self.assertEqual(get_football_data_season_code(today=date(2027, 6, 30)), "2627")
        self.assertEqual(get_football_data_season_code(today=date(2027, 7, 1)), "2728")

        with patch.dict(os.environ, {"DEFAULT_SEASON": ""}, clear=False):
            cfg = Settings.from_env()
            self.assertEqual(cfg.default_season, get_current_season())

        with patch.dict(os.environ, {"DEFAULT_SEASON": "2029-2030"}, clear=False):
            cfg_override = Settings.from_env()
            self.assertEqual(cfg_override.default_season, "2029-2030")

    def test_no_hardcoded_season_in_owned_configs_and_docs(self) -> None:
        hardcoded_token = f"{2026}-{2027}"
        checked_paths = [
            PROJECT_ROOT / "engine" / "config.py",
            PROJECT_ROOT / "engine" / "db" / "schema.sql",
            PROJECT_ROOT / ".env.example",
            PROJECT_ROOT / "HF_DEPLOY.md",
            PROJECT_ROOT / ".github" / "workflows" / "update_bulletin.yml",
        ]
        for path in checked_paths:
            content = path.read_text(encoding="utf-8")
            self.assertNotIn(
                hardcoded_token,
                content,
                f"{path.name} içinde sabit sezon dizgesi bulundu!",
            )


class SourceAdaptersUnitTests(unittest.TestCase):
    def test_espn_adapter_standings_v2_fallback_and_scoreboard(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path.endswith("/scoreboard"):
                return httpx.Response(200, json=MOCK_ESPN_SCOREBOARD)
            if "/apis/site/v2/" in req.url.path and req.url.path.endswith("/standings"):
                return httpx.Response(404, json={"code": 404})
            if "/apis/v2/" in req.url.path and req.url.path.endswith("/standings"):
                return httpx.Response(200, json=MOCK_ESPN_STANDINGS)
            return httpx.Response(404)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            adapter = ESPNAdapter(client=client)
            data, diag = adapter.fetch_league(LeagueId.SUPER_LIG)

        self.assertTrue(diag["ok"])
        self.assertEqual(diag["source"], "ESPN")
        self.assertEqual(diag["http_status"], 200)
        self.assertEqual(len(data.standings), 2)
        self.assertEqual(data.standings[0].rank, 1)
        self.assertEqual(data.standings[0].points, 31)
        self.assertEqual(len(data.fixtures), 1)
        fx = data.fixtures[0]
        self.assertEqual((fx.home_score, fx.away_score), (3, 1))
        self.assertEqual((fx.ht_home_score, fx.ht_away_score), (2, 0))
        self.assertEqual(fx.home_sot, 8.0)
        self.assertIsNotNone(fx.home_win_prob)

    def test_football_data_csv_parser_and_early_july_404_fallback(self) -> None:
        parsed = parse_football_data_csv(MOCK_FD_CSV, LeagueId.SUPER_LIG, season_code="2627")
        self.assertEqual(len(parsed.matches), 2)
        gs = parsed.team_stats["Galatasaray"]
        self.assertEqual(gs.ht_goals_for, 2)
        self.assertEqual(gs.ft_goals_for, 3)
        self.assertEqual(gs.sot_for_per_match, 8.0)
        self.assertEqual(gs.corners_for_per_match, 7.0)
        self.assertIsNotNone(gs.market_win_prob_avg)

        requested_urls: list[str] = []

        def handler(req: httpx.Request) -> httpx.Response:
            requested_urls.append(str(req.url))
            if "/2728/" in req.url.path:
                return httpx.Response(404, text="Not Found")
            if "/2627/" in req.url.path:
                return httpx.Response(200, text=MOCK_FD_CSV)
            return httpx.Response(404)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            adapter = FootballDataAdapter(client=client, allow_mirror_fallback=False)
            data, diag = adapter.fetch_league(LeagueId.SUPER_LIG, season="2027-2028")

        self.assertTrue(diag["ok"])
        self.assertEqual(len(requested_urls), 2)
        self.assertIn("2627", diag["note"] or "")
        self.assertEqual(len(data.matches), 2)

    def test_understat_html_and_ajax_parsing_plus_shot_derived_xg(self) -> None:
        inner_json = json.dumps(
            {
                "1": {
                    "title": "Atlético Madrid",
                    "history": [
                        {"xG": 1.85, "xGA": 0.75},
                        {"xG": 2.15, "xGA": 1.05},
                    ],
                }
            },
            ensure_ascii=False,
        )
        hex_escaped = inner_json.replace('"', "\\x22")
        html_doc = f"<script>var teamsData = JSON.parse('{hex_escaped}');</script>"
        teams = parse_understat_teams_data(html_doc)
        self.assertIn("Atlético Madrid", teams)
        self.assertAlmostEqual(teams["Atlético Madrid"].xg_for_per_match, 2.0, places=3)
        self.assertAlmostEqual(teams["Atlético Madrid"].xg_against_per_match, 0.9, places=3)
        self.assertFalse(teams["Atlético Madrid"].xg_is_derived)

        # Süper Lig için şut/isabetli şut tabanlı xG vekili doğrulaması
        with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(404))) as client:
            adapter = UnderstatAdapter(client=client, allow_opta_bridge=False)
            us_data, us_diag = adapter.fetch_league(
                LeagueId.SUPER_LIG,
                season="2026-2027",
                fallback_team_shots={"Galatasaray": (16.0, 7.0, 9.0, 3.0)},
            )
        self.assertTrue(us_diag["ok"])
        gs_xg = us_data.teams["Galatasaray"]
        self.assertTrue(gs_xg.xg_is_derived)
        # 0.32 * 7 + 0.05 * (16 - 7) = 2.24 + 0.45 = 2.69
        self.assertAlmostEqual(gs_xg.xg_for_per_match, 2.69, places=2)
        xg_f, xg_a = derive_xg_from_shots(
            shots_for_per_match=10.0,
            sot_for_per_match=4.0,
            shots_against_per_match=8.0,
            sot_against_per_match=3.0,
        )
        self.assertAlmostEqual(xg_f or 0.0, 0.32 * 4.0 + 0.05 * 6.0, places=3)
        self.assertAlmostEqual(xg_a or 0.0, 0.32 * 3.0 + 0.05 * 5.0, places=3)

    def test_secondary_check_sportsgambler_and_thesportsdb_fallback(self) -> None:
        sg_rows = parse_sportsgambler_html(MOCK_SPORTSGAMBLER_HTML)
        self.assertEqual(len(sg_rows), 2)
        self.assertEqual(sg_rows[0].player_name, "Mauro Icardi")

        def handler_fallback(req: httpx.Request) -> httpx.Response:
            if "sportsgambler.com" in req.url.host:
                return httpx.Response(403, text="Just a moment...")
            if "thesportsdb.com" in req.url.host:
                return httpx.Response(
                    200,
                    json={
                        "table": [
                            {"strTeam": "Galatasaray", "intRank": "1", "intPoints": "31", "intPlayed": "12"},
                            {"strTeam": "Fenerbahce", "intRank": "2", "intPoints": "27", "intPlayed": "12"},
                        ]
                    },
                )
            return httpx.Response(404)

        with httpx.Client(transport=httpx.MockTransport(handler_fallback)) as client:
            adapter = SecondaryCheckAdapter(client=client, allow_live_fallbacks=False)
            sec_data, sec_diag = adapter.fetch_league(LeagueId.SUPER_LIG, season="2026-2027")

        self.assertTrue(sec_diag["ok"])
        self.assertEqual(sec_diag["source"], "TheSportsDB")
        self.assertEqual(len(sec_data.standings), 2)


class TeamAliasAndFusionTests(unittest.TestCase):
    def test_team_alias_resolver_across_all_four_leagues(self) -> None:
        resolver = TeamAliasResolver(
            [
                "Galatasaray SK",
                "Fenerbahçe",
                "Beşiktaş JK",
                "Çaykur Rizespor",
                "Fatih Karagümrük",
                "RAMS Başakşehir",
                "Tümosan Konyaspor",
                "Corendon Alanyaspor",
                "Göztepe SK",
                "ikas Eyüpspor",
                "Sipay Bodrum FK",
                "Manchester City",
                "Manchester United",
                "Wolverhampton Wanderers",
                "Nottingham Forest",
                "Tottenham Hotspur",
                "Atlético de Madrid",
                "Athletic Bilbao",
                "Celta de Vigo",
                "Real Betis Balompié",
                "Real Sociedad",
                "Deportivo Alavés",
                "RCD Espanyol",
                "Paris Saint-Germain",
                "Paris FC",
                "Olympique Marsilya",
                "AS Saint-Étienne",
                "Borussia Mönchengladbach",
            ]
        )

        pairs = [
            ("Galatasaray SK", "Galatasaray"),
            ("Fenerbahçe", "Fenerbahce SK"),
            ("Beşiktaş JK", "Besiktas"),
            ("Çaykur Rizespor", "Rizespor"),
            ("Fatih Karagümrük", "Karagumruk"),
            ("RAMS Başakşehir", "Istanbul Basaksehir"),
            ("Tümosan Konyaspor", "Konyaspor"),
            ("Corendon Alanyaspor", "Alanyaspor"),
            ("Göztepe SK", "Goztepe"),
            ("ikas Eyüpspor", "Eyupspor"),
            ("Sipay Bodrum FK", "Bodrum"),
            ("Man City", "Manchester City"),
            ("Man United", "Manchester United"),
            ("Man Utd", "Manchester United"),
            ("Wolves", "Wolverhampton Wanderers"),
            ("Nott'm Forest", "Nottingham Forest"),
            ("Spurs", "Tottenham Hotspur"),
            ("Atletico", "Atlético de Madrid"),
            ("Ath Madrid", "Atlético de Madrid"),
            ("Athletic", "Athletic Bilbao"),
            ("Ath Bilbao", "Athletic Bilbao"),
            ("Celta", "Celta de Vigo"),
            ("Betis", "Real Betis Balompié"),
            ("Sociedad", "Real Sociedad"),
            ("Alaves", "Deportivo Alavés"),
            ("Espanyol", "RCD Espanyol"),
            ("PSG", "Paris Saint-Germain"),
            ("Paris SG", "Paris Saint-Germain"),
            ("Olympique Marsilya", "Marseille"),
            ("St Etienne", "AS Saint-Étienne"),
            ("Gladbach", "Borussia Mönchengladbach"),
        ]
        for left, right in pairs:
            self.assertTrue(
                resolver.same_team(left, right),
                f"Eşleşmesi beklenen kulüpler eşleşmedi: {left!r} != {right!r}",
            )

        self.assertFalse(resolver.same_team("Man City", "Man United"))
        self.assertFalse(resolver.same_team("Paris FC", "PSG"))
        self.assertFalse(resolver.same_team("Atlético Madrid", "Real Madrid"))

    def test_damped_ht_share_and_cross_validate_injuries(self) -> None:
        self.assertIsNone(compute_damped_first_half_share(0, 0))
        share = compute_damped_first_half_share(8, 16)
        self.assertIsNotNone(share)
        self.assertGreaterEqual(share or 0.0, 0.25)
        self.assertLessEqual(share or 1.0, 0.65)
        # Uç değer sönümleme kontrolü: 1/1 gol bile %100 yerine <= 0.65 olmalı
        self.assertLessEqual(compute_damped_first_half_share(1, 1) or 1.0, 0.65)
        self.assertGreaterEqual(compute_damped_first_half_share(0, 10) or 0.0, 0.25)

        teams = [
            Team(id=1, league_id=LeagueId.SUPER_LIG, name="Galatasaray SK"),
            Team(id=2, league_id=LeagueId.SUPER_LIG, name="Fenerbahçe"),
        ]
        primaries = [
            Injury(
                team_id=1,
                player_name="Mauro Icardi",
                position=PlayerPosition.FW,
                reason="Çapraz bağ",
                impact_level=ImpactLevel.HIGH,
            ),
            Injury(
                team_id=2,
                player_name="İsmail Yüksek",
                position=PlayerPosition.MID,
                reason="Kas sakatlığı",
                impact_level=ImpactLevel.MEDIUM,
            ),
        ]
        secondaries = [
            SecondaryInjuryRecord(
                team_name="Galatasaray",
                player_name="Icardi",
                reason="Knee Injury",
                source_name="SportsGambler",
            )
        ]
        validated, count = cross_validate_injuries(primaries, teams, secondaries)
        self.assertEqual(count, 1)
        self.assertTrue(validated[0].verified_by_multiple_sources)
        self.assertEqual(validated[0].sources, ["Transfermarkt", "SportsGambler"])
        self.assertFalse(validated[1].verified_by_multiple_sources)

    def test_five_source_pipeline_fusion_end_to_end_mocked(self) -> None:
        def tm_handler(req: httpx.Request) -> httpx.Response:
            if "gesamtspielplan" in req.url.path:
                return httpx.Response(200, text=MOCK_FIXTURES_HTML)
            if "sperrenundverletzungen" in req.url.path:
                return httpx.Response(200, text=MOCK_INJURIES_HTML)
            return httpx.Response(404)

        def ext_handler(req: httpx.Request) -> httpx.Response:
            url_s = str(req.url)
            if "espn.com" in url_s and "scoreboard" in url_s:
                return httpx.Response(200, json=MOCK_ESPN_SCOREBOARD)
            if "espn.com" in url_s and "standings" in url_s:
                return httpx.Response(200, json=MOCK_ESPN_STANDINGS)
            if "football-data.co.uk" in url_s:
                return httpx.Response(200, text=MOCK_FD_CSV)
            if "sportsgambler.com" in url_s:
                return httpx.Response(200, text=MOCK_SPORTSGAMBLER_HTML)
            if "understat.com" in url_s:
                return httpx.Response(
                    200,
                    json={
                        "teams": {
                            "1": {
                                "title": "Galatasaray",
                                "history": [{"xG": 2.30, "xGA": 0.95}, {"xG": 2.10, "xGA": 1.05}],
                            }
                        }
                    },
                )
            return httpx.Response(404)

        with (
            httpx.Client(base_url="https://mock.tm.local", transport=httpx.MockTransport(tm_handler)) as tm_c,
            httpx.Client(transport=httpx.MockTransport(ext_handler)) as ext_c,
        ):
            base_http = BaseScraper(
                base_url="https://mock.tm.local",
                min_delay=0.0,
                max_delay=0.0,
                client=tm_c,
            )
            pipeline = IngestionPipeline(
                http=base_http,
                fixtures_scraper=FixturesScraper(base_http),
                injuries_scraper=InjuriesScraper(base_http),
                enable_multi_source=True,
                espn_adapter=ESPNAdapter(client=ext_c),
                football_data_adapter=FootballDataAdapter(client=ext_c, allow_mirror_fallback=False),
                understat_adapter=UnderstatAdapter(client=ext_c, allow_opta_bridge=False),
                secondary_adapter=SecondaryCheckAdapter(client=ext_c, allow_live_fallbacks=False),
            )
            res = pipeline.run(LeagueId.PREMIER_LEAGUE, reference_date=date(2026, 11, 25), persist=False)

        self.assertEqual(res.sources_total, 5)
        self.assertEqual(
            res.sources_used,
            ["ESPN", "Football-Data", "Understat", "Transfermarkt", "SportsGambler"],
        )
        self.assertEqual(len(res.source_diagnostics), 5)
        self.assertIn("premier_league", res.league_sources)
        gs_team = next(t for t in res.teams if "Galatasaray" in t.name)
        assert gs_team.id is not None
        gs_metrics = res.team_metrics[gs_team.id]
        self.assertEqual(gs_metrics.espn_rank, 1)
        self.assertAlmostEqual(gs_metrics.xg_for_per_match or 0.0, 2.20, places=2)
        self.assertEqual(gs_metrics.sot_for_per_match, 8.0)
        self.assertIsNotNone(gs_metrics.first_half_attack_share)
        icardi = next(i for i in res.injuries if "Icardi" in i.player_name)
        self.assertTrue(icardi.verified_by_multiple_sources)

    def test_cross_validate_match_scores_backfills_recently_finished(self) -> None:
        teams = [
            Team(id=1, league_id=LeagueId.SUPER_LIG, name="Galatasaray SK"),
            Team(id=2, league_id=LeagueId.SUPER_LIG, name="Beşiktaş JK"),
        ]
        matches = [
            Match(
                league_id=LeagueId.SUPER_LIG,
                home_team_id=1,
                away_team_id=2,
                match_date=datetime(2026, 11, 20, 20, 0, tzinfo=UTC),
                round=13,
                status=MatchStatus.SCHEDULED,
            )
        ]
        fd = parse_football_data_csv(MOCK_FD_CSV, LeagueId.SUPER_LIG, season_code="2627")
        updated, confirmed = cross_validate_match_scores(matches, teams, football_data=fd)
        self.assertEqual(confirmed, 1)
        self.assertEqual(updated[0].status, MatchStatus.FINISHED)
        self.assertEqual((updated[0].home_score, updated[0].away_score), (3, 1))


class LiveFiveSourcesSmokeTests(unittest.TestCase):
    def test_live_all_five_sources_http_200_verification(self) -> None:
        """5 kaynağın tamamını canlı HTTP istekleriyle doğrular (ağ yoksa zarifçe atlar)."""
        try:
            with (
                BaseScraper(min_delay=0.3, max_delay=0.6, max_retries=1, timeout=14.0) as http,
                ESPNAdapter(timeout=12.0) as espn,
                FootballDataAdapter(timeout=12.0) as fd,
                UnderstatAdapter(timeout=12.0) as us,
                SecondaryCheckAdapter(timeout=12.0) as sec,
            ):
                pipeline = IngestionPipeline(
                    http=http,
                    fixtures_scraper=FixturesScraper(http),
                    injuries_scraper=InjuriesScraper(http, max_pages=1),
                    enable_multi_source=True,
                    espn_adapter=espn,
                    football_data_adapter=fd,
                    understat_adapter=us,
                    secondary_adapter=sec,
                )
                res = pipeline.run_league(LeagueId.PREMIER_LEAGUE, persist=False)
        except (ScraperError, httpx.HTTPError) as exc:
            self.skipTest(f"Canlı ağ erişilemedi (zarif atlama): {exc}")
            return

        tm_diag = res.source_diagnostics.get("Transfermarkt") or {}
        tm_waf_blocked = not tm_diag.get("ok") and tm_diag.get("http_status") in {202, 403, 429}
        expected_min = 4 if tm_waf_blocked else 5
        self.assertGreaterEqual(
            len(res.sources_used),
            expected_min,
            f"Beklenen en az {expected_min} kaynak, alınan: {res.sources_used} | {res.source_diagnostics}",
        )
        self.assertGreaterEqual(len(res.teams), 18)
        self.assertGreater(len(res.matches), 0)
        for src_name, diag in res.source_diagnostics.items():
            if src_name == "Transfermarkt" and tm_waf_blocked:
                continue
            self.assertTrue(diag.get("ok"), f"{src_name} başarısız: {diag}")
            self.assertEqual(diag.get("http_status"), 200, f"{src_name} HTTP 200 dönmedi: {diag}")
            self.assertGreater(int(diag.get("records") or 0), 0)


if __name__ == "__main__":
    unittest.main()
