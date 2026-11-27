"""Transfermarkt 4 lig haftalık fikstür, maç sonuçları ve takım ayrıştırıcısı."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from bs4 import BeautifulSoup, Tag

from engine.config import LeagueId
from engine.models.schemas import Match, MatchStatus, Team
from engine.scrapers.base import (
    BaseScraper,
    ScraperParseError,
    clean_text,
    normalize_team_name,
    parse_html,
)
from engine.scrapers.injuries import TRANSFERMARKT_LEAGUES

_ROUND_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(\d{1,2})\s*\.?\s*(?:hafta|spieltag|matchday|journ[ée]e|jornada)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:hafta|spieltag|matchday|journ[ée]e|jornada)\s*(\d{1,2})",
        re.IGNORECASE,
    ),
)

_DATUM_HREF_RE = re.compile(r"/datum/(\d{4})-(\d{2})-(\d{2})")
_DOT_DATE_SEARCH_RE = re.compile(r"(\d{1,2})[./](\d{1,2})[./](\d{2,4})")
_ISO_DATE_SEARCH_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_TIME_SEARCH_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")
_SCORE_RE = re.compile(r"^(\d{1,2})\s*[:\-]\s*(\d{1,2})(?:\s|$|\()")

_POSTPONED_MARKERS: tuple[str, ...] = (
    "ert",
    "ertelen",
    "verl",
    "abg",
    "iptal",
    "postp",
    "canc",
    "susp",
)
_PREVIEW_MARKERS: tuple[str, ...] = ("ön rapor", "vorbericht", "preview")
_IGNORED_LINK_TITLES: frozenset[str] = frozenset(
    {"", "ön rapor", "maç raporu", "vorbericht", "spielbericht", "preview", "match report"}
)


@dataclass(frozen=True, slots=True)
class ScrapedTeam:
    league_id: LeagueId
    name: str
    short_name: str | None = None
    logo_url: str | None = None

    def to_team_model(self, team_id: int | None = None) -> Team:
        return Team(
            id=team_id,
            league_id=self.league_id,
            name=self.name[:150],
            short_name=self.short_name[:50] if self.short_name else None,
            logo_url=self.logo_url,
        )


@dataclass(frozen=True, slots=True)
class ScrapedMatch:
    league_id: LeagueId
    home_team_name: str
    away_team_name: str
    match_date: datetime
    round: int
    status: MatchStatus
    home_score: int | None = None
    away_score: int | None = None
    home_short_name: str | None = None
    away_short_name: str | None = None
    home_logo_url: str | None = None
    away_logo_url: str | None = None

    def to_match_model(self, home_team_id: int, away_team_id: int) -> Match:
        return Match(
            league_id=self.league_id,
            home_team_id=home_team_id,
            away_team_id=away_team_id,
            match_date=self.match_date,
            round=self.round,
            status=self.status,
            home_score=self.home_score,
            away_score=self.away_score,
        )


def select_next_round(
    finished_matches: Sequence[Any],
    scheduled_matches: Sequence[Any],
) -> int | None:
    """Ertelenmiş geçmiş hafta maçlarını atlayarak sıradaki aktif lig haftasını seçer."""
    if not scheduled_matches:
        return None

    scheduled_rounds = sorted({int(m.round) for m in scheduled_matches})
    if len(scheduled_rounds) == 1:
        return scheduled_rounds[0]

    max_finished_round = max((int(m.round) for m in finished_matches), default=0)
    finished_in_round: dict[int, int] = {}
    for m in finished_matches:
        r = int(m.round)
        finished_in_round[r] = finished_in_round.get(r, 0) + 1

    sched_in_round: dict[int, int] = {}
    earliest_sched_by_round: dict[int, datetime] = {}
    for m in scheduled_matches:
        r = int(m.round)
        sched_in_round[r] = sched_in_round.get(r, 0) + 1
        cur = earliest_sched_by_round.get(r)
        if cur is None or m.match_date < cur:
            earliest_sched_by_round[r] = m.match_date

    for idx, rnd in enumerate(scheduled_rounds):
        if rnd < max_finished_round:
            continue
        if finished_in_round.get(rnd, 0) > 0 and idx + 1 < len(scheduled_rounds):
            next_rnd = scheduled_rounds[idx + 1]
            if earliest_sched_by_round[rnd] > earliest_sched_by_round[next_rnd]:
                continue
            if (
                finished_in_round[rnd] >= 4
                and sched_in_round[rnd] <= 2
                and sched_in_round[next_rnd] > sched_in_round[rnd] * 2
            ):
                continue
        return rnd

    return scheduled_rounds[-1]


@dataclass(slots=True)
class LeagueFixturesData:
    league_id: LeagueId
    teams: list[ScrapedTeam]
    matches: list[ScrapedMatch]

    @property
    def played_matches(self) -> list[ScrapedMatch]:
        return [m for m in self.matches if m.status == MatchStatus.FINISHED]

    @property
    def scheduled_matches(self) -> list[ScrapedMatch]:
        return [m for m in self.matches if m.status == MatchStatus.SCHEDULED]

    @property
    def next_round(self) -> int | None:
        return select_next_round(self.played_matches, self.scheduled_matches)

    @property
    def next_round_matches(self) -> list[ScrapedMatch]:
        target_round = self.next_round
        if target_round is None:
            return []
        return [m for m in self.matches if m.round == target_round]


def _extract_round_number(text: str) -> int | None:
    cleaned = clean_text(text)
    for pattern in _ROUND_PATTERNS:
        match = pattern.search(cleaned)
        if match:
            round_no = int(match.group(1))
            if round_no > 0:
                return round_no
    return None


def _parse_date_cell(cell: Tag) -> date | None:
    datum_link = cell.select_one("a[href*='/datum/']")
    if datum_link is not None:
        m_href = _DATUM_HREF_RE.search(str(datum_link.get("href", "")))
        if m_href:
            try:
                return date(int(m_href.group(1)), int(m_href.group(2)), int(m_href.group(3)))
            except ValueError:
                pass

    txt = clean_text(cell)
    if not txt:
        return None

    m_iso = _ISO_DATE_SEARCH_RE.search(txt)
    if m_iso:
        try:
            return date(int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3)))
        except ValueError:
            pass

    m_dot = _DOT_DATE_SEARCH_RE.search(txt)
    if m_dot:
        day_v, month_v, year_v = int(m_dot.group(1)), int(m_dot.group(2)), int(m_dot.group(3))
        if year_v < 100:
            year_v += 2000
        try:
            return date(year_v, month_v, day_v)
        except ValueError:
            return None

    return None


def _parse_time_cell(cell: Tag) -> tuple[int, int] | None:
    txt = clean_text(cell)
    if not txt:
        return None
    m_time = _TIME_SEARCH_RE.search(txt)
    if not m_time:
        return None
    hh, mm = int(m_time.group(1)), int(m_time.group(2))
    if 0 <= hh <= 23 and 0 <= mm <= 59:
        return hh, mm
    return None


def _strip_rank_spans(cell: Tag) -> str:
    parts: list[str] = []
    for node in cell.children:
        if isinstance(node, Tag) and "tabellenplatz" in (node.get("class") or []):
            continue
        txt = clean_text(node) if isinstance(node, Tag) else str(node).strip()
        if txt:
            parts.append(txt)
    return normalize_team_name(" ".join(parts))


def _extract_team_fields(name_cell: Tag, logo_cell: Tag) -> tuple[str, str | None, str | None]:
    canonical = ""
    for cell in (name_cell, logo_cell):
        for link in cell.find_all("a", title=True):
            candidate = normalize_team_name(str(link.get("title", "")))
            if candidate.lower() not in _IGNORED_LINK_TITLES:
                canonical = candidate
                break
        if canonical:
            break

    if not canonical:
        for cell in (logo_cell, name_cell):
            img = cell.select_one("img[alt]")
            if img:
                candidate = normalize_team_name(str(img.get("alt", "")))
                if candidate:
                    canonical = candidate
                    break

    short_label = _strip_rank_spans(name_cell)
    if not canonical:
        canonical = short_label

    logo_url: str | None = None
    for cell in (logo_cell, name_cell):
        img = cell.select_one("img")
        if img is not None:
            for attr in ("data-src", "src"):
                val = str(img.get(attr, "")).strip()
                if val and not val.startswith("data:image/"):
                    logo_url = val
                    break
        if logo_url:
            break

    return canonical, (short_label or canonical or None), logo_url


def parse_score_and_status(cell: Tag) -> tuple[MatchStatus, int | None, int | None]:
    """Skor hücresinden maç durumunu (SCHEDULED/FINISHED/POSTPONED) ve golleri çıkarır."""
    link = cell.select_one("a")
    link_title = clean_text(link.get("title") if link else "").lower()
    link_href = str(link.get("href", "") if link else "").lower()

    target_node = cell.select_one("span.matchresult, a.ergebnis-link, a") or cell
    raw = clean_text(target_node)
    lowered = raw.lower()

    if any(marker in lowered for marker in _POSTPONED_MARKERS) or any(
        marker in link_title for marker in _POSTPONED_MARKERS
    ):
        return MatchStatus.POSTPONED, None, None

    if (
        not raw
        or raw in {"-:-", "- - -", "vs", "v", "-"}
        or "vorbericht" in link_href
        or any(pm in link_title for pm in _PREVIEW_MARKERS)
    ):
        return MatchStatus.SCHEDULED, None, None

    m_score = _SCORE_RE.match(raw)
    if m_score:
        g1, g2 = m_score.group(1), m_score.group(2)
        is_clock_like = (
            len(g2) == 2
            and (g2.startswith("0") or int(g1) >= 11)
            and int(g2) in {0, 15, 30, 45}
            and "spielbericht" not in link_href
        )
        if not is_clock_like:
            return MatchStatus.FINISHED, int(g1), int(g2)

    return MatchStatus.SCHEDULED, None, None


def parse_fixtures_soup(
    soup: BeautifulSoup,
    league_id: LeagueId,
    *,
    round_filter: int | None = None,
) -> LeagueFixturesData:
    """Fikstür sayfasındaki tüm hafta kutularını ayrıştırarak takım ve maç listesi üretir."""
    boxes = soup.select("div.box")
    if not boxes:
        raise ScraperParseError(f"{league_id.value} için fikstür kutuları (div.box) bulunamadı.")

    matches: list[ScrapedMatch] = []
    team_map: dict[str, ScrapedTeam] = {}

    for box in boxes:
        header = box.select_one(".content-box-headline, .table-header, h2, h3, h4")
        if header is None:
            continue
        round_no = _extract_round_number(clean_text(header))
        if round_no is None:
            continue
        if round_filter is not None and round_no != round_filter:
            continue

        table = box.find("table")
        if table is None:
            continue
        tbody = table.find("tbody") or table

        last_date: date | None = None
        last_time: tuple[int, int] = (0, 0)

        for row in tbody.find_all("tr", recursive=False):
            row_classes = row.get("class") or ()
            if "bg_blau_20" in row_classes:
                continue

            tds = row.find_all("td", recursive=False)
            if len(tds) >= 7:
                date_td, time_td = tds[0], tds[1]
                home_name_td, home_logo_td = tds[2], tds[3]
                score_td = tds[4]
                away_logo_td, away_name_td = tds[5], tds[6]
            elif len(tds) == 5:
                date_td, time_td = tds[0], tds[1]
                home_name_td = home_logo_td = tds[2]
                score_td = tds[3]
                away_name_td = away_logo_td = tds[4]
            else:
                continue

            parsed_date = _parse_date_cell(date_td)
            parsed_time = _parse_time_cell(time_td)
            if parsed_date is not None:
                if parsed_date != last_date and parsed_time is None:
                    last_time = (0, 0)
                last_date = parsed_date
            if parsed_time is not None:
                last_time = parsed_time

            if last_date is None:
                continue

            home_name, home_short, home_logo = _extract_team_fields(home_name_td, home_logo_td)
            away_name, away_short, away_logo = _extract_team_fields(away_name_td, away_logo_td)
            if not home_name or not away_name or home_name == away_name:
                continue

            status, home_score, away_score = parse_score_and_status(score_td)
            match_dt = datetime(
                last_date.year,
                last_date.month,
                last_date.day,
                last_time[0],
                last_time[1],
                tzinfo=UTC,
            )

            for t_name, t_short, t_logo in (
                (home_name, home_short, home_logo),
                (away_name, away_short, away_logo),
            ):
                existing = team_map.get(t_name)
                if existing is None or (not existing.logo_url and t_logo):
                    team_map[t_name] = ScrapedTeam(
                        league_id=league_id,
                        name=t_name,
                        short_name=t_short,
                        logo_url=t_logo or (existing.logo_url if existing else None),
                    )

            matches.append(
                ScrapedMatch(
                    league_id=league_id,
                    home_team_name=home_name,
                    away_team_name=away_name,
                    match_date=match_dt,
                    round=round_no,
                    status=status,
                    home_score=home_score,
                    away_score=away_score,
                    home_short_name=home_short,
                    away_short_name=away_short,
                    home_logo_url=home_logo,
                    away_logo_url=away_logo,
                )
            )

    return LeagueFixturesData(
        league_id=league_id,
        teams=list(team_map.values()),
        matches=matches,
    )


def parse_fixtures_html(
    html: str,
    league_id: LeagueId,
    *,
    round_filter: int | None = None,
) -> LeagueFixturesData:
    """Ham HTML metninden lig fikstür ve takım verilerini ayrıştırır."""
    return parse_fixtures_soup(parse_html(html), league_id, round_filter=round_filter)


class FixturesScraper:
    """4 ligin fikstürünü, oynanmış skorlarını ve sıradaki maçlarını çeken istemci."""

    def __init__(self, http: BaseScraper | None = None) -> None:
        self._owns_http = http is None
        self.http = http or BaseScraper()

    def close(self) -> None:
        if self._owns_http:
            self.http.close()

    def __enter__(self) -> FixturesScraper:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def fetch_league_fixtures(
        self,
        league_id: LeagueId,
        *,
        round_filter: int | None = None,
    ) -> LeagueFixturesData:
        """Ligin genel fikstürünü (veya belirtilen haftasını) tekilleştirilmiş takımlarla çeker."""
        route = TRANSFERMARKT_LEAGUES[league_id]
        soup = self.http.fetch_soup(route.full_schedule_path)
        return parse_fixtures_soup(soup, league_id, round_filter=round_filter)
