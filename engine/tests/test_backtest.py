"""GÖREV-12: Walk-forward backtest metrikleri, sıfır gelecek sızıntısı ve CLI birim testleri."""

from __future__ import annotations

import math
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from engine.backtest import (
    DEFAULT_ALPHA_GRID,
    HONEST_VALUE_NOTE_TR,
    MODEL_MARKET,
    MODEL_MARKET_BLEND,
    MODEL_POST_FIX,
    MODEL_PRE_FIX,
    MODEL_TIME_DECAY,
    MatchEvaluationRecord,
    actual_ht_ft_code,
    binary_brier_score,
    binary_log_loss,
    compute_calibration_buckets,
    compute_ece,
    devig_1x2_odds,
    devig_power,
    devig_two_way_odds,
    evaluate_favorite_slice,
    extract_market_1x2_probs,
    extract_market_over25_prob,
    extract_market_over_under25_probs,
    ht_ft_log_loss,
    ht_ft_multiclass_brier,
    ht_ft_top_k_hit,
    main,
    multiclass_brier_score,
    multiclass_log_loss,
    paired_bootstrap_rps_diff,
    parse_historical_csv,
    ranked_probability_score,
    run_holdout_v3_evaluation,
    run_walk_forward,
)
from engine.config import PROJECT_ROOT
from engine.scrapers.sources.the_odds_api import devig_three_way, devig_two_way

FIXTURE_CSV = PROJECT_ROOT / "engine" / "tests" / "fixtures" / "sample_football_data.csv"


class BacktestEngineTests(unittest.TestCase):
    def test_rps_brier_and_log_loss_exact_hand_calculations(self) -> None:
        # Ev galibiyeti (2-0) -> one-hot = (1, 0, 0), tahmin = (0.60, 0.25, 0.15)
        # cum_1 = 0.60 - 1 = -0.40 -> 0.16; cum_2 = 0.85 - 1 = -0.15 -> 0.0225
        # RPS = 0.5 * (0.16 + 0.0225) = 0.09125
        rps_hw = ranked_probability_score(0.60, 0.25, 0.15, 2, 0)
        self.assertAlmostEqual(rps_hw, 0.09125, places=8)

        # Sıralama duyarlılığı: Ev kazandığında %100 Beraberlik (RPS=0.5) < %100 Deplasman (RPS=1.0)
        self.assertAlmostEqual(ranked_probability_score(0.0, 1.0, 0.0, 1, 0), 0.5, places=8)
        self.assertAlmostEqual(ranked_probability_score(0.0, 0.0, 1.0, 1, 0), 1.0, places=8)
        self.assertAlmostEqual(ranked_probability_score(1.0, 0.0, 0.0, 1, 0), 0.0, places=8)

        # Beraberlik (1-1) -> one-hot = (0, 1, 0), tahmin = (0.50, 0.30, 0.20)
        # Brier = (0.50-0)^2 + (0.30-1)^2 + (0.20-0)^2 = 0.25 + 0.49 + 0.04 = 0.78
        brier_draw = multiclass_brier_score(0.50, 0.30, 0.20, 1, 1)
        self.assertAlmostEqual(brier_draw, 0.78, places=8)

        # Log-Loss: -ln(0.30) ve sıfır olasılıkta 1e-15 kırpması
        ll_draw = multiclass_log_loss(0.50, 0.30, 0.20, 1, 1)
        self.assertAlmostEqual(ll_draw, -math.log(0.30), places=8)
        ll_zero = multiclass_log_loss(1.0, 0.0, 0.0, 0, 2)
        self.assertAlmostEqual(ll_zero, -math.log(1e-15), places=6)

        # İkili Üst 2.5 Brier ve Log-Loss
        self.assertAlmostEqual(binary_brier_score(0.65, True), 0.35**2, places=8)
        self.assertAlmostEqual(binary_brier_score(0.65, False), 0.65**2, places=8)
        self.assertAlmostEqual(binary_log_loss(0.65, True), -math.log(0.65), places=8)
        self.assertAlmostEqual(binary_log_loss(0.65, False), -math.log(0.35), places=8)

    def test_market_devigging_and_priority_cascade(self) -> None:
        # 2.00 / 4.00 / 4.00 -> ters toplam = 1.00 (marjsız tam 0.50, 0.25, 0.25)
        ph, pd, pa = devig_1x2_odds(2.0, 4.0, 4.0)
        self.assertAlmostEqual(ph, 0.50, places=8)
        self.assertAlmostEqual(pd, 0.25, places=8)
        self.assertAlmostEqual(pa, 0.25, places=8)

        # %5 marjlı 1X2 -> orantısal marj arındırmada (0.50, 0.25, 0.25); varsayılan Power
        # yönteminde ise favori olasılığı 0.50'nin üzerine çıkar, sürprizler 0.25'in altına iner.
        ph2_prop, pd2_prop, pa2_prop = devig_1x2_odds(
            2.0 / 1.05, 4.0 / 1.05, 4.0 / 1.05, method="proportional"
        )
        self.assertAlmostEqual(ph2_prop + pd2_prop + pa2_prop, 1.0, places=8)
        self.assertAlmostEqual(ph2_prop, 0.50, places=6)

        ph2_pow, pd2_pow, pa2_pow = devig_1x2_odds(2.0 / 1.05, 4.0 / 1.05, 4.0 / 1.05)
        self.assertAlmostEqual(ph2_pow + pd2_pow + pa2_pow, 1.0, places=10)
        self.assertGreater(ph2_pow, ph2_prop)
        self.assertLess(pd2_pow, pd2_prop)
        self.assertAlmostEqual(pd2_pow, pa2_pow, places=10)

        p_over_prop, p_under_prop = devig_two_way_odds(1.80, 2.00, method="proportional")
        inv_sum = (1.0 / 1.80) + (1.0 / 2.00)
        self.assertAlmostEqual(p_over_prop, (1.0 / 1.80) / inv_sum, places=8)
        self.assertAlmostEqual(p_over_prop + p_under_prop, 1.0, places=8)

        p_over_pow, p_under_pow = devig_two_way_odds(1.80, 2.00)
        self.assertAlmostEqual(p_over_pow + p_under_pow, 1.0, places=10)
        self.assertGreater(p_over_pow, p_over_prop)

        # Öncelik sırası: PSCH > B365H ve PC>2.5 > B365>2.5
        row = {
            "B365H": "1.50",
            "B365D": "4.00",
            "B365A": "6.00",
            "PSCH": "2.00",
            "PSCD": "4.00",
            "PSCA": "4.00",
            "B365>2.5": "1.90",
            "B365<2.5": "1.90",
            "PC>2.5": "1.50",
            "PC<2.5": "3.00",
        }
        probs_1x2, src_1x2 = extract_market_1x2_probs(row)
        assert probs_1x2 is not None
        self.assertEqual(src_1x2, "Pinnacle-Close")
        self.assertAlmostEqual(probs_1x2[0], 0.50, places=8)

        prob_o25, src_o25 = extract_market_over25_prob(row)
        assert prob_o25 is not None
        self.assertEqual(src_o25, "Pinnacle-Close")
        self.assertAlmostEqual(prob_o25, (1.0 / 1.50) / ((1.0 / 1.50) + (1.0 / 3.00)), places=8)

    def test_zero_future_leakage_in_walk_forward_runner(self) -> None:
        csv_text = FIXTURE_CSV.read_text(encoding="utf-8")
        base_matches = parse_historical_csv(csv_text, season_code="2526")
        self.assertEqual(len(base_matches), 10)

        base_wf = run_walk_forward(base_matches, warmup_matches=4)
        self.assertEqual(base_wf.evaluated_matches, 6)
        self.assertEqual(len(base_wf.records_by_model[MODEL_MARKET]), 6)

        # 1) Son haftanın (29/09/2025) maç skorlarını ve şutlarını aşırı uç değerlerle değiştir:
        # önceki haftaların (15/09 ve 22/09) hiçbir tahmini zerre değişmemeli!
        mutated_future = [
            replace(m, fthg=9, ftag=0, hthg=5, htag=0, hst=28.0, ast=0.0)
            if m.match_day.isoformat() == "2025-09-29"
            else m
            for m in base_matches
        ]
        mutated_wf = run_walk_forward(mutated_future, warmup_matches=4)

        for model_key in (MODEL_POST_FIX, MODEL_PRE_FIX):
            earlier_base = [
                r
                for r in base_wf.records_by_model[model_key]
                if r.match_date < "2025-09-29"
            ]
            earlier_mut = [
                r
                for r in mutated_wf.records_by_model[model_key]
                if r.match_date < "2025-09-29"
            ]
            self.assertEqual(len(earlier_base), 4)
            self.assertEqual(earlier_base, earlier_mut)

        # 2) Aynı gün (22/09/2025) saat 19:00'daki maçın skoru değiştiğinde aynı gün 21:45 maçının
        # tahmini de etkilenmemeli (yalnızca match_day < D geçmişi kullanılır).
        same_day_mutated = [
            replace(m, fthg=8, ftag=7, hst=25.0, ast=22.0)
            if (m.match_day.isoformat() == "2025-09-22" and m.home_team == "Konyaspor")
            else m
            for m in base_matches
        ]
        same_day_wf = run_walk_forward(same_day_mutated, warmup_matches=4)
        derby_base = next(
            r
            for r in base_wf.records_by_model[MODEL_POST_FIX]
            if r.match_date == "2025-09-22" and r.home_team == "Galatasaray"
        )
        derby_mut = next(
            r
            for r in same_day_wf.records_by_model[MODEL_POST_FIX]
            if r.match_date == "2025-09-22" and r.home_team == "Galatasaray"
        )
        self.assertEqual(derby_base.expected_home_goals, derby_mut.expected_home_goals)
        self.assertEqual(derby_base.expected_away_goals, derby_mut.expected_away_goals)
        self.assertEqual(derby_base.p_home, derby_mut.p_home)
        self.assertEqual(derby_base.p_over25, derby_mut.p_over25)

    def test_calibration_buckets_and_offline_cli(self) -> None:
        sample_records = [
            MatchEvaluationRecord(
                league_code="T1",
                season_code="2526",
                match_date="2025-09-15",
                home_team="A",
                away_team="B",
                home_goals=2,
                away_goals=1,
                p_home=0.65,
                p_draw=0.20,
                p_away=0.15,
                p_over25=0.55,
            )
        ]
        buckets = compute_calibration_buckets(sample_records, target="1x2", num_buckets=5)
        self.assertEqual(len(buckets), 5)
        self.assertEqual(sum(b.count for b in buckets), 3)

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_md = Path(tmp_dir) / "offline_report.md"
            rc = main(
                [
                    "--csv",
                    str(FIXTURE_CSV),
                    "--warmup",
                    "4",
                    "--output",
                    str(out_md),
                ]
            )
            self.assertEqual(rc, 0)
            self.assertTrue(out_md.exists())
            content = out_md.read_text(encoding="utf-8")
            self.assertIn("Post-Fix (Yeni Ölçek, max=10)", content)
            self.assertIn("Pre-Fix (Eski Ölçek, max=5)", content)
            self.assertIn("Piyasa (De-vigged Kapanış)", content)
            self.assertIn("Türkiye Süper Lig (`T1`)", content)

            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "engine.backtest",
                    "--csv",
                    str(FIXTURE_CSV),
                    "--warmup",
                    "4",
                ],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(proc.returncode, 0)
            self.assertIn("GÖREV-12 Walk-Forward Backtest", proc.stdout)

    def test_v2_ht_ft_metrics_and_ablation_cli(self) -> None:
        self.assertEqual(actual_ht_ft_code(1, 0, 2, 1), "1/1")
        self.assertEqual(actual_ht_ft_code(0, 0, 1, 0), "X/1")
        self.assertEqual(actual_ht_ft_code(0, 1, 2, 1), "2/1")
        self.assertEqual(actual_ht_ft_code(1, 1, 1, 1), "X/X")

        probs_9 = {
            "1/1": 0.40,
            "X/1": 0.20,
            "2/1": 0.05,
            "1/X": 0.05,
            "X/X": 0.12,
            "2/X": 0.03,
            "1/2": 0.02,
            "X/2": 0.05,
            "2/2": 0.08,
        }
        expected_brier = (0.40 - 1.0) ** 2 + sum(
            v**2 for k, v in probs_9.items() if k != "1/1"
        )
        self.assertAlmostEqual(ht_ft_multiclass_brier(probs_9, "1/1"), expected_brier, places=8)
        self.assertAlmostEqual(ht_ft_log_loss(probs_9, "1/1"), -math.log(0.40), places=8)
        self.assertTrue(ht_ft_top_k_hit(probs_9, "1/1", k=1))
        self.assertFalse(ht_ft_top_k_hit(probs_9, "X/1", k=1))
        self.assertTrue(ht_ft_top_k_hit(probs_9, "X/1", k=3))
        self.assertTrue(ht_ft_top_k_hit(probs_9, "X/X", k=3))
        self.assertFalse(ht_ft_top_k_hit(probs_9, "1/2", k=3))

        ou_pair, ou_src = extract_market_over_under25_probs(
            {"Avg>2.5": "1.80", "Avg<2.5": "2.00"}
        )
        assert ou_pair is not None
        self.assertEqual(ou_src, "MarketAvg-Open")
        self.assertAlmostEqual(ou_pair[0] + ou_pair[1], 1.0, places=8)

        csv_text = FIXTURE_CSV.read_text(encoding="utf-8")
        rows = parse_historical_csv(csv_text, season_code="2526")
        self.assertTrue(all(r.ht_ft_code is not None for r in rows))
        self.assertTrue(all(r.market_under25 is not None for r in rows))

        wf = run_walk_forward(rows, warmup_matches=4)
        for m_name in (MODEL_POST_FIX, MODEL_TIME_DECAY, MODEL_MARKET_BLEND):
            summary = wf.overall_summaries[m_name]
            self.assertEqual(summary.ht_ft_matches, 6)
            self.assertIsNotNone(summary.brier_ht_ft)
            self.assertIsNotNone(summary.log_loss_ht_ft)
            self.assertIsNotNone(summary.ht_ft_top1_accuracy)
            self.assertIsNotNone(summary.ht_ft_top3_accuracy)
            self.assertIsNotNone(summary.accuracy_over25)

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_v2 = Path(tmp_dir) / "v2_report.md"
            rc = main(
                [
                    "--csv",
                    str(FIXTURE_CSV),
                    "--warmup",
                    "4",
                    "--v2",
                    "--output",
                    str(out_v2),
                ]
            )
            self.assertEqual(rc, 0)
            v2_md = out_v2.read_text(encoding="utf-8")
            self.assertIn("GÖREV-13 Walk-Forward Backtest v2", v2_md)
            self.assertIn("9'lu İY/MS Brier", v2_md)
            self.assertIn("Hiperparametre Izgara Duyarlılık Analizi", v2_md)

    def test_power_devigging_properties_and_edge_cases(self) -> None:
        # 1) 3-yollu oranlarda overround > 1 iken p_i = q_i^k ve Σ p_i = 1 doğrulaması
        odds_3 = (1.45, 4.50, 7.50)
        p_pow = devig_power(odds_3)
        p_prop = devig_1x2_odds(*odds_3, method="proportional")
        self.assertEqual(len(p_pow), 3)
        self.assertAlmostEqual(sum(p_pow), 1.0, places=11)
        # Favori olasılığı orantısala göre artmalı, sürpriz olasılığı azalmalı
        self.assertGreater(p_pow[0], p_prop[0])
        self.assertLess(p_pow[2], p_prop[2])
        # Üs k her bileşende aynı olmalı: ln(p_i) / ln(q_i) = k (tol <= 1e-10)
        k_0 = math.log(p_pow[0]) / math.log(1.0 / odds_3[0])
        k_1 = math.log(p_pow[1]) / math.log(1.0 / odds_3[1])
        k_2 = math.log(p_pow[2]) / math.log(1.0 / odds_3[2])
        self.assertGreater(k_0, 1.0)
        self.assertAlmostEqual(k_0, k_1, places=9)
        self.assertAlmostEqual(k_0, k_2, places=9)

        # 2) the_odds_api üretim adaptörü varsayılan olarak Power de-vigging kullanmalı
        prod_3 = devig_three_way(*odds_3)
        assert prod_3 is not None
        self.assertAlmostEqual(prod_3[0], p_pow[0], places=10)
        self.assertAlmostEqual(prod_3[1], p_pow[1], places=10)
        self.assertAlmostEqual(prod_3[2], p_pow[2], places=10)

        prod_2 = devig_two_way(1.60, 2.30)
        assert prod_2 is not None
        p2_pow = devig_power((1.60, 2.30))
        self.assertAlmostEqual(prod_2[0], p2_pow[0], places=10)
        self.assertAlmostEqual(prod_2[0] + prod_2[1], 1.0, places=10)

        # 3) Sınır durumları: overround <= 1.0 (arbitraj/marjsız) orantısal fallback, ağır favori ve geçersiz girdi
        arb = devig_power((2.20, 4.20, 4.20))
        inv_arb = (1.0 / 2.20) + (2.0 / 4.20)
        self.assertLess(inv_arb, 1.0)
        self.assertAlmostEqual(sum(arb), 1.0, places=11)
        self.assertAlmostEqual(arb[0], (1.0 / 2.20) / inv_arb, places=10)

        heavy = devig_power((1.03, 18.0, 45.0))
        self.assertAlmostEqual(sum(heavy), 1.0, places=11)
        self.assertGreater(heavy[0], (1.0 / 1.03) / ((1.0 / 1.03) + (1.0 / 18.0) + (1.0 / 45.0)))

        with self.assertRaises(ValueError):
            devig_power((1.50,))
        with self.assertRaises(ValueError):
            devig_power((1.00, 2.50, 3.00))
        with self.assertRaises(ValueError):
            devig_power((float("nan"), 2.50))
        self.assertIsNone(devig_three_way(1.0, 3.0, 4.0))
        self.assertIsNone(devig_two_way(0.95, 2.10))

    def test_paired_bootstrap_rps_diff_determinism_and_known_ci(self) -> None:
        cand_recs: list[MatchEvaluationRecord] = []
        base_recs: list[MatchEvaluationRecord] = []
        for i in range(30):
            # Ev galibiyeti (2-0); aday model daha keskin (0.75, 0.15, 0.10), baz (0.50, 0.30, 0.20)
            cand_recs.append(
                MatchEvaluationRecord(
                    league_code="T1",
                    season_code="2526",
                    match_date=f"2025-10-{(i % 28) + 1:02d}",
                    home_team=f"H{i}",
                    away_team=f"A{i}",
                    home_goals=2,
                    away_goals=0,
                    p_home=0.75 if i % 2 == 0 else 0.70,
                    p_draw=0.15 if i % 2 == 0 else 0.20,
                    p_away=0.10,
                )
            )
            base_recs.append(
                MatchEvaluationRecord(
                    league_code="T1",
                    season_code="2526",
                    match_date=f"2025-10-{(i % 28) + 1:02d}",
                    home_team=f"H{i}",
                    away_team=f"A{i}",
                    home_goals=2,
                    away_goals=0,
                    p_home=0.50,
                    p_draw=0.30,
                    p_away=0.20,
                )
            )

        b1 = paired_bootstrap_rps_diff(cand_recs, base_recs, n_boot=1000, seed=42)
        b2 = paired_bootstrap_rps_diff(cand_recs, base_recs, n_boot=1000, seed=42)
        self.assertEqual(b1, b2)
        self.assertEqual(b1.paired_matches, 30)
        self.assertEqual(b1.n_boot, 1000)
        self.assertLess(b1.mean_delta_rps, 0.0)
        self.assertLessEqual(b1.ci_low, b1.mean_delta_rps)
        self.assertGreaterEqual(b1.ci_high, b1.mean_delta_rps)
        self.assertLess(b1.ci_high, 0.0)
        self.assertTrue(b1.significant_95)
        self.assertEqual(b1.p_value_two_sided, 0.0)

        # Birebir aynı kayıtlar karşılaştırıldığında ΔRPS = 0 ve anlamsız (CI = [0, 0])
        b_same = paired_bootstrap_rps_diff(base_recs, base_recs, n_boot=1000, seed=42)
        self.assertEqual(b_same.mean_delta_rps, 0.0)
        self.assertEqual(b_same.ci_low, 0.0)
        self.assertEqual(b_same.ci_high, 0.0)
        self.assertFalse(b_same.significant_95)

        fav_slice = evaluate_favorite_slice(cand_recs, low=0.6, high=0.8)
        self.assertEqual(fav_slice.count, 30)
        self.assertAlmostEqual(fav_slice.empirical_rate, 1.0, places=5)
        ece_val = compute_ece(compute_calibration_buckets(cand_recs, target="1x2"))
        self.assertGreater(ece_val, 0.0)

    def test_alpha_grid_full_range_and_strict_holdout_zero_leakage(self) -> None:
        # 1) α ızgarası 0.0'dan 1.0'a tam aralığı kapsamalı
        self.assertEqual(DEFAULT_ALPHA_GRID[0], 0.0)
        self.assertEqual(DEFAULT_ALPHA_GRID[-1], 1.0)
        self.assertGreaterEqual(len(DEFAULT_ALPHA_GRID), 10)
        self.assertEqual(list(DEFAULT_ALPHA_GRID), sorted(DEFAULT_ALPHA_GRID))

        # 2) 2425+2526 Seçim vs 2627 Hold-Out sızıntısız ayrım doğrulaması
        csv_text = FIXTURE_CSV.read_text(encoding="utf-8")
        m_2425 = parse_historical_csv(csv_text, season_code="2425", devig_method="power")
        m_2526 = parse_historical_csv(csv_text, season_code="2526", devig_method="power")
        m_2627 = parse_historical_csv(csv_text, season_code="2627", devig_method="power")

        m_2425_prp = parse_historical_csv(csv_text, season_code="2425", devig_method="proportional")
        m_2526_prp = parse_historical_csv(csv_text, season_code="2526", devig_method="proportional")
        m_2627_prp = parse_historical_csv(csv_text, season_code="2627", devig_method="proportional")

        v3_base = run_holdout_v3_evaluation(
            [*m_2425, *m_2526, *m_2627],
            matches_proportional=[*m_2425_prp, *m_2526_prp, *m_2627_prp],
            selection_seasons=("2425", "2526"),
            holdout_seasons=("2627",),
            warmup_matches=4,
            bootstrap_samples=200,
            bootstrap_seed=42,
        )
        self.assertEqual(v3_base.selection_result.evaluated_matches, 12)
        self.assertEqual(v3_base.holdout_result.evaluated_matches, 6)
        self.assertTrue(
            all(
                r.season in {"2425", "2526"}
                for r in v3_base.selection_result.records_by_model[MODEL_POST_FIX]
            )
        )
        self.assertTrue(
            all(
                r.season == "2627"
                for r in v3_base.holdout_result.records_by_model[MODEL_POST_FIX]
            )
        )

        # 2627 Hold-Out skor ve oranlarını uç değerlerle boz:
        # 2425+2526 seçim metrikleri ve seçilen (ξ*, α*) zerre değişmemeli!
        m_2627_corrupted = [
            replace(m, fthg=0, ftag=8, hthg=0, htag=4, market_1x2=(0.05, 0.10, 0.85))
            for m in m_2627
        ]
        v3_corrupted = run_holdout_v3_evaluation(
            [*m_2425, *m_2526, *m_2627_corrupted],
            selection_seasons=("2425", "2526"),
            holdout_seasons=("2627",),
            warmup_matches=4,
            bootstrap_samples=200,
            bootstrap_seed=42,
        )
        self.assertEqual(v3_base.selected_xi, v3_corrupted.selected_xi)
        self.assertEqual(v3_base.grid_best_alpha, v3_corrupted.grid_best_alpha)
        self.assertEqual(v3_base.xi_grid_selection, v3_corrupted.xi_grid_selection)
        self.assertEqual(v3_base.alpha_grid_selection, v3_corrupted.alpha_grid_selection)
        self.assertEqual(
            v3_base.selection_result.overall_summaries,
            v3_corrupted.selection_result.overall_summaries,
        )
        self.assertEqual(v3_base.bootstrap_selection, v3_corrupted.bootstrap_selection)
        self.assertNotEqual(
            v3_base.holdout_result.overall_summaries[MODEL_POST_FIX].rps,
            v3_corrupted.holdout_result.overall_summaries[MODEL_POST_FIX].rps,
        )

        # CLI --v3 çevrimdışı uçtan uca üretim testi
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_p = Path(tmp_dir)
            f2425 = tmp_p / "2425.csv"
            f2526 = tmp_p / "2526.csv"
            f2627 = tmp_p / "2627.csv"
            for fp in (f2425, f2526, f2627):
                fp.write_text(csv_text, encoding="utf-8")
            out_v3 = tmp_p / "v3_report.md"
            rc = main(
                [
                    "--csv",
                    str(f2425),
                    str(f2526),
                    str(f2627),
                    "--warmup",
                    "4",
                    "--v3",
                    "--bootstrap-samples",
                    "100",
                    "--output",
                    str(out_v3),
                ]
            )
            self.assertEqual(rc, 0)
            v3_md = out_v3.read_text(encoding="utf-8")
            self.assertIn("GÖREV-14 Walk-Forward Backtest v3", v3_md)
            self.assertIn(HONEST_VALUE_NOTE_TR, v3_md)
            self.assertIn("Power Marj Arındırma", v3_md)
            self.assertIn("`1.00`", v3_md)


if __name__ == "__main__":
    unittest.main()
