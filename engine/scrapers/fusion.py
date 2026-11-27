"""5 kaynaklı veri füzyonu, takım takma ad çözümleyicisi (TeamAliasResolver) ve çapraz sakatlık doğrulaması."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from typing import Any

from engine.models.schemas import Injury, Match, MatchStatus, Team
from engine.scrapers.base import normalize_team_name
from engine.scrapers.sources.api_football import ApiFootballLeagueData
from engine.scrapers.sources.espn import ESPNLeagueData
from engine.scrapers.sources.football_data import FootballDataLeagueData
from engine.scrapers.sources.secondary_check import SecondaryCheckData, SecondaryInjuryRecord
from engine.scrapers.sources.the_odds_api import TheOddsLeagueData
from engine.scrapers.sources.understat import UnderstatLeagueData, derive_xg_from_shots

_CHAR_TRANSLATION = str.maketrans(
    {
        "ç": "c",
        "Ç": "c",
        "ğ": "g",
        "Ğ": "g",
        "ı": "i",
        "İ": "i",
        "I": "i",
        "ö": "o",
        "Ö": "o",
        "ş": "s",
        "Ş": "s",
        "ü": "u",
        "Ü": "u",
        "ß": "ss",
        "æ": "ae",
        "Æ": "ae",
        "œ": "oe",
        "Œ": "oe",
        "ø": "o",
        "Ø": "o",
        "ł": "l",
        "Ł": "l",
        "đ": "d",
        "Đ": "d",
        "ă": "a",
        "Ă": "a",
        "ș": "s",
        "Ș": "s",
        "ț": "t",
        "Ț": "t",
    }
)

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")

# Yalnızca şehir/kulüp kimliğini bozmayan jenerik önek, sonek ve kuruluş yılları
_STRIP_TOKENS: frozenset[str] = frozenset(
    {
        "fc",
        "sk",
        "cf",
        "sc",
        "ac",
        "afc",
        "as",
        "rc",
        "rcd",
        "ud",
        "cd",
        "fk",
        "jk",
        "ssc",
        "ogc",
        "osc",
        "aj",
        "sco",
        "ca",
        "sd",
        "ad",
        "hsc",
        "kulubu",
        "club",
        "de",
        "du",
        "foot",
        "football",
        "futbol",
        "sportif",
        "balompie",
        "1899",
        "1901",
        "1903",
        "1905",
        "1907",
        "1910",
        "1919",
        "1922",
        "1923",
        "1928",
        "1946",
        "1967",
        "29",
    }
)

# Sponsor / kısa ad / farklı kaynak yazımları -> kanonik kulüp anahtarı
_ALIAS_GROUPS: dict[str, tuple[str, ...]] = {
    # Süper Lig
    "galatasaray": ("galatasaray", "galatasaray sk", "galatasaray as", "gala"),
    "fenerbahce": ("fenerbahce", "fenerbahce sk", "fener"),
    "besiktas": ("besiktas", "besiktas jk"),
    "trabzonspor": ("trabzonspor", "trabzon"),
    "basaksehir": (
        "basaksehir",
        "istanbul basaksehir",
        "rams basaksehir",
        "medipol basaksehir",
        "basaksehir fk",
        "buyuksehir bld",
    ),
    "kasimpasa": ("kasimpasa", "kasimpasa sk"),
    "rizespor": ("rizespor", "caykur rizespor", "c rizespor"),
    "goztepe": ("goztepe", "goztepe sk"),
    "eyupspor": ("eyupspor", "ikas eyupspor", "eyup"),
    "samsunspor": ("samsunspor", "reeder samsunspor", "yilport samsunspor", "samsun"),
    "alanyaspor": ("alanyaspor", "corendon alanyaspor", "aytemiz alanyaspor", "alanya"),
    "antalyaspor": ("antalyaspor", "onvo antalyaspor", "bitexen antalyaspor", "antalya"),
    "konyaspor": ("konyaspor", "tumosan konyaspor", "arabam com konyaspor", "ittifak holding konyaspor", "konya"),
    "kayserispor": ("kayserispor", "bellona kayserispor", "mondihome kayserispor", "yukatel kayserispor", "kayseri"),
    "gaziantep": ("gaziantep", "gaziantep fk", "gazisehir gaziantep"),
    "hatayspor": ("hatayspor", "atakas hatayspor", "hatay"),
    "adana demirspor": ("adana demirspor", "demirspor", "ads"),
    "bodrum": ("bodrum", "bodrum fk", "bodrumspor", "sipay bodrum", "sipay bodrum fk"),
    "sivasspor": ("sivasspor", "net global sivasspor", "ems yapi sivasspor", "demir grup sivasspor", "sivas"),
    "karagumruk": ("karagumruk", "fatih karagumruk", "vavacars fatih karagumruk"),
    "kocaelispor": ("kocaelispor", "kocaeli"),
    "genclerbirligi": ("genclerbirligi", "genclerbirligi sk"),
    "corum": ("corum", "corum fk", "ahlatci corum", "ahlatci corum fk"),
    "erzurumspor": (
        "erzurumspor",
        "erzurumspor fk",
        "erzurum bb",
        "bb erzurumspor",
        "buyuksehir belediye erzurumspor",
    ),
    "ankaragucu": ("ankaragucu", "mke ankaragucu"),
    "amedspor": ("amed", "amed sk", "amedspor", "amed sportif", "amed sportif faaliyetler"),
    "pendikspor": ("pendikspor", "pendik"),
    "eyupspor_alt": ("ikas eyup",),
    # Premier League
    "manchester city": ("man city", "manchester city", "mancity"),
    "manchester united": ("man united", "man utd", "manchester utd", "manchester united"),
    "wolverhampton": ("wolves", "wolverhampton", "wolverhampton wanderers"),
    "nottingham forest": ("nottm forest", "nott m forest", "nottingham forest", "nottingham", "nfo"),
    "tottenham": ("spurs", "tottenham", "tottenham hotspur"),
    "newcastle": ("newcastle", "newcastle united", "newcastle utd"),
    "west ham": ("west ham", "west ham united", "west ham utd", "westham"),
    "brighton": ("brighton", "brighton and hove albion", "brighton hove albion"),
    "bournemouth": ("bournemouth", "afc bournemouth"),
    "leicester": ("leicester", "leicester city"),
    "ipswich": ("ipswich", "ipswich town"),
    "leeds": ("leeds", "leeds united", "leeds utd"),
    "sheffield united": ("sheffield utd", "sheffield united"),
    "luton": ("luton", "luton town"),
    "aston villa": ("aston villa", "villa"),
    "crystal palace": ("crystal palace", "palace"),
    "sunderland": ("sunderland", "sunderland afc"),
    "burnley": ("burnley", "burnley fc"),
    # La Liga
    "atletico madrid": (
        "atletico",
        "atletico madrid",
        "atletico de madrid",
        "ath madrid",
        "club atletico de madrid",
    ),
    "athletic bilbao": (
        "athletic",
        "athletic club",
        "athletic bilbao",
        "ath bilbao",
        "athletic club bilbao",
    ),
    "celta vigo": ("celta", "celta vigo", "rc celta", "celta de vigo", "rc celta de vigo"),
    "real betis": ("betis", "real betis", "real betis balompie"),
    "real sociedad": ("sociedad", "real sociedad", "real sociedad de futbol"),
    "alaves": ("alaves", "deportivo alaves"),
    "espanyol": ("espanyol", "rcd espanyol", "rcd espanyol de barcelona", "espanyol barcelona"),
    "rayo vallecano": ("rayo", "rayo vallecano", "vallecano"),
    "mallorca": ("mallorca", "rcd mallorca"),
    "valladolid": ("valladolid", "real valladolid", "real valladolid cf"),
    "las palmas": ("las palmas", "ud las palmas"),
    "leganes": ("leganes", "cd leganes"),
    "osasuna": ("osasuna", "ca osasuna"),
    "real madrid": ("real madrid", "real madrid cf"),
    "barcelona": ("barcelona", "fc barcelona", "barca"),
    "real oviedo": ("oviedo", "real oviedo"),
    # Ligue 1 & Avrupa referansları
    "paris fc": ("paris fc",),
    "paris saint germain": (
        "psg",
        "paris sg",
        "paris saint germain",
        "paris st germain",
        "paris saint germain fc",
    ),
    "saint etienne": ("st etienne", "saint etienne", "as saint etienne"),
    "marseille": (
        "marseille",
        "marsilya",
        "olympique marsilya",
        "olympique marseille",
        "olympique de marseille",
        "om",
    ),
    "lyon": ("lyon", "olympique lyon", "olympique lyonnais", "ol"),
    "monaco": ("monaco", "as monaco", "as monaco fc"),
    "lille": ("lille", "losc", "losc lille"),
    "rennes": ("rennes", "stade rennais", "stade rennais fc", "stade rennais fc 1901"),
    "reims": ("reims", "stade de reims", "stade reims"),
    "brest": ("brest", "stade brestois", "stade brestois 29"),
    "strasbourg": ("strasbourg", "rc strasbourg", "rc strasbourg alsace", "strasbourg alsace"),
    "lens": ("lens", "rc lens", "racing club de lens"),
    "nice": ("nice", "ogc nice"),
    "nantes": ("nantes", "fc nantes"),
    "montpellier": ("montpellier", "montpellier hsc"),
    "toulouse": ("toulouse", "toulouse fc"),
    "auxerre": ("auxerre", "aj auxerre"),
    "angers": ("angers", "angers sco"),
    "le havre": ("le havre", "le havre ac", "havre", "hac"),
    "lorient": ("lorient", "fc lorient"),
    "metz": ("metz", "fc metz"),
    "borussia monchengladbach": (
        "gladbach",
        "m gladbach",
        "monchengladbach",
        "borussia m gladbach",
        "borussia monchengladbach",
    ),
}


def fold_ascii(text: str) -> str:
    """Türkçe ve Avrupa aksanlı karakterleri ASCII küçük harfe indirger."""
    translated = normalize_team_name(text).translate(_CHAR_TRANSLATION)
    decomposed = unicodedata.normalize("NFKD", translated)
    no_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    cleaned = _NON_ALNUM_RE.sub(" ", no_marks.lower()).strip()
    return " ".join(cleaned.split())


def _build_explicit_alias_lookup() -> dict[str, str]:
    lookup: dict[str, str] = {}
    for canonical, variants in _ALIAS_GROUPS.items():
        canon_fold = fold_ascii(canonical)
        lookup[canon_fold] = canon_fold
        for v in variants:
            vf = fold_ascii(v)
            if vf:
                lookup[vf] = canon_fold
    return lookup


EXPLICIT_TEAM_ALIASES: dict[str, str] = _build_explicit_alias_lookup()


def _strip_club_affixes(folded: str) -> str:
    if not folded:
        return ""
    if folded in EXPLICIT_TEAM_ALIASES:
        return EXPLICIT_TEAM_ALIASES[folded]
    tokens = [t for t in folded.split() if t not in _STRIP_TOKENS]
    stripped = " ".join(tokens) if tokens else folded
    return EXPLICIT_TEAM_ALIASES.get(stripped, stripped)


class TeamAliasResolver:
    """5 kaynaktaki farklı kulüp yazımlarını kanonik anahtar ve lig takım kimliğine eşler."""

    def __init__(self, canonical_teams: Iterable[Team | str] | None = None) -> None:
        self._key_to_team_id: dict[str, int] = {}
        self._key_to_display: dict[str, str] = {}
        self._tokens_by_key: dict[str, set[str]] = {}
        if canonical_teams is not None:
            self.register_teams(canonical_teams)

    def canonical_key(self, raw_name: str) -> str:
        folded = fold_ascii(raw_name)
        if not folded:
            return ""
        if folded in EXPLICIT_TEAM_ALIASES:
            return EXPLICIT_TEAM_ALIASES[folded]
        base = _strip_club_affixes(folded)
        if base in EXPLICIT_TEAM_ALIASES:
            return EXPLICIT_TEAM_ALIASES[base]
        return base

    def register_teams(self, teams: Iterable[Team | str]) -> None:
        for item in teams:
            if isinstance(item, Team):
                tname = item.name
                tid = item.id
                short = item.short_name
            else:
                tname = str(item)
                tid = None
                short = None
            ck = self.canonical_key(tname)
            if not ck:
                continue
            self._key_to_display.setdefault(ck, tname)
            self._tokens_by_key[ck] = set(ck.split())
            if tid is not None:
                self._key_to_team_id[ck] = tid
            if short:
                sk = self.canonical_key(short)
                if sk and sk != ck:
                    self._key_to_display.setdefault(sk, tname)
                    if tid is not None:
                        self._key_to_team_id.setdefault(sk, tid)

    def resolve_key(self, raw_name: str) -> str:
        ck = self.canonical_key(raw_name)
        if not ck or not self._key_to_display:
            return ck
        if ck in self._key_to_display:
            return ck

        cand_tokens = set(ck.split())
        best_key = ck
        best_score = 0.0

        for known_key, known_tokens in self._tokens_by_key.items():
            # Tek kelimeli sponsorlu veya "spor" ekli Türkçe kulüp eşleşmesi (örn. alanya <-> alanyaspor)
            if cand_tokens and known_tokens:
                overlap = len(cand_tokens & known_tokens)
                if overlap > 0:
                    # "manchester" veya "madrid" gibi tek başına belirsiz şehir adlarını koru
                    ambiguous = {"manchester", "madrid", "paris", "london", "seville", "istanbul"}
                    non_ambig_overlap = (cand_tokens & known_tokens) - ambiguous
                    if non_ambig_overlap:
                        token_score = 0.88 + 0.12 * (overlap / max(len(cand_tokens), len(known_tokens)))
                        if token_score > best_score:
                            best_score = token_score
                            best_key = known_key
                for ct in cand_tokens:
                    for kt in known_tokens:
                        if len(ct) >= 5 and len(kt) >= 5 and (f"{ct}spor" == kt or f"{kt}spor" == ct):
                            return known_key

            seq_ratio = SequenceMatcher(None, ck, known_key).ratio()
            if seq_ratio > best_score:
                best_score = seq_ratio
                best_key = known_key

        return best_key if best_score >= 0.80 else ck

    def resolve_team_id(self, raw_name: str) -> int | None:
        rk = self.resolve_key(raw_name)
        return self._key_to_team_id.get(rk)

    def same_team(self, name_a: str, name_b: str) -> bool:
        ka = self.resolve_key(name_a)
        kb = self.resolve_key(name_b)
        return bool(ka and kb and ka == kb)


@dataclass(slots=True)
class TeamMultiSourceMetrics:
    team_name: str
    canonical_key: str
    matches_sampled: int = 0
    xg_for_per_match: float | None = None
    xg_against_per_match: float | None = None
    xg_is_derived: bool = False
    shots_for_per_match: float | None = None
    shots_against_per_match: float | None = None
    sot_for_per_match: float | None = None
    sot_against_per_match: float | None = None
    corners_for_per_match: float | None = None
    corners_against_per_match: float | None = None
    cards_per_match: float | None = None
    ht_goals_for: int = 0
    ht_goals_against: int = 0
    ft_goals_for_fd: int = 0
    ft_goals_against_fd: int = 0
    first_half_attack_share: float | None = None
    first_half_concede_share: float | None = None
    espn_rank: int | None = None
    espn_points: int | None = None
    espn_goal_diff: int | None = None
    market_win_prob_avg: float | None = None
    sources_matched: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_damped_first_half_share(ht_goals: int, ft_goals: int) -> float | None:
    """Küçük örneklemlerde aşırı uçları önleyen (0.43 * 4 gol önsel ağırlıklı) ilk yarı gol payı."""
    if ft_goals <= 0:
        return None
    safe_ht = max(0, min(ht_goals, ft_goals))
    damped = (safe_ht + 0.43 * 4.0) / (ft_goals + 4.0)
    return round(min(0.65, max(0.25, damped)), 4)


def _add_source(metrics: TeamMultiSourceMetrics, source_name: str) -> None:
    if source_name and source_name not in metrics.sources_matched:
        metrics.sources_matched.append(source_name)


def fuse_team_metrics(
    teams: list[Team],
    *,
    resolver: TeamAliasResolver | None = None,
    espn_data: ESPNLeagueData | None = None,
    football_data: FootballDataLeagueData | None = None,
    understat_data: UnderstatLeagueData | None = None,
    secondary_data: SecondaryCheckData | None = None,
    api_football_data: ApiFootballLeagueData | None = None,
    odds_data: TheOddsLeagueData | None = None,
    primary_source_name: str = "Transfermarkt",
) -> dict[int, TeamMultiSourceMetrics]:
    """Çoklu kaynaktan gelen takım metriklerini kanonik takım kimlikleri altında birleştirir."""
    alias = resolver or TeamAliasResolver(teams)
    alias.register_teams(teams)

    by_id: dict[int, TeamMultiSourceMetrics] = {}
    id_by_key: dict[str, int] = {}

    for tm in teams:
        if tm.id is None:
            continue
        ck = alias.resolve_key(tm.name)
        initial_sources = [primary_source_name] if primary_source_name else []
        m = TeamMultiSourceMetrics(
            team_name=tm.name,
            canonical_key=ck,
            sources_matched=initial_sources,
        )
        by_id[tm.id] = m
        if ck:
            id_by_key[ck] = tm.id

    def _lookup_metric(raw_name: str) -> TeamMultiSourceMetrics | None:
        tid = alias.resolve_team_id(raw_name)
        if tid is None:
            tid = id_by_key.get(alias.resolve_key(raw_name))
        return by_id.get(tid) if tid is not None else None

    # 1. ESPN puan durumu + maç oranları / canlı istatistik yedeği
    if espn_data is not None:
        for row in espn_data.standings:
            tm_metric = _lookup_metric(row.team_name)
            if tm_metric is None:
                continue
            tm_metric.espn_rank = row.rank
            tm_metric.espn_points = row.points
            tm_metric.espn_goal_diff = row.point_differential
            if row.games_played > tm_metric.matches_sampled:
                tm_metric.matches_sampled = row.games_played
            _add_source(tm_metric, "ESPN")

        prob_acc: dict[str, list[float]] = {}
        for fx in espn_data.fixtures:
            hm = _lookup_metric(fx.home_team)
            am = _lookup_metric(fx.away_team)
            if hm is not None:
                _add_source(hm, "ESPN")
                if fx.home_win_prob is not None:
                    prob_acc.setdefault(hm.canonical_key, []).append(fx.home_win_prob)
            if am is not None:
                _add_source(am, "ESPN")
                if fx.away_win_prob is not None:
                    prob_acc.setdefault(am.canonical_key, []).append(fx.away_win_prob)

        for ck, probs in prob_acc.items():
            tid = id_by_key.get(ck)
            if tid is not None and probs and by_id[tid].market_win_prob_avg is None:
                by_id[tid].market_win_prob_avg = round(sum(probs) / len(probs), 4)

    # 2. Football-Data maç başı İY/MS, şut, isabetli şut, korner, kart ve oranlar
    if football_data is not None:
        for raw_tname, fd_stat in football_data.team_stats.items():
            tm_metric = _lookup_metric(raw_tname)
            if tm_metric is None:
                continue
            if fd_stat.matches_played > tm_metric.matches_sampled:
                tm_metric.matches_sampled = fd_stat.matches_played
            tm_metric.ht_goals_for = fd_stat.ht_goals_for
            tm_metric.ht_goals_against = fd_stat.ht_goals_against
            tm_metric.ft_goals_for_fd = fd_stat.ft_goals_for
            tm_metric.ft_goals_against_fd = fd_stat.ft_goals_against
            if fd_stat.ht_matches > 0:
                tm_metric.first_half_attack_share = compute_damped_first_half_share(
                    fd_stat.ht_goals_for, fd_stat.ft_goals_for
                )
                tm_metric.first_half_concede_share = compute_damped_first_half_share(
                    fd_stat.ht_goals_against, fd_stat.ft_goals_against
                )
            if fd_stat.shots_for_per_match is not None:
                tm_metric.shots_for_per_match = fd_stat.shots_for_per_match
            if fd_stat.shots_against_per_match is not None:
                tm_metric.shots_against_per_match = fd_stat.shots_against_per_match
            if fd_stat.sot_for_per_match is not None:
                tm_metric.sot_for_per_match = fd_stat.sot_for_per_match
            if fd_stat.sot_against_per_match is not None:
                tm_metric.sot_against_per_match = fd_stat.sot_against_per_match
            if fd_stat.corners_for_per_match is not None:
                tm_metric.corners_for_per_match = fd_stat.corners_for_per_match
            if fd_stat.corners_against_per_match is not None:
                tm_metric.corners_against_per_match = fd_stat.corners_against_per_match
            if fd_stat.cards_per_match is not None:
                tm_metric.cards_per_match = fd_stat.cards_per_match
            if fd_stat.market_win_prob_avg is not None:
                tm_metric.market_win_prob_avg = fd_stat.market_win_prob_avg
            _add_source(tm_metric, "Football-Data")

    # 3. Understat gerçek xG / xGA ve eksik takımlar için şut tabanlı xG vekili
    if understat_data is not None:
        for raw_tname, ug in understat_data.teams.items():
            tm_metric = _lookup_metric(raw_tname)
            if tm_metric is None:
                continue
            tm_metric.xg_for_per_match = ug.xg_for_per_match
            tm_metric.xg_against_per_match = ug.xg_against_per_match
            tm_metric.xg_is_derived = ug.xg_is_derived
            if ug.matches_played > tm_metric.matches_sampled:
                tm_metric.matches_sampled = ug.matches_played
            _add_source(tm_metric, "Understat")

    for tm_metric in by_id.values():
        if tm_metric.xg_for_per_match is None or tm_metric.xg_against_per_match is None:
            xg_f, xg_a = derive_xg_from_shots(
                shots_for_per_match=tm_metric.shots_for_per_match,
                sot_for_per_match=tm_metric.sot_for_per_match,
                shots_against_per_match=tm_metric.shots_against_per_match,
                sot_against_per_match=tm_metric.sot_against_per_match,
            )
            if tm_metric.xg_for_per_match is None and xg_f is not None:
                tm_metric.xg_for_per_match = xg_f
                tm_metric.xg_is_derived = True
            if tm_metric.xg_against_per_match is None and xg_a is not None:
                tm_metric.xg_against_per_match = xg_a
                tm_metric.xg_is_derived = True

    # 4. İkincil çapraz doğrulama kaynağı (SportsGambler / TheSportsDB)
    if secondary_data is not None:
        sec_label = secondary_data.active_source_name or "TheSportsDB"
        for st_row in secondary_data.standings:
            tm_metric = _lookup_metric(st_row.team_name)
            if tm_metric is not None:
                if tm_metric.espn_rank is None:
                    tm_metric.espn_rank = st_row.rank
                if tm_metric.espn_points is None:
                    tm_metric.espn_points = st_row.points
                _add_source(tm_metric, sec_label)
        for inj_row in secondary_data.injuries:
            tm_metric = _lookup_metric(inj_row.team_name)
            if tm_metric is not None:
                _add_source(tm_metric, inj_row.source_name or sec_label)

    # 5. API-Football resmi fikstür / İY-MS yedek payları ve sakatlık eşleşmeleri
    if api_football_data is not None:
        ht_acc: dict[int, list[int]] = {}
        for sm in api_football_data.matches:
            hm = _lookup_metric(sm.home_team_name)
            am = _lookup_metric(sm.away_team_name)
            if hm is not None:
                _add_source(hm, "API-Football")
            if am is not None:
                _add_source(am, "API-Football")
            if sm.status == MatchStatus.FINISHED and sm.home_score is not None and sm.away_score is not None:
                ht_pair = api_football_data.ht_scores.get((sm.home_team_name, sm.away_team_name))
                if ht_pair is not None:
                    hid = alias.resolve_team_id(sm.home_team_name)
                    aid = alias.resolve_team_id(sm.away_team_name)
                    if hid is not None:
                        acc_h = ht_acc.setdefault(hid, [0, 0, 0, 0])
                        acc_h[0] += ht_pair[0]
                        acc_h[1] += ht_pair[1]
                        acc_h[2] += sm.home_score
                        acc_h[3] += sm.away_score
                    if aid is not None:
                        acc_a = ht_acc.setdefault(aid, [0, 0, 0, 0])
                        acc_a[0] += ht_pair[1]
                        acc_a[1] += ht_pair[0]
                        acc_a[2] += sm.away_score
                        acc_a[3] += sm.home_score

        for tid, totals in ht_acc.items():
            tm_metric = by_id.get(tid)
            if tm_metric is not None and tm_metric.first_half_attack_share is None:
                tm_metric.ht_goals_for = totals[0]
                tm_metric.ht_goals_against = totals[1]
                tm_metric.ft_goals_for_fd = totals[2]
                tm_metric.ft_goals_against_fd = totals[3]
                tm_metric.first_half_attack_share = compute_damped_first_half_share(totals[0], totals[2])
                tm_metric.first_half_concede_share = compute_damped_first_half_share(totals[1], totals[3])

        for af_inj in api_football_data.injuries:
            tm_metric = _lookup_metric(af_inj.team_name)
            if tm_metric is not None:
                _add_source(tm_metric, "API-Football")

    # 6. The Odds API konsensüs piyasa olasılıkları
    if odds_data is not None:
        odds_acc: dict[int, list[float]] = {}
        for om in odds_data.matches:
            hid = alias.resolve_team_id(om.home_team)
            aid = alias.resolve_team_id(om.away_team)
            if hid is not None and hid in by_id:
                _add_source(by_id[hid], "TheOddsAPI")
                odds_acc.setdefault(hid, []).append(om.p_home)
            if aid is not None and aid in by_id:
                _add_source(by_id[aid], "TheOddsAPI")
                odds_acc.setdefault(aid, []).append(om.p_away)
        for tid, probs in odds_acc.items():
            if probs:
                by_id[tid].market_win_prob_avg = round(sum(probs) / len(probs), 4)

    return by_id


def build_market_odds_map(
    teams: list[Team],
    *,
    resolver: TeamAliasResolver | None = None,
    odds_data: TheOddsLeagueData | None = None,
    football_data: FootballDataLeagueData | None = None,
) -> dict[tuple[int, int], dict[str, float]]:
    """(home_team_id, away_team_id) anahtarlı marjsız piyasa olasılık haritası üretir."""
    alias = resolver or TeamAliasResolver(teams)
    alias.register_teams(teams)
    market_map: dict[tuple[int, int], dict[str, float]] = {}

    if football_data is not None:
        for fm in football_data.matches:
            if fm.home_win_prob is None or fm.away_win_prob is None:
                continue
            hid = alias.resolve_team_id(fm.home_team)
            aid = alias.resolve_team_id(fm.away_team)
            if hid is None or aid is None or hid == aid:
                continue
            p_h = round(float(fm.home_win_prob), 6)
            p_a = round(float(fm.away_win_prob), 6)
            p_d = round(max(0.0, 1.0 - p_h - p_a), 6)
            market_map[(hid, aid)] = {
                "p_home": p_h,
                "p_draw": p_d,
                "p_away": p_a,
                "bookmakers_count": 1.0,
            }

    if odds_data is not None:
        for om in odds_data.matches:
            hid = alias.resolve_team_id(om.home_team)
            aid = alias.resolve_team_id(om.away_team)
            if hid is None or aid is None or hid == aid:
                continue
            entry: dict[str, float] = {
                "p_home": om.p_home,
                "p_draw": om.p_draw,
                "p_away": om.p_away,
                "bookmakers_count": float(om.bookmakers_count),
            }
            if om.p_over25 is not None and om.p_under25 is not None:
                entry["p_over25"] = om.p_over25
                entry["p_under25"] = om.p_under25
            if om.overround_1x2 is not None:
                entry["overround_1x2"] = om.overround_1x2
            market_map[(hid, aid)] = entry

    return market_map


def _normalize_player_name(name: str) -> str:
    return fold_ascii(name)


def _players_match(name_a: str, name_b: str) -> bool:
    fa = _normalize_player_name(name_a)
    fb = _normalize_player_name(name_b)
    if not fa or not fb:
        return False
    if fa == fb:
        return True
    if SequenceMatcher(None, fa, fb).ratio() >= 0.82:
        return True

    toks_a = fa.split()
    toks_b = fb.split()
    set_a = set(toks_a)
    set_b = set(toks_b)
    # Tek kelimeli lakap veya İspanyol/Portekiz çift soyad (örn. "Bukayo Saka" <-> "Saka", "Martin Zubimendi Ibanez" <-> "Martin Zubimendi")
    if len(toks_a) == 1 and len(toks_a[0]) >= 4 and toks_a[0] in set_b:
        return True
    if len(toks_b) == 1 and len(toks_b[0]) >= 4 and toks_b[0] in set_a:
        return True
    if len(set_a) >= 2 and set_a.issubset(set_b):
        return True
    if len(set_b) >= 2 and set_b.issubset(set_a):
        return True

    last_a, last_b = toks_a[-1], toks_b[-1]
    if len(last_a) >= 4 and last_a == last_b:
        if toks_a[0][0] == toks_b[0][0]:
            return True
    return False


def cross_validate_injuries(
    primary_injuries: list[Injury],
    teams: list[Team],
    secondary_injuries: list[SecondaryInjuryRecord],
    *,
    resolver: TeamAliasResolver | None = None,
    primary_source_name: str = "Transfermarkt",
) -> tuple[list[Injury], int]:
    """Birincil sakatlıkları ikincil kaynak sakatlık listesiyle çapraz doğrular."""
    if not primary_injuries or not secondary_injuries:
        return primary_injuries, 0

    alias = resolver or TeamAliasResolver(teams)
    alias.register_teams(teams)
    team_key_by_id: dict[int, str] = {
        tm.id: alias.resolve_key(tm.name) for tm in teams if tm.id is not None
    }

    sec_by_team: dict[str, list[SecondaryInjuryRecord]] = {}
    for sec in secondary_injuries:
        tk = alias.resolve_key(sec.team_name)
        if tk:
            sec_by_team.setdefault(tk, []).append(sec)

    supports_verification_fields = "verified_by_multiple_sources" in Injury.model_fields
    updated_list: list[Injury] = []
    verified_count = 0

    for inj in primary_injuries:
        tk = team_key_by_id.get(inj.team_id, "")
        candidates = sec_by_team.get(tk, [])
        matched_sources: list[str] = [primary_source_name] if primary_source_name else []
        for cand in candidates:
            if _players_match(inj.player_name, cand.player_name):
                sec_src = cand.source_name or "SportsGambler"
                if sec_src not in matched_sources:
                    matched_sources.append(sec_src)

        if len(matched_sources) > 1:
            verified_count += 1
            if supports_verification_fields:
                updated_list.append(
                    inj.model_copy(
                        update={
                            "verified_by_multiple_sources": True,
                            "sources": matched_sources,
                        }
                    )
                )
            else:
                updated_list.append(inj)
        else:
            updated_list.append(inj)

    return updated_list, verified_count


def cross_validate_match_scores(
    matches: list[Match],
    teams: list[Team],
    *,
    espn_data: ESPNLeagueData | None = None,
    football_data: FootballDataLeagueData | None = None,
    resolver: TeamAliasResolver | None = None,
) -> tuple[list[Match], int]:
    """Tamamlanmış maç skorlarını ESPN/Football-Data ile doğrular ve eksik bitmiş skorları tamamlar."""
    if not matches:
        return matches, 0

    alias = resolver or TeamAliasResolver(teams)
    alias.register_teams(teams)
    key_by_id = {tm.id: alias.resolve_key(tm.name) for tm in teams if tm.id is not None}

    finished_lookup: dict[tuple[str, str], tuple[int, int]] = {}
    if football_data is not None:
        for fm in football_data.matches:
            hk = alias.resolve_key(fm.home_team)
            ak = alias.resolve_key(fm.away_team)
            if hk and ak:
                finished_lookup[(hk, ak)] = (fm.fthg, fm.ftag)
    if espn_data is not None:
        for ef in espn_data.fixtures:
            if ef.status == "FINISHED" and ef.home_score is not None and ef.away_score is not None:
                hk = alias.resolve_key(ef.home_team)
                ak = alias.resolve_key(ef.away_team)
                if hk and ak:
                    finished_lookup[(hk, ak)] = (ef.home_score, ef.away_score)

    if not finished_lookup:
        return matches, 0

    confirmed = 0
    out: list[Match] = []
    for m in matches:
        pair = (key_by_id.get(m.home_team_id, ""), key_by_id.get(m.away_team_id, ""))
        ext_score = finished_lookup.get(pair)
        if ext_score is not None:
            if m.status == MatchStatus.FINISHED and (m.home_score, m.away_score) == ext_score:
                confirmed += 1
                out.append(m)
            elif m.status == MatchStatus.SCHEDULED and m.home_score is None:
                confirmed += 1
                out.append(
                    m.model_copy(
                        update={
                            "status": MatchStatus.FINISHED,
                            "home_score": ext_score[0],
                            "away_score": ext_score[1],
                        }
                    )
                )
            else:
                out.append(m)
        else:
            out.append(m)
    return out, confirmed
