"""GÖREV-13: Üstel zaman sönümü (M2), 9 yönlü marjinal İY/MS, piyasa harmanı (M5) ve bülten sözleşme testleri."""

from __future__ import annotations

import itertools
import unittest
from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock

from engine.bulletin import build_bulletin_payload
from engine.config import DEFAULT_SEASON, LEAGUES, LeagueId
from engine.models.schemas import (
    ALL_HT_FT_CODES,
    League,
    Match,
    MatchStatus,
    Prediction,
    Team,
)
from engine.predictors import (
    DEFAULT_MARKET_BLEND_ALPHA,
    DEFAULT_TIME_DECAY_XI,
    PredictionService,
    build_team_ratings,
    calculate_league_baseline,
    generate_match_analysis_texts,
    normalized_shannon_entropy_1x2,
    predict_score_distribution,
    run_prediction_pipeline,
)
from engine.predictors.ratings import GOAL_RATIO_WEIGHT, PRIOR_MATCH_WEIGHT
from engine.runner import RunnerStatus, run_full_cycle


class MarketBlendAndTimeDecayTests(unittest.TestCase):
    def test_time_decay_zero_equivalence_and_recency_boost(self) -> None:
        base_dt = datetime(2026, 5, 1, 18, 0, tzinfo=UTC)
        # Takım 1 erken haftalarda gol atamazken son haftalarda farklı kazanıyor;
        # Takım 2 erken haftalarda farklı kazanırken son haftalarda gol atamıyor.
        # Ayrıca naive ve timezone-aware datetime karışımı güvenli çalışmalı.
        matches = [
            Match(
                id=1,
                league_id=LeagueId.SUPER_LIG,
                home_team_id=1,
                away_team_id=3,
                match_date=datetime(2026, 5, 1, 18, 0),  # naive datetime testi
                round=1,
                status=MatchStatus.FINISHED,
                home_score=0,
                away_score=2,
            ),
            Match(
                id=2,
                league_id=LeagueId.SUPER_LIG,
                home_team_id=2,
                away_team_id=4,
                match_date=base_dt + timedelta(days=2),
                round=1,
                status=MatchStatus.FINISHED,
                home_score=4,
                away_score=0,
            ),
            Match(
                id=3,
                league_id=LeagueId.SUPER_LIG,
                home_team_id=3,
                away_team_id=1,
                match_date=base_dt + timedelta(days=15),
                round=2,
                status=MatchStatus.FINISHED,
                home_score=2,
                away_score=0,
            ),
            Match(
                id=4,
                league_id=LeagueId.SUPER_LIG,
                home_team_id=4,
                away_team_id=2,
                match_date=base_dt + timedelta(days=17),
                round=2,
                status=MatchStatus.FINISHED,
                home_score=0,
                away_score=3,
            ),
            # 150 gün sonra yakın dönem maçları: Takım 1 form zirvesinde, Takım 2 düşüşte
            Match(
                id=5,
                league_id=LeagueId.SUPER_LIG,
                home_team_id=1,
                away_team_id=4,
                match_date=base_dt + timedelta(days=150),
                round=3,
                status=MatchStatus.FINISHED,
                home_score=4,
                away_score=0,
            ),
            Match(
                id=6,
                league_id=LeagueId.SUPER_LIG,
                home_team_id=2,
                away_team_id=3,
                match_date=base_dt + timedelta(days=151),
                round=3,
                status=MatchStatus.FINISHED,
                home_score=0,
                away_score=2,
            ),
            Match(
                id=7,
                league_id=LeagueId.SUPER_LIG,
                home_team_id=4,
                away_team_id=1,
                match_date=base_dt + timedelta(days=160),
                round=4,
                status=MatchStatus.FINISHED,
                home_score=0,
                away_score=3,
            ),
            Match(
                id=8,
                league_id=LeagueId.SUPER_LIG,
                home_team_id=3,
                away_team_id=2,
                match_date=base_dt + timedelta(days=162),
                round=4,
                status=MatchStatus.FINISHED,
                home_score=2,
                away_score=0,
            ),
        ]

        bl_zero = calculate_league_baseline(matches, time_decay_xi=0.0)
        n = len(matches)
        raw_h = sum(int(m.home_score or 0) for m in matches) / n
        raw_a = sum(int(m.away_score or 0) for m in matches) / n
        blend = min(1.0, n / 12.0)
        exp_avg_h = round(blend * raw_h + (1.0 - blend) * 1.45, 4)
        exp_avg_a = round(blend * raw_a + (1.0 - blend) * 1.15, 4)
        self.assertAlmostEqual(bl_zero.avg_home_goals, exp_avg_h, delta=1e-12)
        self.assertAlmostEqual(bl_zero.avg_away_goals, exp_avg_a, delta=1e-12)

        prof_zero = build_team_ratings(matches, time_decay_xi=0.0)
        avg_tg = (bl_zero.avg_home_goals + bl_zero.avg_away_goals) / 2.0
        t1 = prof_zero[1]
        exp_t1_overall = (t1.goals_for + PRIOR_MATCH_WEIGHT * avg_tg) / (
            (t1.played + PRIOR_MATCH_WEIGHT) * avg_tg
        )
        self.assertAlmostEqual(t1.base_attack, round(exp_t1_overall, 4), delta=1e-12)
        _ = GOAL_RATIO_WEIGHT

        # Sönümsüz modda Takım 1 ve Takım 2 toplamda birebir aynı golleri (7 attı, 4 yedi) üretti
        self.assertEqual(prof_zero[1].goals_for, prof_zero[2].goals_for)
        self.assertEqual(prof_zero[1].base_attack, prof_zero[2].base_attack)

        # Zaman sönümü aktifken yakın dönemde 7 gol atan Takım 1, erken dönemde atan Takım 2'yi aşmalı
        prof_dec = build_team_ratings(
            matches,
            time_decay_xi=0.006,
            reference_date=datetime(2026, 10, 12, 12, 0, tzinfo=UTC),
        )
        self.assertGreater(prof_dec[1].base_attack, prof_zero[1].base_attack)
        self.assertGreater(prof_dec[1].home_attack, prof_zero[1].home_attack)
        self.assertGreater(prof_dec[1].base_attack, prof_dec[2].base_attack)
        self.assertLess(prof_dec[1].base_defense, prof_dec[2].base_defense)

        # Tam sayı maç sayaçları Bayesian prior ve şema uyumu için değişmeden korunmalı
        for tid in (1, 2, 3, 4):
            self.assertEqual(prof_dec[tid].played, prof_zero[tid].played)
            self.assertEqual(prof_dec[tid].home_played, prof_zero[tid].home_played)
            self.assertEqual(prof_dec[tid].away_played, prof_zero[tid].away_played)
            self.assertIsInstance(prof_dec[tid].played, int)

        # date nesnesi ile çağrı da hatasız çalışmalı
        prof_date_ref = build_team_ratings(
            matches,
            time_decay_xi=DEFAULT_TIME_DECAY_XI,
            reference_date=date(2026, 10, 12),
        )
        self.assertGreater(prof_date_ref[1].base_attack, prof_date_ref[2].base_attack)

    def test_nine_way_ht_ft_and_marginal_consistency_with_and_without_market_blend(self) -> None:
        market_cases = [
            None,
            {"p_home": 0.62, "p_draw": 0.22, "p_away": 0.16, "p_over25": 0.64},
            {"p_home": 0.18, "p_draw": 0.24, "p_away": 0.58, "p_over25": 0.41},
            {"p_home": 0.35, "p_draw": 0.34, "p_away": 0.31},
            # Marjlı (toplamı > 1.0) ham olasılık girişi de otomatik normalize edilmeli
            {"p_home": 0.55, "p_draw": 0.30, "p_away": 0.20, "p_over25": 0.52},
        ]
        alphas = [None, 0.25, 0.65, 1.0]

        for mkt, alpha, (h_att, a_att) in itertools.product(
            market_cases, alphas, [(1.45, 0.85), (0.80, 1.50), (1.05, 1.05)]
        ):
            res = predict_score_distribution(
                home_attack=h_att,
                away_defense=1.05,
                away_attack=a_att,
                home_defense=0.95,
                sample_matches=12,
                market_probs=mkt,
                market_blend_alpha=alpha,
            )

            self.assertEqual(len(res.all_ht_ft), 9)
            self.assertEqual({h.code for h in res.all_ht_ft}, set(ALL_HT_FT_CODES))
            self.assertEqual(res.top_ht_ft, res.all_ht_ft[:3])
            self.assertEqual(res.ht_ft_prediction, res.all_ht_ft[0].code)

            for idx in range(8):
                self.assertGreaterEqual(res.all_ht_ft[idx].prob, res.all_ht_ft[idx + 1].prob)

            total_9 = sum(h.prob for h in res.all_ht_ft)
            self.assertAlmostEqual(total_9, 1.0, delta=1e-6)
            self.assertEqual(round(total_9, 4), 1.0)

            sum_ms_1 = round(sum(h.prob for h in res.all_ht_ft if h.code.endswith("/1")), 4)
            sum_ms_x = round(sum(h.prob for h in res.all_ht_ft if h.code.endswith("/X")), 4)
            sum_ms_2 = round(sum(h.prob for h in res.all_ht_ft if h.code.endswith("/2")), 4)
            self.assertEqual(sum_ms_1, round(res.home_win_prob, 4))
            self.assertEqual(sum_ms_x, round(res.draw_prob, 4))
            self.assertEqual(sum_ms_2, round(res.away_win_prob, 4))
            self.assertAlmostEqual(
                res.home_win_prob + res.draw_prob + res.away_win_prob, 1.0, delta=1e-6
            )

            self.assertAlmostEqual(res.over_25_prob + res.under_25_prob, 1.0, delta=1e-6)
            self.assertAlmostEqual(res.btts_yes_prob + res.btts_no_prob, 1.0, delta=1e-6)
            self.assertEqual(res.over_2_5_prob, res.over_25_prob)

            if mkt is None:
                self.assertFalse(res.market_blended)
                self.assertEqual(res.market_blend_weight, 0.0)
            else:
                expected_w = DEFAULT_MARKET_BLEND_ALPHA if alpha is None else alpha
                self.assertTrue(res.market_blended)
                self.assertAlmostEqual(res.market_blend_weight, expected_w, places=4)
                expected_clarity = round(
                    1.0
                    - normalized_shannon_entropy_1x2(
                        res.home_win_prob, res.draw_prob, res.away_win_prob
                    ),
                    4,
                )
                self.assertAlmostEqual(res.confidence_rate, expected_clarity, delta=0.001)

    def test_service_market_key_resolution_db_stripping_and_bulletin_contract(self) -> None:
        teams = [
            Team(id=11, league_id=LeagueId.SUPER_LIG, name="Fenerbahçe", short_name="FB"),
            Team(id=12, league_id=LeagueId.SUPER_LIG, name="Galatasaray", short_name="GS"),
            Team(id=13, league_id=LeagueId.SUPER_LIG, name="Beşiktaş", short_name="BJK"),
            Team(id=14, league_id=LeagueId.SUPER_LIG, name="Trabzonspor", short_name="TS"),
        ]
        base_dt = datetime(2026, 11, 1, 19, 0, tzinfo=UTC)
        matches = [
            Match(
                id=101,
                league_id=LeagueId.SUPER_LIG,
                home_team_id=11,
                away_team_id=13,
                match_date=base_dt,
                round=1,
                status=MatchStatus.FINISHED,
                home_score=2,
                away_score=1,
            ),
            Match(
                id=102,
                league_id=LeagueId.SUPER_LIG,
                home_team_id=12,
                away_team_id=14,
                match_date=base_dt + timedelta(days=1),
                round=1,
                status=MatchStatus.FINISHED,
                home_score=3,
                away_score=1,
            ),
            # 2. hafta SCHEDULED maçlar: biri normalize isimle, diğeri match.id ile eşleşecek
            Match(
                id=201,
                league_id=LeagueId.SUPER_LIG,
                home_team_id=11,
                away_team_id=12,
                match_date=base_dt + timedelta(days=7),
                round=2,
                status=MatchStatus.SCHEDULED,
            ),
            Match(
                id=202,
                league_id=LeagueId.SUPER_LIG,
                home_team_id=13,
                away_team_id=14,
                match_date=base_dt + timedelta(days=8),
                round=2,
                status=MatchStatus.SCHEDULED,
            ),
        ]

        market_odds = {
            ("fenerbahce", "galatasaray"): {
                "p_home": 0.24,
                "p_draw": 0.26,
                "p_away": 0.50,
                "p_over25": 0.63,
            },
            202: {
                "p_home": 0.56,
                "p_draw": 0.25,
                "p_away": 0.19,
                "p_over25": 0.54,
            },
        }

        svc_res = run_prediction_pipeline(
            matches=matches,
            teams=teams,
            market_odds=market_odds,
            persist=False,
        )
        assert not isinstance(svc_res, dict)
        self.assertEqual(len(svc_res.predictions), 2)

        for bundle in svc_res.bundles:
            pred: Prediction = bundle.prediction
            self.assertTrue(pred.market_blended)
            self.assertAlmostEqual(pred.market_blend_weight, DEFAULT_MARKET_BLEND_ALPHA, places=4)
            self.assertEqual(len(pred.all_ht_ft_json), 9)
            self.assertAlmostEqual(pred.p_home + pred.p_draw + pred.p_away, 1.0, delta=1e-4)
            self.assertAlmostEqual(pred.p_over25 + pred.p_under25, 1.0, delta=1e-4)
            self.assertAlmostEqual(pred.p_btts_yes + pred.p_btts_no, 1.0, delta=1e-4)

            # to_db_payload tüm yeni _non_db_fields alanlarını ayıklamalı
            db_payload = pred.to_db_payload()
            for stripped_field in (
                "all_ht_ft_json",
                "p_home",
                "p_draw",
                "p_away",
                "p_over25",
                "p_under25",
                "p_btts_yes",
                "p_btts_no",
                "market_blended",
                "market_blend_weight",
            ):
                self.assertNotIn(stripped_field, db_payload)

            # Türkçe analiz metinleri 2.5 Üst / KG Var ve piyasa kıyaslamasını doğal biçimde içermeli
            self.assertIn("2.5 Üst", bundle.team_analysis.match_overview_text)
            self.assertIn("KG Var", bundle.team_analysis.match_overview_text)
            self.assertIn("piyasa beklentisi", bundle.team_analysis.match_overview_text)
            self.assertIn("Poisson modeli", bundle.team_analysis.ht_ft_reasoning_text)
            self.assertIn("piyasa beklentisi", bundle.team_analysis.ht_ft_reasoning_text)

        # Bülten JSON sözleşmesi tüm yeni tahmin anahtarlarını eksiksiz üretmeli
        mock_pipeline = MagicMock()
        meta = LEAGUES[LeagueId.SUPER_LIG]
        mock_lg_res = MagicMock()
        mock_lg_res.league = League(
            id=LeagueId.SUPER_LIG, name=meta.name, country=meta.country, season=DEFAULT_SEASON
        )
        mock_lg_res.teams = teams
        mock_lg_res.matches = matches
        mock_lg_res.injuries = []
        mock_lg_res.team_metrics = {}
        mock_lg_res.sources_used = ["Transfermarkt", "Football-Data"]
        mock_lg_res.sources_total = 5
        mock_lg_res.source_diagnostics = {}
        mock_pipeline.run_league.return_value = mock_lg_res

        cycle = run_full_cycle(
            leagues=[LeagueId.SUPER_LIG],
            persist=False,
            only_next_round=True,
            status_tracker=RunnerStatus(),
            ingestion_pipeline=mock_pipeline,
            prediction_service=PredictionService(),
        )
        # Piyasa harmanlı tahmin paketlerini bültene bağlayıp sözleşmeyi doğrula
        cycle.prediction = svc_res
        bulletin = build_bulletin_payload(cycle)
        emitted_matches = bulletin["leagues"][0]["matches"]
        self.assertEqual(len(emitted_matches), 2)
        for m_dict in emitted_matches:
            p_dict = m_dict["prediction"]
            self.assertEqual(len(p_dict["all_ht_ft_json"]), 9)
            self.assertTrue(p_dict["market_blended"])
            self.assertAlmostEqual(
                p_dict["p_home"] + p_dict["p_draw"] + p_dict["p_away"], 1.0, delta=1e-4
            )
            self.assertAlmostEqual(p_dict["p_over25"] + p_dict["p_under25"], 1.0, delta=1e-4)
            self.assertAlmostEqual(p_dict["p_btts_yes"] + p_dict["p_btts_no"], 1.0, delta=1e-4)

    def test_analyst_market_agreement_vs_divergence_sentences(self) -> None:
        prof = build_team_ratings([], team_ids=[1, 2])
        agree_mkt = {"p_home": 0.58, "p_draw": 0.24, "p_away": 0.18}
        diverge_mkt = {"p_home": 0.18, "p_draw": 0.24, "p_away": 0.58}

        res_agree = predict_score_distribution(
            home_attack=1.40,
            away_defense=1.10,
            away_attack=0.80,
            home_defense=0.90,
            market_probs=agree_mkt,
        )
        txt_agree = generate_match_analysis_texts(
            home_name="Galatasaray",
            away_name="Konyaspor",
            home_profile=prof[1],
            away_profile=prof[2],
            poisson_result=res_agree,
            market_probs=agree_mkt,
        )
        self.assertIn("uzlaşarak", txt_agree.match_overview_text)
        self.assertIn("örtüşüyor", txt_agree.ht_ft_reasoning_text)

        res_diverge = predict_score_distribution(
            home_attack=1.40,
            away_defense=1.10,
            away_attack=0.80,
            home_defense=0.90,
            market_probs=diverge_mkt,
            market_blend_alpha=0.25,
        )
        txt_diverge = generate_match_analysis_texts(
            home_name="Galatasaray",
            away_name="Konyaspor",
            home_profile=prof[1],
            away_profile=prof[2],
            poisson_result=res_diverge,
            market_probs=diverge_mkt,
        )
        self.assertIn("yönelmesi", txt_diverge.match_overview_text)
        self.assertIn("ayrışıyor", txt_diverge.ht_ft_reasoning_text)


if __name__ == "__main__":
    unittest.main()
