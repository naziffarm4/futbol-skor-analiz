"""Fikstür ve sakatlık verilerinden Prediction ve TeamAnalysis üreten ve kaydeden ana servis."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from supabase import Client

from engine.config import LeagueId
from engine.db.client import DatabaseConfigError, execute_query, get_supabase_client
from engine.models.schemas import Injury, Match, MatchStatus, Prediction, Team, TeamAnalysis
from engine.predictors.analyst import generate_match_analysis_texts
from engine.predictors.poisson import PoissonPredictionResult, predict_score_distribution
from engine.predictors.ratings import (
    TeamRatingProfile,
    build_team_ratings,
    calculate_league_baseline,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class MatchPredictionBundle:
    """Tek bir sıradaki maç için üretilen tahmin, analiz ve ara model çıktıları."""

    match: Match
    prediction: Prediction
    team_analysis: TeamAnalysis
    poisson: PoissonPredictionResult
    home_profile: TeamRatingProfile
    away_profile: TeamRatingProfile


@dataclass(slots=True)
class PredictionServiceResult:
    """Toplu tahmin ve analiz çalıştırmasının çıktısı."""

    persisted: bool
    predictions: list[Prediction] = field(default_factory=list)
    team_analyses: list[TeamAnalysis] = field(default_factory=list)
    bundles: list[MatchPredictionBundle] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "persisted": self.persisted,
            "predictions": [p.to_db_payload() for p in self.predictions],
            "team_analyses": [ta.to_db_payload() for ta in self.team_analyses],
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


def _resolve_team_names(
    teams: Sequence[Team] | Mapping[int, Team | str] | None,
) -> dict[int, str]:
    if teams is None:
        return {}
    if isinstance(teams, Mapping):
        out: dict[int, str] = {}
        for tid, val in teams.items():
            out[int(tid)] = val.name if isinstance(val, Team) else str(val)
        return out
    return {t.id: t.name for t in teams if t.id is not None}


def _resolve_league_team_metrics(
    team_metrics: Mapping[Any, Any] | None,
    lg_team_ids: set[int],
    team_names: Mapping[int, str],
) -> dict[int, Any] | None:
    if not team_metrics:
        return None
    name_to_id = {
        name.strip().casefold(): tid for tid, name in team_names.items() if tid in lg_team_ids
    }
    resolved: dict[int, Any] = {}
    for raw_key, metric_obj in team_metrics.items():
        if isinstance(raw_key, int) and raw_key in lg_team_ids:
            resolved[raw_key] = metric_obj
        elif isinstance(raw_key, str):
            stripped = raw_key.strip()
            if stripped.isdigit() and int(stripped) in lg_team_ids:
                resolved[int(stripped)] = metric_obj
            else:
                matched_tid = name_to_id.get(stripped.casefold())
                if matched_tid is not None and matched_tid not in resolved:
                    resolved[matched_tid] = metric_obj
    return resolved or None


def select_next_round(
    finished_matches: Sequence[Any],
    scheduled_matches: Sequence[Any],
) -> int | None:
    """Ertelenmiş geçmiş hafta maçlarını atlayarak sıradaki aktif lig haftasını seçer."""
    if not scheduled_matches:
        return None

    scheduled_rounds = sorted({int(m.round) for m in scheduled_matches})
    if len(scheduled_rounds) == 1:
        return scheduled_rounds[0]

    max_finished_round = max((int(m.round) for m in finished_matches), default=0)
    finished_in_round: dict[int, int] = {}
    for m in finished_matches:
        r = int(m.round)
        finished_in_round[r] = finished_in_round.get(r, 0) + 1

    earliest_sched_by_round: dict[int, datetime] = {}
    for m in scheduled_matches:
        r = int(m.round)
        cur = earliest_sched_by_round.get(r)
        if cur is None or m.match_date < cur:
            earliest_sched_by_round[r] = m.match_date

    for idx, rnd in enumerate(scheduled_rounds):
        if rnd < max_finished_round:
            continue
        if finished_in_round.get(rnd, 0) > 0 and idx + 1 < len(scheduled_rounds):
            next_rnd = scheduled_rounds[idx + 1]
            if earliest_sched_by_round[rnd] > earliest_sched_by_round[next_rnd]:
                continue
        return rnd

    return scheduled_rounds[-1]


class PredictionService:
    """Oynanmış maçlar ve sakatlıklardan sıradaki maçların skor tahmin ve analizlerini üretir."""

    def __init__(self, *, supabase_client: Client | None = None) -> None:
        self._explicit_client = supabase_client

    def _resolve_db_client(self, persist: bool) -> Client | None:
        if not persist:
            return None
        if self._explicit_client is not None:
            return self._explicit_client
        try:
            return get_supabase_client(use_service_role=True)
        except DatabaseConfigError:
            logger.info(
                "Supabase yapılandırılmamış; tahmin ve analizler yerel model/dict modunda döndürülecek."
            )
            return None

    def _backfill_missing_match_ids(
        self,
        client: Client,
        league_id: LeagueId,
        scheduled: list[Match],
    ) -> dict[tuple[int, int, int], int]:
        if all(m.id is not None for m in scheduled):
            return {}
        resp = execute_query(
            lambda: client.table("matches")
            .select("id,round,home_team_id,away_team_id")
            .eq("league_id", league_id.value)
            .execute(),
            context=f"select_match_ids:{league_id.value}",
        )
        lookup: dict[tuple[int, int, int], int] = {}
        for row in resp.data or []:
            key = (int(row["round"]), int(row["home_team_id"]), int(row["away_team_id"]))
            lookup[key] = int(row["id"])
        return lookup

    def run(
        self,
        *,
        matches: Sequence[Match] = (),
        played_matches: Sequence[Match] | None = None,
        scheduled_matches: Sequence[Match] | None = None,
        injuries: Sequence[Injury] = (),
        teams: Sequence[Team] | Mapping[int, Team | str] | None = None,
        team_metrics: Mapping[Any, Any] | None = None,
        round_filter: int | None = None,
        only_next_round: bool = False,
        persist: bool = False,
        rho: float = -0.10,
    ) -> PredictionServiceResult:
        """Verilen fikstür ve sakatlıklarla her SCHEDULED maç için Prediction ve TeamAnalysis üretir."""
        finished_list = (
            list(played_matches)
            if played_matches is not None
            else [m for m in matches if m.status == MatchStatus.FINISHED]
        )
        scheduled_list = (
            list(scheduled_matches)
            if scheduled_matches is not None
            else [m for m in matches if m.status == MatchStatus.SCHEDULED]
        )

        if round_filter is not None:
            scheduled_list = [m for m in scheduled_list if m.round == round_filter]

        team_names = _resolve_team_names(teams)
        client = self._resolve_db_client(persist=persist)

        # Lig bazında grupla (her ligin gol ortalaması ve ev avantajı kendi içinde hesaplanır)
        leagues_seen: list[LeagueId] = []
        for m in (*finished_list, *scheduled_list):
            if m.league_id not in leagues_seen:
                leagues_seen.append(m.league_id)

        used_ids = {
            m.id for m in (*finished_list, *scheduled_list) if m.id is not None
        }
        next_local_id = max(used_ids, default=0) + 1

        result = PredictionServiceResult(persisted=client is not None)

        for lid in leagues_seen:
            lg_finished = [m for m in finished_list if m.league_id == lid]
            lg_scheduled = [m for m in scheduled_list if m.league_id == lid]
            if not lg_scheduled:
                continue

            if only_next_round:
                target_round = select_next_round(lg_finished, lg_scheduled)
                lg_scheduled = [m for m in lg_scheduled if m.round == target_round]

            lg_scheduled.sort(key=lambda m: (m.round, m.match_date, m.home_team_id))

            lg_all_matches = [*lg_finished, *lg_scheduled]
            lg_team_ids = {m.home_team_id for m in lg_all_matches} | {
                m.away_team_id for m in lg_all_matches
            }
            lg_injuries = [inj for inj in injuries if inj.team_id in lg_team_ids]
            lg_metrics = _resolve_league_team_metrics(team_metrics, lg_team_ids, team_names)

            baseline = calculate_league_baseline(lg_finished)
            profiles = build_team_ratings(
                lg_all_matches,
                lg_injuries,
                team_ids=lg_team_ids,
                team_metrics=lg_metrics,
            )

            db_id_lookup = (
                self._backfill_missing_match_ids(client, lid, lg_scheduled)
                if client is not None
                else {}
            )

            for match in lg_scheduled:
                resolved_id = match.id
                if resolved_id is None and client is not None:
                    resolved_id = db_id_lookup.get(
                        (match.round, match.home_team_id, match.away_team_id)
                    )
                if resolved_id is None:
                    resolved_id = next_local_id
                    next_local_id += 1

                home_prof = profiles[match.home_team_id]
                away_prof = profiles[match.away_team_id]
                sample_depth = min(home_prof.played, away_prof.played)

                poisson_res = predict_score_distribution(
                    home_attack=home_prof.adjusted_home_attack,
                    away_defense=away_prof.adjusted_away_defense,
                    away_attack=away_prof.adjusted_away_attack,
                    home_defense=home_prof.adjusted_home_defense,
                    avg_home_goals=baseline.avg_home_goals,
                    avg_away_goals=baseline.avg_away_goals,
                    sample_matches=sample_depth,
                    rho=rho,
                    home_ht_attack_share=home_prof.first_half_attack_share,
                    away_ht_concede_share=away_prof.first_half_concede_share,
                    away_ht_attack_share=away_prof.first_half_attack_share,
                    home_ht_concede_share=home_prof.first_half_concede_share,
                )

                home_name = team_names.get(match.home_team_id, f"Takım #{match.home_team_id}")
                away_name = team_names.get(match.away_team_id, f"Takım #{match.away_team_id}")

                texts = generate_match_analysis_texts(
                    home_name=home_name,
                    away_name=away_name,
                    home_profile=home_prof,
                    away_profile=away_prof,
                    poisson_result=poisson_res,
                    round_number=match.round,
                )

                prediction = Prediction(
                    match_id=resolved_id,
                    predicted_home_score=poisson_res.predicted_home_score,
                    predicted_away_score=poisson_res.predicted_away_score,
                    predicted_ht_home_score=poisson_res.predicted_ht_home_score,
                    predicted_ht_away_score=poisson_res.predicted_ht_away_score,
                    ht_ft_prediction=poisson_res.ht_ft_prediction,
                    top_ht_ft_json=poisson_res.top_ht_ft,
                    confidence_rate=poisson_res.confidence_rate,
                    top_scores_json=poisson_res.top_scores,
                )
                analysis = TeamAnalysis(
                    match_id=resolved_id,
                    match_overview_text=texts.match_overview_text,
                    home_analysis_text=texts.home_analysis_text,
                    away_analysis_text=texts.away_analysis_text,
                    ht_ft_reasoning_text=texts.ht_ft_reasoning_text,
                    home_offense_rating=home_prof.adjusted_offense_rating,
                    home_defense_rating=home_prof.adjusted_defense_rating,
                    away_offense_rating=away_prof.adjusted_offense_rating,
                    away_defense_rating=away_prof.adjusted_defense_rating,
                )

                result.predictions.append(prediction)
                result.team_analyses.append(analysis)
                result.bundles.append(
                    MatchPredictionBundle(
                        match=match,
                        prediction=prediction,
                        team_analysis=analysis,
                        poisson=poisson_res,
                        home_profile=home_prof,
                        away_profile=away_prof,
                    )
                )

        if client is not None and result.predictions:
            pred_payloads = [p.to_db_payload() for p in result.predictions]
            execute_query(
                lambda: client.table("predictions")
                .upsert(pred_payloads, on_conflict="match_id")
                .execute(),
                context="upsert_predictions",
            )
            analysis_payloads = [ta.to_db_payload() for ta in result.team_analyses]
            execute_query(
                lambda: client.table("team_analyses")
                .upsert(analysis_payloads, on_conflict="match_id")
                .execute(),
                context="upsert_team_analyses",
            )

        return result


def run_prediction_pipeline(
    *,
    matches: Sequence[Match] = (),
    played_matches: Sequence[Match] | None = None,
    scheduled_matches: Sequence[Match] | None = None,
    injuries: Sequence[Injury] = (),
    teams: Sequence[Team] | Mapping[int, Team | str] | None = None,
    team_metrics: Mapping[Any, Any] | None = None,
    round_filter: int | None = None,
    only_next_round: bool = False,
    persist: bool = False,
    as_dict: bool = False,
) -> PredictionServiceResult | dict[str, Any]:
    """Tek çağrımlık tahmin ve analiz orkestratör fonksiyonu."""
    service = PredictionService()
    res = service.run(
        matches=matches,
        played_matches=played_matches,
        scheduled_matches=scheduled_matches,
        injuries=injuries,
        teams=teams,
        team_metrics=team_metrics,
        round_filter=round_filter,
        only_next_round=only_next_round,
        persist=persist,
    )
    return res.to_dict() if as_dict else res
