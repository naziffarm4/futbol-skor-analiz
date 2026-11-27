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


from engine.scrapers.sources.api_football import (  # noqa: E402
    ApiFootballAdapter,
    ApiFootballLeagueData,
    QuotaBudgetTracker,
    parse_api_football_fixtures,
    parse_api_football_injuries,
    redact_secret,
)
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
from engine.scrapers.sources.the_odds_api import (  # noqa: E402
    MarketMatchOdds,
    TheOddsApiAdapter,
    TheOddsLeagueData,
    devig_three_way,
    devig_two_way,
    parse_the_odds_events,
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
    "ApiFootballAdapter",
    "ApiFootballLeagueData",
    "ESPNAdapter",
    "ESPNFixtureRecord",
    "ESPNLeagueData",
    "ESPNStandingRow",
    "FootballDataAdapter",
    "FootballDataLeagueData",
    "FootballDataMatchRow",
    "FootballDataTeamStats",
    "MarketMatchOdds",
    "QuotaBudgetTracker",
    "SecondaryCheckAdapter",
    "SecondaryCheckData",
    "SecondaryInjuryRecord",
    "SecondaryStandingRecord",
    "TheOddsApiAdapter",
    "TheOddsLeagueData",
    "UnderstatAdapter",
    "UnderstatLeagueData",
    "UnderstatTeamXG",
    "derive_xg_from_shots",
    "devig_three_way",
    "devig_two_way",
    "make_source_diagnostic",
    "parse_api_football_fixtures",
    "parse_api_football_injuries",
    "parse_football_data_csv",
    "parse_sportsgambler_html",
    "parse_the_odds_events",
    "parse_understat_teams_data",
    "redact_secret",
]
