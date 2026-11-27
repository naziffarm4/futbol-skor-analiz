"""GÖREV-13 resmi API adaptörleri, kota takipçisi, WAF'sız boru hattı yedeği ve arşiv birim testleri."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import patch

import httpx

from engine.archive import save_snapshot
from engine.config import LeagueId, Settings
from engine.models.schemas import MatchStatus
from engine.scrapers.base import BaseScraper, ScraperHTTPError
from engine.scrapers.fixtures import FixturesScraper
from engine.scrapers.injuries import InjuriesScraper
from engine.scrapers.pipeline import IngestionPipeline
from engine.scrapers.sources import (
    ApiFootballAdapter,
    ESPNAdapter,
    FootballDataAdapter,
    QuotaBudgetTracker,
    SecondaryCheckAdapter,
    TheOddsApiAdapter,
    UnderstatAdapter,
    redact_secret,
)

FAKE_AF_KEY = "fake_af_test_token_000000000001"
FAKE_ODDS_KEY = "fake_odds_test_token_0000000002"

MOCK_AF_FIXTURES_PAYLOAD = {
    "get": "fixtures",
    "errors": [],
    "results": 2,
    "response": [
        {
            "fixture": {
                "id": 101,
                "date": "2026-11-20T17:00:00+00:00",
                "status": {"short": "FT"},
            },
            "league": {"id": 203, "season": 2026, "round": "Regular Season - 12"},
            "teams": {
                "home": {"name": "Galatasaray", "logo": "https://cdn.example/gs.png"},
                "away": {"name": "Besiktas", "logo": "https://cdn.example/bjk.png"},
            },
            "goals": {"home": 2, "away": 1},
            "score": {
                "halftime": {"home": 1, "away": 0},
                "fulltime": {"home": 2, "away": 1},
            },
        },
        {
            "fixture": {
                "id": 102,
                "date": "2026-11-29T16:00:00+00:00",
                "status": {"short": "NS"},
            },
            "league": {"id": 203, "season": 2026, "round": "Regular Season - 13"},
            "teams": {
                "home": {"name": "Fenerbahce", "logo": "https://cdn.example/fb.png"},
                "away": {"name": "Galatasaray", "logo": "https://cdn.example/gs.png"},
            },
            "goals": {"home": None, "away": None},
            "score": {
                "halftime": {"home": None, "away": None},
                "fulltime": {"home": None, "away": None},
            },
        },
    ],
}

MOCK_AF_INJURIES_PAYLOAD = {
    "get": "injuries",
    "errors": [],
    "results": 1,
    "response": [
        {
            "player": {
                "id": 9,
                "name": "Mauro Icardi",
                "type": "Missing Fixture",
                "reason": "Knee Injury",
            },
            "team": {"name": "Galatasaray"},
            "fixture": {"date": "2026-11-29T16:00:00+00:00"},
        }
    ],
}

MOCK_ODDS_EVENTS = [
    {
        "id": "ev_1",
        "sport_key": "soccer_turkey_super_league",
        "commence_time": "2026-11-29T16:00:00Z",
        "home_team": "Fenerbahce",
        "away_team": "Galatasaray",
        "bookmakers": [
            {
                "key": "pinnacle",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Fenerbahce", "price": 2.10},
                            {"name": "Draw", "price": 3.50},
                            {"name": "Galatasaray", "price": 3.40},
                        ],
                    },
                    {
                        "key": "totals",
                        "outcomes": [
                            {"name": "Over", "point": 2.5, "price": 1.80},
                            {"name": "Under", "point": 2.5, "price": 2.05},
                            {"name": "Over", "point": 3.5, "price": 2.90},
                            {"name": "Under", "point": 3.5, "price": 1.40},
                        ],
                    },
                ],
            },
            {
                "key": "betfair_ex_eu",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Fenerbahce", "price": 2.15},
                            {"name": "Draw", "price": 3.60},
                            {"name": "Galatasaray", "price": 3.50},
                        ],
                    },
                    {
                        "key": "totals",
                        "outcomes": [
                            {"name": "Over", "point": 2.5, "price": 1.85},
                            {"name": "Under", "point": 2.5, "price": 2.10},
                        ],
                    },
                ],
            },
        ],
    }
]

MOCK_FD_CSV = (
    "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HTHG,HTAG,HTR,HS,AS,HST,AST,HC,AC,HY,AY,HR,AR,B365H,B365D,B365A\n"
    "T1,20/11/2026,Galatasaray,Besiktas,2,1,H,1,0,H,16,9,7,3,6,4,2,3,0,0,1.75,3.80,4.20\n"
    "T1,21/11/2026,Fenerbahce,Trabzonspor,3,1,H,2,0,H,18,8,8,3,7,3,1,2,0,0,1.60,4.00,5.00\n"
)

MOCK_ESPN_STANDINGS = {
    "children": [
        {
            "standings": {
                "entries": [
                    {
                        "team": {"displayName": "Galatasaray"},
                        "stats": [
                            {"name": "rank", "value": 1},
                            {"name": "points", "value": 34},
                            {"name": "gamesPlayed", "value": 12},
                            {"name": "pointDifferential", "value": 18},
                        ],
                    },
                    {
                        "team": {"displayName": "Fenerbahce"},
                        "stats": [
                            {"name": "rank", "value": 2},
                            {"name": "points", "value": 31},
                            {"name": "gamesPlayed", "value": 12},
                            {"name": "pointDifferential", "value": 15},
                        ],
                    },
                    {
                        "team": {"displayName": "Besiktas"},
                        "stats": [
                            {"name": "rank", "value": 3},
                            {"name": "points", "value": 24},
                            {"name": "gamesPlayed", "value": 12},
                            {"name": "pointDifferential", "value": 7},
                        ],
                    },
                    {
                        "team": {"displayName": "Trabzonspor"},
                        "stats": [
                            {"name": "rank", "value": 4},
                            {"name": "points", "value": 20},
                            {"name": "gamesPlayed", "value": 12},
                            {"name": "pointDifferential", "value": 3},
                        ],
                    },
                ]
            }
        }
    ]
}

MOCK_ESPN_UPCOMING_SCOREBOARD = {
    "events": [
        {
            "date": "2026-11-29T16:00Z",
            "competitions": [
                {
                    "status": {"type": {"state": "pre", "completed": False}},
                    "competitors": [
                        {"homeAway": "home", "team": {"displayName": "Fenerbahce"}},
                        {"homeAway": "away", "team": {"displayName": "Galatasaray"}},
                    ],
                }
            ],
        },
        {
            "date": "2026-11-30T17:00Z",
            "competitions": [
                {
                    "status": {"type": {"state": "pre", "completed": False}},
                    "competitors": [
                        {"homeAway": "home", "team": {"displayName": "Besiktas"}},
                        {"homeAway": "away", "team": {"displayName": "Trabzonspor"}},
                    ],
                }
            ],
        },
    ]
}

MOCK_SPORTSGAMBLER_HTML = """
<html><body>
<div class="inj-container">
  <h3 class="inj-team-title">Galatasaray</h3>
  <table>
    <tr><td>Mauro Icardi</td><td>FW</td><td>Knee Injury</td><td>Out</td></tr>
  </table>
</div>
</body></html>
"""


class ConfigAndRedactionTests(unittest.TestCase):
    def test_settings_repr_hides_api_keys_and_splits_concatenated_env(self) -> None:
        concat = f"{FAKE_AF_KEY}THE_ODDS_API_KEY={FAKE_ODDS_KEY}"
        with patch.dict(
            os.environ,
            {"API_FOOTBALL_KEY": concat, "THE_ODDS_API_KEY": ""},
            clear=False,
        ):
            cfg = Settings.from_env()
            self.assertEqual(cfg.api_football_key, FAKE_AF_KEY)
            self.assertEqual(cfg.the_odds_api_key, FAKE_ODDS_KEY)
            rendered = repr(cfg)
            self.assertNotIn(FAKE_AF_KEY, rendered)
            self.assertNotIn(FAKE_ODDS_KEY, rendered)

    def test_redact_secret_masks_query_params_and_tokens(self) -> None:
        dirty = (
            f"GET https://api.the-odds-api.com/v4/sports/soccer_epl/odds?apiKey={FAKE_ODDS_KEY}&regions=eu "
            f"header={FAKE_AF_KEY}"
        )
        cleaned = redact_secret(dirty, FAKE_ODDS_KEY, FAKE_AF_KEY)
        self.assertNotIn(FAKE_ODDS_KEY, cleaned)
        self.assertNotIn(FAKE_AF_KEY, cleaned)
        self.assertIn("***REDACTED***", cleaned)


class QuotaAndAdaptersTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.tracker = QuotaBudgetTracker(
            budget_path=base / "quota_budget.json",
            cache_dir=base / "api_cache",
            min_remaining=15,
            default_ttl_seconds=21600.0,
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_quota_threshold_guard_and_period_rollover(self) -> None:
        day1 = datetime(2026, 11, 27, 10, 0, tzinfo=UTC)
        day2 = datetime(2026, 11, 28, 10, 0, tzinfo=UTC)

        self.tracker.record_headers(
            "api_football",
            {"x-ratelimit-requests-remaining": "14", "x-ratelimit-requests-limit": "100"},
            now_utc=day1,
        )
        self.assertFalse(self.tracker.can_request("api_football", now_utc=day1))
        self.assertTrue(self.tracker.can_request("api_football", now_utc=day2))

        self.tracker.record_headers(
            "the_odds_api",
            {"x-requests-remaining": "12", "x-requests-used": "488"},
            now_utc=day1,
        )
        self.assertFalse(self.tracker.can_request("the_odds_api", now_utc=day1))
        self.assertFalse(self.tracker.can_request("the_odds_api", now_utc=day2))
        dec = datetime(2026, 12, 1, 0, 5, tzinfo=UTC)
        self.assertTrue(self.tracker.can_request("the_odds_api", now_utc=dec))

    def test_api_football_adapter_parses_fixtures_injuries_and_caches(self) -> None:
        calls = 0

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            self.assertEqual(req.headers.get("x-apisports-key"), FAKE_AF_KEY)
            if req.url.path == "/fixtures":
                return httpx.Response(
                    200,
                    headers={
                        "x-ratelimit-requests-remaining": "88",
                        "x-ratelimit-requests-limit": "100",
                    },
                    json=MOCK_AF_FIXTURES_PAYLOAD,
                )
            if req.url.path == "/injuries":
                return httpx.Response(
                    200,
                    headers={
                        "x-ratelimit-requests-remaining": "87",
                        "x-ratelimit-requests-limit": "100",
                    },
                    json=MOCK_AF_INJURIES_PAYLOAD,
                )
            return httpx.Response(404)

        client = httpx.Client(
            base_url="https://v3.football.api-sports.io",
            transport=httpx.MockTransport(handler),
        )
        with ApiFootballAdapter(
            api_key=FAKE_AF_KEY,
            client=client,
            tracker=self.tracker,
        ) as adapter:
            data1, diag1 = adapter.fetch_league(
                LeagueId.SUPER_LIG,
                season="2026-2027",
                reference_date=date(2026, 11, 27),
            )
            data2, diag2 = adapter.fetch_league(
                LeagueId.SUPER_LIG,
                season="2026-2027",
                reference_date=date(2026, 11, 27),
            )
        client.close()

        self.assertEqual(calls, 2)  # 2. çağrı tamamen disk önbelleğinden gelir
        assert data1 is not None and data2 is not None
        self.assertTrue(diag1["ok"])
        self.assertIn("önbellek", diag2["note"] or "")
        self.assertEqual(len(data1.matches), 2)
        self.assertEqual(data1.ht_scores[("Galatasaray", "Besiktas")], (1, 0))
        self.assertEqual(len(data1.injuries), 1)
        self.assertEqual(data1.injuries[0].player_name, "Mauro Icardi")
        self.assertEqual(self.tracker.get_provider_status("api_football")["remaining"], 87)

    def test_api_football_free_plan_error_skips_injuries_and_reports_cleanly(self) -> None:
        calls = 0

        def handler(_: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(
                200,
                json={
                    "errors": {
                        "plan": "Free plans do not have access to this season, try from 2022 to 2024."
                    },
                    "results": 0,
                    "response": [],
                },
            )

        client = httpx.Client(
            base_url="https://v3.football.api-sports.io",
            transport=httpx.MockTransport(handler),
        )
        with ApiFootballAdapter(api_key=FAKE_AF_KEY, client=client, tracker=self.tracker) as adapter:
            data, diag = adapter.fetch_league(LeagueId.SUPER_LIG, season="2026-2027")
        client.close()

        self.assertIsNone(data)
        self.assertFalse(diag["ok"])
        self.assertIn("Free plans do not have access", diag["error"] or "")
        self.assertEqual(calls, 1)  # /injuries çağrılmaz

    def test_the_odds_api_devigging_quota_guard_and_key_redaction(self) -> None:
        calls = 0

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            self.assertEqual(req.url.params.get("apiKey"), FAKE_ODDS_KEY)
            return httpx.Response(
                200,
                headers={"x-requests-remaining": "490", "x-requests-used": "10"},
                json=MOCK_ODDS_EVENTS,
            )

        client = httpx.Client(
            base_url="https://api.the-odds-api.com",
            transport=httpx.MockTransport(handler),
        )
        with TheOddsApiAdapter(
            api_key=FAKE_ODDS_KEY,
            client=client,
            tracker=self.tracker,
        ) as adapter:
            odds_data, diag = adapter.fetch_league(LeagueId.SUPER_LIG)
        client.close()

        assert odds_data is not None
        self.assertEqual(calls, 1)
        self.assertTrue(diag["ok"])
        self.assertNotIn(FAKE_ODDS_KEY, diag["url"])
        self.assertEqual(len(odds_data.matches), 1)

        m = odds_data.matches[0]
        self.assertEqual(m.bookmakers_count, 2)
        self.assertAlmostEqual(m.p_home + m.p_draw + m.p_away, 1.0, places=6)
        assert m.p_over25 is not None and m.p_under25 is not None
        self.assertAlmostEqual(m.p_over25 + m.p_under25, 1.0, places=6)
        self.assertGreater(m.overround_1x2 or 0.0, 1.0)

        for cache_file in (Path(self._tmp.name) / "api_cache").glob("*.json"):
            raw_cache = cache_file.read_text(encoding="utf-8")
            self.assertNotIn(FAKE_ODDS_KEY, raw_cache)

    def test_the_odds_api_blocks_uncached_call_when_remaining_below_15(self) -> None:
        self.tracker.record_headers(
            "the_odds_api",
            {"x-requests-remaining": "10", "x-requests-used": "490"},
        )
        called = False

        def handler(_: httpx.Request) -> httpx.Response:
            nonlocal called
            called = True
            return httpx.Response(200, json=MOCK_ODDS_EVENTS)

        client = httpx.Client(
            base_url="https://api.the-odds-api.com",
            transport=httpx.MockTransport(handler),
        )
        with TheOddsApiAdapter(
            api_key=FAKE_ODDS_KEY,
            client=client,
            tracker=self.tracker,
        ) as adapter:
            data, diag = adapter.fetch_league(LeagueId.PREMIER_LEAGUE)
        client.close()

        self.assertFalse(called)
        self.assertIsNone(data)
        self.assertFalse(diag["ok"])
        self.assertIn("kota koruma", (diag["note"] or "").lower())


class ZeroWafAndResilientPipelineTests(unittest.TestCase):
    def test_base_scraper_has_no_playwright_and_errors_cleanly_on_202_or_403(self) -> None:
        client = httpx.Client(
            base_url="https://mock.tm.local",
            transport=httpx.MockTransport(lambda _: httpx.Response(403, text="Forbidden")),
        )
        scraper = BaseScraper(
            base_url="https://mock.tm.local",
            min_delay=0.0,
            max_delay=0.0,
            client=client,
        )
        self.assertFalse(hasattr(scraper, "_ensure_browser_page"))
        self.assertFalse(hasattr(scraper, "_run_browser_get"))
        with self.assertRaises(ScraperHTTPError) as ctx:
            scraper.fetch_text("/blocked")
        client.close()
        self.assertEqual(ctx.exception.status_code, 403)

    def test_pipeline_resilient_when_transfermarkt_returns_202_and_af_restricted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tracker = QuotaBudgetTracker(
                budget_path=Path(tmp) / "budget.json",
                cache_dir=Path(tmp) / "cache",
            )

            def tm_202_handler(_: httpx.Request) -> httpx.Response:
                return httpx.Response(
                    202,
                    headers={"x-amzn-waf-action": "challenge"},
                    text="<script>AwsWafIntegration</script>",
                )

            def ext_handler(req: httpx.Request) -> httpx.Response:
                url_s = str(req.url)
                if "api-sports.io/fixtures" in url_s:
                    return httpx.Response(
                        200,
                        json={
                            "errors": {
                                "plan": "Free plans do not have access to this season, try from 2022 to 2024."
                            },
                            "results": 0,
                            "response": [],
                        },
                    )
                if "the-odds-api.com" in url_s:
                    return httpx.Response(
                        200,
                        headers={"x-requests-remaining": "480", "x-requests-used": "20"},
                        json=MOCK_ODDS_EVENTS,
                    )
                if "espn.com" in url_s and "scoreboard" in url_s:
                    if "dates=" in url_s:
                        return httpx.Response(200, json=MOCK_ESPN_UPCOMING_SCOREBOARD)
                    return httpx.Response(200, json={"events": []})
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
                                    "history": [{"xG": 2.15, "xGA": 0.90}],
                                }
                            }
                        },
                    )
                return httpx.Response(404)

            with (
                httpx.Client(
                    base_url="https://mock.tm.local",
                    transport=httpx.MockTransport(tm_202_handler),
                ) as tm_c,
                httpx.Client(transport=httpx.MockTransport(ext_handler)) as ext_c,
                httpx.Client(
                    base_url="https://v3.football.api-sports.io",
                    transport=httpx.MockTransport(ext_handler),
                ) as af_c,
                httpx.Client(
                    base_url="https://api.the-odds-api.com",
                    transport=httpx.MockTransport(ext_handler),
                ) as odds_c,
            ):
                base_http = BaseScraper(
                    base_url="https://mock.tm.local",
                    min_delay=0.0,
                    max_delay=0.0,
                    max_retries=0,
                    client=tm_c,
                )
                pipeline = IngestionPipeline(
                    http=base_http,
                    fixtures_scraper=FixturesScraper(base_http),
                    injuries_scraper=InjuriesScraper(base_http),
                    enable_multi_source=True,
                    espn_adapter=ESPNAdapter(client=ext_c),
                    football_data_adapter=FootballDataAdapter(
                        client=ext_c, allow_mirror_fallback=False
                    ),
                    understat_adapter=UnderstatAdapter(client=ext_c, allow_opta_bridge=False),
                    secondary_adapter=SecondaryCheckAdapter(
                        client=ext_c, allow_live_fallbacks=False
                    ),
                    api_football_adapter=ApiFootballAdapter(
                        api_key=FAKE_AF_KEY, client=af_c, tracker=tracker
                    ),
                    odds_adapter=TheOddsApiAdapter(
                        api_key=FAKE_ODDS_KEY, client=odds_c, tracker=tracker
                    ),
                )
                res = pipeline.run_league(
                    LeagueId.SUPER_LIG,
                    reference_date=date(2026, 11, 27),
                    persist=False,
                )

            self.assertFalse(res.source_diagnostics["Transfermarkt"]["ok"])
            self.assertEqual(res.source_diagnostics["Transfermarkt"]["http_status"], 202)
            self.assertNotIn("Transfermarkt", res.sources_used)
            self.assertIn("TheOddsAPI", res.sources_used)
            self.assertIn("ESPN", res.sources_used)
            self.assertIn("Football-Data", res.sources_used)

            finished = [m for m in res.matches if m.status == MatchStatus.FINISHED]
            scheduled = [m for m in res.matches if m.status == MatchStatus.SCHEDULED]
            self.assertEqual(len(finished), 2)
            self.assertEqual(len(scheduled), 2)
            self.assertTrue(all(m.round == 13 for m in scheduled))
            self.assertEqual(len(res.injuries), 1)
            self.assertEqual(res.injuries[0].player_name, "Mauro Icardi")

            fb = next(t for t in res.teams if "Fenerbahce" in t.name)
            gs = next(t for t in res.teams if "Galatasaray" in t.name)
            assert fb.id is not None and gs.id is not None
            self.assertIn((fb.id, gs.id), res.market_odds)
            fb_gs_odds = res.market_odds[(fb.id, gs.id)]
            self.assertAlmostEqual(
                fb_gs_odds["p_home"] + fb_gs_odds["p_draw"] + fb_gs_odds["p_away"],
                1.0,
                places=5,
            )
            self.assertIn("p_over25", fb_gs_odds)
            self.assertIn("p_under25", fb_gs_odds)


class ArchiveSnapshotTests(unittest.TestCase):
    def test_save_snapshot_writes_compact_timestamped_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            tracker = QuotaBudgetTracker(
                budget_path=tmp_path / "budget.json",
                cache_dir=tmp_path / "cache",
            )
            now_dt = datetime(2026, 11, 27, 14, 30, 0, tzinfo=UTC)
            tracker.record_headers(
                "the_odds_api",
                {"x-requests-remaining": "496", "x-requests-used": "4"},
                now_utc=now_dt,
            )

            sample_bulletin = {
                "generated_at": "2026-11-27T14:30:00+00:00",
                "sources_used": ["TheOddsAPI", "ESPN", "Football-Data"],
                "total_injuries": 3,
                "leagues": [
                    {
                        "id": "super_lig",
                        "name": "Süper Lig",
                        "next_round": 13,
                        "injuries_count": 3,
                        "matches": [
                            {
                                "id": 10,
                                "round": 13,
                                "match_date": "2026-11-29T16:00:00+00:00",
                                "home_team": "Fenerbahçe",
                                "away_team": "Galatasaray",
                                "status": "SCHEDULED",
                                "prediction": {
                                    "prob_home": 0.44,
                                    "prob_draw": 0.27,
                                    "prob_away": 0.29,
                                    "prob_over_25": 0.54,
                                    "prob_under_25": 0.46,
                                    "confidence_score": 0.72,
                                },
                            }
                        ],
                    }
                ],
            }
            market_odds = {(1, 2): {"p_home": 0.44, "p_draw": 0.27, "p_away": 0.29}}

            snap_dir = tmp_path / "snapshots"
            p1 = save_snapshot(
                sample_bulletin,
                snapshots_dir=snap_dir,
                market_odds=market_odds,
                tracker=tracker,
                now_utc=now_dt,
            )
            p2 = save_snapshot(
                sample_bulletin,
                snapshots_dir=snap_dir,
                market_odds=market_odds,
                tracker=tracker,
                now_utc=now_dt,
            )

            self.assertEqual(p1.name, "snapshot_20261127T143000Z.json")
            self.assertEqual(p2.name, "snapshot_20261127T143000Z_1.json")

            saved = json.loads(p1.read_text(encoding="utf-8"))
            self.assertEqual(saved["generated_at"], "2026-11-27T14:30:00+00:00")
            self.assertEqual(saved["sources_used"], ["TheOddsAPI", "ESPN", "Football-Data"])
            self.assertEqual(saved["market_odds_count"], 1)
            self.assertEqual(saved["injuries_summary"]["total_injuries"], 3)
            self.assertEqual(saved["quota_status"]["the_odds_api"]["remaining"], 496)
            self.assertEqual(len(saved["leagues"]), 1)
            self.assertEqual(
                saved["leagues"][0]["matches"][0]["probabilities"]["prob_home"],
                0.44,
            )


if __name__ == "__main__":
    unittest.main()
