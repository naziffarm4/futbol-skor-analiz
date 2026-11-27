"""4 lig için 5 kaynaklı fikstür, istatistik, xG ve sakatlık verilerini toplayan orkestratör."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from supabase import Client

from engine.config import LEAGUES, LeagueId, get_current_season
from engine.db.client import DatabaseConfigError, execute_query, get_supabase_client
from engine.models.schemas import Injury, League, Match, Team
from engine.scrapers.base import BaseScraper, normalize_team_name
from engine.scrapers.fixtures import FixturesScraper, ScrapedTeam
from engine.scrapers.fusion import (
    TeamAliasResolver,
    TeamMultiSourceMetrics,
    cross_validate_injuries,
    cross_validate_match_scores,
    fuse_team_metrics,
)
from engine.scrapers.injuries import TRANSFERMARKT_LEAGUES, InjuriesScraper
from engine.scrapers.sources import (
    ESPNAdapter,
    FootballDataAdapter,
    SecondaryCheckAdapter,
    UnderstatAdapter,
    make_source_diagnostic,
)

logger = logging.getLogger(__name__)

CANONICAL_SOURCE_ORDER: tuple[str, ...] = (
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


@dataclass(slots=True)
class LeaguePipelineResult:
    league: League
    teams: list[Team]
    matches: list[Match]
    injuries: list[Injury]
    persisted: bool
    team_metrics: dict[int, TeamMultiSourceMetrics] = field(default_factory=dict)
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
            "sources_used": list(self.sources_used),
            "sources_total": self.sources_total,
            "source_diagnostics": dict(self.source_diagnostics),
            "league_sources": dict(self.league_sources),
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


class IngestionPipeline:
    """5 bağımsız veri kaynağını çalıştırıp çapraz doğrulanmış Pydantic modellerine ve Supabase'e bağlar."""

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
    ) -> None:
        both_mocked = fixtures_scraper is not None and injuries_scraper is not None
        if enable_multi_source is None:
            self._enable_multi_source = not both_mocked
        else:
            self._enable_multi_source = bool(enable_multi_source)

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
        """Tek bir lig için 5 kaynağı çalıştırır, çapraz doğrular ve gerekiyorsa kaydeder."""
        meta = LEAGUES[league_id]
        active_season = os.getenv("DEFAULT_SEASON", "").strip() or get_current_season()
        league_model = League(
            id=meta.id,
            name=meta.name,
            country=meta.country,
            season=active_season,
        )

        fixtures_data = self.fixtures_scraper.fetch_league_fixtures(
            league_id, round_filter=round_filter
        )
        scraped_injuries = self.injuries_scraper.fetch_league_injuries(
            league_id, reference_date=reference_date
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

        dedup_matches: dict[tuple[LeagueId, int, int, int], Match] = {}
        for sm in fixtures_data.matches:
            home_id = team_id_by_key.get(_team_lookup_key(sm.home_team_name))
            away_id = team_id_by_key.get(_team_lookup_key(sm.away_team_name))
            if home_id is None or away_id is None or home_id == away_id:
                continue
            match_model = sm.to_match_model(home_team_id=home_id, away_team_id=away_id)
            dedup_matches[
                (match_model.league_id, match_model.round, match_model.home_team_id, match_model.away_team_id)
            ] = match_model

        match_models = list(dedup_matches.values())

        injury_models: list[Injury] = []
        for si in scraped_injuries:
            inj_team_id = team_id_by_key.get(_team_lookup_key(si.team_name))
            if inj_team_id is None:
                continue
            injury_models.append(si.to_injury_model(team_id=inj_team_id))

        team_metrics: dict[int, TeamMultiSourceMetrics] = {}
        sources_used: list[str] = ["Transfermarkt"]
        source_diagnostics: dict[str, dict[str, Any]] = {}

        if self._enable_multi_source:
            route = TRANSFERMARKT_LEAGUES[league_id]
            tm_url = f"{self.http.base_url}{route.full_schedule_path}"
            source_diagnostics["Transfermarkt"] = make_source_diagnostic(
                "Transfermarkt",
                ok=bool(match_models or injury_models),
                http_status=200,
                records=len(match_models) + len(injury_models),
                url=tm_url,
                note=f"{len(match_models)} fikstür, {len(injury_models)} sakatlık/ceza",
            )

            espn_data = None
            fd_data = None
            understat_data = None
            secondary_data = None

            with ThreadPoolExecutor(max_workers=3) as pool:
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
                        logger.warning("Football-Data yürütme hatası (%s): %s", league_id.value, exc)
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
                        logger.warning("5. kaynak yürütme hatası (%s): %s", league_id.value, exc)
                        source_diagnostics["TheSportsDB"] = make_source_diagnostic(
                            "TheSportsDB", ok=False, error=str(exc)
                        )

            if self.understat_adapter is not None:
                fallback_shots: dict[str, tuple[float | None, float | None, float | None, float | None]] = {}
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

            resolver = TeamAliasResolver(team_models)
            match_models, confirmed_scores = cross_validate_match_scores(
                match_models,
                team_models,
                espn_data=espn_data,
                football_data=fd_data,
                resolver=resolver,
            )
            if secondary_data is not None and secondary_data.injuries:
                injury_models, verified_injuries = cross_validate_injuries(
                    injury_models,
                    team_models,
                    secondary_data.injuries,
                    resolver=resolver,
                )
                sec_key = secondary_data.active_source_name
                if sec_key in source_diagnostics and verified_injuries > 0:
                    prev_note = source_diagnostics[sec_key].get("note") or ""
                    source_diagnostics[sec_key]["note"] = (
                        f"{prev_note}; {verified_injuries} çift kaynak onaylı sakatlık".lstrip("; ")
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
            )
            sources_used = _order_sources(sources_used)

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
            sources_used=sources_used,
            sources_total=5,
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
                        prev["records"] = int(prev.get("records") or 0) + int(diag.get("records") or 0)
                        if not prev.get("http_status") and diag.get("http_status"):
                            prev["http_status"] = diag["http_status"]

        combined.sources_used = _order_sources(agg_sources) if self._enable_multi_source else agg_sources
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
