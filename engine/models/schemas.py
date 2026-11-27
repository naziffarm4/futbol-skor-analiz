"""engine/db/schema.sql ile birebir uyumlu Pydantic v2 veri modelleri."""

from __future__ import annotations

import re
from datetime import date, datetime
from enum import StrEnum
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from engine.config import LeagueId

SCORE_PATTERN = re.compile(r"^\d+-\d+$")

HT_FT_LABELS_TR: dict[str, str] = {
    "1/1": "Ev / Ev",
    "1/X": "Ev / Beraberlik",
    "1/2": "Ev / Dep",
    "X/1": "Beraberlik / Ev",
    "X/X": "Beraberlik / Beraberlik",
    "X/2": "Beraberlik / Dep",
    "2/1": "Dep / Ev",
    "2/X": "Dep / Beraberlik",
    "2/2": "Dep / Dep",
}
VALID_HT_FT_CODES: frozenset[str] = frozenset(HT_FT_LABELS_TR.keys())


class MatchStatus(StrEnum):
    SCHEDULED = "SCHEDULED"
    FINISHED = "FINISHED"
    POSTPONED = "POSTPONED"


class PlayerPosition(StrEnum):
    GK = "GK"
    DEF = "DEF"
    MID = "MID"
    FW = "FW"


class ImpactLevel(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class DBModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)
    _non_db_fields: ClassVar[tuple[str, ...]] = ()

    def to_db_payload(self) -> dict[str, Any]:
        """Supabase insert/upsert işlemleri için None değerli otomatik alanları ve SQL dışı alanları ayıklar."""
        data = self.model_dump(mode="json")
        for auto_field in ("id", "created_at", "updated_at"):
            if auto_field in data and data[auto_field] is None:
                del data[auto_field]
        for extra_field in self._non_db_fields:
            data.pop(extra_field, None)
        return data


class League(DBModel):
    id: LeagueId
    name: str = Field(..., min_length=1, max_length=120)
    country: str = Field(..., min_length=1, max_length=80)
    season: str = Field(..., min_length=4, max_length=20)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class Team(DBModel):
    id: int | None = None
    league_id: LeagueId
    name: str = Field(..., min_length=1, max_length=150)
    short_name: str | None = Field(default=None, max_length=50)
    logo_url: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class Match(DBModel):
    id: int | None = None
    league_id: LeagueId
    home_team_id: int = Field(..., gt=0)
    away_team_id: int = Field(..., gt=0)
    match_date: datetime
    round: int = Field(..., gt=0)
    status: MatchStatus = MatchStatus.SCHEDULED
    home_score: int | None = Field(default=None, ge=0)
    away_score: int | None = Field(default=None, ge=0)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @model_validator(mode="after")
    def validate_distinct_teams(self) -> Match:
        if self.home_team_id == self.away_team_id:
            raise ValueError("home_team_id ve away_team_id aynı olamaz.")
        return self


class Injury(DBModel):
    _non_db_fields: ClassVar[tuple[str, ...]] = ("verified_by_multiple_sources", "sources")

    id: int | None = None
    team_id: int = Field(..., gt=0)
    player_name: str = Field(..., min_length=1, max_length=150)
    position: PlayerPosition
    reason: str = Field(..., min_length=1, max_length=255)
    return_date: date | str | None = None
    impact_level: ImpactLevel
    verified_by_multiple_sources: bool = False
    sources: list[str] = Field(default_factory=lambda: ["Transfermarkt"])
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ScoreProbability(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    score: str
    prob: float = Field(..., ge=0.0, le=1.0)

    @field_validator("score")
    @classmethod
    def validate_score_format(cls, value: str) -> str:
        if not SCORE_PATTERN.match(value):
            raise ValueError("Skor formatı 'ev-deplasman' şeklinde olmalıdır (örn: '2-1').")
        return value


class HtFtProbability(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    code: str
    label: str = ""
    prob: float = Field(..., ge=0.0, le=1.0)

    @field_validator("code")
    @classmethod
    def validate_ht_ft_code(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in VALID_HT_FT_CODES:
            raise ValueError(
                f"İY/MS kodu {sorted(VALID_HT_FT_CODES)} değerlerinden biri olmalıdır."
            )
        return normalized

    @model_validator(mode="after")
    def populate_default_label(self) -> HtFtProbability:
        if not self.label:
            self.label = HT_FT_LABELS_TR[self.code]
        return self


class Prediction(DBModel):
    _non_db_fields: ClassVar[tuple[str, ...]] = (
        "predicted_ht_home_score",
        "predicted_ht_away_score",
        "ht_ft_prediction",
        "top_ht_ft_json",
    )

    id: int | None = None
    match_id: int = Field(..., gt=0)
    predicted_home_score: int = Field(..., ge=0)
    predicted_away_score: int = Field(..., ge=0)
    predicted_ht_home_score: int = Field(default=0, ge=0)
    predicted_ht_away_score: int = Field(default=0, ge=0)
    ht_ft_prediction: str = Field(default="X/X")
    top_ht_ft_json: list[HtFtProbability] = Field(default_factory=list)
    confidence_rate: float = Field(..., ge=0.0)
    top_scores_json: list[ScoreProbability] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("ht_ft_prediction")
    @classmethod
    def validate_ht_ft_prediction(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in VALID_HT_FT_CODES:
            raise ValueError(
                f"ht_ft_prediction {sorted(VALID_HT_FT_CODES)} değerlerinden biri olmalıdır."
            )
        return normalized

    @model_validator(mode="after")
    def validate_ft_gte_ht(self) -> Prediction:
        if (
            self.predicted_ht_home_score > self.predicted_home_score
            or self.predicted_ht_away_score > self.predicted_away_score
        ):
            raise ValueError(
                "Maç sonucu skoru ilk yarı skorundan küçük olamaz (FT >= HT zorunludur)."
            )
        return self


class TeamAnalysis(DBModel):
    _non_db_fields: ClassVar[tuple[str, ...]] = ("ht_ft_reasoning_text",)

    id: int | None = None
    match_id: int = Field(..., gt=0)
    match_overview_text: str = Field(..., min_length=1)
    home_analysis_text: str = Field(..., min_length=1)
    away_analysis_text: str = Field(..., min_length=1)
    ht_ft_reasoning_text: str = Field(default="")
    home_offense_rating: float
    home_defense_rating: float
    away_offense_rating: float
    away_defense_rating: float
    created_at: datetime | None = None
    updated_at: datetime | None = None
