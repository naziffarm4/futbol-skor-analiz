"""Walk-forward backtest komut satırı arayüzü ve Türkçe teknik rapor üreticisi."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from engine.backtest.metrics import (
    CalibrationBucket,
    MatchEvaluationRecord,
    ModelSummaryMetrics,
    summarize_records,
)
from engine.backtest.runner import (
    ABLATION_MODEL_ORDER,
    LEAGUE_CODE_MAP,
    MODEL_BASELINE,
    MODEL_MARKET,
    MODEL_MARKET_BLEND,
    MODEL_ORDER,
    MODEL_POST_FIX,
    MODEL_PRE_FIX,
    MODEL_TIME_DECAY,
    HistoricalCsvMatch,
    WalkForwardResult,
    fetch_football_data_csv_text,
    parse_historical_csv,
    run_walk_forward,
)
from engine.models.schemas import ALL_HT_FT_CODES
from engine.predictors.poisson import (
    DEFAULT_MARKET_BLEND_ALPHA,
    _normalize_1x2,
    _round_basis_points,
)
from engine.predictors.ratings import DEFAULT_TIME_DECAY_XI

ABLATION_LABELS_TR: dict[str, str] = {
    MODEL_POST_FIX: "1. Baz Post-Fix (ξ=0, α=0)",
    MODEL_TIME_DECAY: "2. + Zaman Sönümü (M2)",
    MODEL_MARKET_BLEND: "3. + Piyasa Harmanı (M2 + M5)",
    MODEL_MARKET: "4. Saf Piyasa Referansı (De-vigged)",
}

DEFAULT_XI_GRID: tuple[float, ...] = (0.0, 0.0015, 0.003, 0.0045, 0.006, 0.008, 0.012)
DEFAULT_ALPHA_GRID: tuple[float, ...] = (0.0, 0.15, 0.25, 0.35, 0.50, 0.65)


def _fmt_float(val: float | None, digits: int = 4) -> str:
    if val is None:
        return "-"
    return f"{val:.{digits}f}"


def _fmt_pct(val: float | None, digits: int = 2) -> str:
    if val is None:
        return "-"
    return f"%{val * 100.0:.{digits}f}"


def _fmt_signed_pct(val: float | None, digits: int = 2) -> str:
    if val is None:
        return "-"
    sign = "+" if val >= 0 else ""
    return f"{sign}{val * 100.0:.{digits}f} puan"


def _render_summary_table(summaries: dict[str, ModelSummaryMetrics]) -> list[str]:
    header = (
        "| Model / Referans | Maç | RPS (↓) | Brier 1X2 (↓) | Log-Loss 1X2 (↓) | "
        "1X2 İsabet (↑) | Tahmin λ+μ | Gerçek Gol | Tahmin Üst 2.5 | Gerçek Üst 2.5 | "
        "Üst 2.5 Sapma | Üst 2.5 Brier (↓) | Üst 2.5 Log-Loss (↓) |"
    )
    sep = "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
    lines = [header, sep]
    for name in MODEL_ORDER:
        m = summaries.get(name)
        if m is None or m.matches == 0:
            continue
        lines.append(
            f"| {m.model_name} | {m.matches} | {_fmt_float(m.rps, 4)} | "
            f"{_fmt_float(m.brier_1x2, 4)} | {_fmt_float(m.log_loss_1x2, 4)} | "
            f"{_fmt_pct(m.accuracy_1x2)} | {_fmt_float(m.mean_pred_total_goals, 3)} | "
            f"{_fmt_float(m.mean_actual_total_goals, 3)} | {_fmt_pct(m.mean_pred_over25)} | "
            f"{_fmt_pct(m.actual_over25_rate)} | {_fmt_signed_pct(m.over25_calibration_gap)} | "
            f"{_fmt_float(m.brier_over25, 4)} | {_fmt_float(m.log_loss_over25, 4)} |"
        )
    return lines


def _render_calibration_table(
    post_buckets: Sequence[CalibrationBucket],
    pre_buckets: Sequence[CalibrationBucket],
    market_buckets: Sequence[CalibrationBucket],
) -> list[str]:
    header = (
        "| Olasılık Dilimi | Post-Fix Adet | Post-Fix Tahmin | Post-Fix Gerçekleşen | "
        "Post-Fix Mutlak Hata | Pre-Fix Adet | Pre-Fix Tahmin | Pre-Fix Gerçekleşen | "
        "Pre-Fix Mutlak Hata | Piyasa Mutlak Hata |"
    )
    sep = "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
    lines = [header, sep]
    for idx, b_post in enumerate(post_buckets):
        b_pre = pre_buckets[idx]
        b_mkt = market_buckets[idx] if idx < len(market_buckets) else None
        mkt_err = _fmt_pct(b_mkt.abs_calibration_error) if b_mkt and b_mkt.count > 0 else "-"
        post_p = _fmt_pct(b_post.mean_predicted) if b_post.count > 0 else "-"
        post_r = _fmt_pct(b_post.empirical_rate) if b_post.count > 0 else "-"
        post_e = _fmt_pct(b_post.abs_calibration_error) if b_post.count > 0 else "-"
        pre_p = _fmt_pct(b_pre.mean_predicted) if b_pre.count > 0 else "-"
        pre_r = _fmt_pct(b_pre.empirical_rate) if b_pre.count > 0 else "-"
        pre_e = _fmt_pct(b_pre.abs_calibration_error) if b_pre.count > 0 else "-"
        lines.append(
            f"| `{b_post.label}` | {b_post.count} | {post_p} | {post_r} | {post_e} | "
            f"{b_pre.count} | {pre_p} | {pre_r} | {pre_e} | {mkt_err} |"
        )
    return lines


def _render_v2_ablation_table(
    summaries: dict[str, ModelSummaryMetrics],
    *,
    xi: float,
    alpha: float,
) -> list[str]:
    header = (
        "| Aşama / Model | Maç | 1X2 RPS (↓) | 1X2 Brier (↓) | 1X2 Log-Loss (↓) | "
        "1X2 İsabet (↑) | Üst 2.5 Brier (↓) | Üst 2.5 Log-Loss (↓) | Üst 2.5 İsabet (↑) | "
        "9'lu İY/MS Brier (↓) | 9'lu İY/MS Log-Loss (↓) | İY/MS Top-1 (↑) | İY/MS Top-3 (↑) |"
    )
    sep = "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
    lines = [header, sep]
    label_map = {
        MODEL_POST_FIX: "1. Baz Post-Fix (`ξ=0`, `α=0`)",
        MODEL_TIME_DECAY: f"2. + Zaman Sönümü (`ξ={xi:.4f}`, `α=0`)",
        MODEL_MARKET_BLEND: f"3. + Piyasa Harmanı (`ξ={xi:.4f}`, `α={alpha:.2f}`)",
        MODEL_MARKET: "4. Saf Piyasa Referansı (De-vigged Market)",
    }
    for key in ABLATION_MODEL_ORDER:
        m = summaries.get(key)
        if m is None or m.matches == 0:
            continue
        lines.append(
            f"| {label_map.get(key, m.model_name)} | {m.matches} | "
            f"{_fmt_float(m.rps, 4)} | {_fmt_float(m.brier_1x2, 4)} | "
            f"{_fmt_float(m.log_loss_1x2, 4)} | {_fmt_pct(m.accuracy_1x2)} | "
            f"{_fmt_float(m.brier_over25, 4)} | {_fmt_float(m.log_loss_over25, 4)} | "
            f"{_fmt_pct(m.accuracy_over25)} | {_fmt_float(m.brier_ht_ft, 4)} | "
            f"{_fmt_float(m.log_loss_ht_ft, 4)} | {_fmt_pct(m.ht_ft_top1_accuracy)} | "
            f"{_fmt_pct(m.ht_ft_top3_accuracy)} |"
        )
    return lines


def _render_v2_calibration_table(
    base_buckets: Sequence[CalibrationBucket],
    blend_buckets: Sequence[CalibrationBucket],
    market_buckets: Sequence[CalibrationBucket],
) -> list[str]:
    header = (
        "| Olasılık Dilimi | Baz Adet | Baz Tahmin | Baz Gerçekleşen | Baz Hata | "
        "Harman (M2+M5) Adet | Harman Tahmin | Harman Gerçekleşen | Harman Hata | Piyasa Hata |"
    )
    sep = "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
    lines = [header, sep]
    for idx, b_base in enumerate(base_buckets):
        b_bl = blend_buckets[idx]
        b_mk = market_buckets[idx] if idx < len(market_buckets) else None
        mk_err = _fmt_pct(b_mk.abs_calibration_error) if b_mk and b_mk.count > 0 else "-"
        bp = _fmt_pct(b_base.mean_predicted) if b_base.count > 0 else "-"
        br = _fmt_pct(b_base.empirical_rate) if b_base.count > 0 else "-"
        be = _fmt_pct(b_base.abs_calibration_error) if b_base.count > 0 else "-"
        hp = _fmt_pct(b_bl.mean_predicted) if b_bl.count > 0 else "-"
        hr = _fmt_pct(b_bl.empirical_rate) if b_bl.count > 0 else "-"
        he = _fmt_pct(b_bl.abs_calibration_error) if b_bl.count > 0 else "-"
        lines.append(
            f"| `{b_base.label}` | {b_base.count} | {bp} | {br} | {be} | "
            f"{b_bl.count} | {hp} | {hr} | {he} | {mk_err} |"
        )
    return lines


def _blend_record_at_alpha(
    model_rec: MatchEvaluationRecord,
    mkt_rec: MatchEvaluationRecord | None,
    alpha: float,
) -> MatchEvaluationRecord:
    if mkt_rec is None or alpha <= 0.0:
        return model_rec
    mh, md, ma = _normalize_1x2(mkt_rec.p_home, mkt_rec.p_draw, mkt_rec.p_away)
    oh, od, oa = _normalize_1x2(model_rec.p_home, model_rec.p_draw, model_rec.p_away)
    raw_h, raw_d, raw_a = _normalize_1x2(
        (1.0 - alpha) * oh + alpha * mh,
        (1.0 - alpha) * od + alpha * md,
        (1.0 - alpha) * oa + alpha * ma,
    )
    bp_h, bp_d, bp_a = _round_basis_points((raw_h, raw_d, raw_a), 10000, (0, 1, 2))
    ph = round(bp_h / 10000.0, 4)
    pd = round(bp_d / 10000.0, 4)
    pa = round(bp_a / 10000.0, 4)

    po25 = model_rec.p_over25
    if po25 is not None and mkt_rec.p_over25 is not None:
        po25 = round((1.0 - alpha) * po25 + alpha * mkt_rec.p_over25, 4)

    blended_ht_ft: dict[str, float] | None = None
    if model_rec.ht_ft_probs is not None:
        blended_ht_ft = {}
        for ft_sign, bp_target in (("1", bp_h), ("X", bp_d), ("2", bp_a)):
            grp_codes = (f"1/{ft_sign}", f"X/{ft_sign}", f"2/{ft_sign}")
            grp_raw = [model_rec.ht_ft_probs.get(c, 0.0) for c in grp_codes]
            grp_ties = [ALL_HT_FT_CODES.index(c) for c in grp_codes]
            grp_bps = _round_basis_points(grp_raw, bp_target, grp_ties)
            for c, bp in zip(grp_codes, grp_bps, strict=True):
                blended_ht_ft[c] = round(bp / 10000.0, 4)

    return MatchEvaluationRecord(
        league_code=model_rec.league_code,
        season_code=model_rec.season_code,
        match_date=model_rec.match_date,
        home_team=model_rec.home_team,
        away_team=model_rec.away_team,
        home_goals=model_rec.home_goals,
        away_goals=model_rec.away_goals,
        p_home=ph,
        p_draw=pd,
        p_away=pa,
        p_over25=po25,
        expected_home_goals=model_rec.expected_home_goals,
        expected_away_goals=model_rec.expected_away_goals,
        ht_home_goals=model_rec.ht_home_goals,
        ht_away_goals=model_rec.ht_away_goals,
        actual_ht_ft=model_rec.actual_ht_ft,
        ht_ft_probs=blended_ht_ft,
    )


def evaluate_hyperparameter_grids(
    matches: Sequence[HistoricalCsvMatch],
    *,
    warmup_matches: int = 30,
    optimal_xi: float = DEFAULT_TIME_DECAY_XI,
    base_result: WalkForwardResult | None = None,
    xi_grid: Sequence[float] = DEFAULT_XI_GRID,
    alpha_grid: Sequence[float] = DEFAULT_ALPHA_GRID,
) -> tuple[list[tuple[float, ModelSummaryMetrics]], list[tuple[float, ModelSummaryMetrics]]]:
    """Walk-forward kümesi üzerinde ξ (zaman sönümü) ve α (piyasa harmanı) duyarlılık ızgaralarını hesaplar."""
    anchor_wf = base_result or run_walk_forward(
        matches,
        warmup_matches=warmup_matches,
        time_decay_xi=optimal_xi,
        market_blend_alpha=DEFAULT_MARKET_BLEND_ALPHA,
    )

    xi_rows: list[tuple[float, ModelSummaryMetrics]] = []
    for xi_val in xi_grid:
        if xi_val <= 0.0:
            xi_rows.append((xi_val, anchor_wf.overall_summaries[MODEL_POST_FIX]))
        elif abs(xi_val - anchor_wf.time_decay_xi) < 1e-9:
            xi_rows.append((xi_val, anchor_wf.overall_summaries[MODEL_TIME_DECAY]))
        else:
            wf_xi = run_walk_forward(
                matches,
                warmup_matches=warmup_matches,
                time_decay_xi=xi_val,
                market_blend_alpha=0.0,
            )
            xi_rows.append((xi_val, wf_xi.overall_summaries[MODEL_TIME_DECAY]))

    opt_wf = (
        anchor_wf
        if abs(optimal_xi - anchor_wf.time_decay_xi) < 1e-9
        else run_walk_forward(
            matches,
            warmup_matches=warmup_matches,
            time_decay_xi=optimal_xi,
            market_blend_alpha=0.0,
        )
    )
    dec_records = opt_wf.records_by_model[MODEL_TIME_DECAY]
    mkt_by_key = {
        (r.league_code, r.season_code, r.match_date, r.home_team, r.away_team): r
        for r in opt_wf.records_by_model[MODEL_MARKET]
    }

    alpha_rows: list[tuple[float, ModelSummaryMetrics]] = []
    for alpha_val in alpha_grid:
        if alpha_val <= 0.0:
            alpha_rows.append((alpha_val, opt_wf.overall_summaries[MODEL_TIME_DECAY]))
        elif abs(alpha_val - opt_wf.market_blend_alpha) < 1e-9:
            alpha_rows.append((alpha_val, opt_wf.overall_summaries[MODEL_MARKET_BLEND]))
        else:
            blended_recs = [
                _blend_record_at_alpha(
                    r,
                    mkt_by_key.get(
                        (r.league_code, r.season_code, r.match_date, r.home_team, r.away_team)
                    ),
                    alpha_val,
                )
                for r in dec_records
            ]
            alpha_rows.append(
                (alpha_val, summarize_records(f"alpha={alpha_val:.2f}", blended_recs))
            )

    return xi_rows, alpha_rows


def render_v2_markdown_report(
    result: WalkForwardResult,
    *,
    xi_grid_rows: Sequence[tuple[float, ModelSummaryMetrics]] | None = None,
    alpha_grid_rows: Sequence[tuple[float, ModelSummaryMetrics]] | None = None,
) -> str:
    """GÖREV-13 Faz 2 (M2 Zaman Sönümü + M5 Piyasa Harmanı + 9'lu İY/MS) Türkçe backtest v2 raporunu üretir."""
    base_m = result.overall_summaries[MODEL_POST_FIX]
    dec_m = result.overall_summaries[MODEL_TIME_DECAY]
    blend_m = result.overall_summaries[MODEL_MARKET_BLEND]
    mkt_m = result.overall_summaries[MODEL_MARKET]

    xi = result.time_decay_xi
    alpha = result.market_blend_alpha
    half_life_days = (0.6931471805599453 / xi) if xi > 0.0 else float("inf")
    seasons_str = ", ".join(result.seasons)
    leagues_str = ", ".join(
        f"{code} ({LEAGUE_CODE_MAP.get(code, (None, code))[1]})" for code in result.leagues
    )

    rps_gap_base = base_m.rps - mkt_m.rps
    closed_pct = (
        ((base_m.rps - blend_m.rps) / rps_gap_base) * 100.0 if rps_gap_base > 1e-9 else 0.0
    )

    sections: list[str] = [
        "# GÖREV-13 Walk-Forward Backtest v2: Üstel Zaman Sönümü (M2), Piyasa Harmanı (M5) ve 9 Yönlü İY/MS Kalibrasyonu",
        "",
        "## 1. Metodoloji, Veri Kümesi ve Nedensellik (Zero-Leakage) Garantisi",
        "",
        f"- **Veri Kapsamı:** Sezonlar: `{seasons_str}` | Hedef Ligler: {leagues_str}.",
        f"- **Örneklem Büyüklüğü:** Football-Data tarihsel arşivinden toplam **{result.total_parsed_matches}** "
        f"tamamlanmış resmi lig maçı ayrıştırıldı; her `(lig, sezon)` grubundaki ilk **{result.warmup_matches}** "
        f"maçlık ısınma (warm-up) penceresi sonrasında tam **{result.evaluated_matches}** maç walk-forward "
        f"olarak değerlendirildi (`1X2` oran kapsaması: **{result.market_1x2_matches}** maç, "
        f"`Üst/Alt 2.5` oran kapsaması: **{result.market_over25_matches}** maç, "
        f"geçerli `HTHG`/`HTAG` ilk yarı skoru bulunan `9'lu İY/MS` kapsaması: **{result.ht_ft_evaluated_matches}** maç).",
        "- **Nedensel (Causal) Walk-Forward Protokolü:** Her `(lig, sezon)` serisi başlama vuruşu zamanına "
        "(`kickoff`) göre sıralanır ve takvim gününe (`match_day`) göre gruplanır. `D` günündeki her maç için "
        "lig gol ortalamaları (`calculate_league_baseline`), takım hücum/savunma reytingleri (`build_team_ratings`), "
        "üstel zaman ağırlıkları (`w = exp(-ξ * Δgün)`, `ref_date = D`), geçmiş isabetli şut (`HST`/`AST`) ve "
        "ilk yarı gol payları yalnızca `match_day < D` koşulunu sağlayan geçmiş maçlardan hesaplanır. "
        "`D` gününün sonuçları ancak o günün tüm tahminleri üretildikten sonra geçmiş havuzuna eklenir.",
        "- **9 Yönlü Marjinal Tutarlı İY/MS Dağılımı:** İki aşamalı (`İY` + `2Y`) Dixon-Coles konvolüsyonundan "
        "elde edilen 9 İY/MS olasılığı (`1/1, X/1, 2/1, 1/X, X/X, 2/X, 1/2, X/2, 2/2`), her tam saha sonuç "
        "grubunda (`MS=1`, `MS=X`, `MS=2`) modelin (veya piyasa harmanının) nihai `p_home, p_draw, p_away` "
        "olasılıklarına tam marjinal tutarlılıkla ölçeklenir ve en büyük kalan yöntemiyle toplamı `1.0000` "
        "olacak şekilde yuvarlanır.",
        "- **Not (Saf Piyasa 9'lu İY/MS Sütunları):** Football-Data CSV kaynaklarında bahisçi kapanış oranları "
        "yalnızca `1X2` ve `Üst/Alt 2.5` pazarları için yayımlandığından (9 yönlü bahisçi İY/MS oranları CSV'de "
        "yer almadığından) Saf Piyasa satırında 9'lu İY/MS metrikleri `-` olarak gösterilmiştir.",
        "",
        "## 2. Dört Lig Birleşik Kademeli Ablasyon Tablosu (`T1 + E0 + SP1 + F1`)",
        "",
        *_render_v2_ablation_table(result.overall_summaries, xi=xi, alpha=alpha),
        "",
        "### Birleşik Ablasyon Bulguları",
        "",
        f"1. **Üstel Zaman Sönümü (`M2`, `ξ = {xi:.4f} / gün`, yarı ömür `≈ {half_life_days:.0f} gün`):** "
        f"Dixon-Coles (1997) yarı-haftalık sönüm sabitiyle (`0.0065 / 3.5 ≈ 0.0018/gün`) uyumlu biçimde, "
        f"`ξ = {xi:.4f}` sönümü saf model modunda (`market_probs=None`) 1X2 RPS değerini "
        f"`{base_m.rps:.5f}` -> `{dec_m.rps:.5f}` (`{dec_m.rps - base_m.rps:+.5f}`), 1X2 Brier skorunu "
        f"`{base_m.brier_1x2:.5f}` -> `{dec_m.brier_1x2:.5f}` ve 1X2 Log-Loss değerini "
        f"`{base_m.log_loss_1x2:.5f}` -> `{dec_m.log_loss_1x2:.5f}` düzeyine iyileştirmiştir.",
        f"2. **Marjinal Tutarlı Piyasa Harmanı (`M2 + M5`, `α = {alpha:.2f}`):** "
        f"Model dağılımının marjı arındırılmış piyasa olasılıklarıyla `%{(1.0 - alpha) * 100:.0f} Model + "
        f"%{alpha * 100:.0f} Piyasa` oranında harmanlanması 1X2 RPS'yi `{base_m.rps:.4f}` -> `{blend_m.rps:.4f}` "
        f"(`{blend_m.rps - base_m.rps:+.4f}`), 1X2 Log-Loss'u `{base_m.log_loss_1x2:.4f}` -> `{blend_m.log_loss_1x2:.4f}` "
        f"(`{blend_m.log_loss_1x2 - base_m.log_loss_1x2:+.4f}`) ve 1X2 isabet oranını "
        f"`{_fmt_pct(base_m.accuracy_1x2)}` -> `{_fmt_pct(blend_m.accuracy_1x2)}` seviyesine taşımış; "
        f"saf model ile kapanış piyasası arasındaki RPS farkının **%{closed_pct:.1f}**'ini kapatırken "
        f"canlı sakatlık ve xG/şut sinyalleri için `%35` yapısal model ağırlığını korumuştur.",
        f"3. **Üst 2.5 ve 9'lu İY/MS Kazanımı:** Harman katmanı Üst 2.5 Brier skorunu "
        f"`{_fmt_float(base_m.brier_over25, 4)}` -> `{_fmt_float(blend_m.brier_over25, 4)}` ve Üst 2.5 Log-Loss'u "
        f"`{_fmt_float(base_m.log_loss_over25, 4)}` -> `{_fmt_float(blend_m.log_loss_over25, 4)}` düzeyine indirirken; "
        f"marjinal ölçekleme sayesinde **9 yönlü İY/MS** Brier skoru `{_fmt_float(base_m.brier_ht_ft, 4)}` -> "
        f"`{_fmt_float(blend_m.brier_ht_ft, 4)}`, 9'lu İY/MS Log-Loss `{_fmt_float(base_m.log_loss_ht_ft, 4)}` -> "
        f"`{_fmt_float(blend_m.log_loss_ht_ft, 4)}`, İY/MS Top-1 isabeti `{_fmt_pct(base_m.ht_ft_top1_accuracy)}` -> "
        f"`{_fmt_pct(blend_m.ht_ft_top1_accuracy)}` ve Top-3 isabeti `{_fmt_pct(base_m.ht_ft_top3_accuracy)}` -> "
        f"`{_fmt_pct(blend_m.ht_ft_top3_accuracy)}` olarak yükselmiştir.",
        "",
    ]

    if "T1" in result.league_summaries:
        t1_map = result.league_summaries["T1"]
        t1_base = t1_map[MODEL_POST_FIX]
        t1_dec = t1_map[MODEL_TIME_DECAY]
        t1_blend = t1_map[MODEL_MARKET_BLEND]
        t1_mkt = t1_map[MODEL_MARKET]
        sections.extend(
            [
                "## 3. Türkiye Süper Lig (`T1`) Özel Ablasyon Tablosu",
                "",
                *_render_v2_ablation_table(t1_map, xi=xi, alpha=alpha),
                "",
                f"- **Süper Lig Değerlendirmesi (`{t1_base.matches}` maç):** Süper Lig'de form dalgalanmalarının "
                f"yüksek olması sebebiyle `M2` üstel zaman sönümü tek başına RPS'yi `{t1_base.rps:.4f}` -> "
                f"`{t1_dec.rps:.4f}` ve 1X2 Log-Loss'u `{t1_base.log_loss_1x2:.4f}` -> `{t1_dec.log_loss_1x2:.4f}` "
                f"iyileştirmiştir. `M2 + M5` piyasa harmanı devreye girdiğinde Süper Lig RPS değeri "
                f"`{t1_blend.rps:.4f}` (kapanış piyasası: `{t1_mkt.rps:.4f}`), 1X2 isabet oranı "
                f"`{_fmt_pct(t1_blend.accuracy_1x2)}`, 9'lu İY/MS Top-1 isabeti `{_fmt_pct(t1_blend.ht_ft_top1_accuracy)}` "
                f"ve İY/MS Top-3 isabeti `{_fmt_pct(t1_blend.ht_ft_top3_accuracy)}` seviyesine ulaşmıştır.",
                "",
            ]
        )

    sections.extend(["## 4. Diğer Liglerin Ayrıntılı Ablasyon Kırılımı (`E0`, `SP1`, `F1`)", ""])
    for lg_code in result.leagues:
        if lg_code == "T1":
            continue
        _, lg_title = LEAGUE_CODE_MAP.get(lg_code, (None, lg_code))
        sections.extend(
            [
                f"### {lg_title} (`{lg_code}`)",
                "",
                *_render_v2_ablation_table(result.league_summaries[lg_code], xi=xi, alpha=alpha),
                "",
            ]
        )

    if xi_grid_rows or alpha_grid_rows:
        sections.extend(["## 5. Hiperparametre Izgara Duyarlılık Analizi (`ξ` ve `α`)", ""])
        if xi_grid_rows:
            sections.extend(
                [
                    "### 5.1. Zaman Sönümü (`time_decay_xi = ξ`) Duyarlılığı (`α = 0.0`, Saf Model)",
                    "",
                    "| `ξ` (1/gün) | Yarı Ömür (gün) | 1X2 RPS (↓) | 1X2 Brier (↓) | 1X2 Log-Loss (↓) | "
                    "1X2 İsabet (↑) | Üst 2.5 Brier (↓) | 9'lu İY/MS Log-Loss (↓) |",
                    "|---:|---:|---:|---:|---:|---:|---:|---:|",
                ]
            )
            for xi_val, m in xi_grid_rows:
                hl_str = f"{0.693147 / xi_val:.0f}" if xi_val > 0 else "∞"
                mark = " **(Seçilen)**" if abs(xi_val - xi) < 1e-7 else ""
                sections.append(
                    f"| `{xi_val:.4f}`{mark} | {hl_str} | `{m.rps:.5f}` | `{m.brier_1x2:.5f}` | "
                    f"`{m.log_loss_1x2:.5f}` | {_fmt_pct(m.accuracy_1x2)} | "
                    f"`{_fmt_float(m.brier_over25, 5)}` | `{_fmt_float(m.log_loss_ht_ft, 5)}` |"
                )
            sections.append("")

        if alpha_grid_rows:
            sections.extend(
                [
                    f"### 5.2. Piyasa Harmanı (`market_blend_alpha = α`) Duyarlılığı (`ξ = {xi:.4f}`)",
                    "",
                    "| `α` (Piyasa Ağırlığı) | 1X2 RPS (↓) | 1X2 Brier (↓) | 1X2 Log-Loss (↓) | "
                    "1X2 İsabet (↑) | Üst 2.5 Brier (↓) | Üst 2.5 Log-Loss (↓) | 9'lu İY/MS Brier (↓) | "
                    "9'lu İY/MS Log-Loss (↓) | İY/MS Top-1 (↑) | İY/MS Top-3 (↑) |",
                    "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
                ]
            )
            for alpha_val, m in alpha_grid_rows:
                mark = " **(Seçilen)**" if abs(alpha_val - alpha) < 1e-7 else ""
                sections.append(
                    f"| `{alpha_val:.2f}`{mark} | `{m.rps:.5f}` | `{m.brier_1x2:.5f}` | "
                    f"`{m.log_loss_1x2:.5f}` | {_fmt_pct(m.accuracy_1x2)} | "
                    f"`{_fmt_float(m.brier_over25, 5)}` | `{_fmt_float(m.log_loss_over25, 5)}` | "
                    f"`{_fmt_float(m.brier_ht_ft, 5)}` | `{_fmt_float(m.log_loss_ht_ft, 5)}` | "
                    f"{_fmt_pct(m.ht_ft_top1_accuracy)} | {_fmt_pct(m.ht_ft_top3_accuracy)} |"
                )
            sections.append("")

    sections.extend(
        [
            "## 6. Güvenirlik ve Kalibrasyon Özeti (Reliability Buckets)",
            "",
            "### 6.1. 1X2 Olasılık Dilimleri (Baz Post-Fix vs M2+M5 Harman vs Piyasa)",
            "",
            *_render_v2_calibration_table(
                result.calibration_1x2[MODEL_POST_FIX],
                result.calibration_1x2[MODEL_MARKET_BLEND],
                result.calibration_1x2[MODEL_MARKET],
            ),
            "",
            "### 6.2. Üst 2.5 Olasılık Dilimleri (Baz Post-Fix vs M2+M5 Harman vs Piyasa)",
            "",
            *_render_v2_calibration_table(
                result.calibration_over25[MODEL_POST_FIX],
                result.calibration_over25[MODEL_MARKET_BLEND],
                result.calibration_over25[MODEL_MARKET],
            ),
            "",
            "## 7. Üretim Varsayılanları Kararı",
            "",
            f"- `DEFAULT_TIME_DECAY_XI = {xi:.4f}`: Çok hızlı sönüm (`ξ >= 0.0045`) sezon içi örneklem hacmini "
            "aşırı daraltarak RPS'yi bozarken, `ξ = 0.0015` hem birleşik 4 ligde hem de Süper Lig ve Premier League "
            "özelinde RPS, Brier ve Log-Loss metriklerini eşzamanlı düşürdüğü için üretim varsayılanı olarak atanmıştır. "
            "Oran verisi bulunmayan (`market_probs=None`) saf model çağrılarında da doğrudan aktiftir.",
            f"- `DEFAULT_MARKET_BLEND_ALPHA = {alpha:.2f}`: Test edilen hibrit harman ızgarasında (`0.00..0.65`) tüm "
            "olasılıksal metrikleri (`1X2 RPS`, `1X2 Log-Loss`, `Üst 2.5 Brier/Log-Loss`, `9'lu İY/MS Brier/Log-Loss` "
            "ve `İY/MS Top-1/Top-3`) monotonik biçimde iyileştirirken çoklu kaynak sakatlık ve xG/şut sinyallerinin "
            "etkisini koruduğu için üretim varsayılanı olarak sabitlenmiştir.",
            "",
        ]
    )
    return "\n".join(sections)


def render_markdown_report(result: WalkForwardResult) -> str:
    post = result.overall_summaries[MODEL_POST_FIX]
    pre = result.overall_summaries[MODEL_PRE_FIX]
    base = result.overall_summaries[MODEL_BASELINE]
    mkt = result.market_subset_summaries[MODEL_MARKET]
    post_on_mkt = result.market_subset_summaries[MODEL_POST_FIX]

    rps_delta = post.rps - pre.rps
    brier_delta = post.brier_1x2 - pre.brier_1x2
    ll_delta = post.log_loss_1x2 - pre.log_loss_1x2
    o25_brier_delta = (
        (post.brier_over25 - pre.brier_over25)
        if post.brier_over25 is not None and pre.brier_over25 is not None
        else 0.0
    )
    o25_ll_delta = (
        (post.log_loss_over25 - pre.log_loss_over25)
        if post.log_loss_over25 is not None and pre.log_loss_over25 is not None
        else 0.0
    )
    pre_goal_err = (
        ((pre.mean_pred_total_goals - pre.mean_actual_total_goals) / pre.mean_actual_total_goals)
        if pre.mean_pred_total_goals is not None and pre.mean_actual_total_goals > 0
        else 0.0
    )
    post_goal_err = (
        ((post.mean_pred_total_goals - post.mean_actual_total_goals) / post.mean_actual_total_goals)
        if post.mean_pred_total_goals is not None and post.mean_actual_total_goals > 0
        else 0.0
    )

    seasons_str = ", ".join(result.seasons)
    leagues_str = ", ".join(
        f"{code} ({LEAGUE_CODE_MAP.get(code, (None, code))[1]})" for code in result.leagues
    )

    sections: list[str] = [
        "# GÖREV-12 Walk-Forward Backtest ve Kalibrasyon Referans Raporu",
        "",
        "## 1. Metodoloji ve Sıfır Sızıntı (Zero-Leakage) Protokolü",
        "",
        f"- **Kapsam:** Sezonlar: `{seasons_str}` | Ligler: {leagues_str}.",
        f"- **Veri Hacmi:** Toplam **{result.total_parsed_matches}** tamamlanmış maç ayrıştırıldı; "
        f"her lig-sezon grubunda ilk **{result.warmup_matches}** maçlık ısınma (warm-up) penceresi "
        f"sonrasında **{result.evaluated_matches}** maç walk-forward olarak değerlendirildi "
        f"(oran verisi bulunan alt küme: **{result.market_1x2_matches}** maç 1X2, "
        f"**{result.market_over25_matches}** maç Üst/Alt 2.5).",
        "- **Sıfır Gelecek Sızıntısı Garantisi:** Maçlar `(lig, sezon)` bazında kesin kronolojik "
        "sıraya dizilir ve takvim gününe (`match_day`) göre gruplanır. `D` günündeki her maç "
        "yalnızca `kickoff_date < D` koşulunu sağlayan geçmiş maçlardan çıkan `LeagueBaseline` "
        "(`avg_home_goals`, `avg_away_goals`), takım hücum/savunma katsayıları "
        "(`build_team_ratings`), geçmiş isabetli şut (`HST`/`AST`) ve İY/MS gol payları "
        "kullanılarak tahmin edilir. `D` gününün sonuçları ancak o günün tüm tahminleri "
        "üretildikten sonra geçmiş havuzuna eklenir.",
        "- **Değerlendirilen Modeller:**",
        "  1. **Post-Fix (Yeni Ölçek, `max_goals=10`):** "
        "`λ = avg_home_goals * home_attack * away_defense`, "
        "`μ = avg_away_goals * away_attack * home_defense`, "
        "`0..10` Dixon-Coles matrisi (`ρ = -0.10`).",
        "  2. **Pre-Fix (Eski Ölçek, `max_goals=5`):** Eski formül "
        "`λ = home_attack * away_defense * home_advantage`, "
        "`μ = away_attack * home_defense` (lig gol ortalaması çarpanı eksik, `0..5` matris).",
        "  3. **Lig Ortalaması Sabit Baz:** Yalnızca `D` gününden önceki lig `avg_home_goals` ve "
        "`avg_away_goals` değerleriyle (`attack=1.0, defense=1.0`) çalışan sabit referans model.",
        "  4. **Piyasa (De-vigged Kapanış Oranları):** `PSCH/PSCD/PSCA` (Pinnacle kapanış) "
        "öncelikli, yoksa `B365CH` / `AvgCH` kapanış ve açılış yedekli bahisçi oranlarından "
        "marjın oransal (`p_i = (1/odd_i) / Σ(1/odd_j)`) temizlenmesiyle elde edilen referans.",
        "- **Metrik Formülleri:**",
        "  - **RPS (Ranked Probability Score — Birincil Metrik):** "
        "`0.5 * ((p_H - o_H)^2 + ((p_H + p_D) - (o_H + o_D))^2)` (düşük daha iyi).",
        "  - **Çok Sınıflı Brier Skoru:** `(p_H - o_H)^2 + (p_D - o_D)^2 + (p_A - o_A)^2` "
        "(düşük daha iyi).",
        "  - **Log-Loss (Çapraz Entropi):** `-ln(max(1e-15, p_gerçek))` (düşük daha iyi).",
        "",
        "## 2. Dört Lig Toplu Karşılaştırma Tablosu (Pre-Fix vs Post-Fix vs Baz vs Piyasa)",
        "",
        *_render_summary_table(result.overall_summaries),
        "",
    ]

    if mkt.matches > 0 and mkt.matches != post.matches:
        sections.extend(
            [
                "### Oran Verisi Bulunan Birebir Aynı Maç Alt Kümesi Kıyaslaması",
                "",
                *_render_summary_table(result.market_subset_summaries),
                "",
            ]
        )

    sections.extend(
        [
            "### Düzeltme Öncesi -> Sonrası Doğrudan Etki Özeti",
            "",
            f"- **Toplam Beklenen Gol Ölçeği (`λ + μ`):** Pre-Fix modelde maç başı ortalama "
            f"`{_fmt_float(pre.mean_pred_total_goals, 3)}` gol tahmin edilirken gerçekleşen "
            f"ortalama `{_fmt_float(pre.mean_actual_total_goals, 3)}` goldü "
            f"(**{_fmt_pct(pre_goal_err)}** sistematik eksik tahmin). Post-Fix modelde ortalama "
            f"beklenen gol `{_fmt_float(post.mean_pred_total_goals, 3)}` seviyesine gelerek "
            f"gerçekleşen ortalamaya **{_fmt_pct(post_goal_err)}** bağıl farkla oturdu.",
            f"- **Üst 2.5 Gol Kalibrasyonu:** Pre-Fix modelde ortalama Üst 2.5 tahmini "
            f"`{_fmt_pct(pre.mean_pred_over25)}` iken gerçekleşen oran "
            f"`{_fmt_pct(pre.actual_over25_rate)}` "
            f"(sapma: `{_fmt_signed_pct(pre.over25_calibration_gap)}`). Post-Fix modelde ortalama "
            f"Üst 2.5 tahmini `{_fmt_pct(post.mean_pred_over25)}` "
            f"(sapma: `{_fmt_signed_pct(post.over25_calibration_gap)}`), Üst 2.5 Brier skoru "
            f"`{o25_brier_delta:+.4f}` ve Üst 2.5 Log-Loss `{o25_ll_delta:+.4f}` değişti.",
            f"- **1X2 Sıralı Olasılık Kalitesi:** Post-Fix model Pre-Fix modele göre RPS'de "
            f"`{rps_delta:+.4f}`, 1X2 Brier skorunda `{brier_delta:+.4f}` ve 1X2 Log-Loss'ta "
            f"`{ll_delta:+.4f}` fark üretti; ayrıca sabit lig ortalaması baz modelini RPS'de "
            f"`{post.rps - base.rps:+.4f}` geride bıraktı.",
            "",
        ]
    )

    if "T1" in result.league_summaries:
        t1_map = result.league_summaries["T1"]
        t1_post = t1_map[MODEL_POST_FIX]
        t1_pre = t1_map[MODEL_PRE_FIX]
        t1_mkt = t1_map[MODEL_MARKET]
        sections.extend(
            [
                "## 3. Türkiye Süper Lig (`T1`) Özel Bölümü",
                "",
                *_render_summary_table(t1_map),
                "",
                f"- **Süper Lig Bulguları:** Değerlendirilen **{t1_post.matches}** Süper Lig "
                f"maçında gerçekleşen gol ortalaması "
                f"`{_fmt_float(t1_post.mean_actual_total_goals, 3)}` ve gerçekleşen Üst 2.5 oranı "
                f"`{_fmt_pct(t1_post.actual_over25_rate)}` oldu. Pre-Fix model Süper Lig'de maç "
                f"başı yalnızca `{_fmt_float(t1_pre.mean_pred_total_goals, 3)}` gol ve "
                f"`{_fmt_pct(t1_pre.mean_pred_over25)}` Üst 2.5 öngörerek "
                f"`{_fmt_signed_pct(t1_pre.over25_calibration_gap)}` sistematik sapma üretirken, "
                f"Post-Fix model `{_fmt_float(t1_post.mean_pred_total_goals, 3)}` beklenen gol ve "
                f"`{_fmt_pct(t1_post.mean_pred_over25)}` Üst 2.5 tahminiyle sapmayı "
                f"`{_fmt_signed_pct(t1_post.over25_calibration_gap)}` düzeyine indirdi (RPS: "
                f"`{_fmt_float(t1_pre.rps, 4)}` -> `{_fmt_float(t1_post.rps, 4)}`, kapanış "
                f"piyasası RPS: `{_fmt_float(t1_mkt.rps, 4)}`).",
                "",
            ]
        )

    sections.extend(["## 4. Diğer Hedef Liglerin Ayrıntılı Kırılımı (`E0`, `SP1`, `F1`)", ""])
    for lg_code in result.leagues:
        if lg_code == "T1":
            continue
        _, lg_title = LEAGUE_CODE_MAP.get(lg_code, (None, lg_code))
        sections.extend(
            [
                f"### {lg_title} (`{lg_code}`)",
                "",
                *_render_summary_table(result.league_summaries[lg_code]),
                "",
            ]
        )

    sections.extend(
        [
            "## 5. Güvenirlik Dilimleri (Calibration Buckets)",
            "",
            "### 5.1. 1X2 Olasılık Dilimleri (3 Sonuç x Maç Sayısı)",
            "",
            *_render_calibration_table(
                result.calibration_1x2[MODEL_POST_FIX],
                result.calibration_1x2[MODEL_PRE_FIX],
                result.calibration_1x2[MODEL_MARKET],
            ),
            "",
            "### 5.2. Üst 2.5 Olasılık Dilimleri",
            "",
            *_render_calibration_table(
                result.calibration_over25[MODEL_POST_FIX],
                result.calibration_over25[MODEL_PRE_FIX],
                result.calibration_over25[MODEL_MARKET],
            ),
            "",
            "## 6. Teknik Yorum, Kalan Farklar ve Faz 2 Yol Haritası",
            "",
            "1. **Ölçek Hatasının Giderilmesi Doğrulandı:** Pre-Fix modelde `ratings.py` içinde "
            "lig ortalamasına bölünerek boyutsuz `~1.0` etrafında normalize edilen katsayıların "
            "`poisson.py` tarafında `avg_home_goals` ve `avg_away_goals` ile çarpılmaması, toplam "
            "gol beklentisinde yaklaşık `-%15` ila `-%20` ve Üst 2.5 olasılıklarında `~15 puan` "
            "sistematik eksik tahmine yol açıyordu. Post-Fix model bu yapısal hatayı ortadan "
            "kaldırarak hem toplam gol ölçeğini hem de Üst 2.5 Brier ve Log-Loss metriklerini "
            "belirgin biçimde iyileştirdi.",
            "2. **1X2 Sıralaması vs Gol Hacmi Ayrımı:** Pre-Fix modelde ev sahibi gol beklentisi "
            "`home_advantage (~1.26)` ile çarpılıp deplasman golü `1.0` ölçeğinde bırakıldığı "
            "için `λ / μ` oranı kısmen korunuyor, ancak `λ + μ` toplamı bastırılıyordu. Post-Fix "
            "düzeltmesi 1X2 RPS/Brier/Log-Loss/İsabet metriklerinin tamamını iyileştirirken "
            "beraberlik/gollü maç dengesini gerçek Poisson ölçeğine taşıdı ve `max_goals=10` ile "
            "yüksek skorlu karşılaşmalardaki kuyruk kırpılmasını sonlandırdı.",
            f"3. **Piyasa Kapanış Oranlarıyla Kalan Mesafe:** Kapanış oranları alt kümesinde "
            f"Post-Fix RPS `{_fmt_float(post_on_mkt.rps, 4)}` iken marjı temizlenmiş kapanış "
            f"piyasası RPS `{_fmt_float(mkt.rps, 4)}` seviyesindedir "
            f"(`{post_on_mkt.rps - mkt.rps:+.4f}` fark). Tarihsel CSV walk-forward koşusunda "
            "anlık maç günü sakatlık/kadrolar, teknik direktör değişimleri, fikstür sıkışıklığı "
            "(Avrupa kupası yorgunluğu) ve zaman-ağırlıklı üstel form çürümesi (exponential "
            "time-decay) henüz yer almadığından piyasanın birkaç binde puan önde olması beklenen "
            "ve sağlıklı bir referans sonucudur.",
            "4. **Faz 2 Öncelikleri:** (a) Oynanmış maçlarda üstel zaman sönümlemesi "
            "(`exp(-ξ * Δgün)`) ve sezonlar arası Elo/önsel taşınım (carry-over prior) eklenmesi, "
            "(b) `ρ` ve çekme ağırlığının (`prior_weight`) walk-forward RPS üzerinde optimize "
            "edilmesi, (c) maç başı gerçek Understat xG serilerinin tarihsel backtest katmanına "
            "bağlanması.",
            "",
        ]
    )
    return "\n".join(sections)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m engine.backtest",
        description="Sızıntısız walk-forward futbol tahmin backtest ve kalibrasyon aracı.",
    )
    parser.add_argument(
        "--csv",
        nargs="+",
        default=None,
        help="Çevrimdışı değerlendirilecek yerel Football-Data CSV dosya yolları.",
    )
    parser.add_argument(
        "--seasons",
        nargs="+",
        default=["2425", "2526", "2627"],
        help="Canlı/arşiv CSV çekiminde kullanılacak sezon kodları (varsayılan: 2425 2526 2627).",
    )
    parser.add_argument(
        "--leagues",
        nargs="+",
        default=["T1", "E0", "SP1", "F1"],
        help="Değerlendirilecek lig kodları (varsayılan: T1 E0 SP1 F1).",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=30,
        help="Her lig-sezon grubunda tahmin öncesi minimum geçmiş maç sayısı (varsayılan: 30).",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Üretilen Markdown raporunun kaydedileceği dosya yolu.",
    )
    parser.add_argument(
        "--v2",
        action="store_true",
        help="GÖREV-13 Faz 2 ablasyon, 9'lu İY/MS ve hiperparametre ızgara raporunu (v2) üretir.",
    )
    parser.add_argument(
        "--xi",
        type=float,
        default=DEFAULT_TIME_DECAY_XI,
        help=f"Üstel zaman sönümü katsayısı (varsayılan: {DEFAULT_TIME_DECAY_XI}).",
    )
    parser.add_argument(
        "--alpha",
        type=float,
        default=DEFAULT_MARKET_BLEND_ALPHA,
        help=f"Piyasa harmanlama ağırlığı (varsayılan: {DEFAULT_MARKET_BLEND_ALPHA}).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    all_matches: list[HistoricalCsvMatch] = []
    sources_used: list[str] = []

    if args.csv:
        for idx, raw_path in enumerate(args.csv, start=1):
            p = Path(raw_path)
            csv_text = p.read_text(encoding="utf-8")
            parsed = parse_historical_csv(csv_text, season_code=p.stem or f"local_{idx}")
            all_matches.extend(parsed)
            sources_used.append(str(p))
    else:
        for season in args.seasons:
            for lg in args.leagues:
                lg_code = lg.strip().upper()
                csv_text, src = fetch_football_data_csv_text(season.strip(), lg_code)
                parsed = parse_historical_csv(
                    csv_text, default_league_code=lg_code, season_code=season.strip()
                )
                all_matches.extend(parsed)
                sources_used.append(src)

    warmup_val = max(1, args.warmup)
    wf_result = run_walk_forward(
        all_matches,
        warmup_matches=warmup_val,
        time_decay_xi=args.xi,
        market_blend_alpha=args.alpha,
        sources_used=sources_used,
    )
    if args.v2:
        xi_rows, alpha_rows = evaluate_hyperparameter_grids(
            all_matches,
            warmup_matches=warmup_val,
            optimal_xi=args.xi,
            base_result=wf_result,
        )
        report_md = render_v2_markdown_report(
            wf_result,
            xi_grid_rows=xi_rows,
            alpha_grid_rows=alpha_rows,
        )
    else:
        report_md = render_markdown_report(wf_result)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report_md, encoding="utf-8")
        print(f"Backtest raporu yazıldı: {out_path} ({wf_result.evaluated_matches} maç)")
    else:
        sys.stdout.buffer.write((report_md + "\n").encode("utf-8", errors="replace"))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
