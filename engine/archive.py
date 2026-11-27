"""Zaman damgalı kompakt bülten, piyasa oranı ve kota anlık görüntüsü (snapshot) arşivleyici."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from engine.config import PROJECT_ROOT
from engine.scrapers.sources.api_football import QuotaBudgetTracker

DEFAULT_SNAPSHOTS_DIR = PROJECT_ROOT / "data" / "snapshots"


def _coerce_mapping(bulletin_or_cycle: Mapping[str, Any] | Any) -> dict[str, Any]:
    if isinstance(bulletin_or_cycle, Mapping):
        return dict(bulletin_or_cycle)
    to_dict_fn = getattr(bulletin_or_cycle, "to_dict", None)
    if callable(to_dict_fn):
        converted = to_dict_fn()
        if isinstance(converted, Mapping):
            return dict(converted)
    raw_vars = getattr(bulletin_or_cycle, "__dict__", None)
    if isinstance(raw_vars, Mapping):
        return dict(raw_vars)
    return {}


def _extract_compact_match(match_item: Mapping[str, Any]) -> dict[str, Any]:
    pred = match_item.get("prediction")
    pred_map = pred if isinstance(pred, Mapping) else {}
    entry: dict[str, Any] = {
        "match_id": match_item.get("id") or match_item.get("match_id"),
        "round": match_item.get("round"),
        "match_date": match_item.get("match_date"),
        "home_team": match_item.get("home_team") or match_item.get("home_team_name") or match_item.get("home_team_id"),
        "away_team": match_item.get("away_team") or match_item.get("away_team_name") or match_item.get("away_team_id"),
        "status": match_item.get("status"),
    }
    prob_keys = (
        "p_home",
        "p_draw",
        "p_away",
        "p_over25",
        "p_under25",
        "p_btts_yes",
        "p_btts_no",
        "ht_ft_prediction",
        "all_ht_ft_json",
        "top_ht_ft_json",
        "market_blended",
        "market_blend_weight",
        "confidence_rate",
        "prob_home",
        "prob_draw",
        "prob_away",
        "prob_over_25",
        "prob_under_25",
        "prob_btts_yes",
        "top_ht_ft",
        "confidence_score",
    )
    probs: dict[str, Any] = {}
    for pk in prob_keys:
        val = pred_map.get(pk) if pk in pred_map else match_item.get(pk)
        if val is not None:
            probs[pk] = val
    if probs:
        entry["probabilities"] = probs
    if "market_odds" in match_item and isinstance(match_item["market_odds"], Mapping):
        entry["market_odds"] = dict(match_item["market_odds"])
    return entry


def save_snapshot(
    bulletin_or_cycle: Mapping[str, Any] | Any,
    *,
    snapshots_dir: Path | None = None,
    market_odds: Mapping[Any, Any] | None = None,
    tracker: QuotaBudgetTracker | None = None,
    now_utc: datetime | None = None,
) -> Path:
    """Bülten veya döngü çıktısını `data/snapshots/snapshot_<YYYYMMDDTHHMMSSZ>.json` olarak kaydeder."""
    target_dir = snapshots_dir or DEFAULT_SNAPSHOTS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    dt = now_utc or datetime.now(UTC)
    stamp = dt.strftime("%Y%m%dT%H%M%SZ")
    out_path = target_dir / f"snapshot_{stamp}.json"
    suffix_idx = 1
    while out_path.exists():
        out_path = target_dir / f"snapshot_{stamp}_{suffix_idx}.json"
        suffix_idx += 1

    data = _coerce_mapping(bulletin_or_cycle)
    generated_at = str(data.get("generated_at") or dt.isoformat())

    raw_sources = data.get("sources_used")
    sources_used = [str(s) for s in raw_sources if s] if isinstance(raw_sources, list) else []

    resolved_odds: Mapping[Any, Any] | None = market_odds
    if resolved_odds is None:
        attr_odds = getattr(bulletin_or_cycle, "market_odds", None)
        if isinstance(attr_odds, Mapping):
            resolved_odds = attr_odds
        elif isinstance(data.get("market_odds"), Mapping):
            resolved_odds = data["market_odds"]

    leagues_raw = data.get("leagues")
    league_snapshots: list[dict[str, Any]] = []
    injuries_by_league: dict[str, int] = {}
    embedded_odds_count = 0

    if isinstance(leagues_raw, list):
        for lg in leagues_raw:
            if not isinstance(lg, Mapping):
                continue
            lid = str(lg.get("id") or lg.get("league_id") or "unknown")
            lg_matches_raw = lg.get("matches")
            compact_matches: list[dict[str, Any]] = []
            if isinstance(lg_matches_raw, list):
                for m in lg_matches_raw:
                    if isinstance(m, Mapping):
                        cm = _extract_compact_match(m)
                        if "market_odds" in cm:
                            embedded_odds_count += 1
                        compact_matches.append(cm)

            lg_inj_count = lg.get("injuries_count")
            if lg_inj_count is None and isinstance(lg.get("injuries"), list):
                lg_inj_count = len(lg["injuries"])
            inj_int = int(lg_inj_count or 0)
            injuries_by_league[lid] = inj_int

            league_snapshots.append(
                {
                    "id": lid,
                    "name": lg.get("name"),
                    "next_round": lg.get("next_round"),
                    "matches_count": len(compact_matches),
                    "injuries_count": inj_int,
                    "matches": compact_matches,
                }
            )

    top_injuries = data.get("injuries")
    raw_total_inj = data.get("total_injuries")
    if isinstance(raw_total_inj, (int, float, str)):
        total_injuries = int(raw_total_inj)
    elif isinstance(top_injuries, list):
        total_injuries = len(top_injuries)
    else:
        total_injuries = sum(injuries_by_league.values())

    odds_count = len(resolved_odds) if resolved_odds is not None else embedded_odds_count
    budget_tracker = tracker or QuotaBudgetTracker()

    snapshot_payload: dict[str, Any] = {
        "generated_at": generated_at,
        "sources_used": sources_used,
        "quota_status": budget_tracker.snapshot(now_utc=dt),
        "market_odds_count": odds_count,
        "injuries_summary": {
            "total_injuries": total_injuries,
            "by_league": injuries_by_league,
        },
        "leagues": league_snapshots,
    }

    if resolved_odds:
        snapshot_payload["market_odds"] = {
            (f"{k[0]}:{k[1]}" if isinstance(k, tuple) and len(k) == 2 else str(k)): dict(v)
            if isinstance(v, Mapping)
            else v
            for k, v in resolved_odds.items()
        }

    out_path.write_text(
        json.dumps(snapshot_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return out_path
