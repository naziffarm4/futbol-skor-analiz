"""GÖREV-02 veri toplama motoru birim, şema uyumluluk ve canlı duman (smoke) testleri."""

from __future__ import annotations

import json
import logging
import unittest
from datetime import date
from typing import Any
from unittest.mock import MagicMock

import httpx

from engine.config import PROJECT_ROOT, LeagueId
from engine.db.client import reset_clients
from engine.models.schemas import (
    ImpactLevel,
    Injury,
    League,
    Match,
    MatchStatus,
    PlayerPosition,
    Team,
)
from engine.scrapers.base import (
    BaseScraper,
    ScraperError,
    ScraperHTTPError,
    ScraperParseError,
    build_browser_headers,
    normalize_team_name,
    parse_html,
)
from engine.scrapers.fixtures import FixturesScraper, parse_fixtures_html
from engine.scrapers.injuries import (
    TRANSFERMARKT_LEAGUES,
    InjuriesScraper,
    calculate_impact_level,
    map_player_position,
    parse_injuries_html,
    parse_return_date,
)
from engine.scrapers.pipeline import IngestionPipeline
from engine.tests.test_foundation import _extract_sql_table_columns

logger = logging.getLogger(__name__)

MOCK_INJURIES_HTML = """
<!doctype html>
<html>
<body>
<div class="box">
  <table class="items">
    <thead>
      <tr>
        <th>Oyuncu/Pozisyon</th>
        <th>Kulüp</th>
        <th>Sakatlık</th>
        <th>Bitiş tarihi</th>
        <th>Piyasa değeri</th>
      </tr>
    </thead>
    <tbody>
      <tr class="odd">
        <td>
          <table class="inline-table">
            <tr>
              <td rowspan="2"><img alt="Mauro Icardi" src="data:image/gif;base64,R0lG"/></td>
              <td class="hauptlink"><a href="/icardi/profil/spieler/1" title="Mauro Icardi">Mauro Icardi</a></td>
            </tr>
            <tr><td>Santrafor</td></tr>
          </table>
        </td>
        <td class="zentriert"><a href="/gs/startseite/verein/141" title="Galatasaray SK"><img alt="Galatasaray SK"/></a></td>
        <td>Çapraz bağ yırtığı</td>
        <td>15 Nis 2027</td>
        <td>15.00 Mn €</td>
      </tr>
      <tr class="even">
        <td>
          <table class="inline-table">
            <tr>
              <td rowspan="2"><img alt="Lucas Torreira"/></td>
              <td class="hauptlink"><a href="/torreira/profil/spieler/2" title="Lucas Torreira">Lucas Torreira</a></td>
            </tr>
            <tr><td>Ön Libero</td></tr>
          </table>
        </td>
        <td class="zentriert"><a href="/gs/startseite/verein/141" title="Galatasaray SK"><img alt="Galatasaray SK"/></a></td>
        <td>Sarı kart cezalısı</td>
        <td>02.12.2026</td>
        <td>13.00 Mn €</td>
      </tr>
      <tr class="odd">
        <td>
          <table class="inline-table">
            <tr>
              <td rowspan="2"><img alt="Mert Günok"/></td>
              <td class="hauptlink"><a href="/mert/profil/spieler/3" title="Mert Günok">Mert Günok</a></td>
            </tr>
            <tr><td>Kaleci</td></tr>
          </table>
        </td>
        <td class="zentriert"><a href="/bjk/startseite/verein/114" title="Beşiktaş JK"><img alt="Beşiktaş JK"/></a></td>
        <td>Soğuk algınlığı (şüpheli)</td>
        <td>27 Kas 2026</td>
        <td>1.50 Mn €</td>
      </tr>
      <tr class="even">
        <td>
          <table class="inline-table">
            <tr>
              <td rowspan="2"><img alt="Çağlar Söyüncü"/></td>
              <td class="hauptlink"><a href="/caglar/profil/spieler/4" title="Çağlar Söyüncü">Çağlar Söyüncü</a></td>
            </tr>
            <tr><td>Stoper</td></tr>
          </table>
        </td>
        <td class="zentriert"><a href="/fb/startseite/verein/36" title="Fenerbahçe"><img alt="Fenerbahçe"/></a></td>
        <td>Arka adale sorunu</td>
        <td>?</td>
        <td>8.00 Mn €</td>
      </tr>
    </tbody>
  </table>
</div>
</body>
</html>
"""

MOCK_SUSPENSIONS_PAGE1_HTML = """
<html><body>
<table class="items">
  <tbody>
    <tr class="odd">
      <td>
        <table class="inline-table">
          <tr><td rowspan="2"></td><td class="hauptlink"><a title="Edin Visca">Edin Visca</a></td></tr>
          <tr><td>Sağ Kanat</td></tr>
        </table>
      </td>
      <td><a title="Trabzonspor"><img alt="Trabzonspor"/></a></td>
      <td>Kırmızı kart cezalısı</td>
      <td>15 Ara 2026</td>
      <td>2</td>
    </tr>
  </tbody>
</table>
<ul class="tm-pagination">
  <li class="tm-pagination__list-item tm-pagination__list-item--icon-next-page">
    <a class="tm-pagination__link" href="/super-lig/sperrenausfaelle/wettbewerb/TR1/page/2"></a>
  </li>
</ul>
</body></html>
"""

MOCK_SUSPENSIONS_PAGE2_HTML = """
<html><body>
<table class="items">
  <tbody>
    <tr class="odd">
      <td>
        <table class="inline-table">
          <tr><td rowspan="2"></td><td class="hauptlink"><a title="İrfan Can Kahveci">İrfan Can Kahveci</a></td></tr>
          <tr><td>On Numara</td></tr>
        </table>
      </td>
      <td><a title="Fenerbahçe"><img alt="Fenerbahçe"/></a></td>
      <td>Kas sakatlığı</td>
      <td>10 Ara 2026</td>
      <td>1</td>
    </tr>
  </tbody>
</table>
</body></html>
"""

MOCK_FIXTURES_HTML = """
<!doctype html>
<html>
<body>
<div class="box">
  <div class="content-box-headline">12.Hafta</div>
  <table>
    <tbody>
      <tr class="bg_blau_20"><td colspan="7">Cum 20.11.2026 20:00</td></tr>
      <tr>
        <td>Cum <a href="/aktuell/waspassiertheute/aktuell/new/datum/2026-11-20">20.11.2026</a></td>
        <td>20:00</td>
        <td><span class="tabellenplatz">(1.)</span> <a href="/gs" title="Galatasaray SK">Galatasaray</a></td>
        <td><a href="/gs" title="Galatasaray SK"><img src="https://cdn.example.com/gs.png"/></a></td>
        <td><a class="ergebnis-link" href="/spielbericht/index/spielbericht/1001" title="Maç raporu">3:1</a></td>
        <td><a href="/bjk" title="Beşiktaş JK"><img src="https://cdn.example.com/bjk.png"/></a></td>
        <td><a href="/bjk" title="Beşiktaş JK">Beşiktaş</a> <span class="tabellenplatz">(4.)</span></td>
      </tr>
      <tr>
        <td></td>
        <td></td>
        <td><a href="/fb" title="Fenerbahçe">Fenerbahçe</a></td>
        <td><a href="/fb" title="Fenerbahçe"><img data-src="https://cdn.example.com/fb.png" src="data:image/gif;base64,R0lG"/></a></td>
        <td><a class="ergebnis-link" href="/spielbericht/index/spielbericht/1002">2:0</a></td>
        <td><a href="/ts" title="Trabzonspor"><img src="https://cdn.example.com/ts.png"/></a></td>
        <td><a href="/ts" title="Trabzonspor">Trabzonspor</a></td>
      </tr>
    </tbody>
  </table>
</div>
<div class="box">
  <div class="content-box-headline">13.Hafta</div>
  <table>
    <tbody>
      <tr>
        <td>Paz 29.11.2026</td>
        <td>19:00</td>
        <td><a href="/bjk" title="Beşiktaş JK">Beşiktaş</a></td>
        <td><a href="/bjk" title="Beşiktaş JK"><img src="https://cdn.example.com/bjk.png"/></a></td>
        <td><a href="/vorbericht/1003" title="Ön rapor">-:-</a></td>
        <td><a href="/fb" title="Fenerbahçe"><img src="https://cdn.example.com/fb.png"/></a></td>
        <td><a href="/fb" title="Fenerbahçe">Fenerbahçe</a></td>
      </tr>
      <tr>
        <td></td>
        <td>21:30</td>
        <td><a href="/ts" title="Trabzonspor">Trabzonspor</a></td>
        <td><a href="/ts" title="Trabzonspor"><img src="https://cdn.example.com/ts.png"/></a></td>
        <td><a href="/vorbericht/1004" title="Ön rapor">21:30</a></td>
        <td><a href="/gs" title="Galatasaray SK"><img src="https://cdn.example.com/gs.png"/></a></td>
        <td><a href="/gs" title="Galatasaray SK">Galatasaray</a></td>
      </tr>
      <tr>
        <td>Pzt 30.11.2026</td>
        <td>20:00</td>
        <td><a href="/riz" title="Çaykur Rizespor ">Ç. Rizespor</a></td>
        <td><a href="/riz" title="Çaykur Rizespor "><img src="https://cdn.example.com/riz.png"/></a></td>
        <td><span>ert.</span></td>
        <td><a href="/kas" title="Kasımpaşa"><img src="https://cdn.example.com/kas.png"/></a></td>
        <td><a href="/kas" title="Kasımpaşa">Kasımpaşa</a></td>
      </tr>
    </tbody>
  </table>
</div>
</body>
</html>
"""


class BaseScraperTests(unittest.TestCase):
    def test_headers_and_helpers(self) -> None:
        headers = build_browser_headers()
        self.assertIn("Mozilla/5.0", headers["User-Agent"])
        self.assertIn("Accept-Language", headers)
        self.assertIn("Referer", headers)
        self.assertEqual(normalize_team_name("(1.)  Galatasaray SK "), "Galatasaray SK")
        with self.assertRaises(ScraperParseError):
            parse_html("   ")

    def test_rate_limiting_and_retry_backoff(self) -> None:
        attempts = 0
        slept: list[float] = []

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return httpx.Response(429, headers={"Retry-After": "2"}, text="Too Many Requests")
            if attempts == 2:
                raise httpx.ConnectTimeout("timeout", request=request)
            return httpx.Response(200, text="<html><body><div class='box'>ok</div></body></html>")

        client = httpx.Client(
            base_url="https://mock.tm.local",
            transport=httpx.MockTransport(handler),
        )
        with BaseScraper(
            base_url="https://mock.tm.local",
            min_delay=1.2,
            max_delay=1.5,
            max_retries=3,
            backoff_factor=0.5,
            client=client,
            sleep_fn=slept.append,
        ) as scraper:
            soup = scraper.fetch_soup("/test")
            box = soup.select_one(".box")
            assert box is not None
            self.assertEqual(box.get_text(), "ok")
            scraper.fetch_text("/second")

        client.close()
        self.assertEqual(attempts, 4)
        self.assertGreaterEqual(slept[0], 2.0)
        self.assertTrue(any(1.0 <= s <= 1.6 for s in slept))

    def test_non_retryable_404_raises_immediately(self) -> None:
        calls = 0

        def handler(_: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(404, text="Not Found")

        client = httpx.Client(
            base_url="https://mock.tm.local",
            transport=httpx.MockTransport(handler),
        )
        scraper = BaseScraper(
            base_url="https://mock.tm.local",
            min_delay=0.0,
            max_delay=0.0,
            max_retries=3,
            client=client,
        )
        with self.assertRaises(ScraperHTTPError) as ctx:
            scraper.fetch_text("/missing")
        client.close()
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(calls, 1)

    def test_waf_202_raises_http_error_without_browser_bypass(self) -> None:
        http_calls = 0

        def handler(_: httpx.Request) -> httpx.Response:
            nonlocal http_calls
            http_calls += 1
            return httpx.Response(
                202,
                headers={"x-amzn-waf-action": "challenge"},
                text="<script>AwsWafIntegration</script>",
            )

        client = httpx.Client(
            base_url="https://mock.tm.local",
            transport=httpx.MockTransport(handler),
        )
        with BaseScraper(
            base_url="https://mock.tm.local",
            min_delay=0.0,
            max_delay=0.0,
            max_retries=2,
            client=client,
        ) as scraper:
            with self.assertRaises(ScraperHTTPError) as ctx:
                scraper.fetch_soup("/fixtures")
            self.assertEqual(ctx.exception.status_code, 202)

        client.close()
        self.assertEqual(http_calls, 1)


class InjuriesScraperTests(unittest.TestCase):
    def test_four_league_routes(self) -> None:
        expected = {
            LeagueId.SUPER_LIG: ("TR1", "/super-lig/sperrenundverletzungen/wettbewerb/TR1"),
            LeagueId.PREMIER_LEAGUE: (
                "GB1",
                "/premier-league/sperrenundverletzungen/wettbewerb/GB1",
            ),
            LeagueId.LA_LIGA: ("ES1", "/laliga/sperrenundverletzungen/wettbewerb/ES1"),
            LeagueId.LIGUE_1: ("FR1", "/ligue-1/sperrenundverletzungen/wettbewerb/FR1"),
        }
        self.assertEqual(set(TRANSFERMARKT_LEAGUES.keys()), set(expected.keys()))
        for lid, (code, path) in expected.items():
            self.assertEqual(TRANSFERMARKT_LEAGUES[lid].code, code)
            self.assertEqual(TRANSFERMARKT_LEAGUES[lid].combined_injuries_path, path)

    def test_position_date_and_impact_logic(self) -> None:
        self.assertEqual(map_player_position("Kaleci"), PlayerPosition.GK)
        self.assertEqual(map_player_position("Goalkeeper"), PlayerPosition.GK)
        self.assertEqual(map_player_position("Stoper"), PlayerPosition.DEF)
        self.assertEqual(map_player_position("Left-Back"), PlayerPosition.DEF)
        self.assertEqual(map_player_position("Ön Libero"), PlayerPosition.MID)
        self.assertEqual(map_player_position("On Numara"), PlayerPosition.MID)
        self.assertEqual(map_player_position("Santrafor"), PlayerPosition.FW)
        self.assertEqual(map_player_position("Sağ Kanat"), PlayerPosition.FW)

        ref = date(2026, 11, 25)
        self.assertEqual(parse_return_date("27 Kas 2026"), date(2026, 11, 27))
        self.assertEqual(parse_return_date("02.12.2026"), date(2026, 12, 2))
        self.assertIsNone(parse_return_date("?"))

        self.assertEqual(
            calculate_impact_level("Diz ameliyatı", reference_date=ref),
            ImpactLevel.HIGH,
        )
        self.assertEqual(
            calculate_impact_level(
                "Kas sorunu",
                return_date=date(2027, 3, 1),
                reference_date=ref,
            ),
            ImpactLevel.HIGH,
        )
        self.assertEqual(
            calculate_impact_level(
                "Sarı kart cezalısı",
                return_date=date(2026, 11, 28),
                reference_date=ref,
            ),
            ImpactLevel.MEDIUM,
        )
        self.assertEqual(
            calculate_impact_level(
                "Hafif ağrı / şüpheli",
                return_date=date(2026, 11, 28),
                reference_date=ref,
            ),
            ImpactLevel.LOW,
        )

    def test_parse_mock_injuries_html_and_split_fallback(self) -> None:
        ref = date(2026, 11, 25)
        parsed = parse_injuries_html(MOCK_INJURIES_HTML, LeagueId.SUPER_LIG, reference_date=ref)
        self.assertEqual(len(parsed), 4)

        icardi, torreira, mert, caglar = parsed
        self.assertEqual(icardi.team_name, "Galatasaray SK")
        self.assertEqual(icardi.position, PlayerPosition.FW)
        self.assertEqual(icardi.return_date, date(2027, 4, 15))
        self.assertEqual(icardi.impact_level, ImpactLevel.HIGH)

        self.assertEqual(torreira.position, PlayerPosition.MID)
        self.assertEqual(torreira.impact_level, ImpactLevel.MEDIUM)

        self.assertEqual(mert.position, PlayerPosition.GK)
        self.assertEqual(mert.impact_level, ImpactLevel.LOW)

        self.assertEqual(caglar.position, PlayerPosition.DEF)
        self.assertIsNone(caglar.return_date)
        self.assertEqual(caglar.impact_level, ImpactLevel.MEDIUM)

        routes = {
            "/super-lig/sperrenundverletzungen/wettbewerb/TR1": (404, "Not Found"),
            "/super-lig/verletztespieler/wettbewerb/TR1": (200, MOCK_INJURIES_HTML),
            "/super-lig/sperrenausfaelle/wettbewerb/TR1": (200, MOCK_SUSPENSIONS_PAGE1_HTML),
            "/super-lig/sperrenausfaelle/wettbewerb/TR1/page/2": (200, MOCK_SUSPENSIONS_PAGE2_HTML),
        }

        def handler(req: httpx.Request) -> httpx.Response:
            status, body = routes.get(req.url.path, (404, "Not Found"))
            return httpx.Response(status, text=body)

        client = httpx.Client(
            base_url="https://mock.tm.local",
            transport=httpx.MockTransport(handler),
        )
        base = BaseScraper(
            base_url="https://mock.tm.local",
            min_delay=0.0,
            max_delay=0.0,
            client=client,
        )
        scraper = InjuriesScraper(base)
        combined = scraper.fetch_league_injuries(LeagueId.SUPER_LIG, reference_date=ref)
        client.close()

        self.assertEqual(len(combined), 6)
        visca = next(x for x in combined if x.player_name == "Edin Visca")
        self.assertEqual(visca.impact_level, ImpactLevel.HIGH)
        self.assertEqual(visca.position, PlayerPosition.FW)


class FixturesScraperTests(unittest.TestCase):
    def test_parse_fixtures_scores_carryover_and_upcoming_round(self) -> None:
        data = parse_fixtures_html(MOCK_FIXTURES_HTML, LeagueId.SUPER_LIG)
        self.assertEqual(len(data.teams), 6)
        self.assertEqual(len(data.matches), 5)

        self.assertEqual(len(data.played_matches), 2)
        self.assertEqual(data.next_round, 13)
        self.assertEqual(len(data.next_round_matches), 3)

        m1, m2, m3, m4, m5 = data.matches
        self.assertEqual(m1.home_team_name, "Galatasaray SK")
        self.assertEqual(m1.home_short_name, "Galatasaray")
        self.assertEqual(m1.status, MatchStatus.FINISHED)
        self.assertEqual((m1.home_score, m1.away_score), (3, 1))
        self.assertEqual(m1.match_date.isoformat(), "2026-11-20T20:00:00+00:00")

        # Carry-over doğrulaması (boş tarih/saat hücresi önceki satırdan devralınmalı)
        self.assertEqual(m2.match_date.isoformat(), "2026-11-20T20:00:00+00:00")
        self.assertEqual((m2.home_score, m2.away_score), (2, 0))
        fb_team = next(t for t in data.teams if t.name == "Fenerbahçe")
        self.assertEqual(fb_team.logo_url, "https://cdn.example.com/fb.png")

        # Ön rapor ve saat içeren hücreler SCHEDULED olarak kalmalı
        self.assertEqual(m3.status, MatchStatus.SCHEDULED)
        self.assertIsNone(m3.home_score)
        self.assertEqual(m4.status, MatchStatus.SCHEDULED)
        self.assertIsNone(m4.home_score)
        self.assertEqual(m4.match_date.isoformat(), "2026-11-29T21:30:00+00:00")

        # Ertelenen maç doğrulaması
        self.assertEqual(m5.home_team_name, "Çaykur Rizespor")
        self.assertEqual(m5.status, MatchStatus.POSTPONED)


class PipelineTests(unittest.TestCase):
    def tearDown(self) -> None:
        reset_clients()

    def _build_mock_http(self) -> tuple[BaseScraper, httpx.Client]:
        def handler(req: httpx.Request) -> httpx.Response:
            if "gesamtspielplan" in req.url.path:
                return httpx.Response(200, text=MOCK_FIXTURES_HTML)
            if "sperrenundverletzungen" in req.url.path:
                return httpx.Response(200, text=MOCK_INJURIES_HTML)
            return httpx.Response(404, text="Not Found")

        client = httpx.Client(
            base_url="https://mock.tm.local",
            transport=httpx.MockTransport(handler),
        )
        return (
            BaseScraper(
                base_url="https://mock.tm.local",
                min_delay=0.0,
                max_delay=0.0,
                client=client,
            ),
            client,
        )

    def test_pipeline_local_json_fallback_and_schema_parity(self) -> None:
        base_http, raw_client = self._build_mock_http()
        try:
            pipeline = IngestionPipeline(
                http=base_http,
                fixtures_scraper=FixturesScraper(base_http),
                injuries_scraper=InjuriesScraper(base_http),
            )
            result = pipeline.run(
                LeagueId.SUPER_LIG,
                reference_date=date(2026, 11, 25),
                persist=False,
            )
        finally:
            raw_client.close()

        self.assertFalse(result.persisted)
        self.assertTrue(all(isinstance(lg, League) for lg in result.leagues))
        self.assertTrue(all(isinstance(tm, Team) for tm in result.teams))
        self.assertTrue(all(isinstance(mt, Match) for mt in result.matches))
        self.assertTrue(all(isinstance(inj, Injury) for inj in result.injuries))
        self.assertEqual(len(result.matches), 5)
        self.assertEqual(len(result.injuries), 4)

        payload_dict = json.loads(result.to_json())
        sql_text = (PROJECT_ROOT / "engine" / "db" / "schema.sql").read_text(encoding="utf-8")
        sql_cols = _extract_sql_table_columns(sql_text)

        for key_name in ("leagues", "teams", "matches", "injuries"):
            for item in payload_dict[key_name]:
                self.assertTrue(
                    set(item.keys()).issubset(set(sql_cols[key_name])),
                    f"{key_name} çıktısında şema dışı alan: {set(item.keys()) - set(sql_cols[key_name])}",
                )

    def test_pipeline_supabase_persistence_flow(self) -> None:
        base_http, raw_client = self._build_mock_http()
        recorded_ops: list[tuple[str, str, Any]] = []
        mock_sb = MagicMock()

        def table_router(table_name: str) -> MagicMock:
            tbl = MagicMock()

            def upsert_fn(payload: Any, **kwargs: Any) -> MagicMock:
                recorded_ops.append((table_name, "upsert", (payload, kwargs)))
                op = MagicMock()
                if table_name == "teams":
                    op.execute.return_value = MagicMock(
                        data=[
                            {"id": idx + 10, "name": row["name"], "league_id": row["league_id"]}
                            for idx, row in enumerate(payload)
                        ]
                    )
                else:
                    op.execute.return_value = MagicMock(data=[])
                return op

            def delete_fn() -> MagicMock:
                del_op = MagicMock()

                def in_fn(col: str, vals: list[int]) -> MagicMock:
                    recorded_ops.append((table_name, "delete_in", (col, vals)))
                    exec_op = MagicMock()
                    exec_op.execute.return_value = MagicMock(data=[])
                    return exec_op

                del_op.in_.side_effect = in_fn
                return del_op

            def insert_fn(payload: Any) -> MagicMock:
                recorded_ops.append((table_name, "insert", payload))
                op = MagicMock()
                op.execute.return_value = MagicMock(data=payload)
                return op

            tbl.upsert.side_effect = upsert_fn
            tbl.delete.side_effect = delete_fn
            tbl.insert.side_effect = insert_fn
            return tbl

        mock_sb.table.side_effect = table_router

        try:
            pipeline = IngestionPipeline(
                http=base_http,
                fixtures_scraper=FixturesScraper(base_http),
                injuries_scraper=InjuriesScraper(base_http),
                supabase_client=mock_sb,
            )
            result = pipeline.run(
                LeagueId.SUPER_LIG,
                reference_date=date(2026, 11, 25),
                persist=True,
            )
        finally:
            raw_client.close()

        self.assertTrue(result.persisted)
        op_names = [(t, a) for t, a, _ in recorded_ops]
        self.assertIn(("leagues", "upsert"), op_names)
        self.assertIn(("teams", "upsert"), op_names)
        self.assertIn(("matches", "upsert"), op_names)
        self.assertIn(("injuries", "delete_in"), op_names)
        self.assertIn(("injuries", "insert"), op_names)
        self.assertTrue(all(m.home_team_id >= 10 for m in result.matches))
        self.assertTrue(all(i.team_id >= 10 for i in result.injuries))


class LiveSmokeTests(unittest.TestCase):
    def test_live_transfermarkt_super_lig_smoke(self) -> None:
        """Tek lig üzerinden canlı entegrasyon testi; ağ engeli durumunda zarifçe atlar."""
        try:
            with BaseScraper(min_delay=0.5, max_delay=1.0, max_retries=1, timeout=12.0) as http:
                pipeline = IngestionPipeline(
                    http=http,
                    fixtures_scraper=FixturesScraper(http),
                    injuries_scraper=InjuriesScraper(http, max_pages=1),
                )
                res = pipeline.run_league(LeagueId.SUPER_LIG, persist=False)
        except (ScraperError, httpx.HTTPError) as exc:
            logger.warning("Canlı smoke-test ağ/erişim engeli nedeniyle atlandı: %s", exc)
            self.skipTest(f"Canlı kaynak erişilemedi (zarif atlama): {exc}")
            return

        self.assertGreater(len(res.teams), 10)
        self.assertGreater(len(res.matches), 50)
        self.assertGreater(len(res.injuries), 0)


if __name__ == "__main__":
    unittest.main()
