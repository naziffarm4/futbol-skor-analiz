"""GÖREV-11: xG/Şut harmanlaması, iki aşamalı İY/MS (HT/FT) modeli ve 5 kaynaklı analiz testleri."""

from __future__ import annotations

import itertools
import unittest
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

from pydantic import ValidationError

from engine.bulletin import build_bulletin_payload
from engine.config import DEFAULT_SEASON, LEAGUES, LeagueId
from engine.models import (
    VALID_HT_FT_CODES,
    HtFtProbability,
    ImpactLevel,
    Injury,
    League,
    Match,
    MatchStatus,
    PlayerPosition,
    Prediction,
    ScoreProbability,
    Team,
    TeamAnalysis,
)
from engine.predictors import (
    PredictionService,
    build_team_ratings,
    calculate_injury_degradation,
    generate_match_analysis_texts,
    predict_score_distribution,
)
from engine.runner import RunnerStatus, run_full_cycle


@dataclass(slots=True)
class _MockTeamMetrics:
    xg_for_per_match: float | None = None
    xg_against_per_match: float | None = None
    xg_is_derived: bool = False
    shots_for_per_match: float | None = None
    shots_against_per_match: float | None = None
    sot_for_per_match: float | None = None
    sot_against_per_match: float | None = None
    corners_for_per_match: float | None = None
    corners_against_per_match: float | None = None
    first_half_attack_share: float | None = None
    first_half_concede_share: float | None = None
    ht_goals_for: int | None = None
    ft_goals_for_fd: int | None = None
    ht_goals_against: int | None = None
    ft_goals_against_fd: int | None = None
    espn_rank: int | None = None
    espn_points: int | None = None
    sources_matched: list[str] = field(default_factory=list)


@dataclass
class _MockMultiSourceLeagueResult:
    league: League
    teams: list[Team]
    matches: list[Match]
    injuries: list[Injury]
    persisted: bool = False
    team_metrics: dict[int, Any] = field(default_factory=dict)
    sources_used: list[str] = field(default_factory=list)
    sources_total: int = 5
    source_diagnostics: dict[str, dict[str, Any]] = field(default_factory=dict)


def _balanced_four_team_matches() -> list[Match]:
    base_dt = datetime(2026, 9, 15, 18, 0, tzinfo=UTC)
    rows = [
        (1, 1, 1, 2, 1, 1),
        (2, 1, 3, 4, 1, 1),
        (3, 2, 2, 3, 1, 1),
        (4, 2, 4, 1, 1, 1),
        (5, 3, 1, 3, 2, 1),
        (6, 3, 2, 4, 1, 2),
    ]
    matches = [
        Match(
            id=mid,
            league_id=LeagueId.PREMIER_LEAGUE,
            home_team_id=h,
            away_team_id=a,
            match_date=base_dt + timedelta(days=rnd * 7),
            round=rnd,
            status=MatchStatus.FINISHED,
            home_score=hs,
            away_score=as_,
        )
        for mid, rnd, h, a, hs, as_ in rows
    ]
    matches.append(
        Match(
            id=7,
            league_id=LeagueId.PREMIER_LEAGUE,
            home_team_id=1,
            away_team_id=4,
            match_date=base_dt + timedelta(days=28),
            round=4,
            status=MatchStatus.SCHEDULED,
        )
    )
    return matches


class HtFtAndXgEngineTests(unittest.TestCase):
    def test_xg_and_sot_65_35_blend_in_team_ratings(self) -> None:
        matches = _balanced_four_team_matches()
        goal_only = build_team_ratings(matches, injuries=())

        metrics = {
            1: _MockTeamMetrics(
                xg_for_per_match=2.20,
                xg_against_per_match=0.80,
                shots_for_per_match=16.5,
                sot_for_per_match=6.8,
                sot_against_per_match=3.0,
                corners_for_per_match=7.2,
                corners_against_per_match=3.5,
                espn_rank=1,
                espn_points=28,
                sources_matched=["ESPN", "Football-Data", "Understat", "Transfermarkt"],
            ),
            2: {
                "xg_for_per_match": 1.10,
                "xg_against_per_match": 1.40,
                "sot_for_per_match": 3.8,
                "sot_against_per_match": 4.8,
            },
            3: {
                "xg_for_per_match": 0.90,
                "xg_against_per_match": 1.75,
                "sot_for_per_match": 2.9,
                "sot_against_per_match": 5.9,
            },
        }
        blended = build_team_ratings(matches, injuries=(), team_metrics=metrics)

        # Yüksek xG/isabetli şut üreten Takım 1'in hücum ve savunma puanı saf gol modelini aşmalı
        self.assertGreater(blended[1].base_attack, goal_only[1].base_attack)
        self.assertLess(blended[1].base_defense, goal_only[1].base_defense)
        self.assertGreater(blended[1].adjusted_offense_rating, goal_only[1].adjusted_offense_rating)
        self.assertGreater(blended[1].adjusted_defense_rating, goal_only[1].adjusted_defense_rating)

        # %65 gerçek gol + %35 baskı formülünün analitik kontrolü
        avg_xg = (2.20 + 1.10 + 0.90) / 3.0
        avg_sot = (6.8 + 3.8 + 2.9) / 3.0
        expected_pressure_att = 0.70 * (2.20 / avg_xg) + 0.30 * (6.8 / avg_sot)
        expected_base_att = round(0.65 * goal_only[1].base_attack + 0.35 * expected_pressure_att, 4)
        self.assertAlmostEqual(blended[1].base_attack, expected_base_att, places=3)

        # Dış metriği olmayan Takım 4 saf gol oranında kalmalı
        self.assertEqual(blended[4].base_attack, goal_only[4].base_attack)
        self.assertEqual(blended[4].base_defense, goal_only[4].base_defense)

    def test_first_half_share_extraction_clamping_and_default_fallback(self) -> None:
        matches = _balanced_four_team_matches()
        metrics = {
            1: {"first_half_attack_share": 0.54, "first_half_concede_share": 0.36},
            2: {"first_half_attack_share": 0.92, "first_half_concede_share": 0.10},
            3: _MockTeamMetrics(
                ht_goals_for=9,
                ft_goals_for_fd=15,
                ht_goals_against=3,
                ft_goals_against_fd=14,
            ),
        }
        profiles = build_team_ratings(matches, team_metrics=metrics)

        self.assertAlmostEqual(profiles[1].first_half_attack_share, 0.54, places=4)
        self.assertAlmostEqual(profiles[1].first_half_concede_share, 0.36, places=4)

        # Uç değerler [0.25, 0.65] bandına kırpılmalı
        self.assertEqual(profiles[2].first_half_attack_share, 0.65)
        self.assertEqual(profiles[2].first_half_concede_share, 0.25)

        # Ham İY/MS gol sayılarından sönümlü pay çıkarımı
        expected_t3_att = round((9 + 4.0 * 0.43) / (15 + 4.0), 4)
        expected_t3_def = round((3 + 4.0 * 0.43) / (14 + 4.0), 4)
        self.assertAlmostEqual(profiles[3].first_half_attack_share, expected_t3_att, places=4)
        self.assertAlmostEqual(profiles[3].first_half_concede_share, expected_t3_def, places=4)

        # Veri olmayan Takım 4 varsayılan %43 İY / %57 İkinci Yarı payını almalı
        self.assertEqual(profiles[4].first_half_attack_share, 0.43)
        self.assertEqual(profiles[4].first_half_concede_share, 0.43)

    def test_injury_multi_source_confidence_weighting(self) -> None:
        ref = date(2026, 11, 27)
        verified_fw = Injury(
            team_id=1,
            player_name="Kylian Mbappe",
            position=PlayerPosition.FW,
            reason="Arka adale sakatlığı",
            return_date=None,
            impact_level=ImpactLevel.HIGH,
            verified_by_multiple_sources=True,
            sources=["Transfermarkt", "SportsGambler"],
        )
        uncertain_single_fw = Injury(
            team_id=1,
            player_name="Kylian Mbappe",
            position=PlayerPosition.FW,
            reason="Arka adale sakatlığı",
            return_date="Bilinmiyor",
            impact_level=ImpactLevel.HIGH,
            verified_by_multiple_sources=False,
            sources=["Transfermarkt"],
        )
        expired_single_fw = Injury(
            team_id=1,
            player_name="Kylian Mbappe",
            position=PlayerPosition.FW,
            reason="Arka adale sakatlığı",
            return_date=date(2026, 11, 10),
            impact_level=ImpactLevel.HIGH,
            verified_by_multiple_sources=False,
        )
        future_single_fw = Injury(
            team_id=1,
            player_name="Kylian Mbappe",
            position=PlayerPosition.FW,
            reason="Arka adale sakatlığı",
            return_date=date(2026, 12, 20),
            impact_level=ImpactLevel.HIGH,
            verified_by_multiple_sources=False,
        )

        deg_verified = calculate_injury_degradation([verified_fw], reference_date=ref)
        deg_uncertain = calculate_injury_degradation([uncertain_single_fw], reference_date=ref)
        deg_expired = calculate_injury_degradation([expired_single_fw], reference_date=ref)
        deg_future = calculate_injury_degradation([future_single_fw], reference_date=ref)

        # FW HIGH baz kaybı %16 -> 1.0x ağırlıkta %16.0, 0.75x ağırlıkta %12.0
        self.assertAlmostEqual(deg_verified.attack_drop_pct, 16.0, places=2)
        self.assertAlmostEqual(deg_future.attack_drop_pct, 16.0, places=2)
        self.assertAlmostEqual(deg_uncertain.attack_drop_pct, 12.0, places=2)
        self.assertAlmostEqual(deg_expired.attack_drop_pct, 12.0, places=2)
        self.assertLess(deg_verified.attack_multiplier, deg_uncertain.attack_multiplier)

    def test_poisson_ht_ft_invariants_across_diverse_grid(self) -> None:
        attack_grid = [0.12, 0.45, 0.95, 1.35, 2.25, 3.80]
        away_grid = [0.15, 0.55, 1.10, 1.85, 3.40]
        share_pairs = [(0.25, 0.65), (0.43, 0.43), (0.62, 0.30)]

        combo_count = 0
        for h_att, a_att, (sh, sa) in itertools.product(attack_grid, away_grid, share_pairs):
            combo_count += 1
            res = predict_score_distribution(
                home_attack=h_att,
                away_defense=1.0,
                away_attack=a_att,
                home_defense=1.0,
                home_advantage=1.0,
                home_ht_share=sh,
                away_ht_share=sa,
                sample_matches=10,
            )
            self.assertGreaterEqual(res.predicted_ht_home_score, 0)
            self.assertGreaterEqual(res.predicted_ht_away_score, 0)
            self.assertGreaterEqual(res.predicted_home_score, res.predicted_ht_home_score)
            self.assertGreaterEqual(res.predicted_away_score, res.predicted_ht_away_score)
            self.assertIn(res.ht_ft_prediction, VALID_HT_FT_CODES)
            self.assertEqual(len(res.top_ht_ft), 3)
            self.assertEqual(res.top_ht_ft[0].code, res.ht_ft_prediction)
            self.assertGreaterEqual(res.top_ht_ft[0].prob, res.top_ht_ft[1].prob)
            self.assertGreaterEqual(res.top_ht_ft[1].prob, res.top_ht_ft[2].prob)
            self.assertTrue(all(bool(item.label) for item in res.top_ht_ft))

            # Pydantic Prediction model doğrulayıcısından hatasız geçmeli
            pred_model = Prediction(
                match_id=combo_count,
                predicted_home_score=res.predicted_home_score,
                predicted_away_score=res.predicted_away_score,
                predicted_ht_home_score=res.predicted_ht_home_score,
                predicted_ht_away_score=res.predicted_ht_away_score,
                ht_ft_prediction=res.ht_ft_prediction,
                top_ht_ft_json=res.top_ht_ft,
                confidence_rate=res.confidence_rate,
                top_scores_json=res.top_scores,
            )
            self.assertGreaterEqual(
                pred_model.predicted_home_score, pred_model.predicted_ht_home_score
            )

        self.assertGreaterEqual(combo_count, 90)

    def test_pydantic_ht_ft_validator_and_db_payload_stripping(self) -> None:
        with self.assertRaises(ValidationError):
            Prediction(
                match_id=1,
                predicted_home_score=1,
                predicted_away_score=1,
                predicted_ht_home_score=2,
                predicted_ht_away_score=0,
                confidence_rate=0.55,
            )

        with self.assertRaises(ValidationError):
            Prediction(
                match_id=1,
                predicted_home_score=2,
                predicted_away_score=0,
                predicted_ht_home_score=1,
                predicted_ht_away_score=1,
                confidence_rate=0.55,
            )

        with self.assertRaises(ValidationError):
            HtFtProbability(code="3/1", label="Geçersiz", prob=0.2)

        auto_labeled = HtFtProbability(code="x/1", prob=0.28)
        self.assertEqual(auto_labeled.code, "X/1")
        self.assertEqual(auto_labeled.label, "Beraberlik / Ev")

        pred = Prediction(
            match_id=42,
            predicted_home_score=2,
            predicted_away_score=1,
            predicted_ht_home_score=1,
            predicted_ht_away_score=0,
            ht_ft_prediction="1/1",
            top_ht_ft_json=[HtFtProbability(code="1/1", label="Ev / Ev", prob=0.36)],
            confidence_rate=0.68,
            top_scores_json=[ScoreProbability(score="2-1", prob=0.18)],
        )
        pred_db = pred.to_db_payload()
        for non_sql in (
            "predicted_ht_home_score",
            "predicted_ht_away_score",
            "ht_ft_prediction",
            "top_ht_ft_json",
        ):
            self.assertNotIn(non_sql, pred_db)

        inj = Injury(
            team_id=5,
            player_name="Bukayo Saka",
            position=PlayerPosition.FW,
            reason="Kas zorlanması",
            impact_level=ImpactLevel.MEDIUM,
            verified_by_multiple_sources=True,
            sources=["Transfermarkt", "SportsGambler"],
        )
        inj_db = inj.to_db_payload()
        self.assertNotIn("verified_by_multiple_sources", inj_db)
        self.assertNotIn("sources", inj_db)

        ta = TeamAnalysis(
            match_id=42,
            match_overview_text="Genel bakış metni.",
            home_analysis_text="Ev sahibi analiz metni.",
            away_analysis_text="Deplasman analiz metni.",
            ht_ft_reasoning_text="Detaylı İY/MS gerekçesi.",
            home_offense_rating=71.2,
            home_defense_rating=68.4,
            away_offense_rating=58.0,
            away_defense_rating=54.3,
        )
        self.assertNotIn("ht_ft_reasoning_text", ta.to_db_payload())

    def test_comparative_analyst_ht_ft_reasoning_text(self) -> None:
        matches = _balanced_four_team_matches()
        injuries = [
            Injury(
                team_id=1,
                player_name="Martin Odegaard",
                position=PlayerPosition.MID,
                reason="Ayak bileği sakatlığı",
                impact_level=ImpactLevel.HIGH,
                verified_by_multiple_sources=True,
                sources=["Transfermarkt", "SportsGambler"],
            ),
            Injury(
                team_id=4,
                player_name="Yedek Stoper",
                position=PlayerPosition.DEF,
                reason="Hafif ağrı",
                return_date="?",
                impact_level=ImpactLevel.LOW,
                verified_by_multiple_sources=False,
                sources=["Transfermarkt"],
            ),
        ]
        metrics = {
            1: _MockTeamMetrics(
                xg_for_per_match=2.05,
                xg_against_per_match=0.88,
                shots_for_per_match=15.8,
                sot_for_per_match=6.2,
                corners_for_per_match=6.9,
                first_half_attack_share=0.48,
                first_half_concede_share=0.38,
                espn_rank=2,
                espn_points=26,
            ),
            4: _MockTeamMetrics(
                xg_for_per_match=1.02,
                xg_against_per_match=1.74,
                shots_for_per_match=9.4,
                sot_for_per_match=3.3,
                corners_for_per_match=3.8,
                first_half_attack_share=0.37,
                first_half_concede_share=0.46,
                espn_rank=15,
                espn_points=11,
            ),
        }
        profiles = build_team_ratings(matches, injuries=injuries, team_metrics=metrics)
        poisson_res = predict_score_distribution(
            home_attack=profiles[1].adjusted_home_attack,
            away_defense=profiles[4].adjusted_away_defense,
            away_attack=profiles[4].adjusted_away_attack,
            home_defense=profiles[1].adjusted_home_defense,
            home_advantage=profiles[1].home_advantage,
            home_ht_attack_share=profiles[1].first_half_attack_share,
            away_ht_concede_share=profiles[4].first_half_concede_share,
            away_ht_attack_share=profiles[4].first_half_attack_share,
            home_ht_concede_share=profiles[1].first_half_concede_share,
            sample_matches=6,
        )
        texts = generate_match_analysis_texts(
            home_name="Arsenal",
            away_name="Everton",
            home_profile=profiles[1],
            away_profile=profiles[4],
            poisson_result=poisson_res,
            round_number=14,
        )

        reasoning = texts.ht_ft_reasoning_text
        self.assertEqual(len(reasoning.split("\n\n")), 2)
        self.assertTrue(reasoning.startswith("Neden İlk Yarı "))
        self.assertIn(
            f"{poisson_res.predicted_ht_home_score}-{poisson_res.predicted_ht_away_score}",
            reasoning,
        )
        self.assertIn(
            f"{poisson_res.predicted_home_score}-{poisson_res.predicted_away_score}",
            reasoning,
        )
        self.assertIn(poisson_res.ht_ft_prediction, reasoning)
        self.assertIn("2.05 xG", reasoning)
        self.assertIn("6.2 isabetli şut", reasoning)
        self.assertIn("6.9", reasoning)
        self.assertIn("%48", reasoning)
        self.assertIn("çift kaynak onaylı", reasoning)
        self.assertIn("Martin Odegaard", reasoning)

        # Ana 3 metin çoklu kaynak varken de tam 2 paragraf kalmalı
        for main_txt in (
            texts.match_overview_text,
            texts.home_analysis_text,
            texts.away_analysis_text,
        ):
            self.assertEqual(len(main_txt.split("\n\n")), 2)
            self.assertNotIn("xg", main_txt.casefold())

    def test_end_to_end_bulletin_emits_five_source_and_ht_ft_schema(self) -> None:
        five_sources = ["ESPN", "Football-Data", "Understat", "Transfermarkt", "SportsGambler"]

        def build_league_res(lid: LeagueId, idx: int) -> _MockMultiSourceLeagueResult:
            meta = LEAGUES[lid]
            h_id = idx * 10 + 1
            a_id = idx * 10 + 2
            return _MockMultiSourceLeagueResult(
                league=League(
                    id=lid, name=meta.name, country=meta.country, season=DEFAULT_SEASON
                ),
                teams=[
                    Team(id=h_id, league_id=lid, name=f"{meta.name} Lider", short_name="LDR"),
                    Team(id=a_id, league_id=lid, name=f"{meta.name} Konuk", short_name="KNK"),
                ],
                matches=[
                    Match(
                        id=idx * 100 + 1,
                        league_id=lid,
                        home_team_id=h_id,
                        away_team_id=a_id,
                        match_date=datetime(2026, 10, 10, 18, 0, tzinfo=UTC),
                        round=1,
                        status=MatchStatus.FINISHED,
                        home_score=3,
                        away_score=1,
                    ),
                    Match(
                        id=idx * 100 + 2,
                        league_id=lid,
                        home_team_id=h_id,
                        away_team_id=a_id,
                        match_date=datetime(2026, 10, 17, 18, 0, tzinfo=UTC),
                        round=2,
                        status=MatchStatus.SCHEDULED,
                    ),
                ],
                injuries=[
                    Injury(
                        id=idx * 10 + 1,
                        team_id=a_id,
                        player_name=f"Kilit Oyuncu {idx}",
                        position=PlayerPosition.DEF,
                        reason="Kırmızı kart cezası",
                        impact_level=ImpactLevel.HIGH,
                        verified_by_multiple_sources=True,
                        sources=["Transfermarkt", "SportsGambler"],
                    )
                ],
                team_metrics={
                    h_id: {
                        "xg_for_per_match": 2.15,
                        "xg_against_per_match": 0.90,
                        "sot_for_per_match": 6.1,
                        "corners_for_per_match": 6.5,
                        "first_half_attack_share": 0.49,
                        "espn_rank": 1,
                        "espn_points": 24,
                    },
                    a_id: {
                        "xg_for_per_match": 1.05,
                        "xg_against_per_match": 1.65,
                        "sot_for_per_match": 3.4,
                        "corners_for_per_match": 4.0,
                        "first_half_concede_share": 0.47,
                        "espn_rank": 12,
                        "espn_points": 13,
                    },
                },
                sources_used=list(five_sources),
                sources_total=5,
                source_diagnostics={
                    src: {"ok": True, "status": "ok", "records": 10} for src in five_sources
                },
            )

        mock_pipeline = MagicMock()
        mock_pipeline.run_league.side_effect = lambda lid, *, persist=False: build_league_res(
            lid, list(LEAGUES.keys()).index(lid) + 1
        )
        cycle = run_full_cycle(
            leagues=None,
            persist=False,
            only_next_round=True,
            status_tracker=RunnerStatus(),
            ingestion_pipeline=mock_pipeline,
            prediction_service=PredictionService(),
        )
        bulletin = build_bulletin_payload(cycle)

        self.assertEqual(bulletin["sources_used"], five_sources)
        self.assertEqual(bulletin["sources_count"], 5)
        self.assertEqual(bulletin["sources_total"], 5)
        self.assertIn("5 Kaynak Füzyonu", bulletin["data_source"])
        self.assertEqual(set(bulletin["source_diagnostics"].keys()), set(five_sources))
        self.assertEqual(bulletin["source_diagnostics"]["ESPN"]["records"], 40)

        for lg_meta in bulletin["leagues_meta"]:
            self.assertEqual(lg_meta["sources_count"], 5)
            self.assertEqual(lg_meta["sources_total"], 5)

        for lg in bulletin["leagues"]:
            self.assertEqual(lg["sources_used"], five_sources)
            self.assertEqual(lg["sources_count"], 5)
            self.assertEqual(lg["sources_total"], 5)
            for inj_item in lg["injuries"]:
                self.assertTrue(inj_item["verified_by_multiple_sources"])
                self.assertEqual(inj_item["sources"], ["Transfermarkt", "SportsGambler"])
            for m_item in lg["matches"]:
                pred_item = m_item["prediction"]
                self.assertGreaterEqual(
                    pred_item["predicted_home_score"], pred_item["predicted_ht_home_score"]
                )
                self.assertGreaterEqual(
                    pred_item["predicted_away_score"], pred_item["predicted_ht_away_score"]
                )
                self.assertIn(pred_item["ht_ft_prediction"], VALID_HT_FT_CODES)
                self.assertEqual(len(pred_item["top_ht_ft_json"]), 3)
                ta_item = m_item["team_analysis"]
                self.assertIn("Neden İlk Yarı", ta_item["ht_ft_reasoning_text"])
                self.assertTrue(m_item["away_injuries"][0]["verified_by_multiple_sources"])


if __name__ == "__main__":
    unittest.main()
