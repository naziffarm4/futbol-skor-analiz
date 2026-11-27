"""4 ligin canlı bülten JSON ağacını üreten ve bellek + disk önbelleğini yöneten modül."""

from __future__ import annotations

import copy
import json
import logging
import os
import tempfile
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from engine.config import DEFAULT_SEASON, LEAGUES, PROJECT_ROOT, LeagueId
from engine.models.schemas import Injury, League, Match, MatchStatus, Team
from engine.predictors.poisson import predict_score_distribution
from engine.predictors.service import MatchPredictionBundle, select_next_round
from engine.runner import CycleResult

logger = logging.getLogger(__name__)

BULLETIN_CACHE_PATH: Path = PROJECT_ROOT / "engine" / "data" / "bulletin_cache.json"

# shortcut: Bellek önbelleği tek süreç içinde tutulur, çoklu worker/konteyner gerekirse Redis/Supabase kullan.
_memory_cache: dict[str, Any] | None = None


def clear_bulletin_memory_cache() -> None:
    """Test izolasyonu veya manuel sıfırlama için bellek içi önbelleği temizler."""
    global _memory_cache
    _memory_cache = None


def _collect_existing_ids(
    leagues_payload: list[dict[str, Any]],
) -> tuple[set[int], set[int], set[int]]:
    used_teams: set[int] = set()
    used_matches: set[int] = set()
    used_injuries: set[int] = set()

    for lg in leagues_payload:
        for match in lg.get("matches", ()):
            mid = match.get("id")
            if isinstance(mid, int) and mid > 0:
                used_matches.add(mid)
            for side in ("home_team", "away_team"):
                team_obj = match.get(side)
                if isinstance(team_obj, dict):
                    tid = team_obj.get("id")
                    if isinstance(tid, int) and tid > 0:
                        used_teams.add(tid)
        for inj in lg.get("injuries", ()):
            iid = inj.get("id")
            if isinstance(iid, int) and iid > 0:
                used_injuries.add(iid)
            tid = inj.get("team_id")
            if isinstance(tid, int) and tid > 0:
                used_teams.add(tid)

    return used_teams, used_matches, used_injuries


def _alloc_unique_id(preferred: int | None, used: set[int], cursor: list[int]) -> int:
    if preferred is not None and preferred > 0 and preferred not in used:
        used.add(preferred)
        return preferred
    while cursor[0] in used:
        cursor[0] += 1
    allocated = cursor[0]
    used.add(allocated)
    cursor[0] += 1
    return allocated


DEFAULT_SOURCES_TOTAL = 5


def _normalize_sources_list(raw: Any) -> list[str]:
    if isinstance(raw, (list, tuple, set)):
        cleaned = [str(item).strip() for item in raw if str(item).strip()]
        if cleaned:
            return list(dict.fromkeys(cleaned))
    return []


def _format_data_source_label(sources_used: list[str]) -> str:
    if len(sources_used) > 1:
        return f"{len(sources_used)} Kaynak Füzyonu ({', '.join(sources_used)})"
    return sources_used[0] if sources_used else "Transfermarkt"


def _rating_to_strength(rating: float) -> float:
    clamped = min(96.0, max(8.0, float(rating)))
    curved = 0.65 * clamped / (100.0 - clamped)
    return float(curved ** (1.0 / 1.35))


def _ensure_league_predictions_upgraded(lg_dict: dict[str, Any]) -> None:
    """Önceki önbellekten korunan liglerde 9'lu İY/MS ve olasılık alanları eksikse tamamlar."""
    matches = lg_dict.get("matches")
    if not isinstance(matches, list):
        return
    for match in matches:
        if not isinstance(match, dict):
            continue
        pred = match.get("prediction")
        if not isinstance(pred, dict):
            continue
        all_ht_ft = pred.get("all_ht_ft_json")
        if isinstance(all_ht_ft, list) and len(all_ht_ft) == 9 and "p_home" in pred:
            continue
        ta = match.get("team_analysis")
        ta_map = ta if isinstance(ta, Mapping) else {}
        h_att = _rating_to_strength(float(ta_map.get("home_offense_rating", 60.0)))
        h_def = 1.0 / max(0.35, _rating_to_strength(float(ta_map.get("home_defense_rating", 60.0))))
        a_att = _rating_to_strength(float(ta_map.get("away_offense_rating", 58.0)))
        a_def = 1.0 / max(0.35, _rating_to_strength(float(ta_map.get("away_defense_rating", 58.0))))
        p_res = predict_score_distribution(
            home_attack=h_att,
            away_defense=a_def,
            away_attack=a_att,
            home_defense=h_def,
        )
        pred["all_ht_ft_json"] = [
            {"code": h.code, "label": h.label, "prob": float(h.prob)} for h in p_res.all_ht_ft
        ]
        if not pred.get("top_ht_ft_json"):
            pred["top_ht_ft_json"] = pred["all_ht_ft_json"][:3]
        pred.setdefault("p_home", float(p_res.home_win_prob))
        pred.setdefault("p_draw", float(p_res.draw_prob))
        pred.setdefault("p_away", float(p_res.away_win_prob))
        pred.setdefault("p_over25", float(p_res.over_25_prob))
        pred.setdefault("p_under25", float(p_res.under_25_prob))
        pred.setdefault("p_btts_yes", float(p_res.btts_yes_prob))
        pred.setdefault("p_btts_no", float(p_res.btts_no_prob))
        pred.setdefault("market_blended", False)
        pred.setdefault("market_blend_weight", 0.0)


def _build_leagues_meta(leagues_payload: list[dict[str, Any]]) -> list[dict[str, Any]]:
    meta_rows: list[dict[str, Any]] = []
    for lg in leagues_payload:
        if not (isinstance(lg, dict) and {"id", "name", "country", "season"} <= lg.keys()):
            continue
        lg_sources = _normalize_sources_list(lg.get("sources_used")) or ["Transfermarkt"]
        lg_total = int(lg.get("sources_total") or DEFAULT_SOURCES_TOTAL)
        lg_diag = (
            copy.deepcopy(dict(lg["source_diagnostics"]))
            if isinstance(lg.get("source_diagnostics"), Mapping)
            else {}
        )
        meta_rows.append(
            {
                "id": lg["id"],
                "name": lg["name"],
                "country": lg["country"],
                "season": lg["season"],
                "next_round": lg.get("next_round"),
                "played_matches_count": int(lg.get("played_matches_count", 0)),
                "matches_count": int(lg.get("matches_count", 0)),
                "injuries_count": int(lg.get("injuries_count", 0)),
                "sources_used": lg_sources,
                "sources_count": len(lg_sources),
                "sources_total": lg_total,
                "source_diagnostics": lg_diag,
            }
        )
    return meta_rows


def build_bulletin_payload(
    cycle: CycleResult,
    *,
    existing_bulletin: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """CycleResult çıktısını tüm liglerde benzersiz ID garantili bülten sözlüğüne dönüştürür."""
    ingested_leagues: dict[LeagueId, League] = {lg.id: lg for lg in cycle.ingestion.leagues}

    teams_by_league: dict[LeagueId, list[Team]] = {lid: [] for lid in LEAGUES}
    team_league_by_id: dict[int, LeagueId] = {}
    for team in cycle.ingestion.teams:
        teams_by_league[team.league_id].append(team)
        if team.id is not None:
            team_league_by_id[team.id] = team.league_id

    injuries_by_league: dict[LeagueId, list[Injury]] = {lid: [] for lid in LEAGUES}
    for inj in cycle.ingestion.injuries:
        lid = team_league_by_id.get(inj.team_id)
        if lid is not None:
            injuries_by_league[lid].append(inj)

    bundles_by_league: dict[LeagueId, list[MatchPredictionBundle]] = {lid: [] for lid in LEAGUES}
    for bundle in cycle.prediction.bundles:
        bundles_by_league[bundle.match.league_id].append(bundle)

    finished_by_league: dict[LeagueId, list[Match]] = {lid: [] for lid in LEAGUES}
    for match in cycle.ingestion.matches:
        if match.status == MatchStatus.FINISHED:
            finished_by_league[match.league_id].append(match)

    existing_by_id: dict[str, dict[str, Any]] = {}
    if isinstance(existing_bulletin, dict) and isinstance(existing_bulletin.get("leagues"), list):
        for lg_dict in existing_bulletin["leagues"]:
            if isinstance(lg_dict, dict) and isinstance(lg_dict.get("id"), str):
                existing_by_id[lg_dict["id"]] = lg_dict

    def _should_preserve_league(lid: LeagueId) -> bool:
        existing_lg = existing_by_id.get(lid.value)
        if existing_lg is None:
            return False
        if lid not in ingested_leagues or lid.value in cycle.errors:
            return True
        lg_summary = cycle.leagues.get(lid.value)
        if isinstance(lg_summary, dict) and lg_summary.get("status") == "error":
            return True
        return not bundles_by_league[lid] and int(existing_lg.get("matches_count", 0)) > 0

    preserved_leagues: dict[str, dict[str, Any]] = {
        lid.value: copy.deepcopy(existing_by_id[lid.value])
        for lid in LEAGUES
        if _should_preserve_league(lid)
    }

    raw_ing_sources = _normalize_sources_list(
        getattr(cycle.ingestion, "sources_used", None) or getattr(cycle, "sources_used", None)
    )
    raw_sources_total = (
        getattr(cycle.ingestion, "sources_total", None)
        or getattr(cycle, "sources_total", None)
        or DEFAULT_SOURCES_TOTAL
    )
    sources_total = (
        int(raw_sources_total)
        if isinstance(raw_sources_total, int) and raw_sources_total > 0
        else DEFAULT_SOURCES_TOTAL
    )
    raw_diag = getattr(cycle.ingestion, "source_diagnostics", None) or getattr(
        cycle, "source_diagnostics", None
    )
    root_source_diagnostics: dict[str, Any] = (
        copy.deepcopy(dict(raw_diag)) if isinstance(raw_diag, Mapping) else {}
    )
    raw_league_sources = getattr(cycle.ingestion, "league_sources", None) or getattr(
        cycle, "league_sources", None
    )
    league_sources_map: dict[str, Any] = (
        dict(raw_league_sources) if isinstance(raw_league_sources, Mapping) else {}
    )

    used_team_ids, used_match_ids, used_injury_ids = _collect_existing_ids(
        list(preserved_leagues.values())
    )
    team_cursor = [1]
    match_cursor = [1]
    injury_cursor = [1]

    leagues_out: list[dict[str, Any]] = []

    for lid in LEAGUES:
        if lid.value in preserved_leagues:
            preserved_lg = preserved_leagues[lid.value]
            preserved_lg["played_matches_count"] = int(
                preserved_lg.get("played_matches_count", 0)
            )
            pres_sources = _normalize_sources_list(preserved_lg.get("sources_used")) or (
                list(raw_ing_sources) if raw_ing_sources else ["Transfermarkt"]
            )
            preserved_lg["sources_used"] = pres_sources
            preserved_lg["sources_count"] = len(pres_sources)
            preserved_lg["sources_total"] = int(
                preserved_lg.get("sources_total") or sources_total
            )
            preserved_lg["source_diagnostics"] = (
                copy.deepcopy(dict(preserved_lg["source_diagnostics"]))
                if isinstance(preserved_lg.get("source_diagnostics"), Mapping)
                else {}
            )
            _ensure_league_predictions_upgraded(preserved_lg)
            leagues_out.append(preserved_lg)
            continue
        if lid not in ingested_leagues:
            continue

        lg_model = ingested_leagues[lid]
        team_id_remap: dict[int, int] = {}
        team_dicts_by_raw_id: dict[int, dict[str, Any]] = {}

        for team in teams_by_league[lid]:
            preferred_tid = team.id if (cycle.persisted or not preserved_leagues) else None
            resolved_tid = _alloc_unique_id(preferred_tid, used_team_ids, team_cursor)
            if team.id is not None:
                team_id_remap[team.id] = resolved_tid
            team_dict = {
                "id": resolved_tid,
                "league_id": lid.value,
                "name": team.name,
                "short_name": team.short_name or team.name,
                "logo_url": team.logo_url,
            }
            if team.id is not None:
                team_dicts_by_raw_id[team.id] = team_dict

        league_injuries: list[dict[str, Any]] = []
        injuries_by_resolved_team: dict[int, list[dict[str, Any]]] = {}

        for inj in injuries_by_league[lid]:
            resolved_iid = _alloc_unique_id(inj.id, used_injury_ids, injury_cursor)
            resolved_tid = team_id_remap.get(inj.team_id, inj.team_id)
            return_date_val = (
                inj.return_date.isoformat()
                if isinstance(inj.return_date, date)
                else inj.return_date
            )
            inj_sources = _normalize_sources_list(getattr(inj, "sources", None)) or [
                "Transfermarkt"
            ]
            inj_dict = {
                "id": resolved_iid,
                "team_id": resolved_tid,
                "player_name": inj.player_name,
                "position": inj.position.value,
                "reason": inj.reason,
                "return_date": return_date_val,
                "impact_level": inj.impact_level.value,
                "verified_by_multiple_sources": bool(
                    getattr(inj, "verified_by_multiple_sources", False)
                ),
                "sources": inj_sources,
            }
            league_injuries.append(inj_dict)
            injuries_by_resolved_team.setdefault(resolved_tid, []).append(inj_dict)

        lg_bundles = bundles_by_league[lid]
        if lg_bundles:
            target_round = select_next_round(
                finished_by_league[lid],
                [b.match for b in lg_bundles],
            )
            lg_bundles = [b for b in lg_bundles if b.match.round == target_round]
            lg_bundles.sort(
                key=lambda b: (b.match.match_date, b.match.home_team_id, b.match.away_team_id)
            )
        else:
            target_round = None

        league_matches: list[dict[str, Any]] = []
        for bundle in lg_bundles:
            m = bundle.match
            pred = bundle.prediction
            ta = bundle.team_analysis

            if m.id is not None:
                preferred_mid: int | None = m.id
            elif cycle.persisted and pred.match_id > 0:
                preferred_mid = pred.match_id
            else:
                preferred_mid = None

            resolved_mid = _alloc_unique_id(preferred_mid, used_match_ids, match_cursor)

            home_team_dict = team_dicts_by_raw_id.get(m.home_team_id) or {
                "id": team_id_remap.get(m.home_team_id, m.home_team_id),
                "league_id": lid.value,
                "name": f"Takım #{m.home_team_id}",
                "short_name": f"Takım #{m.home_team_id}",
                "logo_url": None,
            }
            away_team_dict = team_dicts_by_raw_id.get(m.away_team_id) or {
                "id": team_id_remap.get(m.away_team_id, m.away_team_id),
                "league_id": lid.value,
                "name": f"Takım #{m.away_team_id}",
                "short_name": f"Takım #{m.away_team_id}",
                "logo_url": None,
            }

            home_tid = int(home_team_dict["id"])
            away_tid = int(away_team_dict["id"])

            league_matches.append(
                {
                    "id": resolved_mid,
                    "league_id": lid.value,
                    "round": int(m.round),
                    "match_date": (
                        m.match_date.isoformat()
                        if isinstance(m.match_date, date)
                        else m.match_date
                    ),
                    "status": m.status.value,
                    "home_team": home_team_dict,
                    "away_team": away_team_dict,
                    "prediction": {
                        "id": pred.id if pred.id is not None else resolved_mid,
                        "match_id": resolved_mid,
                        "predicted_home_score": int(pred.predicted_home_score),
                        "predicted_away_score": int(pred.predicted_away_score),
                        "predicted_ht_home_score": int(pred.predicted_ht_home_score),
                        "predicted_ht_away_score": int(pred.predicted_ht_away_score),
                        "ht_ft_prediction": str(pred.ht_ft_prediction),
                        "top_ht_ft_json": [
                            {"code": h.code, "label": h.label, "prob": float(h.prob)}
                            for h in pred.top_ht_ft_json
                        ],
                        "all_ht_ft_json": [
                            {"code": h.code, "label": h.label, "prob": float(h.prob)}
                            for h in pred.all_ht_ft_json
                        ],
                        "confidence_rate": float(pred.confidence_rate),
                        "top_scores_json": [
                            {"score": sp.score, "prob": float(sp.prob)}
                            for sp in pred.top_scores_json
                        ],
                        "p_home": float(pred.p_home),
                        "p_draw": float(pred.p_draw),
                        "p_away": float(pred.p_away),
                        "p_over25": float(pred.p_over25),
                        "p_under25": float(pred.p_under25),
                        "p_btts_yes": float(pred.p_btts_yes),
                        "p_btts_no": float(pred.p_btts_no),
                        "market_blended": bool(pred.market_blended),
                        "market_blend_weight": float(pred.market_blend_weight),
                    },
                    "team_analysis": {
                        "id": ta.id if ta.id is not None else resolved_mid,
                        "match_id": resolved_mid,
                        "match_overview_text": ta.match_overview_text,
                        "home_analysis_text": ta.home_analysis_text,
                        "away_analysis_text": ta.away_analysis_text,
                        "ht_ft_reasoning_text": str(ta.ht_ft_reasoning_text),
                        "home_offense_rating": float(ta.home_offense_rating),
                        "home_defense_rating": float(ta.home_defense_rating),
                        "away_offense_rating": float(ta.away_offense_rating),
                        "away_defense_rating": float(ta.away_defense_rating),
                    },
                    "home_injuries": list(injuries_by_resolved_team.get(home_tid, ())),
                    "away_injuries": list(injuries_by_resolved_team.get(away_tid, ())),
                }
            )

        raw_lg_entry = league_sources_map.get(lid.value) or league_sources_map.get(lid) or {}
        if isinstance(raw_lg_entry, Mapping):
            lg_sources = _normalize_sources_list(raw_lg_entry.get("sources_used"))
            lg_total = int(raw_lg_entry.get("sources_total") or sources_total)
            lg_diag = (
                copy.deepcopy(dict(raw_lg_entry["source_diagnostics"]))
                if isinstance(raw_lg_entry.get("source_diagnostics"), Mapping)
                else copy.deepcopy(root_source_diagnostics)
            )
        else:
            lg_sources = []
            lg_total = sources_total
            lg_diag = copy.deepcopy(root_source_diagnostics)

        if not lg_sources:
            lg_sources = list(raw_ing_sources) if raw_ing_sources else ["Transfermarkt"]

        leagues_out.append(
            {
                "id": lid.value,
                "name": lg_model.name,
                "country": lg_model.country,
                "season": lg_model.season,
                "next_round": int(target_round) if target_round is not None else None,
                "played_matches_count": len(finished_by_league[lid]),
                "matches_count": len(league_matches),
                "injuries_count": len(league_injuries),
                "sources_used": lg_sources,
                "sources_count": len(lg_sources),
                "sources_total": lg_total,
                "source_diagnostics": lg_diag,
                "matches": league_matches,
                "injuries": league_injuries,
            }
        )

    merged_sources: list[str] = list(raw_ing_sources)
    for lg in leagues_out:
        for s in _normalize_sources_list(lg.get("sources_used")):
            if s not in merged_sources:
                merged_sources.append(s)
    sources_used = merged_sources or ["Transfermarkt"]

    total_matches = sum(int(lg["matches_count"]) for lg in leagues_out)
    total_injuries = sum(int(lg["injuries_count"]) for lg in leagues_out)
    total_played_matches = sum(int(lg.get("played_matches_count", 0)) for lg in leagues_out)
    season = str(leagues_out[0]["season"]) if leagues_out else DEFAULT_SEASON

    return {
        "data_source": _format_data_source_label(sources_used),
        "sources_used": sources_used,
        "sources_count": len(sources_used),
        "sources_total": sources_total,
        "source_diagnostics": root_source_diagnostics,
        "generated_at": datetime.now(UTC).isoformat(),
        "season": season,
        "total_matches": total_matches,
        "total_injuries": total_injuries,
        "total_played_matches": total_played_matches,
        "leagues_meta": _build_leagues_meta(leagues_out),
        "leagues": leagues_out,
    }


def save_bulletin_to_disk(
    bulletin: dict[str, Any],
    *,
    cache_path: Path | None = None,
) -> Path:
    """Bülten sözlüğünü UTF-8 olarak geçici dosyaya yazıp atomik olarak hedef yola taşır."""
    global _memory_cache
    target = cache_path if cache_path is not None else BULLETIN_CACHE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.stem}_",
        suffix=".tmp",
        dir=str(target.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(bulletin, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, target)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise

    if target == BULLETIN_CACHE_PATH:
        _memory_cache = bulletin
    return target


def load_bulletin_from_disk(*, cache_path: Path | None = None) -> dict[str, Any] | None:
    """Diskteki önbellek dosyasını okur, geçerliyse bellek önbelleğine yükleyip döndürür."""
    global _memory_cache
    target = cache_path if cache_path is not None else BULLETIN_CACHE_PATH
    if not target.is_file():
        return None
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Bülten önbellek dosyası okunamadı (%s): %s", target, exc)
        return None

    if not isinstance(raw, dict) or not isinstance(raw.get("leagues"), list):
        logger.warning("Bülten önbellek şeması geçersiz (%s).", target)
        return None

    if int(raw.get("total_matches", 0)) <= 0:
        return None

    raw_sources = _normalize_sources_list(raw.get("sources_used")) or ["Transfermarkt"]
    raw["sources_used"] = raw_sources
    raw["sources_count"] = int(raw.get("sources_count") or len(raw_sources))
    raw["sources_total"] = int(raw.get("sources_total") or DEFAULT_SOURCES_TOTAL)
    if not isinstance(raw.get("source_diagnostics"), dict):
        raw["source_diagnostics"] = {}
    if not raw.get("data_source"):
        raw["data_source"] = _format_data_source_label(raw_sources)
    for lg in raw["leagues"]:
        if isinstance(lg, dict):
            _ensure_league_predictions_upgraded(lg)
            if "played_matches_count" not in lg:
                lg["played_matches_count"] = 0
            lg_sources = _normalize_sources_list(lg.get("sources_used")) or list(raw_sources)
            lg["sources_used"] = lg_sources
            lg["sources_count"] = int(lg.get("sources_count") or len(lg_sources))
            lg["sources_total"] = int(lg.get("sources_total") or raw["sources_total"])
            if not isinstance(lg.get("source_diagnostics"), dict):
                lg["source_diagnostics"] = copy.deepcopy(raw["source_diagnostics"])
    if "total_played_matches" not in raw:
        raw["total_played_matches"] = sum(
            int(lg.get("played_matches_count", 0))
            for lg in raw["leagues"]
            if isinstance(lg, dict)
        )
    if not isinstance(raw.get("leagues_meta"), list):
        raw["leagues_meta"] = _build_leagues_meta(raw["leagues"])

    if target == BULLETIN_CACHE_PATH:
        _memory_cache = raw
    return raw


def get_cached_bulletin(*, cache_path: Path | None = None) -> dict[str, Any] | None:
    """Önce bellek önbelleğine bakar, yoksa diskten yükler."""
    target = cache_path if cache_path is not None else BULLETIN_CACHE_PATH
    if target == BULLETIN_CACHE_PATH and _memory_cache is not None:
        return _memory_cache
    return load_bulletin_from_disk(cache_path=target)


def update_bulletin_cache(
    cycle: CycleResult,
    *,
    cache_path: Path | None = None,
) -> dict[str, Any]:
    """CycleResult çıktısını mevcut önbellekle birleştirip hem diske hem belleğe yazar."""
    target = cache_path if cache_path is not None else BULLETIN_CACHE_PATH
    existing = get_cached_bulletin(cache_path=target)
    bulletin = build_bulletin_payload(cycle, existing_bulletin=existing)
    if bulletin.get("total_matches", 0) > 0:
        save_bulletin_to_disk(bulletin, cache_path=target)
    return bulletin


def export_bulletin_file(cycle: CycleResult, output_path: Path) -> dict[str, Any]:
    """CycleResult çıktısını önceki bültenle birleştirip hedef JSON dosyasına atomik yazar."""
    target = Path(output_path)
    existing = load_bulletin_from_disk(cache_path=target)
    if existing is None and target.resolve() != BULLETIN_CACHE_PATH.resolve():
        existing = load_bulletin_from_disk(cache_path=BULLETIN_CACHE_PATH)
    bulletin = build_bulletin_payload(cycle, existing_bulletin=existing)
    if int(bulletin.get("total_matches", 0)) > 0:
        save_bulletin_to_disk(bulletin, cache_path=target)
    return bulletin
