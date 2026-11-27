"""Dixon-Coles düzeltmeli Poisson skor olasılık matrisi ve güven oranı hesaplayıcısı."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from engine.models.schemas import HT_FT_LABELS_TR, HtFtProbability, ScoreProbability
from engine.predictors.ratings import DEFAULT_AVG_AWAY_GOALS, DEFAULT_AVG_HOME_GOALS

DEFAULT_DIXON_COLES_RHO = -0.10
DEFAULT_MAX_GOALS = 10
MIN_EXPECTED_GOALS = 0.15
MIN_HALF_EXPECTED_GOALS = 0.03
MIN_SECOND_HALF_EXPECTED_GOALS = 0.05
MAX_EXPECTED_GOALS = 4.75
DEFAULT_HT_SHARE = 0.43
MIN_HT_SHARE = 0.25
MAX_HT_SHARE = 0.65

_HT_FT_TIE_ORDER: tuple[str, ...] = (
    "1/1",
    "X/1",
    "X/X",
    "2/2",
    "X/2",
    "1/X",
    "2/X",
    "2/1",
    "1/2",
)


def poisson_pmf(goals: int, expected_goals: float) -> float:
    """Bağımsız Poisson olasılık kütle fonksiyonu P(X = goals | expected_goals)."""
    if goals < 0 or expected_goals <= 0.0:
        return 0.0
    return math.exp(-expected_goals) * (expected_goals**goals) / math.factorial(goals)


def dixon_coles_tau(
    home_goals: int,
    away_goals: int,
    lam: float,
    mu: float,
    rho: float = DEFAULT_DIXON_COLES_RHO,
) -> float:
    """Dixon-Coles (1997) düşük skorlu maç (0-0, 0-1, 1-0, 1-1) korelasyon düzeltme çarpanı."""
    if home_goals == 0 and away_goals == 0:
        tau = 1.0 - lam * mu * rho
    elif home_goals == 0 and away_goals == 1:
        tau = 1.0 + lam * rho
    elif home_goals == 1 and away_goals == 0:
        tau = 1.0 + mu * rho
    elif home_goals == 1 and away_goals == 1:
        tau = 1.0 - rho
    else:
        return 1.0
    return max(0.05, tau)


def calculate_expected_goals(
    home_attack: float,
    away_defense: float,
    away_attack: float,
    home_defense: float,
    avg_home_goals: float = DEFAULT_AVG_HOME_GOALS,
    avg_away_goals: float = DEFAULT_AVG_AWAY_GOALS,
    home_advantage: float | None = None,
) -> tuple[float, float]:
    """Ev sahibi (lambda) ve deplasman (mu) beklenen gol parametrelerini hesaplar."""
    _ = home_advantage  # İç saha avantajı avg_home_goals / avg_away_goals oranında taşınır.
    raw_lam = avg_home_goals * home_attack * away_defense
    raw_mu = avg_away_goals * away_attack * home_defense
    lam = min(MAX_EXPECTED_GOALS, max(MIN_EXPECTED_GOALS, raw_lam))
    mu = min(MAX_EXPECTED_GOALS, max(MIN_EXPECTED_GOALS, raw_mu))
    return round(lam, 4), round(mu, 4)


def _outcome_sign(home_goals: int, away_goals: int) -> str:
    if home_goals > away_goals:
        return "1"
    if home_goals == away_goals:
        return "X"
    return "2"


def _build_bounded_matrix(
    lam: float,
    mu: float,
    *,
    min_xg: float,
    max_goals: int = DEFAULT_MAX_GOALS,
    rho: float = DEFAULT_DIXON_COLES_RHO,
) -> list[list[float]]:
    safe_lam = min(MAX_EXPECTED_GOALS, max(min_xg, lam))
    safe_mu = min(MAX_EXPECTED_GOALS, max(min_xg, mu))

    home_probs = [poisson_pmf(x, safe_lam) for x in range(max_goals + 1)]
    away_probs = [poisson_pmf(y, safe_mu) for y in range(max_goals + 1)]

    raw_matrix: list[list[float]] = []
    total_mass = 0.0
    for x in range(max_goals + 1):
        row: list[float] = []
        for y in range(max_goals + 1):
            cell = home_probs[x] * away_probs[y] * dixon_coles_tau(x, y, safe_lam, safe_mu, rho)
            row.append(cell)
            total_mass += cell
        raw_matrix.append(row)

    if total_mass <= 0.0:
        uniform = 1.0 / ((max_goals + 1) ** 2)
        return [[uniform for _ in range(max_goals + 1)] for _ in range(max_goals + 1)]

    return [[cell / total_mass for cell in row] for row in raw_matrix]


def build_score_matrix(
    lam: float,
    mu: float,
    *,
    max_goals: int = DEFAULT_MAX_GOALS,
    rho: float = DEFAULT_DIXON_COLES_RHO,
) -> list[list[float]]:
    """0..max_goals aralığında toplamı 1.0'a normalize edilmiş Dixon-Coles / Poisson matrisi üretir."""
    return _build_bounded_matrix(
        lam,
        mu,
        min_xg=MIN_EXPECTED_GOALS,
        max_goals=max_goals,
        rho=rho,
    )


def calculate_confidence_rate(
    top_score_prob: float,
    outcome_max_prob: float,
    *,
    sample_matches: int = 10,
) -> float:
    """En olası skor olasılığı, baskın maç sonucu olasılığı ve veri derinliğinden güven oranı üretir."""
    score_signal = min(1.0, max(0.0, top_score_prob / 0.22))
    outcome_signal = min(1.0, max(0.0, outcome_max_prob))
    depth_factor = min(1.0, 0.55 + 0.45 * (max(0, sample_matches) / 10.0))

    raw = (0.60 * score_signal + 0.40 * outcome_signal) * depth_factor
    return round(min(0.95, max(0.15, raw)), 4)


@dataclass(slots=True)
class PoissonPredictionResult:
    """Maç bazlı beklenen goller, 0..max_goals olasılık matrisi, İY/MS dağılımı ve olası skorlar."""

    expected_home_goals: float
    expected_away_goals: float
    matrix: list[list[float]]
    predicted_home_score: int
    predicted_away_score: int
    top_scores: list[ScoreProbability]
    confidence_rate: float
    home_win_prob: float
    draw_prob: float
    away_win_prob: float
    over_2_5_prob: float
    expected_ht_home_goals: float = 0.0
    expected_ht_away_goals: float = 0.0
    predicted_ht_home_score: int = 0
    predicted_ht_away_score: int = 0
    ht_ft_prediction: str = "X/X"
    top_ht_ft: list[HtFtProbability] = field(default_factory=list)


def predict_score_distribution(
    *,
    home_attack: float,
    away_defense: float,
    away_attack: float,
    home_defense: float,
    avg_home_goals: float = DEFAULT_AVG_HOME_GOALS,
    avg_away_goals: float = DEFAULT_AVG_AWAY_GOALS,
    home_advantage: float | None = None,
    sample_matches: int = 10,
    max_goals: int = DEFAULT_MAX_GOALS,
    top_k: int = 3,
    rho: float = DEFAULT_DIXON_COLES_RHO,
    home_ht_share: float | None = None,
    away_ht_share: float | None = None,
    home_ht_attack_share: float = DEFAULT_HT_SHARE,
    away_ht_concede_share: float = DEFAULT_HT_SHARE,
    away_ht_attack_share: float = DEFAULT_HT_SHARE,
    home_ht_concede_share: float = DEFAULT_HT_SHARE,
) -> PoissonPredictionResult:
    """Takım katsayılarından Dixon-Coles tam saha ve iki aşamalı İY/MS dağılımlarını üretir."""
    lam, mu = calculate_expected_goals(
        home_attack=home_attack,
        away_defense=away_defense,
        away_attack=away_attack,
        home_defense=home_defense,
        avg_home_goals=avg_home_goals,
        avg_away_goals=avg_away_goals,
        home_advantage=home_advantage,
    )
    matrix = build_score_matrix(lam, mu, max_goals=max_goals, rho=rho)

    scored_cells: list[tuple[float, int, int]] = []
    home_win = 0.0
    draw = 0.0
    away_win = 0.0
    over_2_5 = 0.0

    for x, row in enumerate(matrix):
        for y, prob in enumerate(row):
            scored_cells.append((prob, x, y))
            if x > y:
                home_win += prob
            elif x == y:
                draw += prob
            else:
                away_win += prob
            if x + y >= 3:
                over_2_5 += prob

    # Olasılığa göre azalan; eşitlikte beklenen gole yakınlığa göre deterministik sıralama
    scored_cells.sort(
        key=lambda item: (-item[0], abs(item[1] - lam) + abs(item[2] - mu), item[1] + item[2])
    )

    best_prob, pred_home, pred_away = scored_cells[0]
    top_scores = [
        ScoreProbability(score=f"{x}-{y}", prob=round(prob, 4))
        for prob, x, y in scored_cells[: max(1, top_k)]
    ]

    dominant_outcome = max(home_win, draw, away_win)
    confidence = calculate_confidence_rate(
        best_prob,
        dominant_outcome,
        sample_matches=sample_matches,
    )

    # İki aşamalı (İlk Yarı + İkinci Yarı) ortak dağılım ve İY/MS olasılıkları
    raw_sh = (
        home_ht_share
        if home_ht_share is not None
        else 0.5 * (home_ht_attack_share + away_ht_concede_share)
    )
    raw_sa = (
        away_ht_share
        if away_ht_share is not None
        else 0.5 * (away_ht_attack_share + home_ht_concede_share)
    )
    s_h = min(MAX_HT_SHARE, max(MIN_HT_SHARE, raw_sh))
    s_a = min(MAX_HT_SHARE, max(MIN_HT_SHARE, raw_sa))

    lam_ht = max(MIN_HALF_EXPECTED_GOALS, lam * s_h)
    mu_ht = max(MIN_HALF_EXPECTED_GOALS, mu * s_a)
    lam_2h = max(MIN_SECOND_HALF_EXPECTED_GOALS, lam - lam_ht)
    mu_2h = max(MIN_SECOND_HALF_EXPECTED_GOALS, mu - mu_ht)

    half_rho = rho * 0.5
    ht_matrix = _build_bounded_matrix(
        lam_ht, mu_ht, min_xg=MIN_HALF_EXPECTED_GOALS, max_goals=max_goals, rho=half_rho
    )
    sh_matrix = _build_bounded_matrix(
        lam_2h, mu_2h, min_xg=MIN_HALF_EXPECTED_GOALS, max_goals=max_goals, rho=half_rho
    )

    ht_ft_mass: dict[str, float] = {code: 0.0 for code in _HT_FT_TIE_ORDER}
    total_joint_mass = 0.0
    for h1 in range(max_goals + 1):
        for h2 in range(max_goals + 1 - h1):
            ft_h = h1 + h2
            for a1 in range(max_goals + 1):
                p_ht = ht_matrix[h1][a1]
                ht_sign = _outcome_sign(h1, a1)
                for a2 in range(max_goals + 1 - a1):
                    ft_a = a1 + a2
                    joint_p = p_ht * sh_matrix[h2][a2]
                    code = f"{ht_sign}/{_outcome_sign(ft_h, ft_a)}"
                    ht_ft_mass[code] += joint_p
                    total_joint_mass += joint_p

    if total_joint_mass > 0.0:
        ht_ft_probs = {code: mass / total_joint_mass for code, mass in ht_ft_mass.items()}
    else:
        ht_ft_probs = {code: (1.0 if code == "X/X" else 0.0) for code in _HT_FT_TIE_ORDER}

    ranked_ht_ft = sorted(
        ht_ft_probs.items(),
        key=lambda item: (-item[1], _HT_FT_TIE_ORDER.index(item[0])),
    )
    ht_ft_prediction = ranked_ht_ft[0][0]
    top_ht_ft = [
        HtFtProbability(
            code=code,
            label=HT_FT_LABELS_TR[code],
            prob=round(prob, 4),
        )
        for code, prob in ranked_ht_ft[: max(1, top_k)]
    ]

    # Garantili 0 <= h1 <= pred_home ve 0 <= a1 <= pred_away alt kümesinde en olası İY skoru
    valid_splits: list[tuple[float, int, int]] = []
    for h1 in range(pred_home + 1):
        h2 = pred_home - h1
        for a1 in range(pred_away + 1):
            a2 = pred_away - a1
            split_p = ht_matrix[h1][a1] * sh_matrix[h2][a2]
            valid_splits.append((split_p, h1, a1))

    valid_splits.sort(
        key=lambda item: (
            -item[0],
            abs(item[1] - lam_ht) + abs(item[2] - mu_ht),
            item[1] + item[2],
        )
    )
    max_split_p = valid_splits[0][0]
    target_ht_sign = ht_ft_prediction.split("/")[0]
    sign_aligned = [
        item
        for item in valid_splits
        if _outcome_sign(item[1], item[2]) == target_ht_sign and item[0] >= 0.55 * max_split_p
    ]
    chosen_ht = sign_aligned[0] if sign_aligned else valid_splits[0]
    pred_ht_home, pred_ht_away = chosen_ht[1], chosen_ht[2]

    return PoissonPredictionResult(
        expected_home_goals=lam,
        expected_away_goals=mu,
        matrix=matrix,
        predicted_home_score=pred_home,
        predicted_away_score=pred_away,
        top_scores=top_scores,
        confidence_rate=confidence,
        home_win_prob=round(home_win, 4),
        draw_prob=round(draw, 4),
        away_win_prob=round(away_win, 4),
        over_2_5_prob=round(over_2_5, 4),
        expected_ht_home_goals=round(lam_ht, 4),
        expected_ht_away_goals=round(mu_ht, 4),
        predicted_ht_home_score=pred_ht_home,
        predicted_ht_away_score=pred_ht_away,
        ht_ft_prediction=ht_ft_prediction,
        top_ht_ft=top_ht_ft,
    )
