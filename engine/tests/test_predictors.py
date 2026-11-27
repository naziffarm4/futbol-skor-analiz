"""GÖREV-03: Skor tahmin motoru, sakatlık etki modeli ve analiz üreticisi test paketi."""

from __future__ import annotations

import math
import random
import re
import unittest
from datetime import UTC, datetime, timedelta
from typing import Any

from engine.config import PROJECT_ROOT, LeagueId
from engine.models.schemas import (
    ImpactLevel,
    Injury,
    Match,
    MatchStatus,
    PlayerPosition,
    Prediction,
    Team,
    TeamAnalysis,
)
from engine.predictors import (
    DEFAULT_MAX_GOALS,
    PredictionService,
    build_score_matrix,
    build_team_ratings,
    calculate_confidence_rate,
    calculate_expected_goals,
    calculate_injury_degradation,
    calculate_league_baseline,
    generate_match_analysis_texts,
    predict_score_distribution,
    run_prediction_pipeline,
)


def _extract_sql_columns(table_name: str) -> set[str]:
    sql_text = (PROJECT_ROOT / "engine" / "db" / "schema.sql").read_text(encoding="utf-8")
    pattern = re.compile(
        rf"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+{table_name}\s*\((.*?)\);",
        re.DOTALL | re.IGNORECASE,
    )
    match = pattern.search(sql_text)
    assert match is not None, f"{table_name} tablosu schema.sql içinde bulunamadı"
    cols: set[str] = set()
    for raw_line in match.group(1).splitlines():
        line = raw_line.strip().rstrip(",")
        if not line or line.startswith("--"):
            continue
        if line.upper().startswith(("CONSTRAINT ", "CHECK ", "UNIQUE ", "PRIMARY KEY", "FOREIGN KEY")):
            continue
        cols.add(line.split()[0])
    return cols


def _sample_league_dataset() -> tuple[list[Team], list[Match]]:
    teams = [
        Team(id=1, league_id=LeagueId.SUPER_LIG, name="Galatasaray", short_name="GS"),
        Team(id=2, league_id=LeagueId.SUPER_LIG, name="Fenerbahçe", short_name="FB"),
        Team(id=3, league_id=LeagueId.SUPER_LIG, name="Konyaspor", short_name="KON"),
        Team(id=4, league_id=LeagueId.SUPER_LIG, name="Sivasspor", short_name="SVS"),
    ]
    base_dt = datetime(2026, 10, 1, 17, 0, tzinfo=UTC)
    finished_raw = [
        # (id, round, home, away, hs, as)
        (1, 1, 1, 3, 3, 0),
        (2, 1, 2, 4, 2, 0),
        (3, 2, 3, 2, 0, 2),
        (4, 2, 4, 1, 1, 3),
        (5, 3, 1, 4, 4, 1),
        (6, 3, 2, 3, 2, 1),
        (7, 4, 3, 4, 1, 1),
        (8, 4, 2, 1, 1, 1),
    ]
    matches: list[Match] = []
    for mid, rnd, h_id, a_id, hs, as_ in finished_raw:
        matches.append(
            Match(
                id=mid,
                league_id=LeagueId.SUPER_LIG,
                home_team_id=h_id,
                away_team_id=a_id,
                match_date=base_dt + timedelta(days=rnd * 7),
                round=rnd,
                status=MatchStatus.FINISHED,
                home_score=hs,
                away_score=as_,
            )
        )

    # 5. hafta sıradaki (SCHEDULED) maçlar
    matches.extend(
        [
            Match(
                id=9,
                league_id=LeagueId.SUPER_LIG,
                home_team_id=1,
                away_team_id=2,
                match_date=base_dt + timedelta(days=35),
                round=5,
                status=MatchStatus.SCHEDULED,
            ),
            Match(
                id=10,
                league_id=LeagueId.SUPER_LIG,
                home_team_id=3,
                away_team_id=4,
                match_date=base_dt + timedelta(days=35, hours=3),
                round=5,
                status=MatchStatus.SCHEDULED,
            ),
        ]
    )
    return teams, matches


class _FakeResponse:
    def __init__(self, data: list[dict[str, Any]]) -> None:
        self.data = data


class _FakeTableQuery:
    def __init__(self, store: dict[str, list[Any]], name: str) -> None:
        self._store = store
        self._name = name
        self._op = ""
        self._payload: Any = None
        self._on_conflict: str | None = None

    def upsert(self, payload: Any, *, on_conflict: str | None = None) -> _FakeTableQuery:
        self._op = "upsert"
        self._payload = payload
        self._on_conflict = on_conflict
        return self

    def select(self, _cols: str) -> _FakeTableQuery:
        self._op = "select"
        return self

    def eq(self, _col: str, _val: Any) -> _FakeTableQuery:
        return self

    def execute(self) -> _FakeResponse:
        if self._op == "upsert":
            self._store.setdefault(self._name, []).append(
                {"on_conflict": self._on_conflict, "rows": self._payload}
            )
            return _FakeResponse(self._payload if isinstance(self._payload, list) else [self._payload])
        return _FakeResponse(self._store.get(f"seed:{self._name}", []))


class _FakeSupabaseClient:
    def __init__(self, seed_matches: list[dict[str, Any]] | None = None) -> None:
        self.recorded: dict[str, list[Any]] = {}
        if seed_matches is not None:
            self.recorded["seed:matches"] = seed_matches

    def table(self, name: str) -> _FakeTableQuery:
        return _FakeTableQuery(self.recorded, name)


class PredictorEngineTests(unittest.TestCase):
    def test_ratings_calculation(self) -> None:
        _, matches = _sample_league_dataset()
        base_profiles = build_team_ratings(matches, injuries=())

        # Güçlü hücum eden Takım 1, zayıf Takım 3'ten daha yüksek baz hücum katsayısına sahip olmalı
        self.assertGreater(base_profiles[1].base_attack, base_profiles[3].base_attack)
        # Az gol yiyen Takım 2, çok gol yiyen Takım 4'ten daha düşük gol yeme çarpanına ve daha yüksek savunma puanına sahip olmalı
        self.assertLess(base_profiles[2].base_defense, base_profiles[4].base_defense)
        self.assertGreater(
            base_profiles[2].adjusted_defense_rating,
            base_profiles[4].adjusted_defense_rating,
        )
        self.assertGreater(base_profiles[1].home_advantage, 1.0)

        for prof in base_profiles.values():
            self.assertGreaterEqual(prof.adjusted_offense_rating, 0.0)
            self.assertLessEqual(prof.adjusted_offense_rating, 100.0)
            self.assertGreaterEqual(prof.adjusted_defense_rating, 0.0)
            self.assertLessEqual(prof.adjusted_defense_rating, 100.0)

        # Forvet (FW - HIGH: -%16) ve Kaleci (GK - HIGH: +%22 zaafiyet) ve Orta Saha (MID - MEDIUM: -%6 hücum, +%5 savunma)
        injuries = [
            Injury(
                team_id=1,
                player_name="Mauro Icardi",
                position=PlayerPosition.FW,
                reason="Çapraz bağ sakatlığı",
                impact_level=ImpactLevel.HIGH,
                verified_by_multiple_sources=True,
            ),
            Injury(
                team_id=2,
                player_name="Dominik Livakovic",
                position=PlayerPosition.GK,
                reason="Omuz sakatlığı",
                impact_level=ImpactLevel.HIGH,
                verified_by_multiple_sources=True,
            ),
            Injury(
                team_id=3,
                player_name="Orta Saha Oyuncusu",
                position=PlayerPosition.MID,
                reason="Sarı kart cezası",
                impact_level=ImpactLevel.MEDIUM,
                verified_by_multiple_sources=True,
            ),
        ]

        fw_deg = calculate_injury_degradation([injuries[0]])
        self.assertAlmostEqual(fw_deg.attack_multiplier, 0.84, places=4)
        self.assertAlmostEqual(fw_deg.defense_vulnerability_multiplier, 1.0, places=4)

        gk_deg = calculate_injury_degradation([injuries[1]])
        self.assertAlmostEqual(gk_deg.attack_multiplier, 1.0, places=4)
        self.assertGreaterEqual(gk_deg.defense_vulnerability_pct, 18.0)
        self.assertLessEqual(gk_deg.defense_vulnerability_pct, 25.0)

        mid_deg = calculate_injury_degradation([injuries[2]])
        self.assertAlmostEqual(mid_deg.attack_drop_pct, 6.0, places=2)
        self.assertAlmostEqual(mid_deg.defense_vulnerability_pct, 5.0, places=2)

        injured_profiles = build_team_ratings(matches, injuries=injuries)

        # Takım 1: FW sakatlığı sonrası hücum katsayısı ve 0-100 hücum reytingi düşmeli, savunma değişmemeli
        self.assertLess(injured_profiles[1].adjusted_attack, base_profiles[1].adjusted_attack)
        self.assertLess(
            injured_profiles[1].adjusted_offense_rating,
            base_profiles[1].adjusted_offense_rating,
        )
        self.assertEqual(
            injured_profiles[1].adjusted_defense_rating,
            base_profiles[1].adjusted_defense_rating,
        )

        # Takım 2: GK sakatlığı sonrası gol yeme çarpanı artmalı ve 0-100 savunma direnci düşmeli
        self.assertGreater(injured_profiles[2].adjusted_defense, base_profiles[2].adjusted_defense)
        self.assertLess(
            injured_profiles[2].adjusted_defense_rating,
            base_profiles[2].adjusted_defense_rating,
        )

        # Takım 3: MID sakatlığı sonrası hem hücum hem savunma direnci düşmeli
        self.assertLess(
            injured_profiles[3].adjusted_offense_rating,
            base_profiles[3].adjusted_offense_rating,
        )
        self.assertLess(
            injured_profiles[3].adjusted_defense_rating,
            base_profiles[3].adjusted_defense_rating,
        )

    def test_poisson_probability_matrix(self) -> None:
        self.assertEqual(DEFAULT_MAX_GOALS, 10)
        lam, mu = calculate_expected_goals(
            home_attack=1.35,
            away_defense=1.10,
            away_attack=0.95,
            home_defense=0.85,
            avg_home_goals=1.52,
            avg_away_goals=1.18,
            home_advantage=1.90,
        )
        self.assertAlmostEqual(lam, round(1.52 * 1.35 * 1.10, 4), places=4)
        self.assertAlmostEqual(mu, round(1.18 * 0.95 * 0.85, 4), places=4)

        for test_lam, test_mu in [(0.45, 0.35), (1.65, 1.05), (3.10, 2.40)]:
            matrix = build_score_matrix(test_lam, test_mu)
            self.assertEqual(len(matrix), DEFAULT_MAX_GOALS + 1)
            self.assertTrue(all(len(row) == DEFAULT_MAX_GOALS + 1 for row in matrix))
            total_prob = sum(sum(row) for row in matrix)
            self.assertAlmostEqual(total_prob, 1.0, delta=0.001)
            self.assertTrue(all(0.0 <= cell <= 1.0 for row in matrix for cell in row))

        res = predict_score_distribution(
            home_attack=1.40,
            away_defense=1.15,
            away_attack=0.85,
            home_defense=0.80,
            home_advantage=1.25,
            sample_matches=12,
        )
        self.assertEqual(len(res.top_scores), 3)
        self.assertEqual(
            f"{res.predicted_home_score}-{res.predicted_away_score}",
            res.top_scores[0].score,
        )
        # İlk 3 skor olasılığa göre azalan sırada olmalı
        self.assertGreaterEqual(res.top_scores[0].prob, res.top_scores[1].prob)
        self.assertGreaterEqual(res.top_scores[1].prob, res.top_scores[2].prob)

        outcome_sum = res.home_win_prob + res.draw_prob + res.away_win_prob
        self.assertAlmostEqual(outcome_sum, 1.0, delta=0.01)
        self.assertGreater(res.confidence_rate, 0.0)
        self.assertLessEqual(res.confidence_rate, 1.0)

        # Veri derinliği arttığında güven oranı da artmalı
        low_depth_conf = calculate_confidence_rate(0.16, 0.55, sample_matches=1)
        high_depth_conf = calculate_confidence_rate(0.16, 0.55, sample_matches=12)
        self.assertGreater(high_depth_conf, low_depth_conf)

    def test_analyst_text_generation(self) -> None:
        _, matches = _sample_league_dataset()
        injuries = [
            Injury(
                team_id=1,
                player_name="Victor Osimhen",
                position=PlayerPosition.FW,
                reason="Arka adale yırtığı",
                impact_level=ImpactLevel.HIGH,
            ),
            Injury(
                team_id=2,
                player_name="Rodrigo Becao",
                position=PlayerPosition.DEF,
                reason="Kırmızı kart cezası",
                impact_level=ImpactLevel.HIGH,
            ),
        ]
        profiles = build_team_ratings(matches, injuries=injuries)
        poisson_res = predict_score_distribution(
            home_attack=profiles[1].adjusted_home_attack,
            away_defense=profiles[2].adjusted_away_defense,
            away_attack=profiles[2].adjusted_away_attack,
            home_defense=profiles[1].adjusted_home_defense,
            home_advantage=profiles[1].home_advantage,
            sample_matches=4,
        )
        texts = generate_match_analysis_texts(
            home_name="Galatasaray",
            away_name="Fenerbahçe",
            home_profile=profiles[1],
            away_profile=profiles[2],
            poisson_result=poisson_res,
            round_number=5,
        )

        banned_jargon = (
            "dixon-coles",
            "poisson",
            "katsayısını",
            "katsayı",
            "olasılık matrisi",
            "0-5 dağılımı",
            "λ",
            "logaritmik",
            "xg",
            "çarpan",
        )

        for field_text in (
            texts.match_overview_text,
            texts.home_analysis_text,
            texts.away_analysis_text,
        ):
            self.assertGreater(len(field_text), 180)
            self.assertGreaterEqual(field_text.count("."), 3)
            paragraphs = field_text.split("\n\n")
            self.assertEqual(len(paragraphs), 2)
            self.assertTrue(all(len(p.strip()) > 60 for p in paragraphs))
            lowered = field_text.casefold()
            for term in banned_jargon:
                self.assertNotIn(term, lowered)

        # 1. paragraf öne çıkan skoru gerekçelendirmeli, 2. paragraf derbi/tempo/kırılma noktasını anlatmalı
        overview_p1, overview_p2 = texts.match_overview_text.split("\n\n")
        expected_score = f"{poisson_res.predicted_home_score}-{poisson_res.predicted_away_score}"
        first_sentence = re.split(r"(?<!\d)\.\s+", overview_p1)[0]
        self.assertIn(expected_score, first_sentence)
        self.assertIn("Galatasaray", overview_p1)
        self.assertIn("Fenerbahçe", overview_p1)
        self.assertIn("derbi", overview_p2.casefold())
        self.assertIn("tempolu", overview_p2.casefold())
        self.assertIn("kırılma noktası", overview_p2.casefold())

        # Ev sahibi: FW mevkiye özel sakatlık etkisi (Osimhen)
        self.assertIn("Victor Osimhen", texts.home_analysis_text)
        self.assertIn("Arka adale yırtığı", texts.home_analysis_text)
        self.assertIn("ceza sahası bitiriciliği", texts.home_analysis_text)
        self.assertIn("ön alan presi", texts.home_analysis_text)

        # Deplasman: DEF mevkiye özel sakatlık etkisi (Becao) ve gol yememe karnesi
        self.assertIn("Rodrigo Becao", texts.away_analysis_text)
        self.assertIn("Kırmızı kart cezası", texts.away_analysis_text)
        self.assertIn("savunma yerleşimi", texts.away_analysis_text)
        self.assertIn("hava topları", texts.away_analysis_text)
        self.assertIn("duran top", texts.away_analysis_text)
        self.assertIn("kalesini gole kapat", texts.away_analysis_text)

        # GK, MID mevkiye özel sakatlık yorumları ve tam kadro (eksiksiz) senaryosu
        gk_mid_injuries = [
            Injury(
                team_id=3,
                player_name="Jakub Slowik",
                position=PlayerPosition.GK,
                reason="Omuz sakatlığı",
                impact_level=ImpactLevel.HIGH,
            ),
            Injury(
                team_id=4,
                player_name="Charilaos Charisis",
                position=PlayerPosition.MID,
                reason="Sarı kart cezası",
                impact_level=ImpactLevel.MEDIUM,
            ),
        ]
        alt_profiles = build_team_ratings(matches, injuries=gk_mid_injuries)
        alt_texts = generate_match_analysis_texts(
            home_name="Konyaspor",
            away_name="Sivasspor",
            home_profile=alt_profiles[3],
            away_profile=alt_profiles[4],
            poisson_result=poisson_res,
            round_number=5,
        )
        self.assertIn("Jakub Slowik", alt_texts.home_analysis_text)
        self.assertIn("kale güvenliği", alt_texts.home_analysis_text)
        self.assertIn("duran top", alt_texts.home_analysis_text)
        self.assertIn("Charilaos Charisis", alt_texts.away_analysis_text)
        self.assertIn("merkezde oyun kurulumu", alt_texts.away_analysis_text)
        self.assertIn("pas bağlantısı", alt_texts.away_analysis_text)
        self.assertIn("top kazanma direncinde", alt_texts.away_analysis_text)

        full_squad_profiles = build_team_ratings(matches, injuries=())
        full_texts = generate_match_analysis_texts(
            home_name="Konyaspor",
            away_name="Sivasspor",
            home_profile=full_squad_profiles[3],
            away_profile=full_squad_profiles[4],
            poisson_result=poisson_res,
            round_number=5,
        )
        self.assertIn("tam kadro", full_texts.home_analysis_text)
        self.assertIn("ideal kadro istikrarı", full_texts.away_analysis_text)

    def test_service_prediction_pipeline(self) -> None:
        teams, matches = _sample_league_dataset()
        injuries = [
            Injury(
                team_id=4,
                player_name="Ali Şaşal Vural",
                position=PlayerPosition.GK,
                reason="Parmak kırığı",
                impact_level=ImpactLevel.HIGH,
            ),
        ]

        # 1) Yerel mod (persist=False) ve schema.sql kolon uyumu
        local_res = run_prediction_pipeline(
            matches=matches,
            injuries=injuries,
            teams=teams,
            persist=False,
        )
        assert not isinstance(local_res, dict)
        self.assertFalse(local_res.persisted)
        self.assertEqual(len(local_res.predictions), 2)
        self.assertEqual(len(local_res.team_analyses), 2)

        pred_sql_cols = _extract_sql_columns("predictions")
        analysis_sql_cols = _extract_sql_columns("team_analyses")

        self.assertEqual(
            set(Prediction.model_fields.keys()) - set(Prediction._non_db_fields),
            pred_sql_cols,
        )
        self.assertEqual(
            set(TeamAnalysis.model_fields.keys()) - set(TeamAnalysis._non_db_fields),
            analysis_sql_cols,
        )

        for pred, analysis in zip(local_res.predictions, local_res.team_analyses, strict=True):
            self.assertIsInstance(pred, Prediction)
            self.assertIsInstance(analysis, TeamAnalysis)
            self.assertEqual(pred.match_id, analysis.match_id)

            pred_payload = pred.to_db_payload()
            analysis_payload = analysis.to_db_payload()
            self.assertTrue(set(pred_payload.keys()).issubset(pred_sql_cols))
            self.assertTrue(set(analysis_payload.keys()).issubset(analysis_sql_cols))
            self.assertEqual(len(pred_payload["top_scores_json"]), 3)

        as_dict_payload = run_prediction_pipeline(
            matches=matches,
            injuries=injuries,
            teams=teams,
            persist=False,
            as_dict=True,
        )
        assert isinstance(as_dict_payload, dict)
        self.assertEqual(len(as_dict_payload["predictions"]), 2)
        self.assertEqual(len(as_dict_payload["team_analyses"]), 2)

        # 2) Mock Supabase istemcisi ile upsert doğrulaması ve id geri doldurma
        idless_scheduled = [
            m.model_copy(update={"id": None})
            for m in matches
            if m.status == MatchStatus.SCHEDULED
        ]
        played_only = [m for m in matches if m.status == MatchStatus.FINISHED]
        fake_db = _FakeSupabaseClient(
            seed_matches=[
                {"id": 109, "round": 5, "home_team_id": 1, "away_team_id": 2},
                {"id": 110, "round": 5, "home_team_id": 3, "away_team_id": 4},
            ]
        )
        svc = PredictionService(supabase_client=fake_db)  # type: ignore[arg-type]
        persisted_res = svc.run(
            played_matches=played_only,
            scheduled_matches=idless_scheduled,
            injuries=injuries,
            teams=teams,
            persist=True,
        )
        self.assertTrue(persisted_res.persisted)
        self.assertEqual([p.match_id for p in persisted_res.predictions], [109, 110])
        self.assertEqual(fake_db.recorded["predictions"][0]["on_conflict"], "match_id")
        self.assertEqual(fake_db.recorded["team_analyses"][0]["on_conflict"], "match_id")

    def test_synthetic_20_team_equal_strength_league_scale_calibration(self) -> None:
        rng = random.Random(202612)

        def sample_poisson(rate: float) -> int:
            threshold = math.exp(-rate)
            k = 0
            prod = 1.0
            while True:
                k += 1
                prod *= rng.random()
                if prod <= threshold:
                    return k - 1

        teams = [
            Team(
                id=tid,
                league_id=LeagueId.PREMIER_LEAGUE,
                name=f"Synthetic Club {tid:02d}",
                short_name=f"S{tid:02d}",
            )
            for tid in range(1, 21)
        ]

        # 20 takımlı çift devreli lig (38 hafta, 380 oynanmış maç) + dengeli 20 maçlık değerlendirme turu
        rotation = list(range(1, 21))
        rounds_pairings: list[list[tuple[int, int]]] = []
        for rnd_idx in range(19):
            pairings: list[tuple[int, int]] = []
            for i in range(10):
                t1 = rotation[i]
                t2 = rotation[19 - i]
                pairings.append((t1, t2) if (rnd_idx + i) % 2 == 0 else (t2, t1))
            rounds_pairings.append(pairings)
            rotation = [rotation[0], rotation[-1], *rotation[1:-1]]

        full_schedule = rounds_pairings + [[(b, a) for a, b in r] for r in rounds_pairings]
        base_dt = datetime(2026, 8, 15, 16, 0, tzinfo=UTC)
        matches: list[Match] = []
        mid = 1
        for rnd_num, pairings in enumerate(full_schedule, start=1):
            for h_id, a_id in pairings:
                matches.append(
                    Match(
                        id=mid,
                        league_id=LeagueId.PREMIER_LEAGUE,
                        home_team_id=h_id,
                        away_team_id=a_id,
                        match_date=base_dt + timedelta(days=rnd_num * 7),
                        round=rnd_num,
                        status=MatchStatus.FINISHED,
                        home_score=sample_poisson(1.52),
                        away_score=sample_poisson(1.19),
                    )
                )
                mid += 1

        # Her takımın 1 iç saha ve 1 dış saha maçına çıktığı dengeli SCHEDULED değerlendirme penceresi
        for h_id in range(1, 21):
            a_id = (h_id % 20) + 1
            matches.append(
                Match(
                    id=mid,
                    league_id=LeagueId.PREMIER_LEAGUE,
                    home_team_id=h_id,
                    away_team_id=a_id,
                    match_date=base_dt + timedelta(days=280),
                    round=39,
                    status=MatchStatus.SCHEDULED,
                )
            )
            mid += 1

        played = [m for m in matches if m.status == MatchStatus.FINISHED]
        realized_home_avg = sum(int(m.home_score or 0) for m in played) / len(played)
        realized_away_avg = sum(int(m.away_score or 0) for m in played) / len(played)
        baseline = calculate_league_baseline(played)
        self.assertAlmostEqual(baseline.avg_home_goals, realized_home_avg, places=3)
        self.assertAlmostEqual(baseline.avg_away_goals, realized_away_avg, places=3)

        svc_res = PredictionService().run(matches=matches, teams=teams, persist=False)
        self.assertEqual(len(svc_res.bundles), 20)

        mean_pred_lam = sum(b.poisson.expected_home_goals for b in svc_res.bundles) / len(
            svc_res.bundles
        )
        mean_pred_mu = sum(b.poisson.expected_away_goals for b in svc_res.bundles) / len(
            svc_res.bundles
        )

        rel_err_lam = abs(mean_pred_lam - realized_home_avg) / realized_home_avg
        rel_err_mu = abs(mean_pred_mu - realized_away_avg) / realized_away_avg
        self.assertLess(rel_err_lam, 0.03)
        self.assertLess(rel_err_mu, 0.03)

        balanced = predict_score_distribution(
            home_attack=1.0,
            away_defense=1.0,
            away_attack=1.0,
            home_defense=1.0,
            avg_home_goals=1.52,
            avg_away_goals=1.18,
        )
        self.assertGreaterEqual(balanced.over_2_5_prob, 0.48)
        self.assertLessEqual(balanced.over_2_5_prob, 0.53)


if __name__ == "__main__":
    unittest.main()
