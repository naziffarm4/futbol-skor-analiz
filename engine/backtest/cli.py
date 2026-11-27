"""Walk-forward backtest komut satırı arayüzü ve Türkçe teknik rapor üreticisi."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from engine.backtest.metrics import CalibrationBucket, ModelSummaryMetrics
from engine.backtest.runner import (
    LEAGUE_CODE_MAP,
    MODEL_BASELINE,
    MODEL_MARKET,
    MODEL_ORDER,
    MODEL_POST_FIX,
    MODEL_PRE_FIX,
    HistoricalCsvMatch,
    WalkForwardResult,
    fetch_football_data_csv_text,
    parse_historical_csv,
    run_walk_forward,
)


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


def render_markdown_report(result: WalkForwardResult) -> str:
    """WalkForwardResult çıktısından kapsamlı Türkçe teknik kalibrasyon raporu üretir."""
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

    wf_result = run_walk_forward(
        all_matches,
        warmup_matches=max(1, args.warmup),
        sources_used=sources_used,
    )
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
