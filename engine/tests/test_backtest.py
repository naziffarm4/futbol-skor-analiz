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
    devig_1x2_odds,
    devig_two_way_odds,
    extract_market_1x2_probs,
    extract_market_over25_prob,
    extract_market_over_under25_probs,
    ht_ft_log_loss,
    ht_ft_multiclass_brier,
    ht_ft_top_k_hit,
    main,
    multiclass_brier_score,
    multiclass_log_loss,
    parse_historical_csv,
    ranked_probability_score,
    run_walk_forward,
)
from engine.config import PROJECT_ROOT

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

        # %5 marjlı 1X2 -> oranlar marj arındırma sonrası yine (0.50, 0.25, 0.25)
        ph2, pd2, pa2 = devig_1x2_odds(2.0 / 1.05, 4.0 / 1.05, 4.0 / 1.05)
        self.assertAlmostEqual(ph2 + pd2 + pa2, 1.0, places=8)
        self.assertAlmostEqual(ph2, 0.50, places=6)

        p_over, p_under = devig_two_way_odds(1.80, 2.00)
        inv_sum = (1.0 / 1.80) + (1.0 / 2.00)
        self.assertAlmostEqual(p_over, (1.0 / 1.80) / inv_sum, places=8)
        self.assertAlmostEqual(p_over + p_under, 1.0, places=8)

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


if __name__ == "__main__":
    unittest.main()
