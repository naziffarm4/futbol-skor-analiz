"""GÖREV-01 temel mimari, SQL-Pydantic uyumu ve Supabase istemci doğrulama testleri."""

from __future__ import annotations

import re
import unittest
from datetime import UTC, date, datetime

import httpx
from postgrest.exceptions import APIError
from pydantic import ValidationError

from engine.config import DEFAULT_SEASON, LEAGUES, PROJECT_ROOT, LeagueId, Settings
from engine.db.client import (
    DatabaseConfigError,
    DatabaseConnectionError,
    DatabaseOperationError,
    execute_query,
    get_supabase_client,
    reset_clients,
)
from engine.models.schemas import (
    DBModel,
    ImpactLevel,
    Injury,
    League,
    Match,
    MatchStatus,
    PlayerPosition,
    Prediction,
    ScoreProbability,
    Team,
    TeamAnalysis,
)


def _extract_sql_table_columns(sql_text: str) -> dict[str, list[str]]:
    tables: dict[str, list[str]] = {}
    pattern = re.compile(
        r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+(\w+)\s*\((.*?)\);",
        re.DOTALL | re.IGNORECASE,
    )
    for table_name, body in pattern.findall(sql_text):
        cols: list[str] = []
        for raw_line in body.splitlines():
            line = raw_line.strip().rstrip(",")
            if not line or line.startswith("--"):
                continue
            upper = line.upper()
            if upper.startswith(("CONSTRAINT ", "CHECK ", "UNIQUE ", "PRIMARY KEY", "FOREIGN KEY")):
                continue
            col_name = line.split()[0]
            cols.append(col_name)
        tables[table_name] = cols
    return tables


class FoundationVerificationTests(unittest.TestCase):
    def tearDown(self) -> None:
        reset_clients()

    def test_four_leagues_metadata(self) -> None:
        expected_ids = {"super_lig", "premier_league", "la_liga", "ligue_1"}
        self.assertEqual({lid.value for lid in LEAGUES}, expected_ids)
        for lid, meta in LEAGUES.items():
            league_model = League(
                id=lid,
                name=meta.name,
                country=meta.country,
                season=meta.season,
            )
            self.assertEqual(league_model.id, lid)

    def test_sql_schema_and_pydantic_parity(self) -> None:
        schema_path = PROJECT_ROOT / "engine" / "db" / "schema.sql"
        sql_text = schema_path.read_text(encoding="utf-8")
        sql_tables = _extract_sql_table_columns(sql_text)

        model_map: dict[str, type[DBModel]] = {
            "leagues": League,
            "teams": Team,
            "matches": Match,
            "injuries": Injury,
            "predictions": Prediction,
            "team_analyses": TeamAnalysis,
        }

        self.assertEqual(set(sql_tables.keys()), set(model_map.keys()))
        for table_name, model_cls in model_map.items():
            sql_cols = set(sql_tables[table_name])
            db_backed_fields = set(model_cls.model_fields.keys()) - set(model_cls._non_db_fields)
            self.assertEqual(
                sql_cols,
                db_backed_fields,
                f"{table_name} tablosu ile {model_cls.__name__} DB alanları uyuşmuyor",
            )

    def test_pydantic_validations_and_payload(self) -> None:
        with self.assertRaises(ValidationError):
            Match(
                league_id=LeagueId.SUPER_LIG,
                home_team_id=5,
                away_team_id=5,
                match_date=datetime.now(UTC),
                round=1,
            )

        with self.assertRaises(ValidationError):
            ScoreProbability(score="invalid", prob=0.5)

        prediction = Prediction(
            match_id=10,
            predicted_home_score=2,
            predicted_away_score=1,
            confidence_rate=0.64,
            top_scores_json=[ScoreProbability(score="2-1", prob=0.17)],
        )
        payload = prediction.to_db_payload()
        self.assertNotIn("id", payload)
        self.assertEqual(payload["top_scores_json"], [{"score": "2-1", "prob": 0.17}])

        injury = Injury(
            team_id=1,
            player_name="Mauro Icardi",
            position=PlayerPosition.FW,
            reason="Diz sakatlığı",
            return_date=date(2026, 12, 15),
            impact_level=ImpactLevel.HIGH,
        )
        self.assertEqual(injury.to_db_payload()["return_date"], "2026-12-15")

        match = Match(
            league_id=LeagueId.PREMIER_LEAGUE,
            home_team_id=1,
            away_team_id=2,
            match_date=datetime.now(UTC),
            round=12,
            status=MatchStatus.SCHEDULED,
        )
        self.assertEqual(match.status, MatchStatus.SCHEDULED)

    def test_supabase_client_config_and_error_handling(self) -> None:
        empty_cfg = Settings(
            supabase_url="",
            supabase_key="",
            supabase_service_role_key="",
            default_season=DEFAULT_SEASON,
            http_timeout_seconds=10.0,
        )
        with self.assertRaises(DatabaseConfigError):
            get_supabase_client(cfg=empty_cfg)

        valid_cfg = Settings(
            supabase_url="https://exampleproject.supabase.co",
            supabase_key="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJyb2xlIjoiYW5vbiJ9.sig",
            supabase_service_role_key="",
            default_season=DEFAULT_SEASON,
            http_timeout_seconds=15.0,
        )
        client = get_supabase_client(cfg=valid_cfg)
        self.assertIsNotNone(client)

        with self.assertRaises(DatabaseConnectionError):
            execute_query(
                lambda: (_ for _ in ()).throw(httpx.ConnectTimeout("timeout")),
                context="test_timeout",
            )

        with self.assertRaises(DatabaseOperationError):
            execute_query(
                lambda: (_ for _ in ()).throw(APIError({"message": "relation does not exist"})),
                context="test_api_error",
            )


if __name__ == "__main__":
    unittest.main()
