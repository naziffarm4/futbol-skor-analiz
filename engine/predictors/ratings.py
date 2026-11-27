"""Oynanmış maçlardan takım baz güçlerini ve sakatlık/ceza kaynaklı güç kayıplarını hesaplayan modül."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, cast

from engine.models.schemas import ImpactLevel, Injury, Match, MatchStatus, PlayerPosition

DEFAULT_AVG_HOME_GOALS = 1.45
DEFAULT_AVG_AWAY_GOALS = 1.15
DEFAULT_AVG_SOT = 4.30
DEFAULT_FIRST_HALF_SHARE = 0.43
MIN_FIRST_HALF_SHARE = 0.25
MAX_FIRST_HALF_SHARE = 0.65
GOAL_RATIO_WEIGHT = 0.65
PRESSURE_RATIO_WEIGHT = 0.35
PRIOR_MATCH_WEIGHT = 3.0
DEFAULT_TIME_DECAY_XI: float = 0.0015
VERIFIED_INJURY_WEIGHT = 1.0
UNCERTAIN_SINGLE_SOURCE_INJURY_WEIGHT = 0.75

_UNCERTAIN_RETURN_TOKENS = frozenset(
    {"", "?", "-", "--", "bilinmiyor", "belirsiz", "unknown", "open", "n/a"}
)
_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_DOT_DATE_RE = re.compile(r"^(\d{1,2})[./](\d{1,2})[./](\d{4})$")

# (hücum_kaybı_oranı, savunma_zaafiyeti_artış_oranı)
# Savunma zaafiyeti artışı: rakibin beklenen golünü artırır ve 0-100 savunma direncini düşürür.
INJURY_PENALTY_MATRIX: dict[PlayerPosition, dict[ImpactLevel, tuple[float, float]]] = {
    PlayerPosition.GK: {
        ImpactLevel.HIGH: (0.00, 0.22),    # +%18-25 bandının merkezi (+%22 yenilen gol beklentisi)
        ImpactLevel.MEDIUM: (0.00, 0.10),  # +%10
        ImpactLevel.LOW: (0.00, 0.03),     # +%3
    },
    PlayerPosition.DEF: {
        ImpactLevel.HIGH: (0.01, 0.12),    # +%12 savunma zaafiyeti
        ImpactLevel.MEDIUM: (0.00, 0.07),  # +%7 savunma zaafiyeti
        ImpactLevel.LOW: (0.00, 0.025),    # +%2.5 savunma zaafiyeti
    },
    PlayerPosition.MID: {
        ImpactLevel.HIGH: (0.08, 0.07),    # Kilit orta saha: hücum beslemesi ve top kazanma kaybı
        ImpactLevel.MEDIUM: (0.06, 0.05),  # Şartname referansı: Hücum -%6, Savunma zaafiyeti +%5
        ImpactLevel.LOW: (0.025, 0.02),
    },
    PlayerPosition.FW: {
        ImpactLevel.HIGH: (0.16, 0.00),    # -%16 hücum bitiriciliği
        ImpactLevel.MEDIUM: (0.08, 0.00),  # -%8
        ImpactLevel.LOW: (0.03, 0.00),     # -%3
    },
}

MIN_ATTACK_MULTIPLIER = 0.45
MAX_DEFENSE_VULNERABILITY_MULTIPLIER = 1.85


def _strength_to_rating_100(strength_ratio: float) -> float:
    """1.0 merkezli boyutsuz güç oranını 0.0 - 100.0 aralığında monotonik skora dönüştürür."""
    clamped = max(0.0, strength_ratio)
    if clamped == 0.0:
        return 0.0
    curved = clamped**1.35
    score = 100.0 * (curved / (curved + 0.65))
    return round(min(100.0, max(0.0, score)), 2)


def offense_ratio_to_rating(attack_ratio: float) -> float:
    """Hücum katsayısını (yüksek = daha üretken) 0-100 puanına çevirir."""
    return _strength_to_rating_100(attack_ratio)


def defense_vulnerability_to_rating(concession_ratio: float) -> float:
    """Savunma gol yeme çarpanını (düşük = daha sağlam savunma) 0-100 savunma direnci puanına çevirir."""
    safe_concession = max(0.20, concession_ratio)
    resistance_strength = 1.0 / safe_concession
    return _strength_to_rating_100(resistance_strength)


@dataclass(slots=True)
class LeagueBaseline:
    """Lig genel gol ortalamaları ve iç saha avantajı katsayısı."""

    played_matches: int
    avg_home_goals: float
    avg_away_goals: float
    home_advantage: float


@dataclass(slots=True)
class InjuryDegradation:
    """Sakat ve cezalı listesinin takım hücum/savunma çarpanlarına etkisi."""

    attack_multiplier: float
    defense_vulnerability_multiplier: float
    attack_drop_pct: float
    defense_vulnerability_pct: float
    injuries: list[Injury] = field(default_factory=list)


@dataclass(slots=True)
class TeamRatingProfile:
    """Tek bir takımın baz istatistikleri, sakatlık sonrası katsayıları ve 0-100 reytingleri."""

    team_id: int
    played: int = 0
    home_played: int = 0
    away_played: int = 0
    home_wins: int = 0
    home_draws: int = 0
    home_losses: int = 0
    away_wins: int = 0
    away_draws: int = 0
    away_losses: int = 0
    goals_for: int = 0
    goals_against: int = 0
    home_goals_for: int = 0
    home_goals_against: int = 0
    away_goals_for: int = 0
    away_goals_against: int = 0
    clean_sheets: int = 0
    away_clean_sheets: int = 0
    recent_form: list[str] = field(default_factory=list)

    base_attack: float = 1.0
    base_defense: float = 1.0
    home_attack: float = 1.0
    away_attack: float = 1.0
    home_defense: float = 1.0
    away_defense: float = 1.0
    home_advantage: float = round(DEFAULT_AVG_HOME_GOALS / DEFAULT_AVG_AWAY_GOALS, 4)

    base_offense_rating: float = 60.61
    base_defense_rating: float = 60.61

    attack_multiplier: float = 1.0
    defense_vulnerability_multiplier: float = 1.0
    adjusted_attack: float = 1.0
    adjusted_defense: float = 1.0
    adjusted_home_attack: float = 1.0
    adjusted_away_attack: float = 1.0
    adjusted_home_defense: float = 1.0
    adjusted_away_defense: float = 1.0
    adjusted_offense_rating: float = 60.61
    adjusted_defense_rating: float = 60.61
    injuries: list[Injury] = field(default_factory=list)

    first_half_attack_share: float = DEFAULT_FIRST_HALF_SHARE
    first_half_concede_share: float = DEFAULT_FIRST_HALF_SHARE
    xg_for_per_match: float | None = None
    xg_against_per_match: float | None = None
    xg_is_derived: bool = False
    xg_source: str | None = None
    shots_for_per_match: float | None = None
    shots_against_per_match: float | None = None
    sot_for_per_match: float | None = None
    sot_against_per_match: float | None = None
    corners_for_per_match: float | None = None
    corners_against_per_match: float | None = None
    espn_rank: int | None = None
    espn_points: int | None = None
    verified_injuries_count: int = 0
    sources_matched: list[str] = field(default_factory=list)


def _to_utc_timestamp(val: datetime | date) -> float:
    """Naive veya timezone-aware datetime/date değerini güvenli biçimde UTC epoch saniyesine çevirir."""
    if isinstance(val, datetime):
        dt = val if val.tzinfo is not None else val.replace(tzinfo=UTC)
        return dt.timestamp()
    return datetime(val.year, val.month, val.day, 0, 0, tzinfo=UTC).timestamp()


def calculate_league_baseline(
    matches: Iterable[Match],
    *,
    time_decay_xi: float = DEFAULT_TIME_DECAY_XI,
    reference_date: datetime | date | None = None,
) -> LeagueBaseline:
    """Oynanmış maçlardan lig ev/deplasman gol ortalamalarını ve iç saha avantajını çıkarır."""
    finished = [
        m
        for m in matches
        if m.status == MatchStatus.FINISHED
        and m.home_score is not None
        and m.away_score is not None
    ]
    if not finished:
        home_adv = round(DEFAULT_AVG_HOME_GOALS / DEFAULT_AVG_AWAY_GOALS, 4)
        return LeagueBaseline(
            played_matches=0,
            avg_home_goals=DEFAULT_AVG_HOME_GOALS,
            avg_away_goals=DEFAULT_AVG_AWAY_GOALS,
            home_advantage=home_adv,
        )

    n = len(finished)
    if time_decay_xi > 0.0:
        ref_ts = (
            _to_utc_timestamp(reference_date)
            if reference_date is not None
            else max(_to_utc_timestamp(m.match_date) for m in finished)
        )
        weights = [
            math.exp(
                -time_decay_xi * max(0.0, (ref_ts - _to_utc_timestamp(m.match_date)) / 86400.0)
            )
            for m in finished
        ]
        w_sum = sum(weights)
        raw_home = (
            sum(w * int(m.home_score or 0) for w, m in zip(weights, finished, strict=True)) / w_sum
            if w_sum > 0.0
            else sum(int(m.home_score or 0) for m in finished) / n
        )
        raw_away = (
            sum(w * int(m.away_score or 0) for w, m in zip(weights, finished, strict=True)) / w_sum
            if w_sum > 0.0
            else sum(int(m.away_score or 0) for m in finished) / n
        )
    else:
        raw_home = sum(int(m.home_score or 0) for m in finished) / n
        raw_away = sum(int(m.away_score or 0) for m in finished) / n

    # Küçük örneklemlerde aşırı uçları yumuşatmak için varsayılan lig ortalamasıyla sönümle
    blend = min(1.0, n / 12.0)
    avg_home = max(0.45, blend * raw_home + (1.0 - blend) * DEFAULT_AVG_HOME_GOALS)
    avg_away = max(0.40, blend * raw_away + (1.0 - blend) * DEFAULT_AVG_AWAY_GOALS)
    home_adv = min(1.60, max(1.05, avg_home / avg_away))

    return LeagueBaseline(
        played_matches=n,
        avg_home_goals=round(avg_home, 4),
        avg_away_goals=round(avg_away, 4),
        home_advantage=round(home_adv, 4),
    )


def _parse_return_date_value(raw: date | str | None) -> date | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    cleaned = str(raw).strip()
    if cleaned.casefold() in _UNCERTAIN_RETURN_TOKENS:
        return None
    m_iso = _ISO_DATE_RE.match(cleaned)
    if m_iso:
        try:
            return date(int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3)))
        except ValueError:
            return None
    m_dot = _DOT_DATE_RE.match(cleaned)
    if m_dot:
        try:
            return date(int(m_dot.group(3)), int(m_dot.group(2)), int(m_dot.group(1)))
        except ValueError:
            return None
    return None


def _injury_confidence_weight(inj: Injury, ref_date: date) -> float:
    """Çift kaynak onaylı eksiklere 1.0x; tek kaynaklı belirsiz/tarihi geçmiş kayıtlara 0.75x verir."""
    if bool(getattr(inj, "verified_by_multiple_sources", False)):
        return VERIFIED_INJURY_WEIGHT
    parsed_ret = _parse_return_date_value(getattr(inj, "return_date", None))
    if parsed_ret is None or parsed_ret < ref_date:
        return UNCERTAIN_SINGLE_SOURCE_INJURY_WEIGHT
    return VERIFIED_INJURY_WEIGHT


def calculate_injury_degradation(
    injuries: Sequence[Injury],
    *,
    reference_date: date | None = None,
) -> InjuryDegradation:
    """Takımın sakat/cezalı oyuncularına göre hücum düşüşü ve savunma zaafiyeti çarpanlarını hesaplar."""
    if not injuries:
        return InjuryDegradation(
            attack_multiplier=1.0,
            defense_vulnerability_multiplier=1.0,
            attack_drop_pct=0.0,
            defense_vulnerability_pct=0.0,
            injuries=[],
        )

    ref = reference_date or date.today()
    total_attack_loss = 0.0
    total_defense_vuln = 0.0

    for inj in injuries:
        pos_map = INJURY_PENALTY_MATRIX.get(inj.position, {})
        att_loss, def_vuln = pos_map.get(inj.impact_level, (0.0, 0.0))
        weight = _injury_confidence_weight(inj, ref)
        total_attack_loss += att_loss * weight
        total_defense_vuln += def_vuln * weight

    attack_mult = max(MIN_ATTACK_MULTIPLIER, 1.0 - total_attack_loss)
    defense_mult = min(MAX_DEFENSE_VULNERABILITY_MULTIPLIER, 1.0 + total_defense_vuln)

    return InjuryDegradation(
        attack_multiplier=round(attack_mult, 4),
        defense_vulnerability_multiplier=round(defense_mult, 4),
        attack_drop_pct=round((1.0 - attack_mult) * 100.0, 2),
        defense_vulnerability_pct=round((defense_mult - 1.0) * 100.0, 2),
        injuries=list(injuries),
    )


def apply_injuries_to_profile(
    profile: TeamRatingProfile,
    injuries: Sequence[Injury],
    *,
    reference_date: date | None = None,
) -> TeamRatingProfile:
    """Baz takım profiline sakatlık zayıflatma çarpanlarını uygular ve 0-100 reytingleri günceller."""
    deg = calculate_injury_degradation(injuries, reference_date=reference_date)
    profile.injuries = deg.injuries
    profile.verified_injuries_count = sum(
        1 for inj in deg.injuries if bool(getattr(inj, "verified_by_multiple_sources", False))
    )
    profile.attack_multiplier = deg.attack_multiplier
    profile.defense_vulnerability_multiplier = deg.defense_vulnerability_multiplier

    profile.adjusted_attack = round(profile.base_attack * deg.attack_multiplier, 4)
    profile.adjusted_home_attack = round(profile.home_attack * deg.attack_multiplier, 4)
    profile.adjusted_away_attack = round(profile.away_attack * deg.attack_multiplier, 4)

    profile.adjusted_defense = round(
        profile.base_defense * deg.defense_vulnerability_multiplier, 4
    )
    profile.adjusted_home_defense = round(
        profile.home_defense * deg.defense_vulnerability_multiplier, 4
    )
    profile.adjusted_away_defense = round(
        profile.away_defense * deg.defense_vulnerability_multiplier, 4
    )

    profile.adjusted_offense_rating = offense_ratio_to_rating(profile.adjusted_attack)
    profile.adjusted_defense_rating = defense_vulnerability_to_rating(profile.adjusted_defense)
    return profile


def _metric_get(metric_obj: Any, *keys: str) -> Any:
    if metric_obj is None:
        return None
    if isinstance(metric_obj, Mapping):
        for k in keys:
            if k in metric_obj and metric_obj[k] is not None:
                return metric_obj[k]
        return None
    for k in keys:
        val = getattr(metric_obj, k, None)
        if val is not None:
            return val
    return None


def _opt_float(val: Any) -> float | None:
    if val is None or isinstance(val, bool):
        return None
    try:
        num = float(val)
    except (TypeError, ValueError):
        return None
    return num if num >= 0.0 else None


def _opt_int(val: Any) -> int | None:
    if val is None or isinstance(val, bool):
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _clamp_ht_share(value: float | None) -> float:
    if value is None:
        return DEFAULT_FIRST_HALF_SHARE
    return round(min(MAX_FIRST_HALF_SHARE, max(MIN_FIRST_HALF_SHARE, value)), 4)


def _populate_external_metrics(profile: TeamRatingProfile, metric_obj: Any) -> None:
    if metric_obj is None:
        return

    profile.xg_for_per_match = _opt_float(
        _metric_get(metric_obj, "xg_for_per_match", "xg_per_match", "xg_for_pg")
    )
    profile.xg_against_per_match = _opt_float(
        _metric_get(metric_obj, "xg_against_per_match", "xga_per_match", "xg_against_pg")
    )
    profile.xg_is_derived = bool(
        _metric_get(metric_obj, "xg_is_derived", "derived_xg", "is_xg_derived") or False
    )
    raw_xg_src = _metric_get(metric_obj, "xg_source")
    if isinstance(raw_xg_src, str) and raw_xg_src.strip():
        profile.xg_source = raw_xg_src.strip()

    profile.shots_for_per_match = _opt_float(
        _metric_get(metric_obj, "shots_for_per_match", "shots_per_match", "hs_per_match")
    )
    profile.shots_against_per_match = _opt_float(
        _metric_get(metric_obj, "shots_against_per_match", "shots_conceded_per_match", "as_per_match")
    )
    profile.sot_for_per_match = _opt_float(
        _metric_get(
            metric_obj,
            "sot_for_per_match",
            "shots_on_target_for_per_match",
            "hst_per_match",
            "sot_per_match",
        )
    )
    profile.sot_against_per_match = _opt_float(
        _metric_get(
            metric_obj,
            "sot_against_per_match",
            "shots_on_target_against_per_match",
            "ast_per_match",
        )
    )
    profile.corners_for_per_match = _opt_float(
        _metric_get(metric_obj, "corners_for_per_match", "corners_per_match", "hc_per_match")
    )
    profile.corners_against_per_match = _opt_float(
        _metric_get(metric_obj, "corners_against_per_match", "ac_per_match")
    )
    profile.espn_rank = _opt_int(_metric_get(metric_obj, "espn_rank", "rank", "standing_rank"))
    profile.espn_points = _opt_int(
        _metric_get(metric_obj, "espn_points", "points", "standing_points")
    )

    raw_sources = _metric_get(metric_obj, "sources_matched", "sources")
    if isinstance(raw_sources, (list, tuple, set)):
        profile.sources_matched = [str(s) for s in raw_sources if str(s).strip()]

    raw_ht_att = _opt_float(
        _metric_get(metric_obj, "first_half_attack_share", "ht_attack_share", "ht_goal_share_for")
    )
    if raw_ht_att is None:
        ht_gf = _opt_float(_metric_get(metric_obj, "ht_goals_for"))
        ft_gf = _opt_float(_metric_get(metric_obj, "ft_goals_for_fd", "fd_goals_for"))
        if ht_gf is not None and ft_gf is not None and ft_gf > 0.0:
            raw_ht_att = (ht_gf + 4.0 * DEFAULT_FIRST_HALF_SHARE) / (ft_gf + 4.0)
    profile.first_half_attack_share = _clamp_ht_share(raw_ht_att)

    raw_ht_def = _opt_float(
        _metric_get(
            metric_obj,
            "first_half_concede_share",
            "ht_concede_share",
            "ht_defense_share",
            "ht_goal_share_against",
        )
    )
    if raw_ht_def is None:
        ht_ga = _opt_float(_metric_get(metric_obj, "ht_goals_against"))
        ft_ga = _opt_float(_metric_get(metric_obj, "ft_goals_against_fd", "fd_goals_against"))
        if ht_ga is not None and ft_ga is not None and ft_ga > 0.0:
            raw_ht_def = (ht_ga + 4.0 * DEFAULT_FIRST_HALF_SHARE) / (ft_ga + 4.0)
    profile.first_half_concede_share = _clamp_ht_share(raw_ht_def)


def _combine_pressure_ratio(
    xg_val: float | None,
    sot_val: float | None,
    avg_xg: float,
    avg_sot: float,
) -> float | None:
    xg_ratio = (xg_val / avg_xg) if (xg_val is not None and xg_val > 0.0 and avg_xg > 0.0) else None
    sot_ratio = (
        (sot_val / avg_sot) if (sot_val is not None and sot_val > 0.0 and avg_sot > 0.0) else None
    )
    if xg_ratio is not None and sot_ratio is not None:
        return 0.70 * xg_ratio + 0.30 * sot_ratio
    if xg_ratio is not None:
        return xg_ratio
    if sot_ratio is not None:
        return sot_ratio
    return None


def build_team_ratings(
    matches: Sequence[Match],
    injuries: Sequence[Injury] = (),
    *,
    team_ids: Iterable[int] | None = None,
    prior_weight: float = PRIOR_MATCH_WEIGHT,
    team_metrics: Mapping[int, Any] | None = None,
    time_decay_xi: float = DEFAULT_TIME_DECAY_XI,
    reference_date: datetime | date | None = None,
) -> dict[int, TeamRatingProfile]:
    """Oynanmış maçlardan ve çoklu kaynak metriklerinden takım reyting profillerini üretir."""
    baseline = calculate_league_baseline(
        matches,
        time_decay_xi=time_decay_xi,
        reference_date=reference_date,
    )
    finished = sorted(
        (
            m
            for m in matches
            if m.status == MatchStatus.FINISHED
            and m.home_score is not None
            and m.away_score is not None
        ),
        key=lambda m: (_to_utc_timestamp(m.match_date), m.round),
    )

    discovered_ids: set[int] = set(team_ids or ())
    for m in matches:
        discovered_ids.add(m.home_team_id)
        discovered_ids.add(m.away_team_id)
    for inj in injuries:
        discovered_ids.add(inj.team_id)
    if team_metrics:
        for raw_tid in team_metrics:
            if isinstance(raw_tid, int):
                discovered_ids.add(raw_tid)

    profiles: dict[int, TeamRatingProfile] = {
        tid: TeamRatingProfile(team_id=tid, home_advantage=baseline.home_advantage)
        for tid in discovered_ids
    }
    form_history: dict[int, list[str]] = {tid: [] for tid in discovered_ids}

    w_played: dict[int, float] = {tid: 0.0 for tid in discovered_ids}
    w_home_played: dict[int, float] = {tid: 0.0 for tid in discovered_ids}
    w_away_played: dict[int, float] = {tid: 0.0 for tid in discovered_ids}
    w_gf: dict[int, float] = {tid: 0.0 for tid in discovered_ids}
    w_ga: dict[int, float] = {tid: 0.0 for tid in discovered_ids}
    w_hgf: dict[int, float] = {tid: 0.0 for tid in discovered_ids}
    w_hga: dict[int, float] = {tid: 0.0 for tid in discovered_ids}
    w_agf: dict[int, float] = {tid: 0.0 for tid in discovered_ids}
    w_aga: dict[int, float] = {tid: 0.0 for tid in discovered_ids}

    ref_ts = (
        _to_utc_timestamp(reference_date)
        if reference_date is not None
        else (max(_to_utc_timestamp(m.match_date) for m in finished) if finished else 0.0)
    )

    for m in finished:
        hs = int(m.home_score or 0)
        as_ = int(m.away_score or 0)
        w = (
            math.exp(
                -time_decay_xi * max(0.0, (ref_ts - _to_utc_timestamp(m.match_date)) / 86400.0)
            )
            if time_decay_xi > 0.0
            else 1.0
        )
        hp = profiles[m.home_team_id]
        ap = profiles[m.away_team_id]

        hp.played += 1
        hp.home_played += 1
        hp.goals_for += hs
        hp.goals_against += as_
        hp.home_goals_for += hs
        hp.home_goals_against += as_
        if as_ == 0:
            hp.clean_sheets += 1

        w_played[m.home_team_id] += w
        w_home_played[m.home_team_id] += w
        w_gf[m.home_team_id] += w * hs
        w_ga[m.home_team_id] += w * as_
        w_hgf[m.home_team_id] += w * hs
        w_hga[m.home_team_id] += w * as_

        ap.played += 1
        ap.away_played += 1
        ap.goals_for += as_
        ap.goals_against += hs
        ap.away_goals_for += as_
        ap.away_goals_against += hs
        if hs == 0:
            ap.clean_sheets += 1
            ap.away_clean_sheets += 1

        w_played[m.away_team_id] += w
        w_away_played[m.away_team_id] += w
        w_gf[m.away_team_id] += w * as_
        w_ga[m.away_team_id] += w * hs
        w_agf[m.away_team_id] += w * as_
        w_aga[m.away_team_id] += w * hs

        if hs > as_:
            hp.home_wins += 1
            ap.away_losses += 1
            form_history[m.home_team_id].append("G")
            form_history[m.away_team_id].append("M")
        elif hs < as_:
            hp.home_losses += 1
            ap.away_wins += 1
            form_history[m.home_team_id].append("M")
            form_history[m.away_team_id].append("G")
        else:
            hp.home_draws += 1
            ap.away_draws += 1
            form_history[m.home_team_id].append("B")
            form_history[m.away_team_id].append("B")

    injuries_by_team: dict[int, list[Injury]] = {}
    for inj in injuries:
        injuries_by_team.setdefault(inj.team_id, []).append(inj)

    if team_metrics:
        for tid, prof in profiles.items():
            metric_obj = team_metrics.get(tid)
            if metric_obj is None and isinstance(team_metrics, Mapping):
                metric_obj = cast(Mapping[object, Any], team_metrics).get(str(tid))
            _populate_external_metrics(prof, metric_obj)

    avg_team_goals = (baseline.avg_home_goals + baseline.avg_away_goals) / 2.0
    xg_samples = [
        p.xg_for_per_match
        for p in profiles.values()
        if p.xg_for_per_match is not None and p.xg_for_per_match > 0.0
    ]
    sot_samples = [
        p.sot_for_per_match
        for p in profiles.values()
        if p.sot_for_per_match is not None and p.sot_for_per_match > 0.0
    ]
    avg_xg = (
        sum(xg_samples) / len(xg_samples) if len(xg_samples) >= 2 else max(0.60, avg_team_goals)
    )
    avg_sot = sum(sot_samples) / len(sot_samples) if len(sot_samples) >= 2 else DEFAULT_AVG_SOT
    inj_ref_date = reference_date.date() if isinstance(reference_date, datetime) else reference_date

    for tid, prof in profiles.items():
        prof.recent_form = form_history[tid][-5:]

        if time_decay_xi > 0.0:
            eff_hgf = (
                prof.home_played * (w_hgf[tid] / w_home_played[tid])
                if w_home_played[tid] > 0.0
                else 0.0
            )
            eff_hga = (
                prof.home_played * (w_hga[tid] / w_home_played[tid])
                if w_home_played[tid] > 0.0
                else 0.0
            )
            eff_agf = (
                prof.away_played * (w_agf[tid] / w_away_played[tid])
                if w_away_played[tid] > 0.0
                else 0.0
            )
            eff_aga = (
                prof.away_played * (w_aga[tid] / w_away_played[tid])
                if w_away_played[tid] > 0.0
                else 0.0
            )
            eff_gf = prof.played * (w_gf[tid] / w_played[tid]) if w_played[tid] > 0.0 else 0.0
            eff_ga = prof.played * (w_ga[tid] / w_played[tid]) if w_played[tid] > 0.0 else 0.0
        else:
            eff_hgf = float(prof.home_goals_for)
            eff_hga = float(prof.home_goals_against)
            eff_agf = float(prof.away_goals_for)
            eff_aga = float(prof.away_goals_against)
            eff_gf = float(prof.goals_for)
            eff_ga = float(prof.goals_against)

        home_att = (eff_hgf + prior_weight * baseline.avg_home_goals) / (
            (prof.home_played + prior_weight) * baseline.avg_home_goals
        )
        away_att = (eff_agf + prior_weight * baseline.avg_away_goals) / (
            (prof.away_played + prior_weight) * baseline.avg_away_goals
        )
        overall_att = (eff_gf + prior_weight * avg_team_goals) / (
            (prof.played + prior_weight) * avg_team_goals
        )

        # Ev sahibi kalesinde deplasman ortalamasına göre; deplasmanda ev ortalamasına göre gol yer
        home_def = (eff_hga + prior_weight * baseline.avg_away_goals) / (
            (prof.home_played + prior_weight) * baseline.avg_away_goals
        )
        away_def = (eff_aga + prior_weight * baseline.avg_home_goals) / (
            (prof.away_played + prior_weight) * baseline.avg_home_goals
        )
        overall_def = (eff_ga + prior_weight * avg_team_goals) / (
            (prof.played + prior_weight) * avg_team_goals
        )

        goal_base_att = overall_att
        goal_home_att = 0.6 * home_att + 0.4 * overall_att
        goal_away_att = 0.6 * away_att + 0.4 * overall_att

        goal_base_def = overall_def
        goal_home_def = 0.6 * home_def + 0.4 * overall_def
        goal_away_def = 0.6 * away_def + 0.4 * overall_def

        pressure_att = _combine_pressure_ratio(
            prof.xg_for_per_match, prof.sot_for_per_match, avg_xg, avg_sot
        )
        pressure_def = _combine_pressure_ratio(
            prof.xg_against_per_match, prof.sot_against_per_match, avg_xg, avg_sot
        )

        if pressure_att is not None:
            prof.base_attack = round(
                GOAL_RATIO_WEIGHT * goal_base_att + PRESSURE_RATIO_WEIGHT * pressure_att, 4
            )
            prof.home_attack = round(
                GOAL_RATIO_WEIGHT * goal_home_att + PRESSURE_RATIO_WEIGHT * pressure_att, 4
            )
            prof.away_attack = round(
                GOAL_RATIO_WEIGHT * goal_away_att + PRESSURE_RATIO_WEIGHT * pressure_att, 4
            )
        else:
            prof.base_attack = round(goal_base_att, 4)
            prof.home_attack = round(goal_home_att, 4)
            prof.away_attack = round(goal_away_att, 4)

        if pressure_def is not None:
            prof.base_defense = round(
                GOAL_RATIO_WEIGHT * goal_base_def + PRESSURE_RATIO_WEIGHT * pressure_def, 4
            )
            prof.home_defense = round(
                GOAL_RATIO_WEIGHT * goal_home_def + PRESSURE_RATIO_WEIGHT * pressure_def, 4
            )
            prof.away_defense = round(
                GOAL_RATIO_WEIGHT * goal_away_def + PRESSURE_RATIO_WEIGHT * pressure_def, 4
            )
        else:
            prof.base_defense = round(goal_base_def, 4)
            prof.home_defense = round(goal_home_def, 4)
            prof.away_defense = round(goal_away_def, 4)

        prof.base_offense_rating = offense_ratio_to_rating(prof.base_attack)
        prof.base_defense_rating = defense_vulnerability_to_rating(prof.base_defense)

        apply_injuries_to_profile(
            prof,
            injuries_by_team.get(tid, ()),
            reference_date=inj_ref_date,
        )

    return profiles
