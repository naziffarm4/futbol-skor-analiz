"""GÖREV-04: Runner orkestratörü, CLI arayüzü ve FastAPI servisi doğrulama testleri."""

from __future__ import annotations

import asyncio
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

import app as service_app
import engine.bulletin as bulletin_mod
from engine.bulletin import clear_bulletin_memory_cache
from engine.cli import main as cli_main
from engine.cli import parse_args
from engine.config import DEFAULT_SEASON, LEAGUES, LeagueId
from engine.models.schemas import (
    ImpactLevel,
    Injury,
    League,
    Match,
    MatchStatus,
    PlayerPosition,
    Team,
)
from engine.predictors.service import PredictionService
from engine.runner import RunnerStatus, get_runner_status, run_full_cycle
from engine.scrapers.pipeline import LeaguePipelineResult


def _build_mock_league_result(league_id: LeagueId, base_id: int) -> LeaguePipelineResult:
    meta = LEAGUES[league_id]
    league = League(
        id=meta.id,
        name=meta.name,
        country=meta.country,
        season=meta.season,
    )
    home_id = base_id * 10 + 1
    away_id = base_id * 10 + 2
    teams = [
        Team(id=home_id, league_id=league_id, name=f"{meta.name} Ev", short_name="EV"),
        Team(id=away_id, league_id=league_id, name=f"{meta.name} Dep", short_name="DEP"),
    ]
    matches = [
        Match(
            id=base_id * 100 + 1,
            league_id=league_id,
            home_team_id=home_id,
            away_team_id=away_id,
            match_date=datetime(2026, 10, 10, 19, 0, tzinfo=UTC),
            round=1,
            status=MatchStatus.FINISHED,
            home_score=2,
            away_score=1,
        ),
        Match(
            id=base_id * 100 + 2,
            league_id=league_id,
            home_team_id=away_id,
            away_team_id=home_id,
            match_date=datetime(2026, 10, 17, 19, 0, tzinfo=UTC),
            round=2,
            status=MatchStatus.SCHEDULED,
        ),
    ]
    injuries = [
        Injury(
            id=base_id * 10 + 1,
            team_id=home_id,
            player_name=f"Oyuncu {base_id}",
            position=PlayerPosition.FW,
            reason="Kas Sakatlığı",
            impact_level=ImpactLevel.HIGH,
        )
    ]
    return LeaguePipelineResult(
        league=league,
        teams=teams,
        matches=matches,
        injuries=injuries,
        persisted=False,
    )


class RunnerAndServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        get_runner_status().reset()
        clear_bulletin_memory_cache()
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_cache_path = Path(self._tmp_dir.name) / "bulletin_cache.json"
        self._cache_patcher = patch.object(
            bulletin_mod, "BULLETIN_CACHE_PATH", self.tmp_cache_path
        )
        self._cache_patcher.start()

    def tearDown(self) -> None:
        self._cache_patcher.stop()
        clear_bulletin_memory_cache()
        self._tmp_dir.cleanup()

    def test_runner_full_cycle(self) -> None:
        call_order: list[str] = []
        mock_pipeline = MagicMock()

        def fake_run_league(lid: LeagueId, *, persist: bool = True) -> LeaguePipelineResult:
            call_order.append(f"ingest:{lid.value}")
            idx = list(LEAGUES.keys()).index(lid) + 1
            return _build_mock_league_result(lid, idx)

        mock_pipeline.run_league.side_effect = fake_run_league

        real_predictor = PredictionService()
        spy_predictor = MagicMock(wraps=real_predictor)

        def tracked_predict(**kwargs):
            matches = kwargs.get("matches", [])
            lid_val = matches[0].league_id.value if matches else "unknown"
            call_order.append(f"predict:{lid_val}")
            return real_predictor.run(**kwargs)

        spy_predictor.run.side_effect = tracked_predict

        tracker = RunnerStatus()
        result = run_full_cycle(
            leagues=None,
            persist=False,
            only_next_round=True,
            status_tracker=tracker,
            ingestion_pipeline=mock_pipeline,
            prediction_service=spy_predictor,
        )

        expected_order = [
            "ingest:super_lig",
            "predict:super_lig",
            "ingest:premier_league",
            "predict:premier_league",
            "ingest:la_liga",
            "predict:la_liga",
            "ingest:ligue_1",
            "predict:ligue_1",
        ]
        self.assertEqual(call_order, expected_order)
        self.assertEqual(result.status, "success")
        self.assertFalse(result.persisted)
        self.assertEqual(result.matches_count, 8)
        self.assertEqual(result.injuries_count, 4)
        self.assertEqual(result.predictions_count, 4)
        self.assertEqual(result.team_analyses_count, 4)
        self.assertEqual(result.errors, {})

        self.assertFalse(tracker.is_running)
        self.assertEqual(tracker.last_status, "success")
        self.assertEqual(tracker.total_runs, 1)
        self.assertEqual(tracker.total_matches_processed, 8)
        self.assertEqual(tracker.total_injuries_processed, 4)
        self.assertEqual(tracker.total_predictions_generated, 4)
        for lid in LeagueId:
            lg_info = tracker.leagues[lid.value]
            self.assertEqual(lg_info.status, "success")
            self.assertEqual(lg_info.matches_count, 2)
            self.assertEqual(lg_info.injuries_count, 1)
            self.assertEqual(lg_info.predictions_count, 1)
            self.assertIsNotNone(lg_info.last_sync_at)

    def test_runner_partial_failure_isolation(self) -> None:
        mock_pipeline = MagicMock()

        def flaky_run_league(lid: LeagueId, *, persist: bool = True) -> LeaguePipelineResult:
            if lid == LeagueId.LA_LIGA:
                raise RuntimeError("simüle edilen ağ zaman aşımı")
            idx = list(LEAGUES.keys()).index(lid) + 1
            return _build_mock_league_result(lid, idx)

        mock_pipeline.run_league.side_effect = flaky_run_league
        tracker = RunnerStatus()

        result = run_full_cycle(
            leagues=None,
            persist=False,
            status_tracker=tracker,
            ingestion_pipeline=mock_pipeline,
            prediction_service=PredictionService(),
        )

        self.assertEqual(result.status, "partial_error")
        self.assertIn("la_liga", result.errors)
        self.assertEqual(result.predictions_count, 3)
        self.assertFalse(tracker.is_running)
        self.assertEqual(tracker.leagues["la_liga"].status, "error")
        self.assertEqual(tracker.leagues["super_lig"].status, "success")
        self.assertEqual(tracker.leagues["ligue_1"].status, "success")

    def test_cli_argument_parsing(self) -> None:
        args_single = parse_args(["--league", "super_lig", "--dry-run"])
        self.assertEqual(args_single.league, "super_lig")
        self.assertFalse(args_single.all)
        self.assertTrue(args_single.dry_run)
        self.assertFalse(args_single.schedule)

        args_all = parse_args(["--all", "--schedule"])
        self.assertIsNone(args_all.league)
        self.assertTrue(args_all.all)
        self.assertFalse(args_all.dry_run)
        self.assertTrue(args_all.schedule)

        with self.assertRaises(SystemExit):
            parse_args(["--league", "super_lig", "--all"])

        with self.assertRaises(SystemExit):
            parse_args(["--league", "bundesliga"])

        mock_pipeline = MagicMock()
        mock_pipeline.run_league.return_value = _build_mock_league_result(LeagueId.SUPER_LIG, 1)
        fake_cycle = run_full_cycle(
            leagues=[LeagueId.SUPER_LIG],
            persist=False,
            status_tracker=RunnerStatus(),
            ingestion_pipeline=mock_pipeline,
            prediction_service=PredictionService(),
        )

        buf = io.StringIO()
        with patch("engine.cli.run_full_cycle", return_value=fake_cycle) as mocked_run:
            with redirect_stdout(buf):
                exit_code = cli_main(["--league", "super_lig", "--dry-run"])

        self.assertEqual(exit_code, 0)
        mocked_run.assert_called_once_with(leagues=[LeagueId.SUPER_LIG], persist=False)
        parsed_json = json.loads(buf.getvalue())
        self.assertEqual(parsed_json["status"], "success")
        self.assertIn("prediction", parsed_json)

    def test_fastapi_endpoints(self) -> None:
        with TestClient(service_app.app) as client:
            health_resp = client.get("/health")
            self.assertEqual(health_resp.status_code, 200)
            health_data = health_resp.json()
            self.assertEqual(health_data["status"], "ok")
            self.assertGreaterEqual(health_data["uptime"], 0.0)
            self.assertTrue(health_data["scheduler_active"])
            self.assertIn("bulletin_age_seconds", health_data)
            self.assertIsNone(health_data["bulletin_age_seconds"])

            status_resp = client.get("/status")
            self.assertEqual(status_resp.status_code, 200)
            status_data = status_resp.json()
            self.assertIn("is_running", status_data)
            self.assertIn("leagues", status_data)
            self.assertEqual(
                set(status_data["leagues"].keys()),
                {"super_lig", "premier_league", "la_liga", "ligue_1"},
            )

            root_json_resp = client.get("/")
            self.assertEqual(root_json_resp.status_code, 200)
            root_data = root_json_resp.json()
            self.assertEqual(root_data["service"], "Futbol Skor ve Analiz Motoru")
            self.assertIn("status", root_data)
            self.assertIn("uptime", root_data)
            self.assertEqual(len(root_data["leagues"]), 4)

            root_html_resp = client.get("/", headers={"Accept": "text/html"})
            self.assertEqual(root_html_resp.status_code, 200)
            self.assertIn("text/html", root_html_resp.headers["content-type"])
            self.assertIn("Futbol Skor ve Analiz Motoru", root_html_resp.text)
            self.assertIn("Süper Lig", root_html_resp.text)

    def test_fastapi_sync_endpoint_and_conflict(self) -> None:
        mock_pipeline = MagicMock()
        mock_pipeline.run_league.return_value = _build_mock_league_result(LeagueId.SUPER_LIG, 1)
        sample_cycle = run_full_cycle(
            leagues=[LeagueId.SUPER_LIG],
            persist=False,
            status_tracker=RunnerStatus(),
            ingestion_pipeline=mock_pipeline,
            prediction_service=PredictionService(),
        )

        auth_headers = {"X-API-Key": "test-sync-secret"}
        with patch.dict(os.environ, {"SYNC_API_KEY": "test-sync-secret"}):
            with TestClient(service_app.app) as client:
                with patch("app.run_full_cycle", return_value=sample_cycle) as mocked_cycle:
                    sync_resp = client.post(
                        "/sync?league=super_lig&dry_run=true",
                        headers=auth_headers,
                    )
                    self.assertEqual(sync_resp.status_code, 200)
                    body = sync_resp.json()
                    self.assertEqual(body["status"], "success")
                    self.assertEqual(body["predictions_count"], 1)
                    mocked_cycle.assert_called_once_with(
                        leagues=LeagueId.SUPER_LIG,
                        persist=False,
                    )

                get_runner_status().is_running = True
                try:
                    conflict_resp = client.post("/sync", headers=auth_headers)
                    self.assertEqual(conflict_resp.status_code, 409)
                finally:
                    get_runner_status().is_running = False

    def test_background_scheduler_triggers_cycle(self) -> None:
        triggered = asyncio.Event()

        def fake_cycle() -> None:
            triggered.set()

        async def run_check() -> None:
            with patch("app.run_full_cycle", side_effect=fake_cycle) as mocked_cycle:
                task = asyncio.create_task(
                    service_app._daily_scheduler_loop(startup_delay=0.0, interval_seconds=3600.0)
                )
                await asyncio.wait_for(triggered.wait(), timeout=2.0)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                self.assertEqual(mocked_cycle.call_count, 1)

        asyncio.run(run_check())

    def test_cors_headers_on_bulletin_and_preflight(self) -> None:
        mock_pipeline = MagicMock()
        mock_pipeline.run_league.side_effect = lambda lid, *, persist=True: _build_mock_league_result(
            lid, list(LEAGUES.keys()).index(lid) + 1
        )
        sample_cycle = run_full_cycle(
            leagues=None,
            persist=False,
            status_tracker=RunnerStatus(),
            ingestion_pipeline=mock_pipeline,
            prediction_service=PredictionService(),
        )

        bulletin_mod.update_bulletin_cache(sample_cycle)

        with TestClient(service_app.app) as client:
            preflight = client.options(
                "/api/v1/bulletin",
                headers={
                    "Origin": "http://localhost:3000",
                    "Access-Control-Request-Method": "GET",
                },
            )
            self.assertEqual(preflight.status_code, 200)
            self.assertEqual(preflight.headers.get("access-control-allow-origin"), "*")

            with patch("app.run_full_cycle") as mocked_cycle:
                resp = client.get(
                    "/api/v1/bulletin",
                    headers={"Origin": "http://10.19.138.89:7860"},
                )
                mocked_cycle.assert_not_called()
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.headers.get("access-control-allow-origin"), "*")

    def test_bulletin_cold_start_returns_503_without_triggering_cycle(self) -> None:
        with TestClient(service_app.app) as client:
            with patch("app.run_full_cycle") as mocked_cycle:
                resp = client.get("/api/v1/bulletin")
                self.assertEqual(resp.status_code, 503)
                self.assertEqual(
                    resp.json()["detail"],
                    "Bülten önbelleği henüz hazırlanmadı; zamanlayıcı veya yetkili senkronizasyon bekleniyor.",
                )
                mocked_cycle.assert_not_called()
                self.assertFalse(self.tmp_cache_path.exists())

    def test_bulletin_auto_generation_cache_and_global_unique_ids(self) -> None:
        def build_idless_league_result(lid: LeagueId, idx: int) -> LeaguePipelineResult:
            meta = LEAGUES[lid]
            league = League(
                id=meta.id,
                name=meta.name,
                country=meta.country,
                season=meta.season,
            )
            t1, t2, t3, t4 = idx * 10 + 1, idx * 10 + 2, idx * 10 + 3, idx * 10 + 4
            teams = [
                Team(id=t1, league_id=lid, name=f"{meta.name} A", short_name=None, logo_url="https://img/a.png"),
                Team(id=t2, league_id=lid, name=f"{meta.name} B", short_name="B", logo_url="https://img/b.png"),
                Team(id=t3, league_id=lid, name=f"{meta.name} C", short_name="C"),
                Team(id=t4, league_id=lid, name=f"{meta.name} D", short_name="D"),
            ]
            matches = [
                Match(
                    id=None,
                    league_id=lid,
                    home_team_id=t1,
                    away_team_id=t2,
                    match_date=datetime(2026, 10, 10, 16, 0, tzinfo=UTC),
                    round=1,
                    status=MatchStatus.FINISHED,
                    home_score=2,
                    away_score=0,
                ),
                Match(
                    id=None,
                    league_id=lid,
                    home_team_id=t1,
                    away_team_id=t3,
                    match_date=datetime(2026, 10, 17, 16, 0, tzinfo=UTC),
                    round=2,
                    status=MatchStatus.SCHEDULED,
                ),
                Match(
                    id=None,
                    league_id=lid,
                    home_team_id=t2,
                    away_team_id=t4,
                    match_date=datetime(2026, 10, 17, 19, 0, tzinfo=UTC),
                    round=2,
                    status=MatchStatus.SCHEDULED,
                ),
            ]
            injuries = [
                Injury(
                    id=None,
                    team_id=t1,
                    player_name=f"Sakat {lid.value} 1",
                    position=PlayerPosition.FW,
                    reason="Diz Sakatlığı",
                    return_date=date(2027, 1, 15),
                    impact_level=ImpactLevel.HIGH,
                ),
                Injury(
                    id=None,
                    team_id=t4,
                    player_name=f"Sakat {lid.value} 2",
                    position=PlayerPosition.DEF,
                    reason="Sarı Kart Cezalısı",
                    return_date=None,
                    impact_level=ImpactLevel.MEDIUM,
                ),
            ]
            return LeaguePipelineResult(
                league=league,
                teams=teams,
                matches=matches,
                injuries=injuries,
                persisted=False,
            )

        mock_pipeline = MagicMock()
        mock_pipeline.run_league.side_effect = lambda lid, *, persist=True: build_idless_league_result(
            lid, list(LEAGUES.keys()).index(lid) + 1
        )
        idless_cycle = run_full_cycle(
            leagues=None,
            persist=False,
            only_next_round=True,
            status_tracker=RunnerStatus(),
            ingestion_pipeline=mock_pipeline,
            prediction_service=PredictionService(),
        )

        # Doğrulama: PredictionService yerel modda her lig için match_id=1,2 üretir (çakışmalı)
        raw_pred_match_ids = [p.match_id for p in idless_cycle.prediction.predictions]
        self.assertEqual(raw_pred_match_ids, [1, 2, 1, 2, 1, 2, 1, 2])

        with patch.dict(os.environ, {"SYNC_API_KEY": "test-sync-secret"}):
            with TestClient(service_app.app) as client:
                with patch("app.run_full_cycle", return_value=idless_cycle) as mocked_cycle:
                    # Soğuk başlangıçta yetkisiz GET /api/v1/bulletin döngü tetiklememeli (503)
                    cold_resp = client.get("/api/v1/bulletin")
                    self.assertEqual(cold_resp.status_code, 503)
                    self.assertEqual(mocked_cycle.call_count, 0)

                    # Yetkili refresh=true ile önbellek doldurulmalı
                    first_resp = client.get(
                        "/api/v1/bulletin?refresh=true",
                        headers={"X-API-Key": "test-sync-secret"},
                    )
                    self.assertEqual(first_resp.status_code, 200)
                    self.assertEqual(mocked_cycle.call_count, 1)

                    # Sonraki yetkisiz istek doğrudan bellek önbelleğinden dönmeli
                    second_resp = client.get("/api/v1/bulletin")
                    self.assertEqual(second_resp.status_code, 200)
                    self.assertEqual(mocked_cycle.call_count, 1)

                    # Bellek temizlendiğinde yetkisiz istek disk önbelleğinden dönmeli
                    clear_bulletin_memory_cache()
                    self.assertTrue(self.tmp_cache_path.is_file())
                    third_resp = client.get("/api/v1/bulletin")
                    self.assertEqual(third_resp.status_code, 200)
                    self.assertEqual(mocked_cycle.call_count, 1)

                    # Yetkili refresh=true tekrar verildiğinde yeniden çekmeli
                    refresh_resp = client.get(
                        "/api/v1/bulletin?refresh=true",
                        headers={"X-API-Key": "test-sync-secret"},
                    )
                    self.assertEqual(refresh_resp.status_code, 200)
                    self.assertEqual(mocked_cycle.call_count, 2)

        payload = first_resp.json()
        self.assertEqual(payload["data_source"], "Transfermarkt")
        self.assertIsNotNone(datetime.fromisoformat(payload["generated_at"]))
        self.assertEqual(payload["total_matches"], 8)
        self.assertEqual(payload["total_injuries"], 8)
        self.assertEqual(payload["total_played_matches"], 4)
        self.assertEqual(len(payload["leagues"]), 4)

        seen_match_ids: list[int] = []
        seen_injury_ids: list[int] = []
        for lg in payload["leagues"]:
            self.assertEqual(lg["next_round"], 2)
            self.assertEqual(lg["played_matches_count"], 1)
            self.assertEqual(lg["matches_count"], 2)
            self.assertEqual(lg["injuries_count"], 2)
            for inj in lg["injuries"]:
                seen_injury_ids.append(inj["id"])
            for match in lg["matches"]:
                mid = match["id"]
                seen_match_ids.append(mid)
                self.assertEqual(match["prediction"]["id"], mid)
                self.assertEqual(match["prediction"]["match_id"], mid)
                self.assertEqual(match["team_analysis"]["id"], mid)
                self.assertEqual(match["team_analysis"]["match_id"], mid)
                self.assertTrue(match["home_team"]["short_name"])
                self.assertGreaterEqual(len(match["prediction"]["top_scores_json"]), 1)

        self.assertEqual(seen_match_ids, list(range(1, 9)))
        self.assertEqual(seen_injury_ids, list(range(1, 9)))

    def test_bulletin_returns_503_when_scrape_produces_zero_matches(self) -> None:
        mock_pipeline = MagicMock()
        mock_pipeline.run_league.side_effect = RuntimeError("ağ hatası")
        failed_cycle = run_full_cycle(
            leagues=None,
            persist=False,
            status_tracker=RunnerStatus(),
            ingestion_pipeline=mock_pipeline,
            prediction_service=PredictionService(),
        )

        with patch.dict(os.environ, {"SYNC_API_KEY": "test-sync-secret"}):
            with TestClient(service_app.app) as client:
                with patch("app.run_full_cycle", return_value=failed_cycle) as mocked_cycle:
                    resp = client.get(
                        "/api/v1/bulletin?refresh=true",
                        headers={"X-API-Key": "test-sync-secret"},
                    )
                    self.assertEqual(resp.status_code, 503)
                    self.assertIn("Bülten verisi üretilemedi", resp.json()["detail"])
                    self.assertEqual(mocked_cycle.call_count, 1)
                    self.assertFalse(self.tmp_cache_path.exists())

    def test_api_v1_sync_updates_cache_and_enforces_409_lock(self) -> None:
        mock_pipeline = MagicMock()
        mock_pipeline.run_league.side_effect = lambda lid, *, persist=True: _build_mock_league_result(
            lid, list(LEAGUES.keys()).index(lid) + 1
        )
        full_cycle = run_full_cycle(
            leagues=None,
            persist=False,
            status_tracker=RunnerStatus(),
            ingestion_pipeline=mock_pipeline,
            prediction_service=PredictionService(),
        )
        single_cycle = run_full_cycle(
            leagues=[LeagueId.SUPER_LIG],
            persist=False,
            status_tracker=RunnerStatus(),
            ingestion_pipeline=mock_pipeline,
            prediction_service=PredictionService(),
        )

        bearer_headers = {"Authorization": "Bearer test-sync-secret"}
        with patch.dict(os.environ, {"SYNC_API_KEY": "test-sync-secret"}):
            with TestClient(service_app.app) as client:
                with patch("app.run_full_cycle", return_value=full_cycle):
                    sync_all = client.post("/api/v1/sync", headers=bearer_headers)
                    self.assertEqual(sync_all.status_code, 200)
                    body_all = sync_all.json()
                    self.assertEqual(body_all["status"], "success")
                    self.assertEqual(body_all["total_matches"], 4)
                    self.assertEqual(body_all["total_injuries"], 4)
                    self.assertIn("generated_at", body_all)
                    self.assertTrue(self.tmp_cache_path.is_file())

                with patch("app.run_full_cycle", return_value=single_cycle):
                    sync_one = client.post(
                        "/api/v1/sync?league=super_lig",
                        headers=bearer_headers,
                    )
                    self.assertEqual(sync_one.status_code, 200)
                    body_one = sync_one.json()
                    # Diğer 3 lig önbellekte korunduğu için toplam 4 maç kalmalı
                    self.assertEqual(body_one["total_matches"], 4)
                    self.assertEqual(body_one["total_injuries"], 4)

                get_runner_status().is_running = True
                try:
                    conflict_resp = client.post("/api/v1/sync", headers=bearer_headers)
                    self.assertEqual(conflict_resp.status_code, 409)
                finally:
                    get_runner_status().is_running = False

    def test_select_next_round_skips_rescheduled_past_round_match(self) -> None:
        meta = LEAGUES[LeagueId.LA_LIGA]
        teams = [
            Team(id=1, league_id=LeagueId.LA_LIGA, name="Real Madrid"),
            Team(id=2, league_id=LeagueId.LA_LIGA, name="FC Barcelona"),
            Team(id=3, league_id=LeagueId.LA_LIGA, name="Rayo Vallecano"),
            Team(id=4, league_id=LeagueId.LA_LIGA, name="Athletic Bilbao"),
        ]
        matches = [
            Match(
                id=1,
                league_id=LeagueId.LA_LIGA,
                home_team_id=1,
                away_team_id=2,
                match_date=datetime(2026, 10, 1, 20, 0, tzinfo=UTC),
                round=8,
                status=MatchStatus.FINISHED,
                home_score=2,
                away_score=1,
            ),
            # 8. haftadan Aralık ayına ertelenmiş tekil SCHEDULED maç
            Match(
                id=2,
                league_id=LeagueId.LA_LIGA,
                home_team_id=3,
                away_team_id=4,
                match_date=datetime(2026, 12, 9, 21, 0, tzinfo=UTC),
                round=8,
                status=MatchStatus.SCHEDULED,
            ),
            Match(
                id=3,
                league_id=LeagueId.LA_LIGA,
                home_team_id=2,
                away_team_id=1,
                match_date=datetime(2026, 11, 20, 20, 0, tzinfo=UTC),
                round=13,
                status=MatchStatus.FINISHED,
                home_score=1,
                away_score=1,
            ),
            # Gerçek sıradaki 14. hafta maçları
            Match(
                id=4,
                league_id=LeagueId.LA_LIGA,
                home_team_id=1,
                away_team_id=3,
                match_date=datetime(2026, 11, 28, 18, 0, tzinfo=UTC),
                round=14,
                status=MatchStatus.SCHEDULED,
            ),
            Match(
                id=5,
                league_id=LeagueId.LA_LIGA,
                home_team_id=2,
                away_team_id=4,
                match_date=datetime(2026, 11, 29, 20, 0, tzinfo=UTC),
                round=14,
                status=MatchStatus.SCHEDULED,
            ),
        ]
        mock_pipeline = MagicMock()
        mock_pipeline.run_league.return_value = LeaguePipelineResult(
            league=League(id=meta.id, name=meta.name, country=meta.country, season=meta.season),
            teams=teams,
            matches=matches,
            injuries=[],
            persisted=False,
        )
        cycle = run_full_cycle(
            leagues=[LeagueId.LA_LIGA],
            persist=False,
            only_next_round=True,
            status_tracker=RunnerStatus(),
            ingestion_pipeline=mock_pipeline,
            prediction_service=PredictionService(),
        )
        bulletin = bulletin_mod.build_bulletin_payload(cycle)
        self.assertEqual(bulletin["data_source"], "Transfermarkt")
        self.assertEqual(bulletin["total_matches"], 2)
        self.assertEqual(bulletin["total_played_matches"], 2)
        self.assertEqual(bulletin["leagues"][0]["played_matches_count"], 2)
        self.assertEqual(bulletin["leagues"][0]["next_round"], 14)

    def test_legacy_disk_cache_backfills_data_source_and_played_counts(self) -> None:
        legacy_payload = {
            "generated_at": "2026-11-25T12:00:00+00:00",
            "season": DEFAULT_SEASON,
            "total_matches": 1,
            "total_injuries": 0,
            "leagues": [
                {
                    "id": "super_lig",
                    "name": "Süper Lig",
                    "country": "Turkey",
                    "season": DEFAULT_SEASON,
                    "next_round": 13,
                    "matches_count": 1,
                    "injuries_count": 0,
                    "matches": [{"id": 1}],
                    "injuries": [],
                }
            ],
        }
        self.tmp_cache_path.write_text(
            json.dumps(legacy_payload, ensure_ascii=False), encoding="utf-8"
        )
        loaded = bulletin_mod.load_bulletin_from_disk()
        assert loaded is not None
        self.assertEqual(loaded["data_source"], "Transfermarkt")
        self.assertEqual(loaded["sources_used"], ["Transfermarkt"])
        self.assertEqual(loaded["sources_count"], 1)
        self.assertEqual(loaded["sources_total"], 5)
        self.assertEqual(loaded["source_diagnostics"], {})
        self.assertEqual(loaded["total_played_matches"], 0)
        self.assertEqual(loaded["leagues"][0]["played_matches_count"], 0)
        self.assertEqual(loaded["leagues"][0]["sources_total"], 5)

    def test_cli_export_bulletin_writes_four_league_schema_atomically(self) -> None:
        export_path = Path(self._tmp_dir.name) / "dist" / "bulletin.json"
        self.assertEqual(
            parse_args(["--export-bulletin", str(export_path)]).export_bulletin,
            export_path,
        )

        mock_pipeline = MagicMock()
        mock_pipeline.run_league.side_effect = lambda lid, *, persist=True: _build_mock_league_result(
            lid, list(LEAGUES.keys()).index(lid) + 1
        )
        full_cycle = run_full_cycle(
            leagues=None,
            persist=False,
            only_next_round=True,
            status_tracker=RunnerStatus(),
            ingestion_pipeline=mock_pipeline,
            prediction_service=PredictionService(),
        )

        buf = io.StringIO()
        with patch("engine.cli.run_full_cycle", return_value=full_cycle) as mocked_run:
            with redirect_stdout(buf):
                exit_code = cli_main(["--export-bulletin", str(export_path)])

        self.assertEqual(exit_code, 0)
        mocked_run.assert_called_once()
        self.assertIsNone(mocked_run.call_args.kwargs["leagues"])
        self.assertTrue(mocked_run.call_args.kwargs["only_next_round"])
        self.assertTrue(export_path.is_file())
        self.assertEqual(list(export_path.parent.glob("*.tmp")), [])

        raw_text = export_path.read_text(encoding="utf-8")
        self.assertIn("Süper Lig", raw_text)
        exported = json.loads(raw_text)

        expected_keys = {
            "data_source",
            "sources_used",
            "sources_count",
            "sources_total",
            "source_diagnostics",
            "generated_at",
            "season",
            "total_matches",
            "total_injuries",
            "total_played_matches",
            "leagues_meta",
            "leagues",
        }
        self.assertEqual(set(exported.keys()), expected_keys)

        with patch.dict(os.environ, {"SYNC_API_KEY": "test-sync-secret"}):
            with TestClient(service_app.app) as client:
                with patch("app.run_full_cycle", return_value=full_cycle):
                    api_resp = client.get(
                        "/api/v1/bulletin?refresh=true",
                        headers={"X-API-Key": "test-sync-secret"},
                    )
                    self.assertEqual(api_resp.status_code, 200)
                    api_bulletin = api_resp.json()
        self.assertEqual(set(exported.keys()), set(api_bulletin.keys()))

        self.assertEqual(
            [lg["id"] for lg in exported["leagues"]],
            ["super_lig", "premier_league", "la_liga", "ligue_1"],
        )
        self.assertEqual(len(exported["leagues_meta"]), 4)
        self.assertEqual(exported["total_matches"], 4)
        self.assertEqual(exported["total_injuries"], 4)
        self.assertEqual(exported["total_played_matches"], 4)

        cli_summary = json.loads(buf.getvalue())
        self.assertEqual(cli_summary["leagues_count"], 4)
        self.assertEqual(cli_summary["total_matches"], 4)

    def test_cli_export_bulletin_preserves_failed_league_from_previous_disk_file(self) -> None:
        export_path = Path(self._tmp_dir.name) / "dist" / "bulletin.json"

        seed_pipeline = MagicMock()
        seed_pipeline.run_league.side_effect = lambda lid, *, persist=True: _build_mock_league_result(
            lid, list(LEAGUES.keys()).index(lid) + 1
        )
        seed_cycle = run_full_cycle(
            leagues=None,
            persist=False,
            only_next_round=True,
            status_tracker=RunnerStatus(),
            ingestion_pipeline=seed_pipeline,
            prediction_service=PredictionService(),
        )
        with patch("engine.cli.run_full_cycle", return_value=seed_cycle):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(
                    cli_main(["--export-bulletin", str(export_path), "--dry-run"]), 0
                )

        seeded = json.loads(export_path.read_text(encoding="utf-8"))
        seeded_ligue1 = next(lg for lg in seeded["leagues"] if lg["id"] == "ligue_1")

        def flaky_run_league(lid: LeagueId, *, persist: bool = True) -> LeaguePipelineResult:
            if lid == LeagueId.LIGUE_1:
                raise RuntimeError("ligue_1 kaynak zaman aşımı")
            return _build_mock_league_result(lid, list(LEAGUES.keys()).index(lid) + 1)

        flaky_pipeline = MagicMock()
        flaky_pipeline.run_league.side_effect = flaky_run_league
        flaky_cycle = run_full_cycle(
            leagues=None,
            persist=False,
            only_next_round=True,
            status_tracker=RunnerStatus(),
            ingestion_pipeline=flaky_pipeline,
            prediction_service=PredictionService(),
        )
        self.assertIn("ligue_1", flaky_cycle.errors)

        buf = io.StringIO()
        with patch("engine.cli.run_full_cycle", return_value=flaky_cycle):
            with redirect_stdout(buf):
                exit_code = cli_main(["--export-bulletin", str(export_path), "--dry-run"])

        self.assertEqual(exit_code, 0)
        recovered = json.loads(export_path.read_text(encoding="utf-8"))
        self.assertEqual(
            [lg["id"] for lg in recovered["leagues"]],
            ["super_lig", "premier_league", "la_liga", "ligue_1"],
        )
        self.assertEqual(recovered["total_matches"], 4)
        recovered_ligue1 = next(lg for lg in recovered["leagues"] if lg["id"] == "ligue_1")
        self.assertEqual(recovered_ligue1["matches_count"], 1)
        self.assertEqual(recovered_ligue1["matches"], seeded_ligue1["matches"])
        self.assertEqual(recovered_ligue1["injuries"], seeded_ligue1["injuries"])


if __name__ == "__main__":
    unittest.main()
