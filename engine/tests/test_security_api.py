"""GÖREV-12: API anahtarı güvenliği, /health bülten yaşı ve Supabase RLS şema testleri."""

from __future__ import annotations

import json
import os
import re
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

import app as service_app
import engine.bulletin as bulletin_mod
from engine.bulletin import clear_bulletin_memory_cache
from engine.config import LEAGUES, PROJECT_ROOT, LeagueId
from engine.predictors.service import PredictionService
from engine.runner import RunnerStatus, get_runner_status, run_full_cycle
from engine.tests.test_runner import _build_mock_league_result


def _make_sample_cycle():
    mock_pipeline = MagicMock()
    mock_pipeline.run_league.side_effect = lambda lid, *, persist=True: _build_mock_league_result(
        lid, list(LEAGUES.keys()).index(lid) + 1
    )
    return run_full_cycle(
        leagues=None,
        persist=False,
        only_next_round=True,
        status_tracker=RunnerStatus(),
        ingestion_pipeline=mock_pipeline,
        prediction_service=PredictionService(),
    )


class SecurityAndObservabilityTests(unittest.TestCase):
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

    def test_sync_endpoints_reject_missing_or_invalid_api_key(self) -> None:
        sample_cycle = _make_sample_cycle()

        # SYNC_API_KEY yapılandırılmamışken her türlü istek 401 dönmeli
        with patch.dict(os.environ, {"SYNC_API_KEY": ""}, clear=False):
            with TestClient(service_app.app) as client:
                r1 = client.post("/sync")
                self.assertEqual(r1.status_code, 401)
                self.assertEqual(r1.headers.get("www-authenticate"), "Bearer")

                r2 = client.post("/api/v1/sync", headers={"X-API-Key": "any-key"})
                self.assertEqual(r2.status_code, 401)

        # SYNC_API_KEY tanımlıyken anahtarsız veya hatalı anahtarlı istekler 401 dönmeli
        with patch.dict(os.environ, {"SYNC_API_KEY": "prod-secret-key"}, clear=False):
            with TestClient(service_app.app) as client:
                with patch("app.run_full_cycle", return_value=sample_cycle) as mocked_cycle:
                    self.assertEqual(client.post("/sync").status_code, 401)
                    self.assertEqual(client.post("/api/v1/sync").status_code, 401)
                    self.assertEqual(
                        client.post("/sync", headers={"X-API-Key": "wrong-key"}).status_code,
                        401,
                    )
                    # Türkçe / UTF-8 karakterli hatalı anahtar 500 değil 401 dönmeli
                    self.assertEqual(
                        client.post("/sync", headers={"X-API-Key": "yanlis-anahtar"}).status_code,
                        401,
                    )
                    self.assertEqual(
                        client.post(
                            "/api/v1/sync",
                            headers={"Authorization": "Basic prod-secret-key"},
                        ).status_code,
                        401,
                    )
                    self.assertEqual(mocked_cycle.call_count, 0)

                    ok_x_key = client.post(
                        "/sync?league=super_lig&dry_run=true",
                        headers={"X-API-Key": "prod-secret-key"},
                    )
                    self.assertEqual(ok_x_key.status_code, 200)

                    ok_bearer = client.post(
                        "/api/v1/sync?dry_run=true",
                        headers={"Authorization": "bearer prod-secret-key"},
                    )
                    self.assertEqual(ok_bearer.status_code, 200)
                    self.assertEqual(mocked_cycle.call_count, 2)

    def test_bulletin_public_read_vs_protected_refresh(self) -> None:
        sample_cycle = _make_sample_cycle()

        with patch.dict(os.environ, {"SYNC_API_KEY": "refresh-secret"}, clear=False):
            with TestClient(service_app.app) as client:
                with patch("app.run_full_cycle", return_value=sample_cycle) as mocked_cycle:
                    # Soğuk başlangıçta anahtarsız GET /api/v1/bulletin 503 dönmeli ve döngü tetiklememeli
                    cold_resp = client.get("/api/v1/bulletin")
                    self.assertEqual(cold_resp.status_code, 503)
                    self.assertEqual(mocked_cycle.call_count, 0)

                    # refresh=true anahtarsız 401 dönmeli
                    unauth_refresh = client.get("/api/v1/bulletin?refresh=true")
                    self.assertEqual(unauth_refresh.status_code, 401)
                    self.assertEqual(mocked_cycle.call_count, 0)

                    # refresh=true geçerli anahtar ile 200 dönmeli ve önbelleği doldurmalı
                    auth_refresh = client.get(
                        "/api/v1/bulletin?refresh=true",
                        headers={"X-API-Key": "refresh-secret"},
                    )
                    self.assertEqual(auth_refresh.status_code, 200)
                    self.assertEqual(mocked_cycle.call_count, 1)

                    # Önbellek sıcakken anahtarsız GET /api/v1/bulletin 200 dönmeli
                    public_resp = client.get("/api/v1/bulletin")
                    self.assertEqual(public_resp.status_code, 200)
                    self.assertEqual(mocked_cycle.call_count, 1)

    def test_health_reports_bulletin_age_seconds(self) -> None:
        with TestClient(service_app.app) as client:
            # Önbellek yokken bulletin_age_seconds None olmalı
            empty_health = client.get("/health").json()
            self.assertIsNone(empty_health["bulletin_age_seconds"])

            # 120 saniye önce üretilmiş bülten önbelleğe yazıldığında yaş ~120 sn olmalı
            ts = (datetime.now(UTC) - timedelta(seconds=120)).isoformat()
            disk_payload = {
                "generated_at": ts,
                "season": "2026-2027",
                "total_matches": 1,
                "total_injuries": 0,
                "leagues": [
                    {
                        "id": LeagueId.SUPER_LIG.value,
                        "name": "Süper Lig",
                        "country": "Turkey",
                        "season": "2026-2027",
                        "matches_count": 1,
                        "injuries_count": 0,
                        "matches": [{"id": 1}],
                        "injuries": [],
                    }
                ],
            }
            self.tmp_cache_path.write_text(
                json.dumps(disk_payload, ensure_ascii=False), encoding="utf-8"
            )
            clear_bulletin_memory_cache()

            populated_health = client.get("/health").json()
            age = populated_health["bulletin_age_seconds"]
            self.assertIsInstance(age, float)
            assert isinstance(age, float)
            self.assertGreaterEqual(age, 118.0)
            self.assertLess(age, 135.0)

            # Bozuk generated_at alanı None olarak güvenle ele alınmalı
            disk_payload["generated_at"] = "gecersiz-tarih"
            self.tmp_cache_path.write_text(
                json.dumps(disk_payload, ensure_ascii=False), encoding="utf-8"
            )
            clear_bulletin_memory_cache()
            invalid_ts_health = client.get("/health").json()
            self.assertIsNone(invalid_ts_health["bulletin_age_seconds"])

    def test_schema_sql_enables_rls_and_select_only_policies_for_all_six_tables(self) -> None:
        schema_path = PROJECT_ROOT / "engine" / "db" / "schema.sql"
        sql_text = schema_path.read_text(encoding="utf-8")

        expected_tables = (
            "leagues",
            "teams",
            "matches",
            "injuries",
            "predictions",
            "team_analyses",
        )
        for tbl in expected_tables:
            self.assertRegex(
                sql_text,
                re.compile(
                    rf"ALTER\s+TABLE\s+{tbl}\s+ENABLE\s+ROW\s+LEVEL\s+SECURITY\s*;",
                    re.IGNORECASE,
                ),
            )
            self.assertRegex(
                sql_text,
                re.compile(
                    rf"CREATE\s+POLICY\s+\w+\s+ON\s+{tbl}\s+FOR\s+SELECT\s+USING\s*\(\s*true\s*\)\s*;",
                    re.IGNORECASE,
                ),
            )


if __name__ == "__main__":
    unittest.main()
