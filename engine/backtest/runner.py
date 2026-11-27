"""Gelecek sızıntısız (zero-leakage) walk-forward backtest yürütücüsü ve CSV okuyucusu."""

from __future__ import annotations

import csv
import io
import logging
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx

from engine.backtest.metrics import (
    CalibrationBucket,
    MatchEvaluationRecord,
    ModelSummaryMetrics,
    compute_calibration_buckets,
    extract_market_1x2_probs,
    extract_market_over25_prob,
    summarize_records,
)
from engine.config import LeagueId
from engine.models.schemas import Match, MatchStatus
from engine.predictors.poisson import (
    DEFAULT_DIXON_COLES_RHO,
    DEFAULT_MAX_GOALS,
    MAX_EXPECTED_GOALS,
    MIN_EXPECTED_GOALS,
    build_score_matrix,
    predict_score_distribution,
)
from engine.predictors.ratings import build_team_ratings, calculate_league_baseline
from engine.scrapers.base import build_browser_headers

logger = logging.getLogger(__name__)

LEAGUE_CODE_MAP: dict[str, tuple[LeagueId, str]] = {
    "T1": (LeagueId.SUPER_LIG, "Süper Lig"),
    "E0": (LeagueId.PREMIER_LEAGUE, "Premier League"),
    "SP1": (LeagueId.LA_LIGA, "La Liga"),
    "F1": (LeagueId.LIGUE_1, "Ligue 1"),
}

MODEL_POST_FIX = "Post-Fix (Yeni Ölçek, max=10)"
MODEL_PRE_FIX = "Pre-Fix (Eski Ölçek, max=5)"
MODEL_BASELINE = "Lig Ortalaması Sabit Baz"
MODEL_MARKET = "Piyasa (De-vigged Kapanış)"

MODEL_ORDER: tuple[str, ...] = (
    MODEL_POST_FIX,
    MODEL_PRE_FIX,
    MODEL_BASELINE,
    MODEL_MARKET,
)


@dataclass(slots=True)
class HistoricalCsvMatch:
    """Kronolojik walk-forward değerlendirme için ayrıştırılmış CSV maç satırı."""

    league_code: str
    league_id: LeagueId
    season_code: str
    kickoff: datetime
    match_day: date
    home_team: str
    away_team: str
    fthg: int
    ftag: int
    hthg: int | None = None
    htag: int | None = None
    hs: float | None = None
    as_: float | None = None
    hst: float | None = None
    ast: float | None = None
    market_1x2: tuple[float, float, float] | None = None
    market_1x2_source: str | None = None
    market_over25: float | None = None
    market_over25_source: str | None = None


@dataclass(slots=True)
class WalkForwardResult:
    """Walk-forward çalıştırmasının tüm lig ve model bazlı metrik ve kalibrasyon sonuçları."""

    warmup_matches: int
    total_parsed_matches: int
    evaluated_matches: int
    market_1x2_matches: int
    market_over25_matches: int
    seasons: list[str]
    leagues: list[str]
    records_by_model: dict[str, list[MatchEvaluationRecord]] = field(default_factory=dict)
    overall_summaries: dict[str, ModelSummaryMetrics] = field(default_factory=dict)
    market_subset_summaries: dict[str, ModelSummaryMetrics] = field(default_factory=dict)
    league_summaries: dict[str, dict[str, ModelSummaryMetrics]] = field(default_factory=dict)
    calibration_1x2: dict[str, list[CalibrationBucket]] = field(default_factory=dict)
    calibration_over25: dict[str, list[CalibrationBucket]] = field(default_factory=dict)
    sources_used: list[str] = field(default_factory=list)


def _opt_int(row: Mapping[str, Any], key: str) -> int | None:
    raw = str(row.get(key) or "").strip()
    if not raw:
        return None
    try:
        return int(float(raw))
    except ValueError:
        return None


def _opt_float(row: Mapping[str, Any], key: str) -> float | None:
    raw = str(row.get(key) or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def parse_csv_kickoff(date_str: str, time_str: str = "") -> datetime | None:
    """Football-Data CSV Date/Time alanlarını UTC datetime nesnesine çevirir."""
    d_clean = date_str.strip()
    if not d_clean:
        return None
    parsed_date: date | None = None
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            parsed_date = datetime.strptime(d_clean, fmt).date()
            break
        except ValueError:
            continue
    if parsed_date is None:
        return None

    hour, minute = 15, 0
    t_clean = time_str.strip()
    if t_clean and ":" in t_clean:
        parts = t_clean.split(":")
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            hour = min(23, max(0, int(parts[0])))
            minute = min(59, max(0, int(parts[1])))
    return datetime(
        parsed_date.year, parsed_date.month, parsed_date.day, hour, minute, tzinfo=UTC
    )


def parse_historical_csv(
    csv_text: str,
    *,
    default_league_code: str = "T1",
    season_code: str = "sample",
) -> list[HistoricalCsvMatch]:
    """Football-Data.co.uk formatındaki CSV metnini kronolojik maç listesine ayrıştırır."""
    cleaned = csv_text.lstrip("﻿").strip()
    if not cleaned:
        return []

    reader = csv.DictReader(io.StringIO(cleaned))
    indexed_rows: list[tuple[datetime, int, HistoricalCsvMatch]] = []
    for idx, row in enumerate(reader):
        if not isinstance(row, dict):
            continue
        div = str(row.get("Div") or default_league_code).strip().upper()
        league_id, _ = LEAGUE_CODE_MAP.get(div, (LeagueId.SUPER_LIG, div))
        home = str(row.get("HomeTeam") or row.get("Home") or "").strip()
        away = str(row.get("AwayTeam") or row.get("Away") or "").strip()
        fthg = _opt_int(row, "FTHG")
        ftag = _opt_int(row, "FTAG")
        if fthg is None:
            fthg = _opt_int(row, "HG")
        if ftag is None:
            ftag = _opt_int(row, "AG")
        kickoff = parse_csv_kickoff(
            str(row.get("Date") or ""),
            str(row.get("Time") or ""),
        )
        if not home or not away or fthg is None or ftag is None or kickoff is None:
            continue

        m_1x2, m_1x2_src = extract_market_1x2_probs(row)
        m_o25, m_o25_src = extract_market_over25_prob(row)

        match_item = HistoricalCsvMatch(
            league_code=div,
            league_id=league_id,
            season_code=season_code,
            kickoff=kickoff,
            match_day=kickoff.date(),
            home_team=home,
            away_team=away,
            fthg=fthg,
            ftag=ftag,
            hthg=_opt_int(row, "HTHG"),
            htag=_opt_int(row, "HTAG"),
            hs=_opt_float(row, "HS"),
            as_=_opt_float(row, "AS"),
            hst=_opt_float(row, "HST"),
            ast=_opt_float(row, "AST"),
            market_1x2=m_1x2,
            market_1x2_source=m_1x2_src,
            market_over25=m_o25,
            market_over25_source=m_o25_src,
        )
        indexed_rows.append((kickoff, idx, match_item))

    indexed_rows.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in indexed_rows]


def _build_prior_team_metrics(
    prior_rows: Sequence[HistoricalCsvMatch],
    team_id_by_name: Mapping[str, int],
) -> dict[int, dict[str, Any]]:
    """Yalnızca geçmiş maçlardan (kickoff < D) şut ve İY/MS gol payı metriklerini toplar."""
    agg: dict[int, dict[str, float]] = {}

    def _slot(tid: int) -> dict[str, float]:
        if tid not in agg:
            agg[tid] = {
                "sot_for": 0.0,
                "sot_against": 0.0,
                "sot_n": 0.0,
                "ht_gf": 0.0,
                "ft_gf": 0.0,
                "ht_ga": 0.0,
                "ft_ga": 0.0,
                "ht_n": 0.0,
            }
        return agg[tid]

    for m in prior_rows:
        h_id = team_id_by_name[m.home_team]
        a_id = team_id_by_name[m.away_team]
        h_s = _slot(h_id)
        a_s = _slot(a_id)

        if m.hst is not None and m.ast is not None:
            h_s["sot_for"] += m.hst
            h_s["sot_against"] += m.ast
            h_s["sot_n"] += 1.0
            a_s["sot_for"] += m.ast
            a_s["sot_against"] += m.hst
            a_s["sot_n"] += 1.0

        if m.hthg is not None and m.htag is not None:
            h_s["ht_gf"] += float(m.hthg)
            h_s["ft_gf"] += float(m.fthg)
            h_s["ht_ga"] += float(m.htag)
            h_s["ft_ga"] += float(m.ftag)
            h_s["ht_n"] += 1.0

            a_s["ht_gf"] += float(m.htag)
            a_s["ft_gf"] += float(m.ftag)
            a_s["ht_ga"] += float(m.hthg)
            a_s["ft_ga"] += float(m.fthg)
            a_s["ht_n"] += 1.0

    metrics: dict[int, dict[str, Any]] = {}
    for tid, vals in agg.items():
        entry: dict[str, Any] = {}
        if vals["sot_n"] > 0:
            entry["sot_for_per_match"] = vals["sot_for"] / vals["sot_n"]
            entry["sot_against_per_match"] = vals["sot_against"] / vals["sot_n"]
        if vals["ht_n"] > 0:
            entry["ht_goals_for"] = int(vals["ht_gf"])
            entry["ft_goals_for_fd"] = int(vals["ft_gf"])
            entry["ht_goals_against"] = int(vals["ht_ga"])
            entry["ft_goals_against_fd"] = int(vals["ft_ga"])
        if entry:
            metrics[tid] = entry
    return metrics


def _legacy_pre_fix_probabilities(
    *,
    home_attack: float,
    away_defense: float,
    away_attack: float,
    home_defense: float,
    home_advantage: float,
    rho: float = DEFAULT_DIXON_COLES_RHO,
) -> tuple[float, float, float, float, float, float]:
    """Düzeltme öncesi (eski ölçek + çift sayılan home_advantage + max_goals=5) model çıktısı."""
    raw_lam = home_attack * away_defense * home_advantage
    raw_mu = away_attack * home_defense
    lam = round(min(MAX_EXPECTED_GOALS, max(MIN_EXPECTED_GOALS, raw_lam)), 4)
    mu = round(min(MAX_EXPECTED_GOALS, max(MIN_EXPECTED_GOALS, raw_mu)), 4)
    matrix = build_score_matrix(lam, mu, max_goals=5, rho=rho)

    p_home = 0.0
    p_draw = 0.0
    p_away = 0.0
    p_over25 = 0.0
    for x, row in enumerate(matrix):
        for y, prob in enumerate(row):
            if x > y:
                p_home += prob
            elif x == y:
                p_draw += prob
            else:
                p_away += prob
            if x + y >= 3:
                p_over25 += prob
    return lam, mu, p_home, p_draw, p_away, p_over25


def run_walk_forward(
    matches: Sequence[HistoricalCsvMatch],
    *,
    warmup_matches: int = 30,
    rho: float = DEFAULT_DIXON_COLES_RHO,
    use_prior_shot_metrics: bool = True,
    sources_used: Sequence[str] = (),
) -> WalkForwardResult:
    """Her (lig, sezon) grubunda kronolojik (match_day < D) walk-forward değerlendirme yapar."""
    grouped: dict[tuple[str, str], list[HistoricalCsvMatch]] = {}
    seasons_seen: list[str] = []
    leagues_seen: list[str] = []

    for m in matches:
        key = (m.league_code, m.season_code)
        grouped.setdefault(key, []).append(m)
        if m.season_code not in seasons_seen:
            seasons_seen.append(m.season_code)
        if m.league_code not in leagues_seen:
            leagues_seen.append(m.league_code)

    records_by_model: dict[str, list[MatchEvaluationRecord]] = {
        name: [] for name in MODEL_ORDER
    }

    for (_, _), season_matches in grouped.items():
        ordered = sorted(season_matches, key=lambda item: item.kickoff)
        all_teams = sorted({m.home_team for m in ordered} | {m.away_team for m in ordered})
        team_id_map = {name: idx + 1 for idx, name in enumerate(all_teams)}
        all_team_ids = set(team_id_map.values())

        # Aynı takvim günündeki maçları birlikte grupla; eğitim kümesi kesinlikle match_day < D!
        days_in_order: list[date] = []
        by_day: dict[date, list[HistoricalCsvMatch]] = {}
        for m in ordered:
            if m.match_day not in by_day:
                days_in_order.append(m.match_day)
                by_day[m.match_day] = []
            by_day[m.match_day].append(m)

        history_csv: list[HistoricalCsvMatch] = []
        history_schema: list[Match] = []
        next_mid = 1

        for current_day in days_in_order:
            todays_matches = by_day[current_day]
            if len(history_csv) >= warmup_matches:
                baseline = calculate_league_baseline(history_schema)
                prior_metrics = (
                    _build_prior_team_metrics(history_csv, team_id_map)
                    if use_prior_shot_metrics
                    else None
                )
                profiles = build_team_ratings(
                    history_schema,
                    injuries=(),
                    team_ids=all_team_ids,
                    team_metrics=prior_metrics,
                    reference_date=current_day,
                )

                const_dist = predict_score_distribution(
                    home_attack=1.0,
                    away_defense=1.0,
                    away_attack=1.0,
                    home_defense=1.0,
                    avg_home_goals=baseline.avg_home_goals,
                    avg_away_goals=baseline.avg_away_goals,
                    max_goals=DEFAULT_MAX_GOALS,
                    rho=rho,
                )

                for tm in todays_matches:
                    hp = profiles[team_id_map[tm.home_team]]
                    ap = profiles[team_id_map[tm.away_team]]
                    depth = min(hp.played, ap.played)
                    d_str = tm.match_day.isoformat()

                    post_res = predict_score_distribution(
                        home_attack=hp.adjusted_home_attack,
                        away_defense=ap.adjusted_away_defense,
                        away_attack=ap.adjusted_away_attack,
                        home_defense=hp.adjusted_home_defense,
                        avg_home_goals=baseline.avg_home_goals,
                        avg_away_goals=baseline.avg_away_goals,
                        sample_matches=depth,
                        max_goals=DEFAULT_MAX_GOALS,
                        rho=rho,
                        home_ht_attack_share=hp.first_half_attack_share,
                        away_ht_concede_share=ap.first_half_concede_share,
                        away_ht_attack_share=ap.first_half_attack_share,
                        home_ht_concede_share=hp.first_half_concede_share,
                    )
                    records_by_model[MODEL_POST_FIX].append(
                        MatchEvaluationRecord(
                            league_code=tm.league_code,
                            season_code=tm.season_code,
                            match_date=d_str,
                            home_team=tm.home_team,
                            away_team=tm.away_team,
                            home_goals=tm.fthg,
                            away_goals=tm.ftag,
                            p_home=post_res.home_win_prob,
                            p_draw=post_res.draw_prob,
                            p_away=post_res.away_win_prob,
                            p_over25=post_res.over_2_5_prob,
                            expected_home_goals=post_res.expected_home_goals,
                            expected_away_goals=post_res.expected_away_goals,
                        )
                    )

                    leg_lam, leg_mu, leg_ph, leg_pd, leg_pa, leg_o25 = (
                        _legacy_pre_fix_probabilities(
                            home_attack=hp.adjusted_home_attack,
                            away_defense=ap.adjusted_away_defense,
                            away_attack=ap.adjusted_away_attack,
                            home_defense=hp.adjusted_home_defense,
                            home_advantage=baseline.home_advantage,
                            rho=rho,
                        )
                    )
                    records_by_model[MODEL_PRE_FIX].append(
                        MatchEvaluationRecord(
                            league_code=tm.league_code,
                            season_code=tm.season_code,
                            match_date=d_str,
                            home_team=tm.home_team,
                            away_team=tm.away_team,
                            home_goals=tm.fthg,
                            away_goals=tm.ftag,
                            p_home=leg_ph,
                            p_draw=leg_pd,
                            p_away=leg_pa,
                            p_over25=leg_o25,
                            expected_home_goals=leg_lam,
                            expected_away_goals=leg_mu,
                        )
                    )

                    records_by_model[MODEL_BASELINE].append(
                        MatchEvaluationRecord(
                            league_code=tm.league_code,
                            season_code=tm.season_code,
                            match_date=d_str,
                            home_team=tm.home_team,
                            away_team=tm.away_team,
                            home_goals=tm.fthg,
                            away_goals=tm.ftag,
                            p_home=const_dist.home_win_prob,
                            p_draw=const_dist.draw_prob,
                            p_away=const_dist.away_win_prob,
                            p_over25=const_dist.over_2_5_prob,
                            expected_home_goals=const_dist.expected_home_goals,
                            expected_away_goals=const_dist.expected_away_goals,
                        )
                    )

                    if tm.market_1x2 is not None:
                        mph, mpd, mpa = tm.market_1x2
                        records_by_model[MODEL_MARKET].append(
                            MatchEvaluationRecord(
                                league_code=tm.league_code,
                                season_code=tm.season_code,
                                match_date=d_str,
                                home_team=tm.home_team,
                                away_team=tm.away_team,
                                home_goals=tm.fthg,
                                away_goals=tm.ftag,
                                p_home=mph,
                                p_draw=mpd,
                                p_away=mpa,
                                p_over25=tm.market_over25,
                            )
                        )

            # Günün maçları değerlendirildikten SONRA geçmiş havuzuna eklenir (sıfır sızıntı)
            for req_idx, tm in enumerate(todays_matches, start=1):
                history_csv.append(tm)
                history_schema.append(
                    Match(
                        id=next_mid,
                        league_id=tm.league_id,
                        home_team_id=team_id_map[tm.home_team],
                        away_team_id=team_id_map[tm.away_team],
                        match_date=tm.kickoff,
                        round=max(1, (len(history_schema) // max(1, len(all_teams) // 2)) + 1),
                        status=MatchStatus.FINISHED,
                        home_score=tm.fthg,
                        away_score=tm.ftag,
                    )
                )
                _ = req_idx
                next_mid += 1

    overall_summaries = {
        name: summarize_records(name, records_by_model[name]) for name in MODEL_ORDER
    }

    market_keys = {
        (r.league_code, r.season_code, r.match_date, r.home_team, r.away_team)
        for r in records_by_model[MODEL_MARKET]
    }
    market_subset_summaries: dict[str, ModelSummaryMetrics] = {}
    for name in MODEL_ORDER:
        filtered = [
            r
            for r in records_by_model[name]
            if (r.league_code, r.season_code, r.match_date, r.home_team, r.away_team)
            in market_keys
        ]
        market_subset_summaries[name] = summarize_records(name, filtered)

    league_summaries: dict[str, dict[str, ModelSummaryMetrics]] = {}
    for lg_code in leagues_seen:
        league_summaries[lg_code] = {
            name: summarize_records(
                name,
                [r for r in records_by_model[name] if r.league_code == lg_code],
            )
            for name in MODEL_ORDER
        }

    calibration_1x2 = {
        name: compute_calibration_buckets(records_by_model[name], target="1x2")
        for name in MODEL_ORDER
    }
    calibration_over25 = {
        name: compute_calibration_buckets(records_by_model[name], target="over25")
        for name in MODEL_ORDER
    }

    eval_count = len(records_by_model[MODEL_POST_FIX])
    m_1x2_count = len(records_by_model[MODEL_MARKET])
    m_o25_count = sum(1 for r in records_by_model[MODEL_MARKET] if r.p_over25 is not None)

    return WalkForwardResult(
        warmup_matches=warmup_matches,
        total_parsed_matches=len(matches),
        evaluated_matches=eval_count,
        market_1x2_matches=m_1x2_count,
        market_over25_matches=m_o25_count,
        seasons=seasons_seen,
        leagues=leagues_seen,
        records_by_model=records_by_model,
        overall_summaries=overall_summaries,
        market_subset_summaries=market_subset_summaries,
        league_summaries=league_summaries,
        calibration_1x2=calibration_1x2,
        calibration_over25=calibration_over25,
        sources_used=list(sources_used),
    )


def fetch_football_data_csv_text(
    season_code: str,
    league_code: str,
    *,
    cache_dir: Path | None = None,
    client: httpx.Client | None = None,
) -> tuple[str, str]:
    """Football-Data CSV dosyasını çeker (İSS SNI engelinde Archive ham yansısına düşer)."""
    resolved_cache = cache_dir or (Path(tempfile.gettempdir()) / "futbol_backtest_csv_cache")
    resolved_cache.mkdir(parents=True, exist_ok=True)
    cache_file = resolved_cache / f"{season_code}_{league_code}.csv"
    if cache_file.exists() and cache_file.stat().st_size > 200:
        return cache_file.read_text(encoding="utf-8"), f"cache:{cache_file.name}"

    primary_url = f"https://www.football-data.co.uk/mmz4281/{season_code}/{league_code}.csv"
    archive_url = (
        f"https://web.archive.org/web/2026id_/"
        f"https://www.football-data.co.uk/mmz4281/{season_code}/{league_code}.csv"
    )

    owns_client = client is None
    http = client or httpx.Client(
        headers=build_browser_headers(
            referer="https://www.football-data.co.uk/",
            accept_language="en-GB,en;q=0.9",
        ),
        follow_redirects=True,
    )
    try:
        for candidate_url, req_timeout in ((primary_url, 4.5), (archive_url, 20.0)):
            try:
                resp = http.get(candidate_url, timeout=req_timeout)
                if resp.status_code == 200 and "HomeTeam" in resp.text:
                    cache_file.write_text(resp.text, encoding="utf-8")
                    return resp.text, candidate_url
            except Exception as exc:
                logger.debug("Backtest CSV aday URL başarısız (%s): %s", candidate_url, exc)
    finally:
        if owns_client:
            http.close()

    raise RuntimeError(f"{season_code}/{league_code}.csv indirilemedi.")
