"""Transfermarkt 4 lig (TR1, GB1, ES1, FR1) sakatlık ve ceza ayrıştırıcısı."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from engine.config import LeagueId
from engine.models.schemas import ImpactLevel, Injury, PlayerPosition
from engine.scrapers.base import (
    BaseScraper,
    ScraperHTTPError,
    ScraperParseError,
    clean_text,
    normalize_team_name,
    parse_html,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TransfermarktLeagueRoute:
    league_id: LeagueId
    code: str
    slug: str

    @property
    def combined_injuries_path(self) -> str:
        """Şartnamede tanımlı birleşik sakatlık/ceza URL yolu."""
        return f"/{self.slug}/sperrenundverletzungen/wettbewerb/{self.code}"

    @property
    def injuries_only_path(self) -> str:
        """Güncel Transfermarkt müsabaka sakatlıkları URL yolu."""
        return f"/{self.slug}/verletztespieler/wettbewerb/{self.code}"

    @property
    def suspensions_only_path(self) -> str:
        """Güncel Transfermarkt müsabaka cezaları ve eksikleri URL yolu."""
        return f"/{self.slug}/sperrenausfaelle/wettbewerb/{self.code}"

    @property
    def full_schedule_path(self) -> str:
        return f"/{self.slug}/gesamtspielplan/wettbewerb/{self.code}"

    def matchday_path(self, round_number: int) -> str:
        return f"/{self.slug}/spieltag/wettbewerb/{self.code}/spieltag/{round_number}"


TRANSFERMARKT_LEAGUES: dict[LeagueId, TransfermarktLeagueRoute] = {
    LeagueId.SUPER_LIG: TransfermarktLeagueRoute(
        league_id=LeagueId.SUPER_LIG,
        code="TR1",
        slug="super-lig",
    ),
    LeagueId.PREMIER_LEAGUE: TransfermarktLeagueRoute(
        league_id=LeagueId.PREMIER_LEAGUE,
        code="GB1",
        slug="premier-league",
    ),
    LeagueId.LA_LIGA: TransfermarktLeagueRoute(
        league_id=LeagueId.LA_LIGA,
        code="ES1",
        slug="laliga",
    ),
    LeagueId.LIGUE_1: TransfermarktLeagueRoute(
        league_id=LeagueId.LIGUE_1,
        code="FR1",
        slug="ligue-1",
    ),
}

_MONTH_MAP: dict[str, int] = {
    "oca": 1,
    "ocak": 1,
    "jan": 1,
    "şub": 2,
    "sub": 2,
    "şubat": 2,
    "subat": 2,
    "feb": 2,
    "mar": 3,
    "mart": 3,
    "nis": 4,
    "nisan": 4,
    "apr": 4,
    "may": 5,
    "mayıs": 5,
    "mayis": 5,
    "haz": 6,
    "haziran": 6,
    "jun": 6,
    "tem": 7,
    "temmuz": 7,
    "jul": 7,
    "ağu": 8,
    "agu": 8,
    "ağustos": 8,
    "agustos": 8,
    "aug": 8,
    "eyl": 9,
    "eylül": 9,
    "eylul": 9,
    "sep": 9,
    "sept": 9,
    "eki": 10,
    "ekim": 10,
    "oct": 10,
    "kas": 11,
    "kasım": 11,
    "kasim": 11,
    "nov": 11,
    "ara": 12,
    "aralık": 12,
    "aralik": 12,
    "dec": 12,
}

_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_DOT_DATE_RE = re.compile(r"^(\d{1,2})[./](\d{1,2})[./](\d{4})$")
_TEXT_DATE_RE = re.compile(r"^(\d{1,2})\s+([A-Za-zÇĞİÖŞÜçğıöşü.]+)\s+(\d{4})$")

_GK_KEYWORDS: tuple[str, ...] = ("kaleci", "goalkeeper", "torwart", "gk", "tw")
_MID_FIRST_KEYWORDS: tuple[str, ...] = (
    "ön libero",
    "on libero",
    "defansif orta saha",
    "ofansif orta saha",
    "merkez orta saha",
    "orta saha",
    "on numara",
    "10 numara",
    "midfield",
    "mittelfeld",
)
_DEF_KEYWORDS: tuple[str, ...] = (
    "stoper",
    "sol bek",
    "sağ bek",
    "sag bek",
    "bek",
    "defans",
    "libero",
    "centre-back",
    "center-back",
    "left-back",
    "right-back",
    "defender",
    "verteidiger",
    "abwehr",
)
_FW_KEYWORDS: tuple[str, ...] = (
    "santrafor",
    "ikinci forvet",
    "forvet",
    "sol kanat",
    "sağ kanat",
    "sag kanat",
    "kanat",
    "hücum",
    "hucum",
    "centre-forward",
    "center-forward",
    "second striker",
    "striker",
    "forward",
    "winger",
    "stürmer",
    "linksaußen",
    "rechtsaußen",
    "angriff",
)

_HIGH_IMPACT_KEYWORDS: tuple[str, ...] = (
    "çapraz bağ",
    "capraz bag",
    "cruciate",
    "acl",
    "mcl",
    "aşil",
    "asil",
    "achilles",
    "kırık",
    "kirik",
    "kırığı",
    "kirigi",
    "fracture",
    "ameliyat",
    "cerrahi",
    "surgery",
    "operation",
    "menisküs",
    "meniskus",
    "meniscus",
    "kopma",
    "yırtık",
    "yirtik",
    "yırtığı",
    "yirtigi",
    "rupture",
    "tear",
    "kırmızı kart",
    "kirmizi kart",
    "red card",
    "doping",
    "sezon sonu",
)

_LOW_IMPACT_KEYWORDS: tuple[str, ...] = (
    "şüpheli",
    "supheli",
    "doubtful",
    "questionable",
    "hafif",
    "ufak",
    "minor",
    "knock",
    "soğuk algınlığı",
    "soguk alginligi",
    "grip",
    "nezle",
    "hastalık",
    "hastalik",
    "illness",
    "flu",
    "cold",
    "dinlendirme",
    "rest",
    "yorgunluk",
    "fatigue",
    "antrenman eksiği",
    "idman eksiği",
)

_SUSPENSION_HINTS: tuple[str, ...] = ("kart", "ceza", "sperre", "suspen", "kadro dışı")


def _fold_tr(text: str) -> str:
    return text.replace("İ", "i").replace("I", "ı").lower().casefold().replace("i̇", "i")


def map_player_position(raw_position: str) -> PlayerPosition:
    """Ham mevki metnini GK, DEF, MID veya FW enum değerine dönüştürür."""
    norm = _fold_tr(clean_text(raw_position))
    if not norm:
        return PlayerPosition.MID

    if norm in {"gk", "def", "mid", "fw"}:
        return PlayerPosition(norm.upper())

    if any(k in norm for k in _GK_KEYWORDS):
        return PlayerPosition.GK
    if any(k in norm for k in _MID_FIRST_KEYWORDS):
        return PlayerPosition.MID
    if any(k in norm for k in _DEF_KEYWORDS):
        return PlayerPosition.DEF
    if any(k in norm for k in _FW_KEYWORDS):
        return PlayerPosition.FW
    return PlayerPosition.MID


def parse_return_date(raw_value: str | None) -> date | str | None:
    """Tahmini dönüş tarihini ISO date nesnesine veya temiz metne çevirir."""
    cleaned = clean_text(raw_value)
    if not cleaned:
        return None

    folded = _fold_tr(cleaned)
    if folded in {"?", "-", "--", "bilinmiyor", "belirsiz", "unknown", "open", "n/a"}:
        return None

    m_iso = _ISO_DATE_RE.match(cleaned)
    if m_iso:
        try:
            return date(int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3)))
        except ValueError:
            return cleaned[:64]

    m_dot = _DOT_DATE_RE.match(cleaned)
    if m_dot:
        try:
            return date(int(m_dot.group(3)), int(m_dot.group(2)), int(m_dot.group(1)))
        except ValueError:
            return cleaned[:64]

    m_txt = _TEXT_DATE_RE.match(cleaned)
    if m_txt:
        month_key = _fold_tr(m_txt.group(2).rstrip("."))
        month_num = _MONTH_MAP.get(month_key)
        if month_num is not None:
            try:
                return date(int(m_txt.group(3)), month_num, int(m_txt.group(1)))
            except ValueError:
                return cleaned[:64]

    return cleaned[:64]


def calculate_impact_level(
    reason: str,
    *,
    return_date: date | str | None = None,
    reference_date: date | None = None,
    missed_matches: int | None = None,
) -> ImpactLevel:
    """Sakatlık/ceza nedeni, dönüş süresi ve kaçırılan maça göre HIGH/MEDIUM/LOW hesaplar."""
    folded_reason = _fold_tr(clean_text(reason))
    ref = reference_date or date.today()
    days_out: int | None = None
    if isinstance(return_date, date):
        days_out = (return_date - ref).days

    if days_out is not None and days_out >= 75:
        return ImpactLevel.HIGH

    if any(k in folded_reason for k in _HIGH_IMPACT_KEYWORDS):
        return ImpactLevel.HIGH

    if missed_matches is not None and missed_matches >= 4:
        return ImpactLevel.HIGH

    if any(k in folded_reason for k in _LOW_IMPACT_KEYWORDS):
        if days_out is not None and days_out >= 21:
            return ImpactLevel.MEDIUM
        return ImpactLevel.LOW

    if (
        days_out is not None
        and 0 <= days_out <= 7
        and (missed_matches is None or missed_matches <= 1)
        and not any(h in folded_reason for h in _SUSPENSION_HINTS)
    ):
        return ImpactLevel.LOW

    return ImpactLevel.MEDIUM


@dataclass(frozen=True, slots=True)
class ScrapedInjury:
    league_id: LeagueId
    team_name: str
    player_name: str
    position: PlayerPosition
    reason: str
    return_date: date | str | None
    impact_level: ImpactLevel

    def to_injury_model(self, team_id: int) -> Injury:
        return Injury(
            team_id=team_id,
            player_name=self.player_name,
            position=self.position,
            reason=self.reason,
            return_date=self.return_date,
            impact_level=self.impact_level,
        )


def _extract_player_and_position(cell: Tag) -> tuple[str, str]:
    inline_table = cell.select_one("table.inline-table")
    if inline_table is not None:
        player_link = inline_table.select_one("td.hauptlink a") or inline_table.select_one(
            "a[href*='/spieler/']"
        )
        player_name = ""
        if player_link is not None:
            player_name = clean_text(player_link.get("title") or player_link)
        if not player_name:
            img = inline_table.select_one("img[alt]")
            player_name = clean_text(img.get("alt") if img else "")

        inline_rows = inline_table.find_all("tr")
        raw_pos = ""
        if len(inline_rows) >= 2:
            pos_cells = inline_rows[-1].find_all("td")
            if pos_cells:
                raw_pos = clean_text(pos_cells[-1])
        return player_name, raw_pos

    player_link = cell.select_one("a[title]") or cell.select_one("a")
    player_name = clean_text(player_link.get("title") or player_link) if player_link else clean_text(cell)
    raw_pos = clean_text(cell.get("data-position") or "")
    return player_name, raw_pos


def _extract_club_name(cell: Tag) -> str:
    club_link = cell.select_one("a[title]")
    if club_link and clean_text(club_link.get("title")):
        return normalize_team_name(str(club_link["title"]))
    img = cell.select_one("img[alt]")
    if img and clean_text(img.get("alt")):
        return normalize_team_name(str(img["alt"]))
    return normalize_team_name(clean_text(cell))


def parse_injuries_soup(
    soup: BeautifulSoup,
    league_id: LeagueId,
    *,
    reference_date: date | None = None,
) -> list[ScrapedInjury]:
    """BeautifulSoup belgesindeki sakatlık/ceza tablosunu ScrapedInjury listesine ayrıştırır."""
    table = soup.select_one("table.items")
    if table is None:
        if soup.select_one(".empty, .box, #main, main"):
            return []
        raise ScraperParseError(f"{league_id.value} için sakatlık/ceza tablosu bulunamadı.")

    tbody = table.find("tbody")
    rows = tbody.find_all("tr", recursive=False) if tbody else table.find_all("tr", recursive=False)

    records: list[ScrapedInjury] = []
    for row in rows:
        tds = row.find_all("td", recursive=False)
        if len(tds) < 3:
            continue

        player_name, raw_pos = _extract_player_and_position(tds[0])
        if not raw_pos and len(tds) >= 6:
            raw_pos = clean_text(tds[1])
            club_td, reason_td = tds[2], tds[3]
            return_td = tds[4] if len(tds) > 4 else None
            extra_td = tds[5] if len(tds) > 5 else None
        else:
            club_td, reason_td = tds[1], tds[2]
            return_td = tds[3] if len(tds) > 3 else None
            extra_td = tds[4] if len(tds) > 4 else None

        team_name = _extract_club_name(club_td)
        if not player_name or not team_name:
            continue

        reason = clean_text(reason_td)
        if not reason:
            icon_span = reason_td.select_one("[title]")
            reason = clean_text(icon_span.get("title") if icon_span else "") or "Belirtilmemiş eksiklik"

        return_date = parse_return_date(clean_text(return_td) if return_td is not None else None)

        missed_matches: int | None = None
        if extra_td is not None:
            extra_txt = clean_text(extra_td)
            if extra_txt.isdigit():
                missed_matches = int(extra_txt)

        position = map_player_position(raw_pos)
        impact = calculate_impact_level(
            reason,
            return_date=return_date,
            reference_date=reference_date,
            missed_matches=missed_matches,
        )

        records.append(
            ScrapedInjury(
                league_id=league_id,
                team_name=team_name,
                player_name=player_name[:150],
                position=position,
                reason=reason[:255],
                return_date=return_date,
                impact_level=impact,
            )
        )

    return records


def parse_injuries_html(
    html: str,
    league_id: LeagueId,
    *,
    reference_date: date | None = None,
) -> list[ScrapedInjury]:
    """Ham HTML metninden sakatlık/ceza kayıtlarını ayrıştırır."""
    return parse_injuries_soup(parse_html(html), league_id, reference_date=reference_date)


def _find_next_page_path(soup: BeautifulSoup, current_path: str) -> str | None:
    next_link = soup.select_one(
        "li.tm-pagination__list-item--icon-next-page a.tm-pagination__link[href]"
    )
    if next_link is None:
        return None
    href = str(next_link.get("href", "")).strip()
    if not href or href == current_path:
        return None
    return urljoin(current_path, href)


class InjuriesScraper:
    """Transfermarkt üzerinden 4 ligin sakatlık ve ceza verilerini toplayan istemci."""

    def __init__(
        self,
        http: BaseScraper | None = None,
        *,
        max_pages: int = 4,
    ) -> None:
        self._owns_http = http is None
        self.http = http or BaseScraper()
        self.max_pages = max(1, max_pages)
        self._use_split_endpoints = False

    def close(self) -> None:
        if self._owns_http:
            self.http.close()

    def __enter__(self) -> InjuriesScraper:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _scrape_paginated(
        self,
        start_path: str,
        league_id: LeagueId,
        *,
        reference_date: date | None = None,
    ) -> list[ScrapedInjury]:
        collected: list[ScrapedInjury] = []
        visited: set[str] = set()
        next_path: str | None = start_path

        while next_path and next_path not in visited and len(visited) < self.max_pages:
            visited.add(next_path)
            soup = self.http.fetch_soup(next_path)
            collected.extend(parse_injuries_soup(soup, league_id, reference_date=reference_date))
            next_path = _find_next_page_path(soup, next_path)

        return collected

    def fetch_league_injuries(
        self,
        league_id: LeagueId,
        *,
        reference_date: date | None = None,
    ) -> list[ScrapedInjury]:
        """Belirtilen ligin sakatlık ve ceza kayıtlarını tekilleştirilmiş olarak döndürür."""
        route = TRANSFERMARKT_LEAGUES[league_id]
        raw_items: list[ScrapedInjury] = []

        if not self._use_split_endpoints:
            try:
                raw_items.extend(
                    self._scrape_paginated(
                        route.combined_injuries_path,
                        league_id,
                        reference_date=reference_date,
                    )
                )
            except ScraperHTTPError as exc:
                if exc.status_code != 404:
                    raise
                # shortcut: Transfermarkt müsabaka düzeyinde sperrenundverletzungen yerine
                # verletztespieler + sperrenausfaelle uç noktalarını sunar; ilk 404 sonrası önbelleğe alınır.
                logger.info(
                    "%s birleşik uç nokta 404 döndü; ayrık sakatlık/ceza uç noktalarına geçiliyor.",
                    route.combined_injuries_path,
                )
                self._use_split_endpoints = True

        if self._use_split_endpoints:
            for split_path in (route.injuries_only_path, route.suspensions_only_path):
                raw_items.extend(
                    self._scrape_paginated(
                        split_path,
                        league_id,
                        reference_date=reference_date,
                    )
                )

        deduped: list[ScrapedInjury] = []
        seen_keys: set[tuple[str, str, str]] = set()
        for item in raw_items:
            key = (_fold_tr(item.team_name), _fold_tr(item.player_name), _fold_tr(item.reason))
            if key not in seen_keys:
                seen_keys.add(key)
                deduped.append(item)
        return deduped
