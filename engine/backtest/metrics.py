"""Walk-forward backtest olasılıksal doğruluk, kalibrasyon ve piyasa marj arındırma metrikleri."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from engine.models.schemas import ALL_HT_FT_CODES

EPSILON = 1e-15

ODDS_1X2_PRIORITY: tuple[tuple[str, str, str, str], ...] = (
    ("PSCH", "PSCD", "PSCA", "Pinnacle-Close"),
    ("B365CH", "B365CD", "B365CA", "Bet365-Close"),
    ("AvgCH", "AvgCD", "AvgCA", "MarketAvg-Close"),
    ("PSH", "PSD", "PSA", "Pinnacle-Open"),
    ("B365H", "B365D", "B365A", "Bet365-Open"),
    ("AvgH", "AvgD", "AvgA", "MarketAvg-Open"),
)

ODDS_OVER25_PRIORITY: tuple[tuple[str, str, str], ...] = (
    ("PC>2.5", "PC<2.5", "Pinnacle-Close"),
    ("B365C>2.5", "B365C<2.5", "Bet365-Close"),
    ("AvgC>2.5", "AvgC<2.5", "MarketAvg-Close"),
    ("P>2.5", "P<2.5", "Pinnacle-Open"),
    ("B365>2.5", "B365<2.5", "Bet365-Open"),
    ("Avg>2.5", "Avg<2.5", "MarketAvg-Open"),
)


@dataclass(slots=True)
class MatchEvaluationRecord:
    """Tek bir maç için sızıntısız model veya piyasa olasılık tahmini ve gerçekleşen sonuç."""

    league_code: str
    season_code: str
    match_date: str
    home_team: str
    away_team: str
    home_goals: int
    away_goals: int
    p_home: float
    p_draw: float
    p_away: float
    p_over25: float | None = None
    expected_home_goals: float | None = None
    expected_away_goals: float | None = None
    ht_home_goals: int | None = None
    ht_away_goals: int | None = None
    actual_ht_ft: str | None = None
    ht_ft_probs: dict[str, float] | None = None


@dataclass(slots=True)
class CalibrationBucket:
    """Olasılık dilimi bazında ortalama tahmin ve gerçekleşen isabet oranı (güvenirlik dilimi)."""

    label: str
    low: float
    high: float
    count: int
    mean_predicted: float
    empirical_rate: float
    abs_calibration_error: float


@dataclass(slots=True)
class ModelSummaryMetrics:
    """Toplu maç kümesi üzerinde hesaplanan sıralı/çok sınıflı, Üst 2.5 ve 9'lu İY/MS metrikleri."""

    model_name: str
    matches: int
    rps: float
    brier_1x2: float
    log_loss_1x2: float
    accuracy_1x2: float
    mean_pred_home_goals: float | None
    mean_pred_away_goals: float | None
    mean_pred_total_goals: float | None
    mean_actual_home_goals: float
    mean_actual_away_goals: float
    mean_actual_total_goals: float
    over25_matches: int
    mean_pred_over25: float | None
    actual_over25_rate: float
    over25_calibration_gap: float | None
    brier_over25: float | None
    log_loss_over25: float | None
    accuracy_over25: float | None = None
    ht_ft_matches: int = 0
    brier_ht_ft: float | None = None
    log_loss_ht_ft: float | None = None
    ht_ft_top1_accuracy: float | None = None
    ht_ft_top3_accuracy: float | None = None


MetricsSummary = ModelSummaryMetrics


def outcome_one_hot(home_goals: int, away_goals: int) -> tuple[int, int, int]:
    """Gerçekleşen maç sonucunu (Ev, Beraberlik, Deplasman) one-hot vektörüne çevirir."""
    if home_goals > away_goals:
        return (1, 0, 0)
    if home_goals == away_goals:
        return (0, 1, 0)
    return (0, 0, 1)


def _normalize_triplet(p_home: float, p_draw: float, p_away: float) -> tuple[float, float, float]:
    total = p_home + p_draw + p_away
    if total <= 0.0:
        return (1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0)
    return (p_home / total, p_draw / total, p_away / total)


def ranked_probability_score(
    p_home: float,
    p_draw: float,
    p_away: float,
    home_goals: int,
    away_goals: int,
) -> float:
    """Sıralı 3 sonuçlu (1-X-2) tahmin için Ranked Probability Score (RPS, [0, 1], düşük=iyi)."""
    ph, pd, _ = _normalize_triplet(p_home, p_draw, p_away)
    oh, od, _ = outcome_one_hot(home_goals, away_goals)
    cum_1 = ph - oh
    cum_2 = (ph + pd) - (oh + od)
    return 0.5 * (cum_1 * cum_1 + cum_2 * cum_2)


def multiclass_brier_score(
    p_home: float,
    p_draw: float,
    p_away: float,
    home_goals: int,
    away_goals: int,
) -> float:
    """Çok sınıflı Brier skoru: sum_i (p_i - o_i)^2 ([0, 2] aralığında, düşük=iyi)."""
    ph, pd, pa = _normalize_triplet(p_home, p_draw, p_away)
    oh, od, oa = outcome_one_hot(home_goals, away_goals)
    return (ph - oh) ** 2 + (pd - od) ** 2 + (pa - oa) ** 2


def multiclass_log_loss(
    p_home: float,
    p_draw: float,
    p_away: float,
    home_goals: int,
    away_goals: int,
) -> float:
    """Gerçekleşen 1X2 sınıfının negatif doğal logaritması (-ln p_gerçek)."""
    ph, pd, pa = _normalize_triplet(p_home, p_draw, p_away)
    if home_goals > away_goals:
        target_p = ph
    elif home_goals == away_goals:
        target_p = pd
    else:
        target_p = pa
    return -math.log(max(EPSILON, min(1.0, target_p)))


def binary_brier_score(prob: float, outcome: bool | int) -> float:
    """İkili olay (ör. Üst 2.5) için Brier skoru: (p - y)^2."""
    clamped = min(1.0, max(0.0, prob))
    y = 1.0 if outcome else 0.0
    return (clamped - y) ** 2


def binary_log_loss(prob: float, outcome: bool | int) -> float:
    """İkili olay (ör. Üst 2.5) için çapraz entropi (log-loss)."""
    clamped = min(1.0 - EPSILON, max(EPSILON, prob))
    return -math.log(clamped if outcome else (1.0 - clamped))


def is_1x2_hit(
    p_home: float,
    p_draw: float,
    p_away: float,
    home_goals: int,
    away_goals: int,
) -> bool:
    """Argmax 1/X/2 tahmini gerçekleşen sonuçla eşleşiyor mu?"""
    # Eşitlik durumunda deterministik sıra: 1 > X > 2
    best_idx = 0
    best_p = p_home
    if p_draw > best_p:
        best_idx = 1
        best_p = p_draw
    if p_away > best_p:
        best_idx = 2
    actual_idx = 0 if home_goals > away_goals else (1 if home_goals == away_goals else 2)
    return best_idx == actual_idx


def devig_1x2_odds(odd_h: float, odd_d: float, odd_a: float) -> tuple[float, float, float]:
    """Bahisçi marjını (overround) oransal yöntemle temizleyip 1X2 olasılıklarına çevirir."""
    if odd_h <= 1.0 or odd_d <= 1.0 or odd_a <= 1.0:
        raise ValueError("1X2 oranlarının tamamı 1.0'dan büyük olmalıdır.")
    ih = 1.0 / odd_h
    id_ = 1.0 / odd_d
    ia = 1.0 / odd_a
    overround = ih + id_ + ia
    return (ih / overround, id_ / overround, ia / overround)


def devig_two_way_odds(odd_over: float, odd_under: float) -> tuple[float, float]:
    """İki yönlü (Üst/Alt 2.5) oranlardan marjı oransal temizleyip (p_over, p_under) döndürür."""
    if odd_over <= 1.0 or odd_under <= 1.0:
        raise ValueError("Üst/Alt oranlarının tamamı 1.0'dan büyük olmalıdır.")
    io = 1.0 / odd_over
    iu = 1.0 / odd_under
    overround = io + iu
    return (io / overround, iu / overround)


def _parse_positive_odd(row: Mapping[str, Any], key: str) -> float | None:
    raw = str(row.get(key) or "").strip()
    if not raw:
        return None
    try:
        val = float(raw)
    except ValueError:
        return None
    return val if math.isfinite(val) and val > 1.0 else None


def extract_market_1x2_probs(
    row: Mapping[str, Any],
) -> tuple[tuple[float, float, float] | None, str | None]:
    """CSV satırından öncelik sırasına göre (Kapanış -> Açılış) marjsız 1X2 olasılığı çıkarır."""
    for h_col, d_col, a_col, label in ODDS_1X2_PRIORITY:
        oh = _parse_positive_odd(row, h_col)
        od = _parse_positive_odd(row, d_col)
        oa = _parse_positive_odd(row, a_col)
        if oh is not None and od is not None and oa is not None:
            return devig_1x2_odds(oh, od, oa), label
    return None, None


def actual_ht_ft_code(ht_home: int, ht_away: int, ft_home: int, ft_away: int) -> str:
    """Gerçekleşen İY ve MS gol sayılarından 9 yönlü İY/MS kodunu ('1/1'..'2/2') üretir."""
    ht_s = "1" if ht_home > ht_away else ("X" if ht_home == ht_away else "2")
    ft_s = "1" if ft_home > ft_away else ("X" if ft_home == ft_away else "2")
    return f"{ht_s}/{ft_s}"


def _normalize_ht_ft_probs(ht_ft_probs: Mapping[str, float]) -> dict[str, float]:
    vals = {c: max(0.0, float(ht_ft_probs.get(c, 0.0))) for c in ALL_HT_FT_CODES}
    tot = sum(vals.values())
    if tot <= 0.0 or not math.isfinite(tot):
        u = 1.0 / len(ALL_HT_FT_CODES)
        return {c: u for c in ALL_HT_FT_CODES}
    return {c: v / tot for c, v in vals.items()}


def ht_ft_multiclass_brier(ht_ft_probs: Mapping[str, float], actual_code: str) -> float:
    """9 yönlü İY/MS çok sınıflı Brier skoru: sum_{c in 9} (p_c - y_c)^2 ([0, 2] aralığında)."""
    normed = _normalize_ht_ft_probs(ht_ft_probs)
    return sum((normed[c] - (1.0 if c == actual_code else 0.0)) ** 2 for c in ALL_HT_FT_CODES)


def ht_ft_log_loss(ht_ft_probs: Mapping[str, float], actual_code: str) -> float:
    """9 yönlü İY/MS gerçekleşen sınıfının negatif doğal logaritması (-ln p_gerçek)."""
    normed = _normalize_ht_ft_probs(ht_ft_probs)
    target_p = normed.get(actual_code, 0.0)
    return -math.log(max(EPSILON, min(1.0, target_p)))


def ht_ft_top_k_hit(ht_ft_probs: Mapping[str, float], actual_code: str, k: int = 1) -> bool:
    """En yüksek olasılıklı ilk k İY/MS tahmini içinde gerçekleşen kod var mı?"""
    normed = _normalize_ht_ft_probs(ht_ft_probs)
    ranked = sorted(ALL_HT_FT_CODES, key=lambda c: (-normed[c], ALL_HT_FT_CODES.index(c)))
    return actual_code in ranked[: max(1, k)]


def extract_market_over_under25_probs(
    row: Mapping[str, Any],
) -> tuple[tuple[float, float] | None, str | None]:
    """CSV satırından öncelik sırasına göre marjsız (Üst 2.5, Alt 2.5) olasılık ikilisini çıkarır."""
    for o_col, u_col, label in ODDS_OVER25_PRIORITY:
        oo = _parse_positive_odd(row, o_col)
        ou = _parse_positive_odd(row, u_col)
        if oo is not None and ou is not None:
            return devig_two_way_odds(oo, ou), label
    return None, None


def extract_market_over25_prob(row: Mapping[str, Any]) -> tuple[float | None, str | None]:
    """CSV satırından öncelik sırasına göre marjsız Üst 2.5 olasılığını çıkarır."""
    pair, label = extract_market_over_under25_probs(row)
    if pair is None:
        return None, None
    return pair[0], label


def summarize_records(
    model_name: str,
    records: Sequence[MatchEvaluationRecord],
) -> ModelSummaryMetrics:
    """Değerlendirme kayıtlarından özet performans ve kalibrasyon metriklerini üretir."""
    n = len(records)
    if n == 0:
        return ModelSummaryMetrics(
            model_name=model_name,
            matches=0,
            rps=0.0,
            brier_1x2=0.0,
            log_loss_1x2=0.0,
            accuracy_1x2=0.0,
            mean_pred_home_goals=None,
            mean_pred_away_goals=None,
            mean_pred_total_goals=None,
            mean_actual_home_goals=0.0,
            mean_actual_away_goals=0.0,
            mean_actual_total_goals=0.0,
            over25_matches=0,
            mean_pred_over25=None,
            actual_over25_rate=0.0,
            over25_calibration_gap=None,
            brier_over25=None,
            log_loss_over25=None,
        )

    rps_sum = 0.0
    brier_sum = 0.0
    ll_sum = 0.0
    hits = 0
    act_h_sum = 0.0
    act_a_sum = 0.0

    xg_records = [
        r
        for r in records
        if r.expected_home_goals is not None and r.expected_away_goals is not None
    ]
    over_records = [r for r in records if r.p_over25 is not None]

    for rec in records:
        rps_sum += ranked_probability_score(
            rec.p_home, rec.p_draw, rec.p_away, rec.home_goals, rec.away_goals
        )
        brier_sum += multiclass_brier_score(
            rec.p_home, rec.p_draw, rec.p_away, rec.home_goals, rec.away_goals
        )
        ll_sum += multiclass_log_loss(
            rec.p_home, rec.p_draw, rec.p_away, rec.home_goals, rec.away_goals
        )
        if is_1x2_hit(rec.p_home, rec.p_draw, rec.p_away, rec.home_goals, rec.away_goals):
            hits += 1
        act_h_sum += rec.home_goals
        act_a_sum += rec.away_goals

    mean_pred_h: float | None = None
    mean_pred_a: float | None = None
    mean_pred_tot: float | None = None
    if xg_records:
        mean_pred_h = sum(float(r.expected_home_goals or 0.0) for r in xg_records) / len(xg_records)
        mean_pred_a = sum(float(r.expected_away_goals or 0.0) for r in xg_records) / len(xg_records)
        mean_pred_tot = mean_pred_h + mean_pred_a

    all_over_rate = sum(1 for r in records if (r.home_goals + r.away_goals) >= 3) / n

    mean_pred_o25: float | None = None
    o25_gap: float | None = None
    o25_brier: float | None = None
    o25_ll: float | None = None
    o25_acc: float | None = None
    if over_records:
        m_cnt = len(over_records)
        sub_actual_rate = (
            sum(1 for r in over_records if (r.home_goals + r.away_goals) >= 3) / m_cnt
        )
        mean_pred_o25 = sum(float(r.p_over25 or 0.0) for r in over_records) / m_cnt
        o25_gap = mean_pred_o25 - sub_actual_rate
        o25_brier = (
            sum(
                binary_brier_score(float(r.p_over25 or 0.0), (r.home_goals + r.away_goals) >= 3)
                for r in over_records
            )
            / m_cnt
        )
        o25_ll = (
            sum(
                binary_log_loss(float(r.p_over25 or 0.0), (r.home_goals + r.away_goals) >= 3)
                for r in over_records
            )
            / m_cnt
        )
        o25_acc = (
            sum(
                1
                for r in over_records
                if (float(r.p_over25 or 0.0) >= 0.5) == ((r.home_goals + r.away_goals) >= 3)
            )
            / m_cnt
        )
        all_over_rate = sub_actual_rate

    ht_ft_records = [
        r
        for r in records
        if r.ht_ft_probs is not None and r.actual_ht_ft is not None
    ]
    ht_ft_cnt = len(ht_ft_records)
    ht_ft_brier: float | None = None
    ht_ft_ll: float | None = None
    ht_ft_t1: float | None = None
    ht_ft_t3: float | None = None
    if ht_ft_cnt > 0:
        ht_ft_brier = (
            sum(
                ht_ft_multiclass_brier(r.ht_ft_probs or {}, str(r.actual_ht_ft))
                for r in ht_ft_records
            )
            / ht_ft_cnt
        )
        ht_ft_ll = (
            sum(
                ht_ft_log_loss(r.ht_ft_probs or {}, str(r.actual_ht_ft))
                for r in ht_ft_records
            )
            / ht_ft_cnt
        )
        ht_ft_t1 = (
            sum(
                1
                for r in ht_ft_records
                if ht_ft_top_k_hit(r.ht_ft_probs or {}, str(r.actual_ht_ft), k=1)
            )
            / ht_ft_cnt
        )
        ht_ft_t3 = (
            sum(
                1
                for r in ht_ft_records
                if ht_ft_top_k_hit(r.ht_ft_probs or {}, str(r.actual_ht_ft), k=3)
            )
            / ht_ft_cnt
        )

    mean_act_h = act_h_sum / n
    mean_act_a = act_a_sum / n

    return ModelSummaryMetrics(
        model_name=model_name,
        matches=n,
        rps=round(rps_sum / n, 5),
        brier_1x2=round(brier_sum / n, 5),
        log_loss_1x2=round(ll_sum / n, 5),
        accuracy_1x2=round(hits / n, 5),
        mean_pred_home_goals=round(mean_pred_h, 4) if mean_pred_h is not None else None,
        mean_pred_away_goals=round(mean_pred_a, 4) if mean_pred_a is not None else None,
        mean_pred_total_goals=round(mean_pred_tot, 4) if mean_pred_tot is not None else None,
        mean_actual_home_goals=round(mean_act_h, 4),
        mean_actual_away_goals=round(mean_act_a, 4),
        mean_actual_total_goals=round(mean_act_h + mean_act_a, 4),
        over25_matches=len(over_records),
        mean_pred_over25=round(mean_pred_o25, 5) if mean_pred_o25 is not None else None,
        actual_over25_rate=round(all_over_rate, 5),
        over25_calibration_gap=round(o25_gap, 5) if o25_gap is not None else None,
        brier_over25=round(o25_brier, 5) if o25_brier is not None else None,
        log_loss_over25=round(o25_ll, 5) if o25_ll is not None else None,
        accuracy_over25=round(o25_acc, 5) if o25_acc is not None else None,
        ht_ft_matches=ht_ft_cnt,
        brier_ht_ft=round(ht_ft_brier, 5) if ht_ft_brier is not None else None,
        log_loss_ht_ft=round(ht_ft_ll, 5) if ht_ft_ll is not None else None,
        ht_ft_top1_accuracy=round(ht_ft_t1, 5) if ht_ft_t1 is not None else None,
        ht_ft_top3_accuracy=round(ht_ft_t3, 5) if ht_ft_t3 is not None else None,
    )


def compute_calibration_buckets(
    records: Sequence[MatchEvaluationRecord],
    *,
    target: str = "1x2",
    num_buckets: int = 5,
) -> list[CalibrationBucket]:
    """Tahmin olasılıklarını eşit genişlikli dilimlere ayırarak kalibrasyon tablosu üretir."""
    pairs: list[tuple[float, int]] = []
    if target == "over25":
        for r in records:
            if r.p_over25 is not None:
                clamped_p = min(1.0, max(0.0, r.p_over25))
                pairs.append((clamped_p, int((r.home_goals + r.away_goals) >= 3)))
    else:
        for r in records:
            ph, pd, pa = _normalize_triplet(r.p_home, r.p_draw, r.p_away)
            oh, od, oa = outcome_one_hot(r.home_goals, r.away_goals)
            pairs.append((ph, oh))
            pairs.append((pd, od))
            pairs.append((pa, oa))

    step = 1.0 / max(1, num_buckets)
    buckets: list[CalibrationBucket] = []
    for idx in range(num_buckets):
        low = round(idx * step, 4)
        high = round((idx + 1) * step, 4)
        is_last = idx == num_buckets - 1
        label = f"[{low:.1f}, {high:.1f}{']' if is_last else ')'}"
        in_bucket = [
            (p, y)
            for p, y in pairs
            if (low <= p <= high if is_last else low <= p < high)
        ]
        if not in_bucket:
            buckets.append(
                CalibrationBucket(
                    label=label,
                    low=low,
                    high=high,
                    count=0,
                    mean_predicted=0.0,
                    empirical_rate=0.0,
                    abs_calibration_error=0.0,
                )
            )
            continue
        cnt = len(in_bucket)
        mean_p = sum(p for p, _ in in_bucket) / cnt
        emp_r = sum(y for _, y in in_bucket) / cnt
        buckets.append(
            CalibrationBucket(
                label=label,
                low=low,
                high=high,
                count=cnt,
                mean_predicted=round(mean_p, 4),
                empirical_rate=round(emp_r, 4),
                abs_calibration_error=round(abs(mean_p - emp_r), 4),
            )
        )
    return buckets
