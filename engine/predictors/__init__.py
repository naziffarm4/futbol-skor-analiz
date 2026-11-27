"""Dixon-Coles / Poisson skor tahmin, sakatlık etki ve Türkçe takım analiz motoru."""

from engine.predictors.analyst import MatchAnalysisTexts, generate_match_analysis_texts
from engine.predictors.poisson import (
    DEFAULT_MAX_GOALS,
    PoissonPredictionResult,
    build_score_matrix,
    calculate_confidence_rate,
    calculate_expected_goals,
    dixon_coles_tau,
    poisson_pmf,
    predict_score_distribution,
)
from engine.predictors.ratings import (
    INJURY_PENALTY_MATRIX,
    InjuryDegradation,
    LeagueBaseline,
    TeamRatingProfile,
    apply_injuries_to_profile,
    build_team_ratings,
    calculate_injury_degradation,
    calculate_league_baseline,
    defense_vulnerability_to_rating,
    offense_ratio_to_rating,
)
from engine.predictors.service import (
    MatchPredictionBundle,
    PredictionService,
    PredictionServiceResult,
    run_prediction_pipeline,
)

__all__ = [
    "DEFAULT_MAX_GOALS",
    "INJURY_PENALTY_MATRIX",
    "InjuryDegradation",
    "LeagueBaseline",
    "MatchAnalysisTexts",
    "MatchPredictionBundle",
    "PoissonPredictionResult",
    "PredictionService",
    "PredictionServiceResult",
    "TeamRatingProfile",
    "apply_injuries_to_profile",
    "build_score_matrix",
    "build_team_ratings",
    "calculate_confidence_rate",
    "calculate_expected_goals",
    "calculate_injury_degradation",
    "calculate_league_baseline",
    "defense_vulnerability_to_rating",
    "dixon_coles_tau",
    "generate_match_analysis_texts",
    "offense_ratio_to_rating",
    "poisson_pmf",
    "predict_score_distribution",
    "run_prediction_pipeline",
]
