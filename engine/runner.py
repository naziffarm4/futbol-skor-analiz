"""4 lig için veri toplama ve tahmin/analiz motorlarını birleştiren ana orkestratör."""

from __future__ import annotations

import copy
import json
import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from engine.config import LEAGUES, LeagueId
from engine.predictors.service import PredictionService, PredictionServiceResult
from engine.scrapers.pipeline import IngestionPipeline, PipelineResult

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class LeagueSyncStatus:
    """Tek bir ligin son senkronizasyon durumunu tutar."""

    league_id: str
    name: str
    country: str
    status: str = "idle"
    last_sync_at: str | None = None
    teams_count: int = 0
    matches_count: int = 0
    injuries_count: int = 0
    predictions_count: int = 0
    persisted: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "league_id": self.league_id,
            "name": self.name,
            "country": self.country,
            "status": self.status,
            "last_sync_at": self.last_sync_at,
            "teams_count": self.teams_count,
            "matches_count": self.matches_count,
            "injuries_count": self.injuries_count,
            "predictions_count": self.predictions_count,
            "persisted": self.persisted,
            "error": self.error,
        }


def _default_league_statuses() -> dict[str, LeagueSyncStatus]:
    return {
        lid.value: LeagueSyncStatus(
            league_id=lid.value,
            name=meta.name,
            country=meta.country,
        )
        for lid, meta in LEAGUES.items()
    }


@dataclass(slots=True)
class RunnerStatus:
    """Orkestratörün çalışma zamanı durumunu, sayaçlarını ve lig özetlerini bellekte tutar."""

    is_running: bool = False
    last_status: str = "idle"
    last_run_started_at: str | None = None
    last_run_finished_at: str | None = None
    last_error: str | None = None
    total_runs: int = 0
    last_matches_count: int = 0
    last_injuries_count: int = 0
    last_predictions_count: int = 0
    total_matches_processed: int = 0
    total_injuries_processed: int = 0
    total_predictions_generated: int = 0
    leagues: dict[str, LeagueSyncStatus] = field(default_factory=_default_league_statuses)

    def reset(self) -> None:
        self.is_running = False
        self.last_status = "idle"
        self.last_run_started_at = None
        self.last_run_finished_at = None
        self.last_error = None
        self.total_runs = 0
        self.last_matches_count = 0
        self.last_injuries_count = 0
        self.last_predictions_count = 0
        self.total_matches_processed = 0
        self.total_injuries_processed = 0
        self.total_predictions_generated = 0
        self.leagues = _default_league_statuses()

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_running": self.is_running,
            "last_status": self.last_status,
            "last_run_started_at": self.last_run_started_at,
            "last_run_finished_at": self.last_run_finished_at,
            "last_error": self.last_error,
            "total_runs": self.total_runs,
            "last_matches_count": self.last_matches_count,
            "last_injuries_count": self.last_injuries_count,
            "last_predictions_count": self.last_predictions_count,
            "total_matches_processed": self.total_matches_processed,
            "total_injuries_processed": self.total_injuries_processed,
            "total_predictions_generated": self.total_predictions_generated,
            "leagues": {k: v.to_dict() for k, v in self.leagues.items()},
        }


@dataclass(slots=True)
class CycleResult:
    """Tek bir run_full_cycle çalıştırmasının birleşik çıktısı."""

    status: str
    started_at: str
    finished_at: str
    persisted: bool
    matches_count: int
    injuries_count: int
    predictions_count: int
    team_analyses_count: int
    leagues: dict[str, dict[str, Any]]
    errors: dict[str, str]
    ingestion: PipelineResult
    prediction: PredictionServiceResult
    sources_used: list[str] = field(default_factory=list)
    sources_total: int = 5
    source_diagnostics: dict[str, Any] = field(default_factory=dict)
    league_sources: dict[str, dict[str, Any]] = field(default_factory=dict)
    team_metrics: dict[Any, Any] = field(default_factory=dict)

    def to_dict(self, *, include_records: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "persisted": self.persisted,
            "matches_count": self.matches_count,
            "injuries_count": self.injuries_count,
            "predictions_count": self.predictions_count,
            "team_analyses_count": self.team_analyses_count,
            "leagues": self.leagues,
            "errors": self.errors,
        }
        if include_records:
            payload["ingestion"] = self.ingestion.to_dict()
            payload["prediction"] = self.prediction.to_dict()
        return payload

    def to_json(self, *, include_records: bool = False, indent: int = 2) -> str:
        return json.dumps(
            self.to_dict(include_records=include_records),
            ensure_ascii=False,
            indent=indent,
        )


# shortcut: RunnerStatus tek konteyner belleğinde tutulur (yeniden başlatmada sıfırlanır), çoklu kopya gerekirse Supabase tablosuna taşı.
runner_status = RunnerStatus()


def get_runner_status() -> RunnerStatus:
    return runner_status


def _normalize_leagues(
    leagues: Iterable[LeagueId | str] | LeagueId | str | None,
) -> list[LeagueId]:
    if leagues is None:
        return list(LEAGUES.keys())
    if isinstance(leagues, (LeagueId, str)):
        return [LeagueId(leagues)]
    resolved = [LeagueId(item) for item in leagues]
    return resolved or list(LEAGUES.keys())


_SUMMABLE_DIAG_KEYS = frozenset(
    {"matches", "teams", "injuries", "records", "count", "verified_count", "rows"}
)


def _merge_source_diagnostics(
    acc: dict[str, dict[str, Any]],
    incoming: Mapping[Any, Any],
) -> None:
    for raw_src, raw_info in incoming.items():
        src = str(raw_src)
        if not isinstance(raw_info, Mapping):
            acc.setdefault(src, {"status": str(raw_info)})
            continue
        info = copy.deepcopy(dict(raw_info))
        if src not in acc:
            acc[src] = info
            continue
        existing = acc[src]
        if "ok" in info or "ok" in existing:
            existing["ok"] = bool(existing.get("ok")) or bool(info.get("ok"))
        if "status" in info:
            if info["status"] == "ok" or existing.get("status") != "ok":
                existing["status"] = info["status"]
        for k, v in info.items():
            if k in {"ok", "status"}:
                continue
            if k in _SUMMABLE_DIAG_KEYS and isinstance(v, int) and not isinstance(v, bool):
                prev = existing.get(k, 0)
                if isinstance(prev, int) and not isinstance(prev, bool):
                    existing[k] = prev + v
                else:
                    existing[k] = v
            elif k not in existing or existing[k] is None:
                existing[k] = v


def _try_assign_ingestion_attr(target: Any, attr: str, value: Any) -> None:
    if hasattr(target, attr):
        cur = getattr(target, attr)
        if isinstance(cur, dict) and isinstance(value, dict):
            cur.update(value)
            return
        if isinstance(cur, list) and isinstance(value, list):
            cur[:] = value
            return
    try:
        setattr(target, attr, value)
    except (AttributeError, TypeError):
        pass


def run_full_cycle(
    leagues: Iterable[LeagueId | str] | LeagueId | str | None = None,
    persist: bool = True,
    only_next_round: bool = True,
    *,
    status_tracker: RunnerStatus | None = None,
    ingestion_pipeline: IngestionPipeline | None = None,
    prediction_service: PredictionService | None = None,
) -> CycleResult:
    """Hedef liglerin fikstür ve sakatlıklarını sırayla çekip tahmin ve analizlerini üretir."""
    target_leagues = _normalize_leagues(leagues)
    tracker = status_tracker if status_tracker is not None else runner_status

    started_at = _utc_now_iso()
    tracker.is_running = True
    tracker.last_status = "running"
    tracker.last_run_started_at = started_at
    tracker.last_error = None

    owns_ingestion = ingestion_pipeline is None
    pipeline = ingestion_pipeline if ingestion_pipeline is not None else IngestionPipeline()
    predictor = prediction_service if prediction_service is not None else PredictionService()

    combined_ingestion = PipelineResult(persisted=False)
    combined_prediction = PredictionServiceResult(persisted=False)
    league_summaries: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}
    any_persisted = False

    all_sources_used: list[str] = []
    sources_total = 5
    all_source_diagnostics: dict[str, dict[str, Any]] = {}
    all_league_sources: dict[str, dict[str, Any]] = {}
    all_team_metrics: dict[Any, Any] = {}

    try:
        for lid in target_leagues:
            lg_state = tracker.leagues[lid.value]
            lg_state.status = "running"
            lg_state.error = None

            try:
                logger.info("Lig senkronizasyonu başlatıldı: %s", lid.value)
                ing_res = pipeline.run_league(lid, persist=persist)
                ing_team_metrics = getattr(ing_res, "team_metrics", None)
                pred_kwargs: dict[str, Any] = {
                    "matches": ing_res.matches,
                    "injuries": ing_res.injuries,
                    "teams": ing_res.teams,
                    "only_next_round": only_next_round,
                    "persist": persist,
                }
                if ing_team_metrics is not None:
                    pred_kwargs["team_metrics"] = ing_team_metrics
                    if isinstance(ing_team_metrics, Mapping):
                        all_team_metrics.update(ing_team_metrics)

                pred_res = predictor.run(**pred_kwargs)

                lg_persisted = ing_res.persisted or pred_res.persisted
                any_persisted = any_persisted or lg_persisted

                combined_ingestion.leagues.append(ing_res.league)
                combined_ingestion.teams.extend(ing_res.teams)
                combined_ingestion.matches.extend(ing_res.matches)
                combined_ingestion.injuries.extend(ing_res.injuries)

                raw_lg_sources = getattr(ing_res, "sources_used", None)
                lg_sources = (
                    [str(s) for s in raw_lg_sources if str(s).strip()]
                    if isinstance(raw_lg_sources, (list, tuple, set))
                    else []
                )
                for src_name in lg_sources:
                    if src_name not in all_sources_used:
                        all_sources_used.append(src_name)

                raw_lg_total = getattr(ing_res, "sources_total", None)
                if isinstance(raw_lg_total, int) and raw_lg_total > 0:
                    sources_total = raw_lg_total

                raw_lg_diag = getattr(ing_res, "source_diagnostics", None)
                lg_diag_dict: dict[str, dict[str, Any]] = {}
                if isinstance(raw_lg_diag, Mapping):
                    _merge_source_diagnostics(lg_diag_dict, raw_lg_diag)
                    _merge_source_diagnostics(all_source_diagnostics, raw_lg_diag)

                raw_ing_league_sources = getattr(ing_res, "league_sources", None)
                if isinstance(raw_ing_league_sources, Mapping) and lid.value in raw_ing_league_sources:
                    entry = raw_ing_league_sources[lid.value]
                    if isinstance(entry, Mapping):
                        all_league_sources[lid.value] = copy.deepcopy(dict(entry))
                elif lg_sources or lg_diag_dict:
                    all_league_sources[lid.value] = {
                        "sources_used": lg_sources,
                        "sources_count": len(lg_sources),
                        "sources_total": sources_total,
                        "source_diagnostics": lg_diag_dict,
                    }

                combined_prediction.predictions.extend(pred_res.predictions)
                combined_prediction.team_analyses.extend(pred_res.team_analyses)
                combined_prediction.bundles.extend(pred_res.bundles)

                lg_state.status = "success"
                lg_state.last_sync_at = _utc_now_iso()
                lg_state.teams_count = len(ing_res.teams)
                lg_state.matches_count = len(ing_res.matches)
                lg_state.injuries_count = len(ing_res.injuries)
                lg_state.predictions_count = len(pred_res.predictions)
                lg_state.persisted = lg_persisted
                lg_state.error = None

                league_summaries[lid.value] = lg_state.to_dict()
                logger.info(
                    "Lig tamamlandı (%s): %d maç, %d sakatlık, %d tahmin.",
                    lid.value,
                    lg_state.matches_count,
                    lg_state.injuries_count,
                    lg_state.predictions_count,
                )
            except Exception as exc:
                err_msg = f"{type(exc).__name__}: {exc}"
                logger.exception("Lig döngüsünde hata oluştu (%s): %s", lid.value, err_msg)
                errors[lid.value] = err_msg
                lg_state.status = "error"
                lg_state.last_sync_at = _utc_now_iso()
                lg_state.error = err_msg
                league_summaries[lid.value] = lg_state.to_dict()
    finally:
        if owns_ingestion:
            pipeline.close()

        finished_at = _utc_now_iso()
        combined_ingestion.persisted = any_persisted
        combined_prediction.persisted = any_persisted

        if all_team_metrics:
            _try_assign_ingestion_attr(combined_ingestion, "team_metrics", all_team_metrics)
        if all_sources_used:
            _try_assign_ingestion_attr(combined_ingestion, "sources_used", all_sources_used)
        _try_assign_ingestion_attr(combined_ingestion, "sources_total", sources_total)
        if all_source_diagnostics:
            _try_assign_ingestion_attr(
                combined_ingestion, "source_diagnostics", all_source_diagnostics
            )
        if all_league_sources:
            _try_assign_ingestion_attr(combined_ingestion, "league_sources", all_league_sources)

        if not errors:
            final_status = "success"
        elif len(errors) < len(target_leagues):
            final_status = "partial_error"
        else:
            final_status = "error"

        matches_count = len(combined_ingestion.matches)
        injuries_count = len(combined_ingestion.injuries)
        predictions_count = len(combined_prediction.predictions)
        analyses_count = len(combined_prediction.team_analyses)

        tracker.is_running = False
        tracker.last_status = final_status
        tracker.last_run_finished_at = finished_at
        tracker.last_error = "; ".join(f"{k}: {v}" for k, v in errors.items()) or None
        tracker.total_runs += 1
        tracker.last_matches_count = matches_count
        tracker.last_injuries_count = injuries_count
        tracker.last_predictions_count = predictions_count
        tracker.total_matches_processed += matches_count
        tracker.total_injuries_processed += injuries_count
        tracker.total_predictions_generated += predictions_count

    return CycleResult(
        status=final_status,
        started_at=started_at,
        finished_at=finished_at,
        persisted=any_persisted,
        matches_count=matches_count,
        injuries_count=injuries_count,
        predictions_count=predictions_count,
        team_analyses_count=analyses_count,
        leagues=league_summaries,
        errors=errors,
        ingestion=combined_ingestion,
        prediction=combined_prediction,
        sources_used=all_sources_used,
        sources_total=sources_total,
        source_diagnostics=all_source_diagnostics,
        league_sources=all_league_sources,
        team_metrics=all_team_metrics,
    )
