"""Maç senaryosu, takım formları ve kadro eksiklerini yorumlayan Türkçe spor analiz motoru."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from engine.models.schemas import HT_FT_LABELS_TR, ImpactLevel, Injury, PlayerPosition
from engine.predictors.poisson import PoissonPredictionResult
from engine.predictors.ratings import TeamRatingProfile

POSITION_LABELS_TR: dict[PlayerPosition, str] = {
    PlayerPosition.GK: "kaleci",
    PlayerPosition.DEF: "savunma",
    PlayerPosition.MID: "orta saha",
    PlayerPosition.FW: "hücum",
}

IMPACT_ORDER: dict[ImpactLevel, int] = {
    ImpactLevel.HIGH: 0,
    ImpactLevel.MEDIUM: 1,
    ImpactLevel.LOW: 2,
}

RIVAL_CLUSTERS: tuple[frozenset[str], ...] = (
    frozenset({"galatasaray", "fenerbahçe", "beşiktaş", "trabzonspor"}),
    frozenset({"real madrid", "barcelona", "atlético madrid", "atletico madrid"}),
    frozenset(
        {
            "arsenal",
            "chelsea",
            "liverpool",
            "manchester city",
            "manchester united",
            "tottenham",
            "tottenham hotspur",
        }
    ),
    frozenset({"paris saint-germain", "psg", "marsilya", "olympique marseille", "lyon", "monaco"}),
)


@dataclass(slots=True)
class MatchAnalysisTexts:
    """TeamAnalysis tablosuna ve bültene yazılacak Türkçe analiz metinleri."""

    match_overview_text: str
    home_analysis_text: str
    away_analysis_text: str
    ht_ft_reasoning_text: str = ""


def _is_marquee_rivalry(home_name: str, away_name: str) -> bool:
    h = home_name.casefold()
    a = away_name.casefold()
    for cluster in RIVAL_CLUSTERS:
        if any(alias in h for alias in cluster) and any(alias in a for alias in cluster):
            return True
    return False


def _prioritize_injuries(injuries: list[Injury]) -> list[Injury]:
    ordered = sorted(
        injuries,
        key=lambda i: (
            0 if getattr(i, "verified_by_multiple_sources", False) else 1,
            IMPACT_ORDER.get(i.impact_level, 3),
            i.player_name,
        ),
    )
    seen: set[str] = set()
    unique: list[Injury] = []
    for inj in ordered:
        key = inj.player_name.casefold()
        if key not in seen:
            seen.add(key)
            unique.append(inj)
    return unique


def _form_breakdown(recent_form: list[str]) -> tuple[int, int, int, int]:
    """Son maç dizisinden (galibiyet, beraberlik, yenilgi, puan) döndürür."""
    wins = sum(1 for r in recent_form if r == "G")
    draws = sum(1 for r in recent_form if r == "B")
    losses = sum(1 for r in recent_form if r == "M")
    pts = wins * 3 + draws
    return wins, draws, losses, pts


def _clean_reason(reason: str) -> str:
    cleaned = reason.strip()
    if not cleaned or cleaned.isdigit():
        return "kadro dışı / cezalı"
    return cleaned


def _format_player_list(ordered: list[Injury], limit: int = 3) -> str:
    featured = ordered[:limit]
    chunks: list[str] = []
    for inj in featured:
        verified_tag = (
            ", çift kaynak onaylı" if getattr(inj, "verified_by_multiple_sources", False) else ""
        )
        chunks.append(
            f"{inj.player_name} ({POSITION_LABELS_TR[inj.position]} - {_clean_reason(inj.reason)}{verified_tag})"
        )
    extra = len(ordered) - len(featured)
    text = ", ".join(chunks)
    if extra > 0:
        text = f"{text} ve {extra} diğer isim"
    return text


def _build_injury_paragraph(team_name: str, profile: TeamRatingProfile, *, is_home: bool) -> str:
    """Kadro durumunu ve mevkiye özel taktiksel eksik etkisini somut oyuncu isimleriyle anlatır."""
    if not profile.injuries:
        if is_home:
            return (
                f"Kadro cephesinde {team_name} adına kayıtlı sakat veya cezalı oyuncu bulunmuyor. "
                f"Teknik heyetin ideal kadro istikrarını koruyarak tam kadro sahaya çıkacak olması, "
                f"taraftarı önünde hem başlangıç baskısında hem de ikinci yarıdaki hamle çeşitliliğinde "
                f"önemli bir taktiksel avantaj sağlıyor."
            )
        return (
            f"Kadro cephesinde {team_name} cephesinde eksik veya cezalı isim yer almıyor. "
            f"Zorlu deplasmana tam kadro çıkmanın getirdiği ideal kadro istikrarı, konuk ekibin "
            f"hatlar arası mesafeyi korumasını ve oyun planını doksan dakikaya yaymasını kolaylaştırıyor."
        )

    ordered = _prioritize_injuries(profile.injuries)
    names_text = _format_player_list(ordered)
    positions = {inj.position for inj in ordered}
    high_count = sum(1 for inj in ordered if inj.impact_level == ImpactLevel.HIGH)

    prefix = (
        f"Kadroda ilk 11 kurgusunu doğrudan etkileyen {high_count} kilit ismin de aralarında bulunduğu "
        if high_count > 0
        else "Maç öncesinde kadro rotasyonunda yer alan "
    )

    tactical_clauses: list[str] = []
    if PlayerPosition.GK in positions or PlayerPosition.DEF in positions:
        if PlayerPosition.GK in positions and PlayerPosition.DEF in positions:
            tactical_clauses.append(
                "kale güvenliği, savunma yerleşimi, hava topları ve duran top savunmasında ciddi risk yaratıyor"
            )
        elif PlayerPosition.GK in positions:
            tactical_clauses.append(
                "kale güvenliği, savunma arkası zamanlaması ve duran top savunmasında belirgin risk oluşturuyor"
            )
        else:
            tactical_clauses.append(
                "savunma yerleşimi, hava topları ve duran top güvenliğinde dikkat çeken bir risk doğuruyor"
            )

    if PlayerPosition.MID in positions:
        tactical_clauses.append(
            "merkezde oyun kurulumu, pas bağlantısı ve top kazanma direncinde düşüşe yol açıyor"
        )

    if PlayerPosition.FW in positions:
        tactical_clauses.append(
            "ceza sahası bitiriciliği, ön alan presi ve hücum derinliğinde güç kaybı beraberinde getiriyor"
        )

    if len(tactical_clauses) == 1:
        effect_text = tactical_clauses[0]
    elif len(tactical_clauses) == 2:
        effect_text = f"{tactical_clauses[0]}; aynı zamanda {tactical_clauses[1]}"
    else:
        effect_text = (
            f"{tactical_clauses[0]}, {tactical_clauses[1]} ve {tactical_clauses[2]}"
        )

    venue_tail = (
        "Teknik ekibin iç sahada bu boşlukları takım boyunu kısaltarak ve yardımlaşmayı artırarak kapatması gerekecek."
        if is_home
        else "Deplasmanda bu eksikleri telafi edebilmek için bloklar arası yardımlaşmanın üst seviyede tutulması şart."
    )
    absence_word = "yokluğu" if len(ordered) == 1 else "eksikleri"
    return f"{prefix}{names_text} {absence_word}, {team_name} adına {effect_text}. {venue_tail}"


def _build_team_form_paragraph(team_name: str, profile: TeamRatingProfile, *, is_home: bool) -> str:
    """Son 5 maç performansı, gol ortalamaları ve gol yememe karnesini takım kimliğiyle harmanlar."""
    n_form = len(profile.recent_form)
    wins, draws, losses, pts = _form_breakdown(profile.recent_form)
    home_clean_sheets = max(0, profile.clean_sheets - profile.away_clean_sheets)

    if profile.played == 0:
        if is_home:
            return (
                f"Sezonun bu bölümünde henüz tamamlanmış resmi lig maçı bulunmayan {team_name}, "
                f"taraftarı önünde oynayacağı bu karşılaşmayla birlikte iç saha ritmini yakalamayı hedefliyor. "
                f"Takımın sahaya dengeli bir yerleşimle çıkıp savunma güvenliğini elden bırakmadan skor araması bekleniyor."
            )
        return (
            f"Henüz resmi lig sınavı kaydı bulunmayan {team_name}, bu dış saha randevusunda kontrollü bir "
            f"başlangıç yaparak oyun disiplinini korumaya odaklanacak. "
            f"Konuk ekip, savunmada kalesini gole kapatıp hızlı hücumlarla etkili olmayı amaçlıyor."
        )

    overall_gpg = profile.goals_for / profile.played
    overall_gapg = profile.goals_against / profile.played

    if is_home:
        v_played = profile.home_played
        v_wins, v_draws, v_losses = profile.home_wins, profile.home_draws, profile.home_losses
        v_gpg = profile.home_goals_for / v_played if v_played > 0 else overall_gpg
        v_gapg = profile.home_goals_against / v_played if v_played > 0 else overall_gapg
        v_cs = home_clean_sheets
        venue_record = (
            f"Taraftarı önünde çıktığı {v_played} iç saha maçında {v_wins} galibiyet, "
            f"{v_draws} beraberlik ve {v_losses} yenilgi alan ekip, maç başına {v_gpg:.2f} gol üretirken "
            f"kalesinde {v_gapg:.2f} gol gördü"
            if v_played > 0
            else f"Genel lig tablosunda maç başına {overall_gpg:.2f} gol atıp kalesinde {overall_gapg:.2f} gol gören ekip, iç sahada ilk sınavına moralli çıkmak istiyor"
        )
        if profile.clean_sheets == 0:
            cs_clause = (
                f"Geride kalan {profile.played} lig maçında henüz kalesini gole kapatamayan ekip, "
                f"bu kez taraftarı önünde savunma konsantrasyonunu doksan dakikaya yaymak istiyor."
            )
        elif v_played > 0 and v_cs == 0:
            cs_clause = (
                f"Sezon genelinde {profile.played} maçın {profile.clean_sheets} tanesinde gol yemeyen ekip, "
                f"iç sahada ise henüz kalesini gole kapatamadı."
            )
        elif v_played > 0:
            cs_clause = (
                f"Genel toplamda {profile.played} maçın {profile.clean_sheets} tanesinde, iç sahada ise "
                f"{v_cs} karşılaşmada kalesini gole kapatmayı başardı."
            )
        else:
            cs_clause = f"Geride kalan {profile.played} lig maçının {profile.clean_sheets} tanesinde kalesini gole kapattı."
    else:
        v_played = profile.away_played
        v_wins, v_draws, v_losses = profile.away_wins, profile.away_draws, profile.away_losses
        v_gpg = profile.away_goals_for / v_played if v_played > 0 else overall_gpg
        v_gapg = profile.away_goals_against / v_played if v_played > 0 else overall_gapg
        v_cs = profile.away_clean_sheets
        venue_record = (
            f"Bu sezon çıktığı {v_played} deplasman sınavında {v_wins} galibiyet, "
            f"{v_draws} beraberlik ve {v_losses} yenilgi elde eden konuk ekip, dış sahada maç başına "
            f"{v_gpg:.2f} gol bulup kalesinde {v_gapg:.2f} gol gördü"
            if v_played > 0
            else f"Lig genelinde maç başına {overall_gpg:.2f} gol üretip {overall_gapg:.2f} gol yiyen konuk takım, dış sahada sağlam bir başlangıç peşinde"
        )
        if profile.clean_sheets == 0:
            cs_clause = (
                f"Ligdeki {profile.played} maçta henüz kalesini gole kapatamayan {team_name}, "
                f"bu deplasmanda savunma güvenliğini ön planda tutmaya çalışacak."
            )
        elif v_played > 0 and v_cs == 0:
            cs_clause = (
                f"Lig genelinde {profile.played} maçın {profile.clean_sheets} tanesinde gol yemeyen {team_name}, "
                f"dış sahada ise henüz kalesini gole kapatamadı."
            )
        elif v_played > 0:
            cs_clause = (
                f"Ligdeki {profile.played} maçın {profile.clean_sheets} tanesinde gol yemeyen {team_name}, "
                f"deplasmanda da {v_cs} kez kalesini gole kapatarak dirençli bir görüntü çizdi."
            )
        else:
            cs_clause = f"Toplam {profile.played} maçın {profile.clean_sheets} tanesinde gol yemeden sahadan ayrıldı."

    form_detail = (
        f"son {n_form} lig maçında {wins} galibiyet, {draws} beraberlik ve {losses} yenilgiyle {pts} puan toplayan"
    )
    if profile.espn_rank is not None and profile.espn_points is not None:
        standing_prefix = f"puan tablosunda {profile.espn_rank}. sırada {profile.espn_points} puanla yer alıp "
    elif profile.espn_rank is not None:
        standing_prefix = f"puan tablosunda {profile.espn_rank}. basamakta yer alıp "
    else:
        standing_prefix = ""

    # Takım profiline göre farklılaşan anlatım yapısı (hücumcu, savunmacı, formsuz, dengeli)
    if v_gpg >= 1.65 and pts >= 7:
        lead = (
            f"Üretken hücum kimliğiyle öne çıkan, {standing_prefix}{form_detail} {team_name}, "
            f"rakip ceza sahasında çoğalma becerisiyle dikkat çekiyor."
        )
    elif v_gapg <= 0.95 or (profile.played >= 3 and profile.clean_sheets / profile.played >= 0.40):
        lead = (
            f"Disiplinli savunma kurgusuyla güven veren, {standing_prefix}{form_detail} {team_name}, "
            f"rakiplerine kolay pozisyon tanımayan kompakt yapısıyla öne çıkıyor."
        )
    elif (n_form >= 3 and pts <= 4) or v_gapg >= 1.75:
        lead = (
            f"Son haftalarda istediği istikrarı yakalamakta zorlanan, {standing_prefix}{form_detail} {team_name}, "
            f"özellikle geçiş savunmasındaki dalgalanmaları gidermeye çalışıyor."
        )
    else:
        lead = (
            f"Oyunun iki yönünü dengeli oynamaya gayret eden, {standing_prefix}{form_detail} {team_name}, "
            f"puan ritmini koruyarak üst sıralara tutunma mücadelesi veriyor."
        )

    metric_bits: list[str] = []
    if profile.xg_for_per_match is not None:
        metric_bits.append(f"maç başına {profile.xg_for_per_match:.2f} gol beklentisi")
    if profile.sot_for_per_match is not None:
        if profile.shots_for_per_match is not None:
            metric_bits.append(
                f"{profile.shots_for_per_match:.1f} şutta {profile.sot_for_per_match:.1f} isabet"
            )
        else:
            metric_bits.append(f"{profile.sot_for_per_match:.1f} isabetli şut")
    if profile.corners_for_per_match is not None:
        metric_bits.append(f"{profile.corners_for_per_match:.1f} korner")

    ht_att_pct = round(profile.first_half_attack_share * 100)
    extra_metrics_sentence = ""
    if metric_bits:
        joined_metrics = ", ".join(metric_bits)
        extra_metrics_sentence = (
            f" Saha içi üretim metriklerinde {joined_metrics} ortalaması yakalayan ekip, "
            f"gollerinin yaklaşık yüzde {ht_att_pct}'ini ilk yarılarda buluyor."
        )

    return f"{lead} {venue_record}. {cs_clause}{extra_metrics_sentence}"


def _pure_matrix_1x2(matrix: list[list[float]]) -> tuple[float, float, float]:
    ph = pd = pa = 0.0
    for x, row in enumerate(matrix):
        for y, prob in enumerate(row):
            if x > y:
                ph += prob
            elif x == y:
                pd += prob
            else:
                pa += prob
    tot = ph + pd + pa
    if tot <= 0.0:
        return (1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0)
    return (ph / tot, pd / tot, pa / tot)


def _extract_market_triplet(
    market_probs: Mapping[str, Any] | None,
) -> tuple[float, float, float] | None:
    if not market_probs:
        return None
    vals: list[float] = []
    for keys in (
        ("p_home", "home_prob", "prob_home"),
        ("p_draw", "draw_prob", "prob_draw"),
        ("p_away", "away_prob", "prob_away"),
    ):
        found: float | None = None
        for k in keys:
            raw = market_probs.get(k) if isinstance(market_probs, Mapping) else getattr(market_probs, k, None)
            if raw is None or isinstance(raw, bool):
                continue
            try:
                fval = float(raw)
            except (TypeError, ValueError):
                continue
            if math.isfinite(fval) and fval > 0.0:
                found = fval
                break
        if found is None:
            return None
        vals.append(found)
    s = vals[0] + vals[1] + vals[2]
    if s <= 0.0:
        return None
    return (vals[0] / s, vals[1] / s, vals[2] / s)


def _favorite_label_tr(
    ph: float,
    pd: float,
    pa: float,
    home_name: str,
    away_name: str,
) -> str:
    if ph >= pd and ph >= pa:
        return f"{home_name} galibiyeti"
    if pa >= ph and pa >= pd:
        return f"{away_name} galibiyeti"
    return "beraberlik"


def _build_score_justification_paragraph(
    *,
    home_name: str,
    away_name: str,
    home_profile: TeamRatingProfile,
    away_profile: TeamRatingProfile,
    poisson_result: PoissonPredictionResult,
    round_number: int | None,
    market_probs: Mapping[str, float] | None = None,
) -> str:
    """1. Paragraf: Öne çıkan tahmini skoru ilk cümlede belirterek somut saha verileriyle gerekçelendirir."""
    pred_h = poisson_result.predicted_home_score
    pred_a = poisson_result.predicted_away_score
    score_str = f"{pred_h}-{pred_a}"
    round_prefix = f"Ligde {round_number}. hafta mücadelesinde " if round_number else "Haftanın öne çıkan karşılaşmasında "

    if pred_h == 0 and pred_a == 0:
        first_sentence = (
            f"{round_prefix}{home_name} ile {away_name} arasındaki randevuda {score_str} skoru, "
            f"iki takımın da savunma güvenliğini ön planda tutan yapısı, kalelerini gole kapatma alışkanlığı "
            f"ve son haftalardaki kontrollü hücum temposu nedeniyle öne çıkıyor."
        )
    elif pred_h == pred_a:
        first_sentence = (
            f"{round_prefix}{home_name} ile {away_name} eşleşmesinde {score_str} skoru, "
            f"iki ekibin de son haftalarda skor üretme becerisini korurken birbirine yakın saha içi "
            f"dengesi sergilemesi nedeniyle en güçlü sonuç olarak öne çıkıyor."
        )
    elif pred_h > pred_a and pred_a == 0:
        first_sentence = (
            f"{round_prefix}{home_name} - {away_name} karşılaşmasında {score_str} skoru, "
            f"ev sahibinin taraftarı önündeki gol üretkenliği ve gol yememe disiplininin konuk ekibin "
            f"dış saha hücum direncine ağır basması sayesinde öne çıkıyor."
        )
    elif pred_h > pred_a:
        first_sentence = (
            f"{round_prefix}{home_name} - {away_name} randevusunda {score_str} skoru, "
            f"ev sahibinin iç sahadaki yüksek bitiriciliği ile konuk ekibin deplasmanda gol bulabilen "
            f"ancak kalesini kapatmakta zorlanan savunma dengesinin kesişmesiyle öne çıkıyor."
        )
    elif pred_h == 0:
        first_sentence = (
            f"{round_prefix}{home_name} - {away_name} mücadelesinde {score_str} skoru, "
            f"konuk ekibin deplasmandaki sağlam savunma yerleşimi ve gol yememe alışkanlığının ev sahibinin "
            f"son haftalardaki hücum üretkenliği sorunlarıyla birleşmesi nedeniyle öne çıkıyor."
        )
    else:
        first_sentence = (
            f"{round_prefix}{home_name} - {away_name} eşleşmesinde {score_str} skoru, "
            f"konuk ekibin son haftalardaki yüksek hücum ritmi ve dış saha bitiriciliğinin ev sahibinin "
            f"savunma zaaflarına üstün gelmesiyle ilk sıraya yerleşiyor."
        )

    if home_profile.played > 0 and away_profile.played > 0:
        h_gpg = (
            home_profile.home_goals_for / home_profile.home_played
            if home_profile.home_played > 0
            else home_profile.goals_for / home_profile.played
        )
        h_gapg = (
            home_profile.home_goals_against / home_profile.home_played
            if home_profile.home_played > 0
            else home_profile.goals_against / home_profile.played
        )
        a_gpg = (
            away_profile.away_goals_for / away_profile.away_played
            if away_profile.away_played > 0
            else away_profile.goals_for / away_profile.played
        )
        a_gapg = (
            away_profile.away_goals_against / away_profile.away_played
            if away_profile.away_played > 0
            else away_profile.goals_against / away_profile.played
        )
        h_cs_text = (
            f"toplam {home_profile.clean_sheets} maçta kalesini gole kapattı"
            if home_profile.clean_sheets > 0
            else "henüz kalesini gole kapatamadı"
        )
        a_cs_text = (
            f"sezon genelinde {away_profile.clean_sheets} kez gol yemeden sahadan ayrıldı"
            if away_profile.clean_sheets > 0
            else "sezon genelinde henüz gol yemeden tamamladığı maç bulunmuyor"
        )
        stats_sentence = (
            f"{home_name} iç sahada maç başına {h_gpg:.2f} gol üretip kalesinde {h_gapg:.2f} gol görürken "
            f"{h_cs_text}; {away_name} ise deplasmanda "
            f"{a_gpg:.2f} gol ortalaması yakalayıp {a_gapg:.2f} gol yedi ve {a_cs_text}."
        )
    else:
        stats_sentence = (
            "İki ekibin mevcut kadro kalitesi, iç-dış saha yerleşim alışkanlıkları ve savunma "
            "öncelikleri bir araya geldiğinde tabelada bu skor dengesi belirginlik kazanıyor."
        )

    alt_scores = [sp.score for sp in poisson_result.top_scores[1:3]]
    if len(alt_scores) == 2:
        alt_sentence = (
            f"Maç içi kırılmalara bağlı olarak {alt_scores[0]} ve {alt_scores[1]} sonuçları da "
            f"öne çıkan diğer güçlü skor ihtimalleri arasında yer alıyor."
        )
    elif len(alt_scores) == 1:
        alt_sentence = (
            f"Oyun dengesinin değişmesi durumunda {alt_scores[0]} skoru en yakın alternatif olarak dikkat çekiyor."
        )
    else:
        alt_sentence = ""

    pressure_sentence = ""
    if home_profile.sot_for_per_match is not None and away_profile.sot_for_per_match is not None:
        corner_tail = (
            f" ve {home_profile.corners_for_per_match:.1f} - {away_profile.corners_for_per_match:.1f} korner dengesi"
            if home_profile.corners_for_per_match is not None
            and away_profile.corners_for_per_match is not None
            else ""
        )
        pressure_sentence = (
            f"İki ekibin maç başına {home_profile.sot_for_per_match:.1f} ile "
            f"{away_profile.sot_for_per_match:.1f} isabetli şut temposu{corner_tail} de bu skor "
            f"beklentisini sahadaki pozisyon hacmiyle destekliyor."
        )

    ht_ft_seq = poisson_result.all_ht_ft or poisson_result.top_ht_ft
    over25_pct = poisson_result.over_2_5_prob * 100.0
    btts_pct = poisson_result.btts_yes_prob * 100.0
    if len(ht_ft_seq) >= 2:
        h1, h2 = ht_ft_seq[0], ht_ft_seq[1]
        outlook_sentence = (
            f"İY/MS görünümünde {h1.code} ({h1.label}, %{h1.prob * 100:.1f}) başı çekerken "
            f"{h2.code} ({h2.label}, %{h2.prob * 100:.1f}) en yakın takipçi konumunda bulunuyor; "
            f"ayrıca 2.5 Üst ihtimali %{over25_pct:.1f} ve KG Var beklentisi %{btts_pct:.1f} düzeyinde seyrediyor."
        )
    else:
        outlook_sentence = (
            f"Karşılaşmada 2.5 Üst ihtimali %{over25_pct:.1f} ve KG Var beklentisi %{btts_pct:.1f} "
            f"düzeyinde öne çıkıyor."
        )

    mkt_triplet = _extract_market_triplet(market_probs)
    market_sentence = ""
    if mkt_triplet is not None or poisson_result.market_blended:
        pure_h, pure_d, pure_a = _pure_matrix_1x2(poisson_result.matrix)
        mh, md, ma = mkt_triplet or (
            poisson_result.home_win_prob,
            poisson_result.draw_prob,
            poisson_result.away_win_prob,
        )
        pure_fav = _favorite_label_tr(pure_h, pure_d, pure_a, home_name, away_name)
        mkt_fav = _favorite_label_tr(mh, md, ma, home_name, away_name)
        if pure_fav == mkt_fav:
            market_sentence = (
                f"Saha içi istatistik modeli ile marjı arındırılmış piyasa beklentisi de "
                f"{pure_fav} yönünde uzlaşarak bu tahmini teyit ediyor."
            )
        else:
            market_sentence = (
                f"Saha içi istatistik modeli {pure_fav} sinyali üretirken marjı arındırılmış "
                f"piyasa beklentisinin {mkt_fav} tarafına yönelmesi eşleşmedeki taktik dengeye dikkat çekiyor."
            )

    return " ".join(
        part
        for part in (
            first_sentence,
            stats_sentence,
            pressure_sentence,
            alt_sentence,
            outlook_sentence,
            market_sentence,
        )
        if part
    )


def _select_turning_point(
    home_name: str,
    away_name: str,
    home_profile: TeamRatingProfile,
    away_profile: TeamRatingProfile,
) -> str:
    """Maçın somut kırılma noktasını (kilit eksikler, form farkı veya iç saha baskısı) belirler."""
    home_high = [i for i in _prioritize_injuries(home_profile.injuries) if i.impact_level == ImpactLevel.HIGH]
    away_high = [i for i in _prioritize_injuries(away_profile.injuries) if i.impact_level == ImpactLevel.HIGH]

    home_swing = (1.0 - home_profile.attack_multiplier) + (
        home_profile.defense_vulnerability_multiplier - 1.0
    )
    away_swing = (1.0 - away_profile.attack_multiplier) + (
        away_profile.defense_vulnerability_multiplier - 1.0
    )

    if max(home_swing, away_swing) >= 0.14 and (home_profile.injuries or away_profile.injuries):
        if home_swing >= away_swing and home_profile.injuries:
            key_inj = (home_high or _prioritize_injuries(home_profile.injuries))[0]
            pos_label = POSITION_LABELS_TR[key_inj.position]
            return (
                f"Maçın kırılma noktasını, {home_name} cephesinde {key_inj.player_name} başta olmak üzere "
                f"{pos_label} hattındaki önemli eksiklerin oyun dengesinde yaratacağı boşluk belirleyecek."
            )
        if away_profile.injuries:
            key_inj = (away_high or _prioritize_injuries(away_profile.injuries))[0]
            pos_label = POSITION_LABELS_TR[key_inj.position]
            return (
                f"Maçın kırılma noktasını, {away_name} kadrosunda {key_inj.player_name} öncülüğündeki "
                f"{pos_label} eksikleri nedeniyle konuk ekibin baskı altında vereceği reaksiyon belirleyecek."
            )

    _, _, _, home_pts = _form_breakdown(home_profile.recent_form)
    _, _, _, away_pts = _form_breakdown(away_profile.recent_form)
    if len(home_profile.recent_form) >= 3 and len(away_profile.recent_form) >= 3:
        if home_pts - away_pts >= 5:
            return (
                f"Karşılaşmanın kırılma noktası, son haftalarda {home_pts} puan toplayarak form zirvesine çıkan "
                f"{home_name} ekibinin yakaladığı özgüven farkını erken dakikalarda skora yansıtıp yansıtamayacağı olacak."
            )
        if away_pts - home_pts >= 5:
            return (
                f"Karşılaşmanın kırılma noktası, son dönemde {away_pts} puanlık seri yakalayan formda {away_name} "
                f"ekibinin bu ritim üstünlüğünü deplasman geçişlerinde ne ölçüde değerlendireceği olacak."
            )

    if home_profile.adjusted_offense_rating - away_profile.adjusted_defense_rating >= 7.0:
        return (
            f"Mücadelenin kırılma noktası, {home_name} ekibinin iç saha baskısıyla ilk yarım saatte kuracağı "
            f"ceza sahası kuşatmasına konuk savunmanın ne kadar dayanabileceği olacak."
        )
    if away_profile.adjusted_defense_rating >= 65.0:
        return (
            f"Mücadelenin kırılma noktası, {away_name} savunma bloğunun merkezdeki pas kanallarını kapatıp "
            f"ev sahibini kenar ortalarına zorlama planının işleyip işlemeyeceği olacak."
        )
    return (
        f"Maçın kırılma noktasını, {home_name} ekibinin taraftar desteğiyle kuracağı ön alan baskısı ile "
        f"merkez orta sahadaki ikili mücadele üstünlüğü belirleyecek."
    )


def _build_scenario_paragraph(
    *,
    home_name: str,
    away_name: str,
    home_profile: TeamRatingProfile,
    away_profile: TeamRatingProfile,
    poisson_result: PoissonPredictionResult,
) -> str:
    """2. Paragraf: Maç profili (tek taraflı baskı, gollü düello, dengeli taktik, savunma savaşı + derbi), tempo ve kırılma noktası."""
    total_goals_est = poisson_result.expected_home_goals + poisson_result.expected_away_goals
    home_power = (home_profile.adjusted_offense_rating + home_profile.adjusted_defense_rating) / 2.0
    away_power = (away_profile.adjusted_offense_rating + away_profile.adjusted_defense_rating) / 2.0
    power_gap = home_power - away_power
    is_derby = _is_marquee_rivalry(home_name, away_name)

    derby_lead = (
        f"Derbi atmosferinin getirdiği yüksek heyecan ve psikolojik gerilim altında {home_name} ile {away_name} "
        f"kozlarını paylaşırken, anlık bireysel kalite her zamankinden daha belirleyici olacak. "
        if is_derby
        else ""
    )

    if abs(power_gap) >= 6.5 or max(poisson_result.home_win_prob, poisson_result.away_win_prob) >= 0.56:
        # Senaryo 1: Güçlü favori / tek taraflı baskı
        tempo_label = "yüksek tempolu" if total_goals_est >= 2.65 else "orta-yüksek tempolu"
        if power_gap >= 0 or poisson_result.home_win_prob >= poisson_result.away_win_prob:
            scenario_body = (
                f"Oyun senaryosunda saha içi güç üstünlüğünü elinde bulunduran {home_name} ekibinin topa "
                f"hükmederek oyunu rakip yarı alana yıkması, {away_name} tarafının ise derinde bekleyip "
                f"hızlı çıkışlarla nefes araması bekleniyor; karşılaşmanın {tempo_label} ve tek taraflı "
                f"baskı sekanslarıyla ilerlemesi öngörülüyor."
            )
        else:
            scenario_body = (
                f"Deplasmanda olmasına rağmen belirgin kadro ve oyun gücüne sahip {away_name} ekibinin "
                f"topun kontrolünü alarak tempoyu belirlemesi, {home_name} cephesinin ise kalabalık savunma "
                f"yerleşimiyle direnç göstermesi bekleniyor; mücadelenin {tempo_label} bir baskı düzeninde "
                f"geçeceği öngörülüyor."
            )
    elif total_goals_est >= 2.75 or (
        poisson_result.expected_home_goals >= 1.25 and poisson_result.expected_away_goals >= 1.15
    ):
        # Senaryo 2: Gollü düello / karşılıklı açık oyun
        scenario_body = (
            "Her iki takımın da geride beklemek yerine dikine paslarla doğrudan rakip kaleyi düşündüğü, "
            "yüksek tempolu ve karşılıklı açık oyuna sahne olacak gollü bir düello bekleniyor. "
            "Kanat bindirmeleri ve hızlı geçiş hücumlarıyla iki ceza sahasında da pozisyon zenginliği yaşanacaktır."
        )
    elif total_goals_est >= 2.05:
        # Senaryo 3: Dengeli taktik mücadelesi
        scenario_body = (
            "Orta saha üstünlüğü ve alan paylaşımının ön planda olacağı orta tempolu, dengeli bir taktik "
            "mücadelesi öne çıkıyor. İki teknik adamın da kontrollü başlayacağı oyunda ilk golü bulan taraf "
            "rakibini risk almaya zorlayarak ciddi bir taktik avantaj yakalayacaktır."
        )
    else:
        # Senaryo 4: Düşük tempolu savunma savaşı
        scenario_body = (
            "Savunma bloklarının hatlar arası mesafeyi daraltacağı, düşük tempolu ve sabır gerektiren "
            "sert bir savunma savaşı bekleniyor. Açık oyunda boşluk bulmanın zorlaşacağı bu düzende "
            "duran toplar ve ikinci top kazanımları skoru tayin edecek ana silahlar olacak."
        )

    turning_point = _select_turning_point(home_name, away_name, home_profile, away_profile)
    return f"{derby_lead}{scenario_body} {turning_point}"


def _describe_finishing_gap(actual_gpg: float, xg_pg: float) -> str:
    diff = actual_gpg - xg_pg
    if diff >= 0.25:
        return f"beklentinin üzerinde yüksek bitiricilik verimiyle (+{diff:.2f} fark)"
    if diff <= -0.25:
        return f"pozisyon kalitesinin altında kalan şanssız bitiricilikle ({diff:.2f} fark, yukarı yönlü düzeltme sinyali)"
    return "ürettiği pozisyon kalitesiyle uyumlu dengeli bir bitiricilikle"


def _build_ht_ft_reasoning_text(
    *,
    home_name: str,
    away_name: str,
    home_profile: TeamRatingProfile,
    away_profile: TeamRatingProfile,
    poisson_result: PoissonPredictionResult,
    market_probs: Mapping[str, float] | None = None,
) -> str:
    """5 kaynaktaki tüm metrikleri sentezleyerek 'Neden bu İY ve MS çıktı?' sorusunu 2 paragrafta açıklar."""
    ht_h = poisson_result.predicted_ht_home_score
    ht_a = poisson_result.predicted_ht_away_score
    ft_h = poisson_result.predicted_home_score
    ft_a = poisson_result.predicted_away_score
    ht_ft_code = poisson_result.ht_ft_prediction
    ht_ft_label = HT_FT_LABELS_TR.get(ht_ft_code, ht_ft_code)
    top_ht_ft_prob = (
        poisson_result.top_ht_ft[0].prob * 100.0 if poisson_result.top_ht_ft else 0.0
    )

    # 1) Puan durumu & form & ev/deplasman gerçek gol dengesi (ESPN + Transfermarkt)
    _, _, _, h_form_pts = _form_breakdown(home_profile.recent_form)
    _, _, _, a_form_pts = _form_breakdown(away_profile.recent_form)
    h_gpg = (
        home_profile.goals_for / home_profile.played
        if home_profile.played > 0
        else poisson_result.expected_home_goals
    )
    a_gpg = (
        away_profile.goals_for / away_profile.played
        if away_profile.played > 0
        else poisson_result.expected_away_goals
    )
    h_home_gpg = (
        home_profile.home_goals_for / home_profile.home_played
        if home_profile.home_played > 0
        else h_gpg
    )
    a_away_gpg = (
        away_profile.away_goals_for / away_profile.away_played
        if away_profile.away_played > 0
        else a_gpg
    )

    if home_profile.espn_rank is not None and away_profile.espn_rank is not None:
        h_pts_str = f" ({home_profile.espn_points} puan)" if home_profile.espn_points is not None else ""
        a_pts_str = f" ({away_profile.espn_points} puan)" if away_profile.espn_points is not None else ""
        table_clause = (
            f"ESPN puan tablosunda {home_profile.espn_rank}. sırada{h_pts_str} yer alan {home_name} "
            f"(son {len(home_profile.recent_form)} maçta {h_form_pts} puan, iç sahada {h_home_gpg:.2f} gol) "
            f"ile {away_profile.espn_rank}. basamaktaki{a_pts_str} {away_name} "
            f"(son {len(away_profile.recent_form)} maçta {a_form_pts} puan, dış sahada {a_away_gpg:.2f} gol) "
            f"karşılaştırıldığında"
        )
    else:
        table_clause = (
            f"Son {len(home_profile.recent_form)} maçta {h_form_pts} puan toplayıp iç sahada maç başı "
            f"{h_home_gpg:.2f} gol üreten {home_name} ile {a_form_pts} puanlık form grafiği ve "
            f"deplasmanda {a_away_gpg:.2f} gol ortalamasıyla oynayan {away_name} yan yana konulduğunda"
        )

    # 2) xG / xGA vs gerçek gol karşılaştırması (Understat, FotMob-xG veya ShotProxy-xG)
    if home_profile.xg_for_per_match is not None and away_profile.xg_for_per_match is not None:
        combined_sources = set(home_profile.sources_matched) | set(away_profile.sources_matched)
        has_fotmob_xg = (
            home_profile.xg_source == "FotMob-xG"
            or away_profile.xg_source == "FotMob-xG"
            or "FotMob-xG" in combined_sources
        )
        has_understat_xg = (
            home_profile.xg_source == "Understat"
            or away_profile.xg_source == "Understat"
            or "Understat" in combined_sources
        )
        if (
            home_profile.xg_is_derived
            or away_profile.xg_is_derived
            or home_profile.xg_source == "ShotProxy-xG"
            or away_profile.xg_source == "ShotProxy-xG"
        ):
            xg_source_note = "isabetli şut kalitesinden türetilen xG vekili (ShotProxy-xG) modelinde"
        elif has_fotmob_xg and not has_understat_xg:
            xg_source_note = "FotMob-xG beklenen gol verilerinde"
        elif has_understat_xg:
            xg_source_note = "Understat beklenen gol verilerinde"
        else:
            xg_source_note = "beklenen gol verilerinde"
        h_xga = (
            f" / {home_profile.xg_against_per_match:.2f} xGA"
            if home_profile.xg_against_per_match is not None
            else ""
        )
        a_xga = (
            f" / {away_profile.xg_against_per_match:.2f} xGA"
            if away_profile.xg_against_per_match is not None
            else ""
        )
        h_finish = _describe_finishing_gap(h_gpg, home_profile.xg_for_per_match)
        a_finish = _describe_finishing_gap(a_gpg, away_profile.xg_for_per_match)
        xg_clause = (
            f"{xg_source_note} {home_name} maç başı {home_profile.xg_for_per_match:.2f} xG{h_xga} üretip "
            f"{h_gpg:.2f} gerçek gol ortalamasıyla {h_finish} ilerlerken, {away_name} "
            f"{away_profile.xg_for_per_match:.2f} xG{a_xga} karşısında {a_gpg:.2f} golle {a_finish} sahada yer alıyor."
        )
    else:
        xg_clause = (
            f"maç özelinde hesaplanan beklenen gol dengesinde {home_name} {poisson_result.expected_home_goals:.2f} xG, "
            f"{away_name} ise {poisson_result.expected_away_goals:.2f} xG üretim seviyesine ulaşıyor."
        )

    # 3) Football-Data şut, isabetli şut ve korner baskısı
    if home_profile.sot_for_per_match is not None or away_profile.sot_for_per_match is not None:
        h_shots = (
            f"{home_profile.shots_for_per_match:.1f} şut ve "
            if home_profile.shots_for_per_match is not None
            else ""
        )
        a_shots = (
            f"{away_profile.shots_for_per_match:.1f} şut ve "
            if away_profile.shots_for_per_match is not None
            else ""
        )
        h_sot = f"{(home_profile.sot_for_per_match or 0.0):.1f} isabetli şut"
        a_sot = f"{(away_profile.sot_for_per_match or 0.0):.1f} isabetli şut"
        corner_cmp = (
            f"; korner baskısında da {home_profile.corners_for_per_match:.1f} - "
            f"{away_profile.corners_for_per_match:.1f} korner ortalamasıyla duran top tehdidi şekilleniyor"
            if home_profile.corners_for_per_match is not None
            and away_profile.corners_for_per_match is not None
            else ""
        )
        shot_clause = (
            f"Football-Data şut hacmi verilerinde {home_name} maç başı {h_shots}{h_sot} üretirken "
            f"{away_name} {a_shots}{a_sot} seviyesinde kalıyor{corner_cmp}."
        )
    else:
        shot_clause = (
            f"Hücum reytinglerinde {home_name} ({home_profile.adjusted_offense_rating:.1f}) ile "
            f"{away_name} ({away_profile.adjusted_offense_rating:.1f}) arasındaki şut ve ceza sahası "
            f"üretkenlik farkı savunma dirençleriyle ({home_profile.adjusted_defense_rating:.1f} - "
            f"{away_profile.adjusted_defense_rating:.1f}) doğrudan örtüşüyor."
        )

    p1 = (
        f"Neden İlk Yarı {ht_h}-{ht_a} ve Maç Sonucu {ft_h}-{ft_a} "
        f"(İY/MS: {ht_ft_code} - {ht_ft_label} — %{top_ht_ft_prob:.1f})? "
        f"Çoklu kaynak sinyalleri bir arada değerlendirildiğinde, {table_clause} {xg_clause} {shot_clause}"
    )

    # Paragraf 2: İlk 45 / İkinci 45 tempo dağılımı + çift kaynak onaylı eksikler + ilk 3 İY/MS karşılaştırması
    h_ht_pct = round(home_profile.first_half_attack_share * 100)
    h_2h_pct = 100 - h_ht_pct
    a_ht_pct = round(away_profile.first_half_attack_share * 100)
    a_conc_ht_pct = round(away_profile.first_half_concede_share * 100)

    lam_ht = poisson_result.expected_ht_home_goals
    mu_ht = poisson_result.expected_ht_away_goals
    lam_2h = max(0.05, poisson_result.expected_home_goals - lam_ht)
    mu_2h = max(0.05, poisson_result.expected_away_goals - mu_ht)

    sh_h = ft_h - ht_h
    sh_a = ft_a - ht_a
    if ht_h == 0 and ht_a == 0 and (sh_h > 0 or sh_a > 0):
        half_flow = (
            f"İlk 45 dakikada {lam_ht:.2f} - {mu_ht:.2f} düzeyinde kalan sınırlı gol beklentisi ve "
            f"kontrollü blok yerleşimi devrenin {ht_h}-{ht_a} dengesinde kapanmasını öne çıkarırken, "
            f"ikinci yarıda ({lam_2h:.2f} - {mu_2h:.2f} gol beklentisi) artan yorgunluk ve hamlelerle "
            f"tabelanın {ft_h}-{ft_a} sonucuna açılması bekleniyor."
        )
    elif ht_h > ht_a:
        half_flow = (
            f"Ev sahibinin ilk devre gol beklentisi ({lam_ht:.2f} - {mu_ht:.2f}) erken baskıyla soyunma "
            f"odasına {ht_h}-{ht_a} üstünlüğüyle gitmesini desteklerken, ikinci 45 dakikada "
            f"({lam_2h:.2f} - {mu_2h:.2f} gol beklentisi) oluşan geçiş alanlarıyla maçın {ft_h}-{ft_a} "
            f"skoruna taşınması en güçlü senaryo olarak ayrışıyor."
        )
    elif ht_h < ht_a:
        half_flow = (
            f"Konuk ekibin ilk yarıdaki geçiş etkinliği ({lam_ht:.2f} - {mu_ht:.2f} ilk devre beklentisi) "
            f"devreyi {ht_h}-{ht_a} önde kapatma ihtimalini güçlendirirken, ikinci yarıdaki "
            f"({lam_2h:.2f} - {mu_2h:.2f}) oyun dengesiyle karşılaşmanın {ft_h}-{ft_a} tamamlanması öngörülüyor."
        )
    else:
        half_flow = (
            f"İlk 45 dakikadaki {lam_ht:.2f} - {mu_ht:.2f} ve ikinci 45 dakikadaki {lam_2h:.2f} - {mu_2h:.2f} "
            f"beklenen gol dağılımı, ilk yarının {ht_h}-{ht_a} dengesiyle geçilip doksan dakikanın "
            f"{ft_h}-{ft_a} skoruyla noktalanmasına işaret ediyor."
        )

    tempo_clause = (
        f"Devre bazlı tempo profilinde {home_name} ilk yarıda %{h_ht_pct}, ikinci yarıda %{h_2h_pct} "
        f"gol üretim payıyla oynarken; {away_name} ilk 45 dakikada %{a_ht_pct} gol üretim payına sahip olup "
        f"yediği gollerde ilk devre payı %{a_conc_ht_pct} düzeyinde seyrediyor. {half_flow}"
    )

    all_inj = [
        *(
            (home_name, inj)
            for inj in _prioritize_injuries(home_profile.injuries)
        ),
        *(
            (away_name, inj)
            for inj in _prioritize_injuries(away_profile.injuries)
        ),
    ]
    verified_inj = [
        (tname, inj)
        for tname, inj in all_inj
        if getattr(inj, "verified_by_multiple_sources", False)
    ]
    single_inj = [
        (tname, inj)
        for tname, inj in all_inj
        if not getattr(inj, "verified_by_multiple_sources", False)
    ]

    if verified_inj:
        v_samples = ", ".join(
            f"{inj.player_name} ({tname}, {'+'.join(getattr(inj, 'sources', ['Transfermarkt'])[:2])})"
            for tname, inj in verified_inj[:3]
        )
        if single_inj:
            injury_cmp_clause = (
                f"Kadro doğrulamasında çift kaynak onaylı {v_samples} eksikleri tam ağırlıkla (%100 etki) "
                f"taktik denklemi doğrudan aşağı çekerken, yalnızca tek kaynakta yer alan {len(single_inj)} "
                f"şüpheli/tarihi belirsiz kayıt %75 temkinli ağırlıkla dengeleniyor."
            )
        else:
            injury_cmp_clause = (
                f"Kadro doğrulamasında çift kaynak onaylı {v_samples} eksikleri tam ağırlıkla (%100 etki) "
                f"taktik denklemi doğrudan aşağı çekiyor."
            )
    elif single_inj:
        s_samples = ", ".join(
            f"{inj.player_name} ({tname})" for tname, inj in single_inj[:3]
        )
        injury_cmp_clause = (
            f"Kadro cephesinde tek kaynaklı {s_samples} eksikleri modelde taktiksel risk olarak "
            f"hesaba katılıyor."
        )
    else:
        injury_cmp_clause = (
            "Her iki takımın da ideal kadro istikrarını koruması devreler arası güç düşüşünü sınırlıyor."
        )

    if len(poisson_result.top_ht_ft) >= 3:
        h1, h2, h3 = poisson_result.top_ht_ft[:3]
        top3_clause = (
            f"İY/MS olasılık sıralamasında {h1.code} ({h1.label}, %{h1.prob * 100:.1f}) ilk sırada yer alırken, "
            f"olası bir erken duran top veya kart kırılmasında {h2.code} ({h2.label}, %{h2.prob * 100:.1f}) "
            f"ve {h3.code} ({h3.label}, %{h3.prob * 100:.1f}) en güçlü alternatif senaryolar olarak öne çıkıyor."
        )
    elif len(poisson_result.top_ht_ft) == 2:
        h1, h2 = poisson_result.top_ht_ft[:2]
        top3_clause = (
            f"İY/MS dağılımında {h1.code} (%{h1.prob * 100:.1f}) liderliğini korurken {h2.code} "
            f"(%{h2.prob * 100:.1f}) en yakın alternatif konumunda bulunuyor."
        )
    else:
        top3_clause = ""

    over25_pct = poisson_result.over_2_5_prob * 100.0
    btts_pct = poisson_result.btts_yes_prob * 100.0
    ou_btts_clause = (
        f"Gol piyasası projeksiyonlarında 2.5 Üst ihtimali %{over25_pct:.1f} ve KG Var olasılığı "
        f"%{btts_pct:.1f} olarak hesaplanıyor."
    )

    mkt_triplet = _extract_market_triplet(market_probs)
    mkt_cmp_clause = ""
    if mkt_triplet is not None or poisson_result.market_blended:
        pure_h, pure_d, pure_a = _pure_matrix_1x2(poisson_result.matrix)
        mh, md, ma = mkt_triplet or (
            poisson_result.home_win_prob,
            poisson_result.draw_prob,
            poisson_result.away_win_prob,
        )
        pure_fav = _favorite_label_tr(pure_h, pure_d, pure_a, home_name, away_name)
        mkt_fav = _favorite_label_tr(mh, md, ma, home_name, away_name)
        if pure_fav == mkt_fav:
            mkt_cmp_clause = (
                f"Poisson modeli (Ev %{pure_h * 100:.1f} - Dep %{pure_a * 100:.1f}) ile marjı arındırılmış "
                f"piyasa beklentisi (Ev %{mh * 100:.1f} - Dep %{ma * 100:.1f}) {pure_fav} ekseninde örtüşüyor."
            )
        else:
            mkt_cmp_clause = (
                f"Poisson modeli (Ev %{pure_h * 100:.1f} - Dep %{pure_a * 100:.1f}) {pure_fav} yönünü işaret "
                f"ederken marjı arındırılmış piyasa beklentisi (Ev %{mh * 100:.1f} - Dep %{ma * 100:.1f}) "
                f"{mkt_fav} tarafında ayrışıyor."
            )

    p2 = " ".join(
        part
        for part in (tempo_clause, injury_cmp_clause, top3_clause, ou_btts_clause, mkt_cmp_clause)
        if part
    )
    return f"{p1}\n\n{p2}"


def generate_match_analysis_texts(
    *,
    home_name: str,
    away_name: str,
    home_profile: TeamRatingProfile,
    away_profile: TeamRatingProfile,
    poisson_result: PoissonPredictionResult,
    round_number: int | None = None,
    market_probs: Mapping[str, float] | None = None,
) -> MatchAnalysisTexts:
    """Takım profilleri ve skor tahmininden doğal, 2'şer paragraflı Türkçe maç ve takım analizleri üretir."""
    overview_p1 = _build_score_justification_paragraph(
        home_name=home_name,
        away_name=away_name,
        home_profile=home_profile,
        away_profile=away_profile,
        poisson_result=poisson_result,
        round_number=round_number,
        market_probs=market_probs,
    )
    overview_p2 = _build_scenario_paragraph(
        home_name=home_name,
        away_name=away_name,
        home_profile=home_profile,
        away_profile=away_profile,
        poisson_result=poisson_result,
    )
    overview_text = f"{overview_p1}\n\n{overview_p2}"

    home_p1 = _build_team_form_paragraph(home_name, home_profile, is_home=True)
    home_p2 = _build_injury_paragraph(home_name, home_profile, is_home=True)
    home_text = f"{home_p1}\n\n{home_p2}"

    away_p1 = _build_team_form_paragraph(away_name, away_profile, is_home=False)
    away_p2 = _build_injury_paragraph(away_name, away_profile, is_home=False)
    away_text = f"{away_p1}\n\n{away_p2}"

    ht_ft_reasoning = _build_ht_ft_reasoning_text(
        home_name=home_name,
        away_name=away_name,
        home_profile=home_profile,
        away_profile=away_profile,
        poisson_result=poisson_result,
        market_probs=market_probs,
    )

    return MatchAnalysisTexts(
        match_overview_text=overview_text,
        home_analysis_text=home_text,
        away_analysis_text=away_text,
        ht_ft_reasoning_text=ht_ft_reasoning,
    )
