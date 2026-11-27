"""5 bağımsız kamuya açık futbol veri kaynağı adaptör paketi."""

from __future__ import annotations

from typing import Any


def make_source_diagnostic(
    source: str,
    *,
    ok: bool,
    http_status: int | None = None,
    records: int = 0,
    url: str = "",
    note: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Tüm veri kaynağı adaptörleri için standart tanılama sözlüğü üretir."""
    return {
        "source": source,
        "ok": bool(ok),
        "http_status": http_status,
        "records": int(records),
        "url": url,
        "note": note,
        "error": error,
    }


from engine.scrapers.sources.espn import (  # noqa: E402
    ESPN_LEAGUE_SLUGS,
    ESPNAdapter,
    ESPNFixtureRecord,
    ESPNLeagueData,
    ESPNStandingRow,
)
from engine.scrapers.sources.football_data import (  # noqa: E402
    FOOTBALL_DATA_CODES,
    FootballDataAdapter,
    FootballDataLeagueData,
    FootballDataMatchRow,
    FootballDataTeamStats,
    parse_football_data_csv,
)
from engine.scrapers.sources.secondary_check import (  # noqa: E402
    SecondaryCheckAdapter,
    SecondaryCheckData,
    SecondaryInjuryRecord,
    SecondaryStandingRecord,
    parse_sportsgambler_html,
)
from engine.scrapers.sources.understat import (  # noqa: E402
    UNDERSTAT_LEAGUE_SLUGS,
    UnderstatAdapter,
    UnderstatLeagueData,
    UnderstatTeamXG,
    derive_xg_from_shots,
    parse_understat_teams_data,
)

__all__ = [
    "ESPN_LEAGUE_SLUGS",
    "FOOTBALL_DATA_CODES",
    "UNDERSTAT_LEAGUE_SLUGS",
    "ESPNAdapter",
    "ESPNFixtureRecord",
    "ESPNLeagueData",
    "ESPNStandingRow",
    "FootballDataAdapter",
    "FootballDataLeagueData",
    "FootballDataMatchRow",
    "FootballDataTeamStats",
    "SecondaryCheckAdapter",
    "SecondaryCheckData",
    "SecondaryInjuryRecord",
    "SecondaryStandingRecord",
    "UnderstatAdapter",
    "UnderstatLeagueData",
    "UnderstatTeamXG",
    "derive_xg_from_shots",
    "make_source_diagnostic",
    "parse_football_data_csv",
    "parse_sportsgambler_html",
    "parse_understat_teams_data",
]
