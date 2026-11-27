"""Ortam değişkenleri ve desteklenen 4 ligin sabit metadata yapılandırması."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


class LeagueId(StrEnum):
    SUPER_LIG = "super_lig"
    PREMIER_LEAGUE = "premier_league"
    LA_LIGA = "la_liga"
    LIGUE_1 = "ligue_1"


@dataclass(frozen=True, slots=True)
class LeagueMetadata:
    id: LeagueId
    name: str
    country: str
    country_code: str
    season: str


def get_current_season(today: date | None = None) -> str:
    """Temmuz (ay >= 7) itibarıyla YIL-(YIL+1), öncesinde (YIL-1)-YIL sezonunu döndürür."""
    d = today or date.today()
    if d.month >= 7:
        return f"{d.year}-{d.year + 1}"
    return f"{d.year - 1}-{d.year}"


def get_season_start_year(season: str | None = None, *, today: date | None = None) -> int:
    """Sezon dizgesinin başlangıç yılını (örn. 'YYYY-ZZZZ' -> YYYY) döndürür."""
    s = (season or "").strip() or get_current_season(today)
    return int(s.split("-")[0])


def get_football_data_season_code(season: str | None = None, *, today: date | None = None) -> str:
    """Football-Data CSV uç noktaları için 4 haneli sezon kodunu (örn. 'YYZZ') üretir."""
    s = (season or "").strip() or get_current_season(today)
    parts = s.split("-")
    if len(parts) >= 2 and len(parts[0]) >= 2 and len(parts[1]) >= 2:
        return f"{parts[0][-2:]}{parts[1][-2:]}"
    start_yr = int(parts[0])
    return f"{start_yr % 100:02d}{(start_yr + 1) % 100:02d}"


DEFAULT_SEASON: str = os.getenv("DEFAULT_SEASON", "").strip() or get_current_season()

LEAGUES: dict[LeagueId, LeagueMetadata] = {
    LeagueId.SUPER_LIG: LeagueMetadata(
        id=LeagueId.SUPER_LIG,
        name="Süper Lig",
        country="Turkey",
        country_code="TR",
        season=DEFAULT_SEASON,
    ),
    LeagueId.PREMIER_LEAGUE: LeagueMetadata(
        id=LeagueId.PREMIER_LEAGUE,
        name="Premier League",
        country="England",
        country_code="GB-ENG",
        season=DEFAULT_SEASON,
    ),
    LeagueId.LA_LIGA: LeagueMetadata(
        id=LeagueId.LA_LIGA,
        name="La Liga",
        country="Spain",
        country_code="ES",
        season=DEFAULT_SEASON,
    ),
    LeagueId.LIGUE_1: LeagueMetadata(
        id=LeagueId.LIGUE_1,
        name="Ligue 1",
        country="France",
        country_code="FR",
        season=DEFAULT_SEASON,
    ),
}


@dataclass(frozen=True, slots=True)
class Settings:
    supabase_url: str
    supabase_key: str
    supabase_service_role_key: str
    default_season: str
    http_timeout_seconds: float

    @classmethod
    def from_env(cls) -> Settings:
        timeout_raw = os.getenv("HTTP_TIMEOUT_SECONDS", "30").strip()
        try:
            timeout = float(timeout_raw)
            if timeout <= 0:
                raise ValueError
        except ValueError:
            timeout = 30.0

        return cls(
            supabase_url=os.getenv("SUPABASE_URL", "").strip(),
            supabase_key=os.getenv("SUPABASE_KEY", "").strip(),
            supabase_service_role_key=os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip(),
            default_season=os.getenv("DEFAULT_SEASON", "").strip() or get_current_season(),
            http_timeout_seconds=timeout,
        )

    def resolve_api_key(self, use_service_role: bool = False) -> str:
        if use_service_role and self.supabase_service_role_key:
            return self.supabase_service_role_key
        return self.supabase_key or self.supabase_service_role_key


settings = Settings.from_env()
