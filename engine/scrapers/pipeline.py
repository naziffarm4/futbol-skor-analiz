"""4 lig için çok kaynaklı fikstür, istatistik, xG, piyasa oranları ve sakatlık verilerini toplayan orkestratör."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from supabase import Client

from engine.config import LEAGUES, LeagueId, Settings, get_current_season
from engine.db.client import DatabaseConfigError, execute_query, get_supabase_client
from engine.models.schemas import Injury, League, Match, MatchStatus, Team
from engine.scrapers.base import BaseScraper, ScraperError, normalize_team_name
from engine.scrapers.fixtures import (
    FixturesScraper,
    LeagueFixturesData,
    ScrapedMatch,
    ScrapedTeam,
)
from engine.scrapers.fusion import (
    TeamAliasResolver,
    TeamMultiSourceMetrics,
    build_market_odds_map,
    cross_validate_injuries,
    cross_validate_match_scores,
    fold_ascii,
    fuse_team_metrics,
)
from engine.scrapers.injuries import (
    TRANSFERMARKT_LEAGUES,
    InjuriesScraper,
    ScrapedInjury,
    calculate_impact_level,
    map_player_position,
)
from engine.scrapers.sources import (
    ESPN_LEAGUE_SLUGS,
    ApiFootballAdapter,
    ApiFootballLeagueData,
    ESPNAdapter,
    ESPNLeagueData,
    FootballDataAdapter,
    FootballDataLeagueData,
    QuotaBudgetTracker,
    SecondaryCheckAdapter,
    SecondaryCheckData,
    SecondaryInjuryRecord,
    TheOddsApiAdapter,
    TheOddsLeagueData,
    UnderstatAdapter,
    make_source_diagnostic,
)
from engine.scrapers.sources.espn import parse_espn_scoreboard_json

logger = logging.getLogger(__name__)

CANONICAL_SOURCE_ORDER: tuple[str, ...] = (
    "API-Football",
    "TheOddsAPI",
    "ESPN",
    "Football-Data",
    "Understat",
    "Transfermarkt",
    "SportsGambler",
    "TheSportsDB",
)


def _order_sources(sources: Iterable[str]) -> list[str]:
    unique: list[str] = []
    for s in sources:
        if s and s not in unique:
            unique.append(s)
    rank_map = {name: idx for idx, name in enumerate(CANONICAL_SOURCE_ORDER)}
    return sorted(unique, key=lambda name: (rank_map.get(name, 99), name))


def _team_lookup_key(name: str) -> str:
    return (
        normalize_team_name(name)
        .replace("İ", "i")
        .replace("I", "ı")
        .lower()
        .casefold()
        .replace("i̇", "i")
    )


def _parse_flexible_datetime(raw: str, *, fallback_date: date | None = None) -> datetime:
    cleaned = (raw or "").strip()
    if cleaned:
        try:
            dt = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
            return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
        except ValueError:
            pass
        for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d.%m.%Y"):
            try:
                parsed_d = datetime.strptime(cleaned[:10], fmt)
                return parsed_d.replace(hour=17, minute=0, tzinfo=UTC)
            except ValueError:
                continue
    d = fallback_date or date.today()
    return datetime(d.year, d.month, d.day, 17, 0, tzinfo=UTC)


@dataclass(slots=True)
class LeaguePipelineResult:
    league: League
    teams: list[Team]
    matches: list[Match]
    injuries: list[Injury]
    persisted: bool
    team_metrics: dict[int, TeamMultiSourceMetrics] = field(default_factory=dict)
    market_odds: dict[tuple[int, int], dict[str, float]] = field(default_factory=dict)
    sources_used: list[str] = field(default_factory=lambda: ["Transfermarkt"])
    sources_total: int = 5
    source_diagnostics: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "persisted": self.persisted,
            "league": self.league.to_db_payload(),
            "teams": [t.to_db_payload() for t in self.teams],
            "matches": [m.to_db_payload() for m in self.matches],
            "injuries": [i.to_db_payload() for i in self.injuries],
            "market_odds": {f"{h}:{a}": dict(v) for (h, a), v in self.market_odds.items()},
            "sources_used": list(self.sources_used),
            "sources_total": self.sources_total,
            "source_diagnostics": dict(self.source_diagnostics),
        }


@dataclass(slots=True)
class PipelineResult:
    persisted: bool
    leagues: list[League] = field(default_factory=list)
    teams: list[Team] = field(default_factory=list)
    matches: list[Match] = field(default_factory=list)
    injuries: list[Injury] = field(default_factory=list)
    team_metrics: dict[int, TeamMultiSourceMetrics] = field(default_factory=dict)
    market_odds: dict[tuple[int, int], dict[str, float]] = field(default_factory=dict)
    sources_used: list[str] = field(default_factory=list)
    sources_total: int = 5
    source_diagnostics: dict[str, dict[str, Any]] = field(default_factory=dict)
    league_sources: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "persisted": self.persisted,
            "leagues": [lg.to_db_payload() for lg in self.leagues],
            "teams": [tm.to_db_payload() for tm in self.teams],
            "matches": [mt.to_db_payload() for mt in self.matches],
            "injuries": [inj.to_db_payload() for inj in self.injuries],
            "market_odds": {f"{h}:{a}": dict(v) for (h, a), v in self.market_odds.items()},
            "sources_used": list(self.sources_used),
            "sources_total": self.sources_total,
            "source_diagnostics": dict(self.source_diagnostics),
            "league_sources": dict(self.league_sources),
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


class IngestionPipeline:
    """Çoklu bağımsız veri kaynağını çalıştırıp çapraz doğrulanmış Pydantic modellerine ve Supabase'e bağlar."""

    def __init__(
        self,
        *,
        http: BaseScraper | None = None,
        fixtures_scraper: FixturesScraper | None = None,
        injuries_scraper: InjuriesScraper | None = None,
        supabase_client: Client | None = None,
        enable_multi_source: bool | None = None,
        espn_adapter: ESPNAdapter | None = None,
        football_data_adapter: FootballDataAdapter | None = None,
        understat_adapter: UnderstatAdapter | None = None,
        secondary_adapter: SecondaryCheckAdapter | None = None,
        api_football_adapter: ApiFootballAdapter | None = None,
        odds_adapter: TheOddsApiAdapter | None = None,
    ) -> None:
        both_mocked = fixtures_scraper is not None and injuries_scraper is not None
        if enable_multi_source is None:
            self._enable_multi_source = not both_mocked
        else:
            self._enable_multi_source = bool(enable_multi_source)

        explicit_legacy_bundle = (
            espn_adapter is not None
            and football_data_adapter is not None
            and understat_adapter is not None
            and secondary_adapter is not None
            and api_football_adapter is None
            and odds_adapter is None
        )

        self._owns_http = http is None and fixtures_scraper is None and injuries_scraper is None
        self.http = http or BaseScraper()
        self.fixtures_scraper = fixtures_scraper or FixturesScraper(self.http)
        self.injuries_scraper = injuries_scraper or InjuriesScraper(self.http)
        self._explicit_client = supabase_client
        self._next_local_team_id = 1

        self._owns_espn = espn_adapter is None and self._enable_multi_source
        self._owns_fd = football_data_adapter is None and self._enable_multi_source
        self._owns_understat = understat_adapter is None and self._enable_multi_source
        self._owns_secondary = secondary_adapter is None and self._enable_multi_source

        self.espn_adapter = espn_adapter or (ESPNAdapter() if self._enable_multi_source else None)
        self.football_data_adapter = football_data_adapter or (
            FootballDataAdapter() if self._enable_multi_source else None
        )
        self.understat_adapter = understat_adapter or (
            UnderstatAdapter() if self._enable_multi_source else None
        )
        self.secondary_adapter = secondary_adapter or (
            SecondaryCheckAdapter() if self._enable_multi_source else None
        )

        env_cfg = Settings.from_env()
        shared_tracker = QuotaBudgetTracker() if self._enable_multi_source else None

        auto_af = (
            self._enable_multi_source
            and not explicit_legacy_bundle
            and api_football_adapter is None
            and bool(env_cfg.api_football_key)
        )
        auto_odds = (
            self._enable_multi_source
            and not explicit_legacy_bundle
            and odds_adapter is None
            and bool(env_cfg.the_odds_api_key)
        )
        self._owns_af = auto_af
        self._owns_odds = auto_odds

        self.api_football_adapter = api_football_adapter or (
            ApiFootballAdapter(tracker=shared_tracker) if auto_af else None
        )
        self.odds_adapter = odds_adapter or (
            TheOddsApiAdapter(tracker=shared_tracker) if auto_odds else None
        )

    def close(self) -> None:
        if self._owns_http:
            self.http.close()
        if self._owns_espn and self.espn_adapter is not None:
            self.espn_adapter.close()
        if self._owns_fd and self.football_data_adapter is not None:
            self.football_data_adapter.close()
        if self._owns_understat and self.understat_adapter is not None:
            self.understat_adapter.close()
        if self._owns_secondary and self.secondary_adapter is not None:
            self.secondary_adapter.close()
        if self._owns_af and self.api_football_adapter is not None:
            self.api_football_adapter.close()
        if self._owns_odds and self.odds_adapter is not None:
            self.odds_adapter.close()

    def __enter__(self) -> IngestionPipeline:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _resolve_db_client(self, persist: bool) -> Client | None:
        if not persist:
            return None
        if self._explicit_client is not None:
            return self._explicit_client
        try:
            return get_supabase_client(use_service_role=True)
        except DatabaseConfigError:
            logger.info("Supabase yapılandırılmamış; veriler yerel model/JSON modunda döndürülecek.")
            return None

    def _merge_scraped_teams(
        self,
        league_id: LeagueId,
        fixture_teams: list[ScrapedTeam],
        injury_team_names: Iterable[str],
    ) -> tuple[list[ScrapedTeam], dict[str, str]]:
        by_key: dict[str, ScrapedTeam] = {}
        key_to_canonical: dict[str, str] = {}

        for st in fixture_teams:
            k = _team_lookup_key(st.name)
            if k and k not in by_key:
                by_key[k] = st
                key_to_canonical[k] = st.name

        for raw_name in injury_team_names:
            norm_name = normalize_team_name(raw_name)
            k = _team_lookup_key(norm_name)
            if k and k not in by_key:
                by_key[k] = ScrapedTeam(
                    league_id=league_id,
                    name=norm_name,
                    short_name=norm_name[:50],
                )
                key_to_canonical[k] = norm_name

        return list(by_key.values()), key_to_canonical

    def _fetch_espn_upcoming_window(
        self,
        league_id: LeagueId,
        espn_data: ESPNLeagueData,
        *,
        reference_date: date | None = None,
    ) -> None:
        if self.espn_adapter is None:
            return
        start_d = reference_date or date.today()
        end_d = start_d + timedelta(days=21)
        slug = ESPN_LEAGUE_SLUGS[league_id]
        url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard"
        try:
            resp = self.espn_adapter._client.get(
                url,
                params={"dates": f"{start_d:%Y%m%d}-{end_d:%Y%m%d}"},
                headers={"Accept": "application/json"},
            )
            if resp.status_code == 200:
                extra_fixtures = parse_espn_scoreboard_json(resp.json())
                existing_pairs = {
                    (fold_ascii(fx.home_team), fold_ascii(fx.away_team), fx.match_date[:10])
                    for fx in espn_data.fixtures
                }
                for fx in extra_fixtures:
                    key = (fold_ascii(fx.home_team), fold_ascii(fx.away_team), fx.match_date[:10])
                    if key not in existing_pairs:
                        existing_pairs.add(key)
                        espn_data.fixtures.append(fx)
        except Exception as exc:
            logger.warning("ESPN 21 günlük takvim penceresi hatası (%s): %s", league_id.value, exc)

    def _synthesize_fallback_fixtures(
        self,
        league_id: LeagueId,
        *,
        af_data: ApiFootballLeagueData | None,
        espn_data: ESPNLeagueData | None,
        fd_data: FootballDataLeagueData | None,
        secondary_data: SecondaryCheckData | None,
        odds_data: TheOddsLeagueData | None,
        round_filter: int | None = None,
        reference_date: date | None = None,
    ) -> LeagueFixturesData:
        """Transfermarkt erişilemediğinde resmi API ve açık kaynaklardan tam lig fikstürü sentezler."""
        if af_data is not None and af_data.matches:
            has_scheduled = any(m.status == MatchStatus.SCHEDULED for m in af_data.matches)
            if has_scheduled:
                filtered_af = [
                    m for m in af_data.matches if round_filter is None or m.round == round_filter
                ]
                return LeagueFixturesData(
                    league_id=league_id,
                    teams=list(af_data.teams),
                    matches=filtered_af,
                )

        if espn_data is not None:
            has_espn_sched = any(fx.status != "FINISHED" for fx in espn_data.fixtures)
            if not has_espn_sched:
                self._fetch_espn_upcoming_window(
                    league_id, espn_data, reference_date=reference_date
                )

        alias = TeamAliasResolver()
        canonical_display: dict[str, str] = {}

        def _register_name(raw_name: str) -> str:
            cleaned = normalize_team_name(raw_name)
            if not cleaned:
                return ""
            alias.register_teams([cleaned])
            rk = alias.resolve_key(cleaned)
            if rk and rk not in canonical_display:
                canonical_display[rk] = cleaned
            return canonical_display.get(rk, cleaned)

        if af_data is not None:
            for t in af_data.teams:
                _register_name(t.name)
        if espn_data is not None:
            for row in espn_data.standings:
                _register_name(row.team_name)
        if fd_data is not None:
            for tname in fd_data.team_stats:
                _register_name(tname)
        if secondary_data is not None:
            for srow in secondary_data.standings:
                _register_name(srow.team_name)
        if odds_data is not None:
            for om in odds_data.matches:
                _register_name(om.home_team)
                _register_name(om.away_team)
        if espn_data is not None:
            for fx in espn_data.fixtures:
                _register_name(fx.home_team)
                _register_name(fx.away_team)

        teams = [
            ScrapedTeam(league_id=league_id, name=disp, short_name=disp[:50])
            for disp in canonical_display.values()
        ]
        matches_per_round = max(1, len(teams) // 2) if teams else 9

        synth_matches: list[ScrapedMatch] = []
        seen_finished: set[tuple[str, str]] = set()
        max_played_round = 0

        if af_data is not None and af_data.matches:
            for m in af_data.matches:
                h_disp = _register_name(m.home_team_name)
                a_disp = _register_name(m.away_team_name)
                if not h_disp or not a_disp or h_disp == a_disp:
                    continue
                if m.status == MatchStatus.FINISHED:
                    seen_finished.add((alias.resolve_key(h_disp), alias.resolve_key(a_disp)))
                    max_played_round = max(max_played_round, m.round)
                synth_matches.append(
                    ScrapedMatch(
                        league_id=league_id,
                        home_team_name=h_disp,
                        away_team_name=a_disp,
                        match_date=m.match_date,
                        round=m.round,
                        status=m.status,
                        home_score=m.home_score,
                        away_score=m.away_score,
                        home_short_name=h_disp[:50],
                        away_short_name=a_disp[:50],
                        home_logo_url=m.home_logo_url,
                        away_logo_url=m.away_logo_url,
                    )
                )

        if fd_data is not None and not seen_finished:
            sorted_fd = sorted(
                fd_data.matches,
                key=lambda r: _parse_flexible_datetime(r.match_date, fallback_date=reference_date),
            )
            for idx, fm in enumerate(sorted_fd):
                h_disp = _register_name(fm.home_team)
                a_disp = _register_name(fm.away_team)
                hk, ak = alias.resolve_key(h_disp), alias.resolve_key(a_disp)
                if not h_disp or not a_disp or hk == ak or (hk, ak) in seen_finished:
                    continue
                seen_finished.add((hk, ak))
                approx_round = (idx // matches_per_round) + 1
                max_played_round = max(max_played_round, approx_round)
                synth_matches.append(
                    ScrapedMatch(
                        league_id=league_id,
                        home_team_name=h_disp,
                        away_team_name=a_disp,
                        match_date=_parse_flexible_datetime(
                            fm.match_date, fallback_date=reference_date
                        ),
                        round=approx_round,
                        status=MatchStatus.FINISHED,
                        home_score=fm.fthg,
                        away_score=fm.ftag,
                        home_short_name=h_disp[:50],
                        away_short_name=a_disp[:50],
                    )
                )

        if espn_data is not None:
            for row in espn_data.standings:
                max_played_round = max(max_played_round, int(row.games_played))
            for fx in espn_data.fixtures:
                if fx.status != "FINISHED" or fx.home_score is None or fx.away_score is None:
                    continue
                h_disp = _register_name(fx.home_team)
                a_disp = _register_name(fx.away_team)
                hk, ak = alias.resolve_key(h_disp), alias.resolve_key(a_disp)
                if not h_disp or not a_disp or hk == ak or (hk, ak) in seen_finished:
                    continue
                seen_finished.add((hk, ak))
                round_est = max(1, max_played_round)
                synth_matches.append(
                    ScrapedMatch(
                        league_id=league_id,
                        home_team_name=h_disp,
                        away_team_name=a_disp,
                        match_date=_parse_flexible_datetime(
                            fx.match_date, fallback_date=reference_date
                        ),
                        round=round_est,
                        status=MatchStatus.FINISHED,
                        home_score=fx.home_score,
                        away_score=fx.away_score,
                        home_short_name=h_disp[:50],
                        away_short_name=a_disp[:50],
                    )
                )

        next_round_num = max(1, max_played_round + 1)
        upcoming_candidates: list[tuple[datetime, str, str]] = []
        seen_upcoming: set[tuple[str, str]] = set()

        if espn_data is not None:
            for fx in espn_data.fixtures:
                if fx.status == "FINISHED":
                    continue
                h_disp = _register_name(fx.home_team)
                a_disp = _register_name(fx.away_team)
                hk, ak = alias.resolve_key(h_disp), alias.resolve_key(a_disp)
                if not h_disp or not a_disp or hk == ak or (hk, ak) in seen_upcoming:
                    continue
                seen_upcoming.add((hk, ak))
                upcoming_candidates.append(
                    (
                        _parse_flexible_datetime(fx.match_date, fallback_date=reference_date),
                        h_disp,
                        a_disp,
                    )
                )

        if odds_data is not None:
            for om in odds_data.matches:
                h_disp = _register_name(om.home_team)
                a_disp = _register_name(om.away_team)
                hk, ak = alias.resolve_key(h_disp), alias.resolve_key(a_disp)
                if not h_disp or not a_disp or hk == ak or (hk, ak) in seen_upcoming:
                    continue
                seen_upcoming.add((hk, ak))
                upcoming_candidates.append(
                    (
                        _parse_flexible_datetime(om.commence_time, fallback_date=reference_date),
                        h_disp,
                        a_disp,
                    )
                )

        upcoming_candidates.sort(key=lambda item: item[0])
        team_sched_counts: dict[str, int] = {}
        for m_dt, h_disp, a_disp in upcoming_candidates:
            hk, ak = alias.resolve_key(h_disp), alias.resolve_key(a_disp)
            slot = max(team_sched_counts.get(hk, 0), team_sched_counts.get(ak, 0))
            assigned_round = next_round_num + slot
            team_sched_counts[hk] = slot + 1
            team_sched_counts[ak] = slot + 1
            synth_matches.append(
                ScrapedMatch(
                    league_id=league_id,
                    home_team_name=h_disp,
                    away_team_name=a_disp,
                    match_date=m_dt,
                    round=assigned_round,
                    status=MatchStatus.SCHEDULED,
                    home_short_name=h_disp[:50],
                    away_short_name=a_disp[:50],
                )
            )

        final_teams = [
            ScrapedTeam(league_id=league_id, name=disp, short_name=disp[:50])
            for disp in canonical_display.values()
        ]
        if round_filter is not None:
            synth_matches = [m for m in synth_matches if m.round == round_filter]

        return LeagueFixturesData(
            league_id=league_id,
            teams=final_teams,
            matches=synth_matches,
        )

    @staticmethod
    def _synthesize_fallback_injuries(
        league_id: LeagueId,
        *,
        af_data: ApiFootballLeagueData | None,
        secondary_data: SecondaryCheckData | None,
        reference_date: date | None = None,
    ) -> tuple[list[ScrapedInjury], str]:
        dedup: dict[tuple[str, str], ScrapedInjury] = {}
        primary_src = ""

        if af_data is not None and af_data.injuries:
            primary_src = "API-Football"
            for inj in af_data.injuries:
                key = (fold_ascii(inj.team_name), fold_ascii(inj.player_name))
                dedup[key] = inj

        if secondary_data is not None and secondary_data.injuries:
            if not primary_src:
                primary_src = secondary_data.active_source_name or "SportsGambler"
            for rec in secondary_data.injuries:
                key = (fold_ascii(rec.team_name), fold_ascii(rec.player_name))
                if key not in dedup:
                    dedup[key] = ScrapedInjury(
                        league_id=league_id,
                        team_name=normalize_team_name(rec.team_name),
                        player_name=rec.player_name,
                        position=map_player_position(""),
                        reason=rec.reason or "Sakatlık / eksik",
                        return_date=None,
                        impact_level=calculate_impact_level(
                            rec.reason or "", reference_date=reference_date
                        ),
                    )

        return list(dedup.values()), primary_src

    def _persist_league_bundle(
        self,
        client: Client,
        league_model: League,
        scraped_teams: list[ScrapedTeam],
    ) -> tuple[list[Team], dict[str, int]]:
        execute_query(
            lambda: client.table("leagues")
            .upsert(league_model.to_db_payload(), on_conflict="id")
            .execute(),
            context=f"upsert_league:{league_model.id.value}",
        )

        if not scraped_teams:
            return [], {}

        team_payloads = [st.to_team_model().to_db_payload() for st in scraped_teams]
        upsert_resp = execute_query(
            lambda: client.table("teams")
            .upsert(team_payloads, on_conflict="league_id,name")
            .execute(),
            context=f"upsert_teams:{league_model.id.value}",
        )

        rows: list[dict[str, Any]] = list(upsert_resp.data or [])
        if len(rows) < len(scraped_teams):
            select_resp = execute_query(
                lambda: client.table("teams")
                .select("id,league_id,name,short_name,logo_url")
                .eq("league_id", league_model.id.value)
                .execute(),
                context=f"select_teams:{league_model.id.value}",
            )
            rows = list(select_resp.data or [])

        id_by_key: dict[str, int] = {}
        persisted_teams: list[Team] = []
        for row in rows:
            tid = int(row["id"])
            tname = str(row["name"])
            id_by_key[_team_lookup_key(tname)] = tid

        for st in scraped_teams:
            tid = id_by_key[_team_lookup_key(st.name)]
            persisted_teams.append(st.to_team_model(team_id=tid))

        return persisted_teams, id_by_key

    def run_league(
        self,
        league_id: LeagueId,
        *,
        round_filter: int | None = None,
        reference_date: date | None = None,
        persist: bool = True,
    ) -> LeaguePipelineResult:
        """Tek bir lig için aktif kaynakları çalıştırır, çapraz doğrular ve gerekiyorsa kaydeder."""
        meta = LEAGUES[league_id]
        active_season = os.getenv("DEFAULT_SEASON", "").strip() or get_current_season()
        league_model = League(
            id=meta.id,
            name=meta.name,
            country=meta.country,
            season=active_season,
        )

        tm_fixtures_err: ScraperError | None = None
        tm_injuries_err: ScraperError | None = None

        try:
            fixtures_data = self.fixtures_scraper.fetch_league_fixtures(
                league_id, round_filter=round_filter
            )
        except ScraperError as exc:
            if not self._enable_multi_source:
                raise
            tm_fixtures_err = exc
            logger.warning(
                "Transfermarkt fikstür erişim engeli (%s); çoklu kaynak yedeği kullanılacak: %s",
                league_id.value,
                exc,
            )
            fixtures_data = LeagueFixturesData(league_id=league_id, teams=[], matches=[])

        try:
            scraped_injuries = self.injuries_scraper.fetch_league_injuries(
                league_id, reference_date=reference_date
            )
        except ScraperError as exc:
            if not self._enable_multi_source:
                raise
            tm_injuries_err = exc
            logger.warning(
                "Transfermarkt sakatlık erişim engeli (%s); ikincil kaynak yedeği kullanılacak: %s",
                league_id.value,
                exc,
            )
            scraped_injuries = []

        espn_data: ESPNLeagueData | None = None
        fd_data: FootballDataLeagueData | None = None
        understat_data = None
        secondary_data: SecondaryCheckData | None = None
        af_data: ApiFootballLeagueData | None = None
        odds_data: TheOddsLeagueData | None = None
        sources_used: list[str] = []
        source_diagnostics: dict[str, dict[str, Any]] = {}

        if self._enable_multi_source:
            with ThreadPoolExecutor(max_workers=5) as pool:
                fut_espn = (
                    pool.submit(self.espn_adapter.fetch_league, league_id)
                    if self.espn_adapter is not None
                    else None
                )
                fut_fd = (
                    pool.submit(
                        self.football_data_adapter.fetch_league,
                        league_id,
                        season=active_season,
                    )
                    if self.football_data_adapter is not None
                    else None
                )
                fut_sec = (
                    pool.submit(
                        self.secondary_adapter.fetch_league,
                        league_id,
                        season=active_season,
                    )
                    if self.secondary_adapter is not None
                    else None
                )
                fut_af = (
                    pool.submit(
                        self.api_football_adapter.fetch_league,
                        league_id,
                        season=active_season,
                        reference_date=reference_date,
                    )
                    if self.api_football_adapter is not None
                    else None
                )
                fut_odds = (
                    pool.submit(self.odds_adapter.fetch_league, league_id)
                    if self.odds_adapter is not None
                    else None
                )

                if fut_af is not None:
                    try:
                        af_data, af_diag = fut_af.result()
                        source_diagnostics["API-Football"] = af_diag
                        if af_diag.get("ok"):
                            sources_used.append("API-Football")
                    except Exception as exc:
                        logger.warning("API-Football yürütme hatası (%s): %s", league_id.value, exc)
                        source_diagnostics["API-Football"] = make_source_diagnostic(
                            "API-Football", ok=False, error=str(exc)
                        )

                if fut_odds is not None:
                    try:
                        odds_data, odds_diag = fut_odds.result()
                        source_diagnostics["TheOddsAPI"] = odds_diag
                        if odds_diag.get("ok"):
                            sources_used.append("TheOddsAPI")
                    except Exception as exc:
                        logger.warning("TheOddsAPI yürütme hatası (%s): %s", league_id.value, exc)
                        source_diagnostics["TheOddsAPI"] = make_source_diagnostic(
                            "TheOddsAPI", ok=False, error=str(exc)
                        )

                if fut_espn is not None:
                    try:
                        espn_data, espn_diag = fut_espn.result()
                        source_diagnostics["ESPN"] = espn_diag
                        if espn_diag.get("ok"):
                            sources_used.append("ESPN")
                    except Exception as exc:
                        logger.warning("ESPN yürütme hatası (%s): %s", league_id.value, exc)
                        source_diagnostics["ESPN"] = make_source_diagnostic(
                            "ESPN", ok=False, error=str(exc)
                        )

                if fut_fd is not None:
                    try:
                        fd_data, fd_diag = fut_fd.result()
                        source_diagnostics["Football-Data"] = fd_diag
                        if fd_diag.get("ok"):
                            sources_used.append("Football-Data")
                    except Exception as exc:
                        logger.warning(
                            "Football-Data yürütme hatası (%s): %s", league_id.value, exc
                        )
                        source_diagnostics["Football-Data"] = make_source_diagnostic(
                            "Football-Data", ok=False, error=str(exc)
                        )

                if fut_sec is not None:
                    try:
                        secondary_data, sec_diag = fut_sec.result()
                        sec_name = str(sec_diag.get("source") or "TheSportsDB")
                        source_diagnostics[sec_name] = sec_diag
                        if sec_diag.get("ok"):
                            sources_used.append(sec_name)
                    except Exception as exc:
                        logger.warning("İkincil kaynak yürütme hatası (%s): %s", league_id.value, exc)
                        source_diagnostics["TheSportsDB"] = make_source_diagnostic(
                            "TheSportsDB", ok=False, error=str(exc)
                        )

            if self.understat_adapter is not None:
                fallback_shots: dict[
                    str, tuple[float | None, float | None, float | None, float | None]
                ] = {}
                if fd_data is not None:
                    for tname, fd_stats in fd_data.team_stats.items():
                        fallback_shots[tname] = (
                            fd_stats.shots_for_per_match,
                            fd_stats.sot_for_per_match,
                            fd_stats.shots_against_per_match,
                            fd_stats.sot_against_per_match,
                        )
                try:
                    understat_data, us_diag = self.understat_adapter.fetch_league(
                        league_id,
                        season=active_season,
                        fallback_team_shots=fallback_shots or None,
                    )
                    source_diagnostics["Understat"] = us_diag
                    if us_diag.get("ok"):
                        sources_used.append("Understat")
                except Exception as exc:
                    logger.warning("Understat yürütme hatası (%s): %s", league_id.value, exc)
                    source_diagnostics["Understat"] = make_source_diagnostic(
                        "Understat", ok=False, error=str(exc)
                    )

        tm_had_data = bool(fixtures_data.matches or scraped_injuries)
        primary_team_source = "Transfermarkt" if tm_had_data else ""
        primary_injury_source = "Transfermarkt" if scraped_injuries else ""

        if self._enable_multi_source and not fixtures_data.matches:
            fixtures_data = self._synthesize_fallback_fixtures(
                league_id,
                af_data=af_data,
                espn_data=espn_data,
                fd_data=fd_data,
                secondary_data=secondary_data,
                odds_data=odds_data,
                round_filter=round_filter,
                reference_date=reference_date,
            )

        if self._enable_multi_source and not scraped_injuries:
            scraped_injuries, primary_injury_source = self._synthesize_fallback_injuries(
                league_id,
                af_data=af_data,
                secondary_data=secondary_data,
                reference_date=reference_date,
            )

        merged_teams, _ = self._merge_scraped_teams(
            league_id,
            fixtures_data.teams,
            (inj.team_name for inj in scraped_injuries),
        )

        client = self._resolve_db_client(persist=persist)
        persisted = client is not None

        if client is not None:
            team_models, team_id_by_key = self._persist_league_bundle(
                client, league_model, merged_teams
            )
        else:
            team_models = []
            team_id_by_key = {}
            for st in merged_teams:
                tid = self._next_local_team_id
                self._next_local_team_id += 1
                team_id_by_key[_team_lookup_key(st.name)] = tid
                team_models.append(st.to_team_model(team_id=tid))

        resolver = TeamAliasResolver(team_models)

        def _resolve_tid(raw_team_name: str) -> int | None:
            direct = team_id_by_key.get(_team_lookup_key(raw_team_name))
            if direct is not None:
                return direct
            return resolver.resolve_team_id(raw_team_name)

        dedup_matches: dict[tuple[LeagueId, int, int, int], Match] = {}
        for sm in fixtures_data.matches:
            home_id = _resolve_tid(sm.home_team_name)
            away_id = _resolve_tid(sm.away_team_name)
            if home_id is None or away_id is None or home_id == away_id:
                continue
            match_model = sm.to_match_model(home_team_id=home_id, away_team_id=away_id)
            dedup_matches[
                (
                    match_model.league_id,
                    match_model.round,
                    match_model.home_team_id,
                    match_model.away_team_id,
                )
            ] = match_model

        match_models = list(dedup_matches.values())

        injury_models: list[Injury] = []
        for si in scraped_injuries:
            inj_team_id = _resolve_tid(si.team_name)
            if inj_team_id is None:
                continue
            inj_model = si.to_injury_model(team_id=inj_team_id)
            if primary_injury_source and primary_injury_source != "Transfermarkt":
                inj_model = inj_model.model_copy(update={"sources": [primary_injury_source]})
            injury_models.append(inj_model)

        team_metrics: dict[int, TeamMultiSourceMetrics] = {}
        market_odds: dict[tuple[int, int], dict[str, float]] = {}
        sources_total = 5

        if not self._enable_multi_source:
            sources_used = ["Transfermarkt"]
        else:
            route = TRANSFERMARKT_LEAGUES[league_id]
            tm_url = f"{self.http.base_url}{route.full_schedule_path}"
            if tm_had_data:
                sources_used.append("Transfermarkt")
                source_diagnostics["Transfermarkt"] = make_source_diagnostic(
                    "Transfermarkt",
                    ok=True,
                    http_status=200,
                    records=len(match_models) + len(injury_models),
                    url=tm_url,
                    note=f"{len(match_models)} fikstür, {len(injury_models)} sakatlık/ceza",
                )
            else:
                first_tm_err = tm_fixtures_err or tm_injuries_err
                tm_code = getattr(first_tm_err, "status_code", None)
                source_diagnostics["Transfermarkt"] = make_source_diagnostic(
                    "Transfermarkt",
                    ok=False,
                    http_status=tm_code,
                    records=0,
                    url=tm_url,
                    note="Erişim engeli; çoklu kaynak yedeği devrede",
                    error=str(first_tm_err) if first_tm_err is not None else "Veri alınamadı",
                )

            match_models, confirmed_scores = cross_validate_match_scores(
                match_models,
                team_models,
                espn_data=espn_data,
                football_data=fd_data,
                resolver=resolver,
            )

            sec_inj_pool: list[SecondaryInjuryRecord] = []
            if secondary_data is not None and secondary_data.injuries:
                sec_inj_pool.extend(secondary_data.injuries)
            if af_data is not None and af_data.secondary_injuries:
                sec_inj_pool.extend(af_data.secondary_injuries)

            if sec_inj_pool and injury_models:
                injury_models, verified_injuries = cross_validate_injuries(
                    injury_models,
                    team_models,
                    sec_inj_pool,
                    resolver=resolver,
                    primary_source_name=primary_injury_source or "Transfermarkt",
                )
                if secondary_data is not None:
                    sec_key = secondary_data.active_source_name
                    if sec_key in source_diagnostics and verified_injuries > 0:
                        prev_note = source_diagnostics[sec_key].get("note") or ""
                        source_diagnostics[sec_key]["note"] = (
                            f"{prev_note}; {verified_injuries} çift kaynak onaylı sakatlık".lstrip(
                                "; "
                            )
                        )

            if confirmed_scores > 0 and "ESPN" in source_diagnostics:
                prev_espn_note = source_diagnostics["ESPN"].get("note") or ""
                source_diagnostics["ESPN"]["note"] = (
                    f"{prev_espn_note}; {confirmed_scores} maç skoru doğrulandı".lstrip("; ")
                )

            team_metrics = fuse_team_metrics(
                team_models,
                resolver=resolver,
                espn_data=espn_data,
                football_data=fd_data,
                understat_data=understat_data,
                secondary_data=secondary_data,
                api_football_data=af_data,
                odds_data=odds_data,
                primary_source_name=primary_team_source,
            )
            market_odds = build_market_odds_map(
                team_models,
                resolver=resolver,
                odds_data=odds_data,
                football_data=fd_data,
            )
            sources_used = _order_sources(sources_used)
            sources_total = max(5, len(source_diagnostics), len(sources_used))

        if client is not None:
            if match_models:
                match_payloads = [m.to_db_payload() for m in match_models]
                execute_query(
                    lambda: client.table("matches")
                    .upsert(
                        match_payloads,
                        on_conflict="league_id,round,home_team_id,away_team_id",
                    )
                    .execute(),
                    context=f"upsert_matches:{league_id.value}",
                )

            league_team_ids = list(team_id_by_key.values())
            if league_team_ids:
                # shortcut: schema.sql içinde injuries tablosunda bileşik UNIQUE kısıtı olmadığından
                # ilgili ligin güncel sakatlık anlık görüntüsü sil-ve-yeniden-ekle ile yenilenir.
                execute_query(
                    lambda: client.table("injuries")
                    .delete()
                    .in_("team_id", league_team_ids)
                    .execute(),
                    context=f"refresh_delete_injuries:{league_id.value}",
                )
            if injury_models:
                injury_payloads = [inj.to_db_payload() for inj in injury_models]
                execute_query(
                    lambda: client.table("injuries").insert(injury_payloads).execute(),
                    context=f"insert_injuries:{league_id.value}",
                )

        return LeaguePipelineResult(
            league=league_model,
            teams=team_models,
            matches=match_models,
            injuries=injury_models,
            persisted=persisted,
            team_metrics=team_metrics,
            market_odds=market_odds,
            sources_used=sources_used,
            sources_total=sources_total,
            source_diagnostics=source_diagnostics,
        )

    def run(
        self,
        leagues: Iterable[LeagueId] | LeagueId | None = None,
        *,
        round_filter: int | None = None,
        reference_date: date | None = None,
        persist: bool = True,
    ) -> PipelineResult:
        """Belirtilen lig(ler) veya 4 ligin tamamı için uçtan uca veri toplama akışını çalıştırır."""
        if leagues is None:
            target_leagues = list(LEAGUES.keys())
        elif isinstance(leagues, LeagueId):
            target_leagues = [leagues]
        else:
            target_leagues = list(leagues)

        combined = PipelineResult(persisted=False, sources_total=5)
        any_persisted = False
        agg_sources: list[str] = []

        for lid in target_leagues:
            res = self.run_league(
                lid,
                round_filter=round_filter,
                reference_date=reference_date,
                persist=persist,
            )
            any_persisted = any_persisted or res.persisted
            combined.leagues.append(res.league)
            combined.teams.extend(res.teams)
            combined.matches.extend(res.matches)
            combined.injuries.extend(res.injuries)
            combined.team_metrics.update(res.team_metrics)
            combined.market_odds.update(res.market_odds)
            combined.sources_total = max(combined.sources_total, res.sources_total)

            for s in res.sources_used:
                if s not in agg_sources:
                    agg_sources.append(s)

            if res.source_diagnostics:
                combined.league_sources[lid.value] = {
                    "sources_used": list(res.sources_used),
                    "sources_count": len(res.sources_used),
                    "sources_total": res.sources_total,
                    "source_diagnostics": dict(res.source_diagnostics),
                }
                for src_key, diag in res.source_diagnostics.items():
                    prev = combined.source_diagnostics.get(src_key)
                    if prev is None:
                        combined.source_diagnostics[src_key] = dict(diag)
                    else:
                        prev["ok"] = bool(prev.get("ok")) or bool(diag.get("ok"))
                        prev["records"] = int(prev.get("records") or 0) + int(
                            diag.get("records") or 0
                        )
                        if not prev.get("http_status") and diag.get("http_status"):
                            prev["http_status"] = diag["http_status"]

        combined.sources_used = (
            _order_sources(agg_sources) if self._enable_multi_source else agg_sources
        )
        combined.sources_total = max(
            combined.sources_total, len(combined.source_diagnostics), len(combined.sources_used)
        )
        combined.persisted = any_persisted
        return combined


def run_ingestion_pipeline(
    leagues: Iterable[LeagueId] | LeagueId | None = None,
    *,
    round_filter: int | None = None,
    reference_date: date | None = None,
    persist: bool = True,
    as_dict: bool = False,
) -> PipelineResult | dict[str, Any]:
    """Tek çağrımlık yardımcı orkestratör fonksiyonu."""
    with IngestionPipeline() as pipeline:
        result = pipeline.run(
            leagues=leagues,
            round_filter=round_filter,
            reference_date=reference_date,
            persist=persist,
        )
        return result.to_dict() if as_dict else result
