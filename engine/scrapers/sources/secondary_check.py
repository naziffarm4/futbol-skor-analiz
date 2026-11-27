"""Kaynak 5 — Bağımsız 2. sakatlık/ceza ve puan durumu çapraz doğrulama adaptörü."""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

import httpx

from engine.config import LeagueId, get_current_season
from engine.scrapers.base import build_browser_headers, clean_text, parse_html
from engine.scrapers.sources import make_source_diagnostic

logger = logging.getLogger(__name__)

SPORTSGAMBLER_SLUGS: dict[LeagueId, str] = {
    LeagueId.SUPER_LIG: "turkey-super-lig",
    LeagueId.PREMIER_LEAGUE: "england-premier-league",
    LeagueId.LA_LIGA: "spain-la-liga",
    LeagueId.LIGUE_1: "france-ligue-1",
}

THESPORTSDB_LEAGUE_IDS: dict[LeagueId, str] = {
    LeagueId.SUPER_LIG: "4339",
    LeagueId.PREMIER_LEAGUE: "4328",
    LeagueId.LA_LIGA: "4335",
    LeagueId.LIGUE_1: "4334",
}

FOTMOB_OVERVIEW_ROUTES: dict[LeagueId, tuple[int, str]] = {
    LeagueId.SUPER_LIG: (71, "super-lig"),
    LeagueId.PREMIER_LEAGUE: (47, "premier-league"),
    LeagueId.LA_LIGA: (87, "laliga"),
    LeagueId.LIGUE_1: (53, "ligue-1"),
}

_NEXT_DATA_RE = re.compile(
    r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>',
    re.DOTALL,
)


@dataclass(frozen=True, slots=True)
class SecondaryInjuryRecord:
    team_name: str
    player_name: str
    reason: str
    return_info: str | None = None
    source_name: str = "SportsGambler"


@dataclass(frozen=True, slots=True)
class SecondaryStandingRecord:
    team_name: str
    rank: int
    points: int
    played: int


@dataclass(slots=True)
class SecondaryCheckData:
    league_id: LeagueId
    active_source_name: str = "TheSportsDB"
    injuries: list[SecondaryInjuryRecord] = field(default_factory=list)
    standings: list[SecondaryStandingRecord] = field(default_factory=list)


def parse_sportsgambler_html(html: str) -> list[SecondaryInjuryRecord]:
    """SportsGambler sakatlık/ceza HTML bloklarını ayrıştırır."""
    if not html or not html.strip():
        return []
    soup = parse_html(html)
    records: list[SecondaryInjuryRecord] = []

    blocks = soup.select(".injuries-block, .injury-block, .team-injuries, div.inj-wrapper")
    if not blocks:
        # Genel başlık + tablo/satır yapısı yedeği
        for heading in soup.select("h2, h3, .inj-team-name"):
            tname = clean_text(heading)
            if not tname or len(tname) > 80:
                continue
            container = heading.find_next_sibling()
            if container is None:
                continue
            for row in container.select(".inj-row, tr"):
                cells = [clean_text(c) for c in row.select(".inj-player, .inj-info, .inj-return, td") if clean_text(c)]
                if len(cells) >= 2 and cells[0].lower() not in {"player", "name", "oyuncu"}:
                    records.append(
                        SecondaryInjuryRecord(
                            team_name=tname,
                            player_name=cells[0],
                            reason=cells[1],
                            return_info=cells[2] if len(cells) >= 3 else None,
                            source_name="SportsGambler",
                        )
                    )
        return records

    for block in blocks:
        title_el = block.select_one("h2, h3, .inj-team, .team-name, .title")
        team_name = clean_text(title_el)
        if not team_name:
            continue
        for row in block.select(".inj-row, .inj-container, tbody tr"):
            p_el = row.select_one(".inj-player, .player-name")
            r_el = row.select_one(".inj-info, .inj-type, .reason")
            ret_el = row.select_one(".inj-return, .return-date")
            if p_el is not None:
                pname = clean_text(p_el)
                reason = clean_text(r_el) or "Injury / Suspension"
                ret = clean_text(ret_el) or None
            else:
                tds = [clean_text(td) for td in row.find_all("td") if clean_text(td)]
                if len(tds) < 2:
                    continue
                pname, reason = tds[0], tds[1]
                ret = tds[2] if len(tds) >= 3 else None
            if pname and pname.lower() not in {"player", "name"}:
                records.append(
                    SecondaryInjuryRecord(
                        team_name=team_name,
                        player_name=pname,
                        reason=reason,
                        return_info=ret,
                        source_name="SportsGambler",
                    )
                )
    return records


def parse_thesportsdb_table(payload: dict[str, Any]) -> list[SecondaryStandingRecord]:
    """TheSportsDB lookuptable.php JSON çıktısını ayrıştırır."""
    rows: list[SecondaryStandingRecord] = []
    for idx, item in enumerate(payload.get("table") or [], start=1):
        if not isinstance(item, dict):
            continue
        tname = str(item.get("strTeam") or "").strip()
        if not tname:
            continue
        try:
            rank = int(item.get("intRank") or idx)
            pts = int(item.get("intPoints") or 0)
            played = int(item.get("intPlayed") or 0)
        except (TypeError, ValueError):
            rank, pts, played = idx, 0, 0
        rows.append(
            SecondaryStandingRecord(
                team_name=tname,
                rank=rank,
                points=pts,
                played=played,
            )
        )
    return rows


def parse_fpl_bootstrap_injuries(payload: dict[str, Any]) -> list[SecondaryInjuryRecord]:
    """Resmi Premier League FPL bootstrap-static JSON verisinden sakat/cezalı oyuncuları çıkarır."""
    teams_by_id: dict[int, str] = {}
    for tm in payload.get("teams") or []:
        if isinstance(tm, dict) and tm.get("id") is not None and tm.get("name"):
            teams_by_id[int(tm["id"])] = str(tm["name"]).strip()

    injuries: list[SecondaryInjuryRecord] = []
    for el in payload.get("elements") or []:
        if not isinstance(el, dict):
            continue
        status = str(el.get("status") or "")
        news = str(el.get("news") or "").strip()
        if status not in {"i", "s", "d", "u"} or not news:
            continue
        tname = teams_by_id.get(int(el.get("team") or 0), "")
        full_name = f"{el.get('first_name', '')} {el.get('second_name', '')}".strip()
        pname = full_name or str(el.get("web_name") or "").strip()
        if not tname or not pname:
            continue
        parts = [p.strip() for p in news.split(" - ", 1)]
        reason = parts[0] if parts else news
        ret = parts[1] if len(parts) > 1 else None
        injuries.append(
            SecondaryInjuryRecord(
                team_name=tname,
                player_name=pname,
                reason=reason or "Injury",
                return_info=ret,
                source_name="TheSportsDB",
            )
        )
    return injuries


class SecondaryCheckAdapter:
    """5. bağımsız doğrulama kaynağı: SportsGambler sakatlıkları + TheSportsDB / resmi lig sakatlık yedeği."""

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        timeout: float = 12.0,
        allow_live_fallbacks: bool | None = None,
    ) -> None:
        self._owns_client = client is None
        self._allow_live_fallbacks = (
            self._owns_client if allow_live_fallbacks is None else allow_live_fallbacks
        )
        self._client = client or httpx.Client(
            headers=build_browser_headers(
                referer="https://www.thesportsdb.com/",
                accept_language="en-US,en;q=0.9",
            ),
            follow_redirects=True,
            timeout=timeout,
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> SecondaryCheckAdapter:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _fetch_round_lineup_injuries(self, league_id: LeagueId) -> list[SecondaryInjuryRecord]:
        lid_num, slug = FOTMOB_OVERVIEW_ROUTES[league_id]
        ov_resp = self._client.get(
            f"https://www.fotmob.com/leagues/{lid_num}/overview/{slug}",
            timeout=10.0,
        )
        if ov_resp.status_code != 200:
            return []
        m = _NEXT_DATA_RE.search(ov_resp.text)
        if not m:
            return []
        nd = json.loads(m.group(1))
        all_matches = (
            (((nd.get("props") or {}).get("pageProps") or {}).get("fixtures") or {}).get("allMatches")
            or []
        )
        unplayed = [
            item
            for item in all_matches
            if isinstance(item, dict)
            and not (item.get("status") or {}).get("finished")
            and not (item.get("status") or {}).get("cancelled")
            and item.get("pageUrl")
        ]
        if not unplayed:
            return []
        next_rnd = unplayed[0].get("round")
        target_matches = [item for item in unplayed if item.get("round") == next_rnd][:10]

        def _fetch_one(match_item: dict[str, Any]) -> list[SecondaryInjuryRecord]:
            page_url = str(match_item.get("pageUrl") or "").split("#", 1)[0]
            if not page_url:
                return []
            try:
                r = self._client.get(f"https://www.fotmob.com{page_url}", timeout=8.0)
                if r.status_code != 200:
                    return []
                mm = _NEXT_DATA_RE.search(r.text)
                if not mm:
                    return []
                lineup = (
                    (((json.loads(mm.group(1)).get("props") or {}).get("pageProps") or {}).get("content") or {}).get("lineup")
                    or {}
                )
                found: list[SecondaryInjuryRecord] = []
                for side_key in ("homeTeam", "awayTeam"):
                    side = lineup.get(side_key) or {}
                    tname = str(side.get("name") or "").strip()
                    if not tname:
                        continue
                    for p in side.get("unavailable") or []:
                        if not isinstance(p, dict):
                            continue
                        pname = str(p.get("name") or "").strip()
                        unav = p.get("unavailability") or {}
                        utype = str(unav.get("type") or "injury")
                        ret = str(unav.get("expectedReturn") or "").strip() or None
                        if pname:
                            found.append(
                                SecondaryInjuryRecord(
                                    team_name=tname,
                                    player_name=pname,
                                    reason=utype,
                                    return_info=ret,
                                    source_name="TheSportsDB",
                                )
                            )
                return found
            except Exception:
                return []

        collected: list[SecondaryInjuryRecord] = []
        with ThreadPoolExecutor(max_workers=5) as pool:
            for chunk in pool.map(_fetch_one, target_matches):
                collected.extend(chunk)
        return collected

    def fetch_league(
        self,
        league_id: LeagueId,
        *,
        season: str | None = None,
    ) -> tuple[SecondaryCheckData, dict[str, Any]]:
        resolved_season = (season or "").strip() or get_current_season()
        sg_slug = SPORTSGAMBLER_SLUGS[league_id]
        sg_url = f"https://www.sportsgambler.com/injuries/football/{sg_slug}/"

        # 1. Öncelik: SportsGambler (İSS engeli olmayan bulut/ağ ortamlarında doğrudan çalışır)
        sg_status: int | None = None
        sg_err: str | None = None
        try:
            sg_timeout = 4.5 if self._owns_client else None
            sg_resp = (
                self._client.get(sg_url, timeout=sg_timeout)
                if sg_timeout
                else self._client.get(sg_url)
            )
            sg_status = sg_resp.status_code
            if sg_resp.status_code == 200 and "Just a moment..." not in sg_resp.text[:2048]:
                sg_injuries = parse_sportsgambler_html(sg_resp.text)
                if sg_injuries:
                    data = SecondaryCheckData(
                        league_id=league_id,
                        active_source_name="SportsGambler",
                        injuries=sg_injuries,
                    )
                    return data, make_source_diagnostic(
                        "SportsGambler",
                        ok=True,
                        http_status=200,
                        records=len(sg_injuries),
                        url=sg_url,
                        note=f"{len(sg_injuries)} ikinci kaynak sakatlık/ceza kaydı alındı",
                    )
        except Exception as exc:
            sg_err = str(exc)
            logger.info(
                "SportsGambler erişilemedi (%s - %s); TheSportsDB + 2. kaynak sakatlık doğrulamasına geçiliyor.",
                league_id.value,
                exc,
            )

        # 2. Öncelik: TheSportsDB (key=123) + ikincil sakatlık/ceza doğrulaması
        tsdb_id = THESPORTSDB_LEAGUE_IDS[league_id]
        tsdb_url = f"https://www.thesportsdb.com/api/v1/json/123/lookuptable.php?l={tsdb_id}&s={resolved_season}"
        data = SecondaryCheckData(league_id=league_id, active_source_name="TheSportsDB")
        http_status: int | None = sg_status
        notes: list[str] = []
        errors: list[str] = []

        try:
            tsdb_resp = self._client.get(tsdb_url, headers={"Accept": "application/json"})
            http_status = tsdb_resp.status_code
            if tsdb_resp.status_code == 200:
                data.standings = parse_thesportsdb_table(tsdb_resp.json() or {})
                if data.standings:
                    notes.append(f"TheSportsDB {len(data.standings)} sıra kaydı")
            else:
                errors.append(f"TheSportsDB HTTP {tsdb_resp.status_code}")
        except Exception as exc:
            errors.append(f"TheSportsDB: {exc}")

        if self._allow_live_fallbacks:
            try:
                if league_id == LeagueId.PREMIER_LEAGUE:
                    fpl_resp = self._client.get(
                        "https://fantasy.premierleague.com/api/bootstrap-static/",
                        timeout=10.0,
                    )
                    if fpl_resp.status_code == 200:
                        data.injuries = parse_fpl_bootstrap_injuries(fpl_resp.json() or {})
                        http_status = http_status or 200
                        if data.injuries:
                            notes.append(f"FPL {len(data.injuries)} sakat/şüpheli oyuncu")
                if not data.injuries:
                    data.injuries = self._fetch_round_lineup_injuries(league_id)
                    if data.injuries:
                        http_status = http_status or 200
                        notes.append(f"2. kaynak {len(data.injuries)} sakat/cezalı oyuncu")
            except Exception as exc:
                logger.debug("İkincil sakatlık yedeği hatası (%s): %s", league_id.value, exc)

        total_records = len(data.injuries) + len(data.standings)
        ok = total_records > 0
        return data, make_source_diagnostic(
            "TheSportsDB",
            ok=ok,
            http_status=http_status if ok else (http_status or sg_status),
            records=total_records,
            url=tsdb_url,
            note="; ".join(notes) if notes else None,
            error=None if ok else ("; ".join(errors) or sg_err or "5. kaynak verisi alınamadı"),
        )
