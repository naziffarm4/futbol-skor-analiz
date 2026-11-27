"""Kaynak 3 — Understat takım bazlı beklenen gol (xG / xGA) adaptörü ve şut tabanlı xG türeticisi."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from engine.config import LeagueId, get_current_season, get_season_start_year
from engine.scrapers.base import build_browser_headers
from engine.scrapers.sources import make_source_diagnostic

logger = logging.getLogger(__name__)

UNDERSTAT_LEAGUE_SLUGS: dict[LeagueId, str] = {
    LeagueId.PREMIER_LEAGUE: "EPL",
    LeagueId.LA_LIGA: "La_liga",
    LeagueId.LIGUE_1: "Ligue_1",
}

FOTMOB_XG_ROUTES: dict[LeagueId, tuple[int, str]] = {
    LeagueId.SUPER_LIG: (71, "super-lig"),
    LeagueId.PREMIER_LEAGUE: (47, "premier-league"),
    LeagueId.LA_LIGA: (87, "laliga"),
    LeagueId.LIGUE_1: (53, "ligue-1"),
}

_TEAMS_DATA_RE = re.compile(
    r"teamsData\s*=\s*JSON\.parse\(\s*'([^']+)'\s*\)",
    re.DOTALL,
)
_HEX_ESCAPE_RE = re.compile(r"\\x([0-9a-fA-F]{2})")
_NEXT_DATA_RE = re.compile(
    r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>',
    re.DOTALL,
)


@dataclass(frozen=True, slots=True)
class UnderstatTeamXG:
    team_name: str
    matches_played: int
    xg_for_per_match: float
    xg_against_per_match: float
    xg_is_derived: bool = False


@dataclass(slots=True)
class UnderstatLeagueData:
    league_id: LeagueId
    start_year: int
    teams: dict[str, UnderstatTeamXG] = field(default_factory=dict)


def derive_xg_from_shots(
    *,
    shots_for_per_match: float | None,
    sot_for_per_match: float | None,
    shots_against_per_match: float | None,
    sot_against_per_match: float | None,
) -> tuple[float | None, float | None]:
    """İsabetli şut (0.32) ve isabetsiz şut (0.05) katsayılarıyla xG/xGA vekili hesaplar."""

    def _one_side(shots: float | None, sot: float | None) -> float | None:
        if sot is None and shots is None:
            return None
        eff_sot = sot if sot is not None else max(0.0, (shots or 0.0) * 0.35)
        eff_shots = shots if shots is not None else eff_sot * 2.75
        off_target = max(0.0, eff_shots - eff_sot)
        return round(0.32 * eff_sot + 0.05 * off_target, 3)

    return (
        _one_side(shots_for_per_match, sot_for_per_match),
        _one_side(shots_against_per_match, sot_against_per_match),
    )


def _decode_understat_js_string(escaped: str) -> str:
    step1 = _HEX_ESCAPE_RE.sub(lambda m: chr(int(m.group(1), 16)), escaped)
    return (
        step1.replace('\\"', '"')
        .replace("\\'", "'")
        .replace("\\\\", "\\")
        .replace("\\/", "/")
    )


def parse_understat_teams_data(raw_payload: dict[str, Any] | str) -> dict[str, UnderstatTeamXG]:
    """Understat getLeagueData JSON sözlüğünü veya gömülü HTML teamsData metnini ayrıştırır."""
    teams_dict: dict[str, Any] | None = None

    if isinstance(raw_payload, str):
        stripped = raw_payload.strip()
        if stripped.startswith("{"):
            try:
                loaded = json.loads(stripped)
                if isinstance(loaded, dict):
                    teams_dict = loaded.get("teams") if isinstance(loaded.get("teams"), dict) else loaded
            except json.JSONDecodeError:
                teams_dict = None
        if teams_dict is None:
            m = _TEAMS_DATA_RE.search(raw_payload)
            if m:
                decoded = _decode_understat_js_string(m.group(1))
                loaded = json.loads(decoded)
                if isinstance(loaded, dict):
                    teams_dict = loaded
    elif isinstance(raw_payload, dict):
        teams_dict = raw_payload.get("teams") if isinstance(raw_payload.get("teams"), dict) else raw_payload

    if not isinstance(teams_dict, dict):
        return {}

    parsed: dict[str, UnderstatTeamXG] = {}
    for entry in teams_dict.values():
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("title") or "").strip()
        history = entry.get("history")
        if not title or not isinstance(history, list) or not history:
            continue
        xg_sum = 0.0
        xga_sum = 0.0
        valid_rows = 0
        for h in history:
            if not isinstance(h, dict):
                continue
            try:
                xg_sum += float(h.get("xG", 0.0))
                xga_sum += float(h.get("xGA", 0.0))
                valid_rows += 1
            except (TypeError, ValueError):
                continue
        if valid_rows > 0:
            parsed[title] = UnderstatTeamXG(
                team_name=title,
                matches_played=valid_rows,
                xg_for_per_match=round(xg_sum / valid_rows, 3),
                xg_against_per_match=round(xga_sum / valid_rows, 3),
                xg_is_derived=False,
            )
    return parsed


class UnderstatAdapter:
    """Understat xG/xGA birincil adaptörü; bakım veya Süper Lig durumunda canlı Opta/şut xG köprüsü."""

    SOURCE_NAME = "Understat"

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        timeout: float = 14.0,
        allow_opta_bridge: bool | None = None,
    ) -> None:
        self._owns_client = client is None
        self._allow_opta_bridge = (
            self._owns_client if allow_opta_bridge is None else allow_opta_bridge
        )
        self._client = client or httpx.Client(
            headers=build_browser_headers(
                referer="https://understat.com/",
                accept_language="en-US,en;q=0.9",
            ),
            follow_redirects=True,
            timeout=timeout,
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> UnderstatAdapter:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _fetch_opta_xg_bridge(
        self,
        league_id: LeagueId,
        season: str,
    ) -> tuple[dict[str, UnderstatTeamXG], int | None, str]:
        lid_num, slug = FOTMOB_XG_ROUTES[league_id]
        stats_url = f"https://www.fotmob.com/leagues/{lid_num}/stats/{slug}"
        resp = self._client.get(stats_url, timeout=12.0)
        if resp.status_code != 200:
            return {}, resp.status_code, stats_url

        m = _NEXT_DATA_RE.search(resp.text)
        if not m:
            return {}, 200, stats_url
        nd = json.loads(m.group(1))
        stat_links = (
            ((nd.get("props") or {}).get("pageProps") or {}).get("stats") or {}
        ).get("seasonStatLinks") or []

        target_name = season.replace("-", "/")
        chosen_sid: str | None = None
        for item in stat_links:
            if isinstance(item, dict) and str(item.get("Name") or "") == target_name:
                chosen_sid = str(item.get("TournamentId") or "")
                break
        if not chosen_sid and stat_links and isinstance(stat_links[0], dict):
            chosen_sid = str(stat_links[0].get("TournamentId") or "")
        if not chosen_sid:
            return {}, 200, stats_url

        xg_url = f"https://data.fotmob.com/stats/{lid_num}/season/{chosen_sid}/expected_goals_team.json"
        xga_url = f"https://data.fotmob.com/stats/{lid_num}/season/{chosen_sid}/expected_goals_conceded_team.json"

        r_xg = self._client.get(xg_url, timeout=10.0)
        r_xga = self._client.get(xga_url, timeout=10.0)
        if r_xg.status_code != 200:
            return {}, r_xg.status_code, xg_url

        xg_by_team: dict[str, tuple[int, float]] = {}
        xga_by_team: dict[str, float] = {}

        for row in (((r_xg.json() or {}).get("TopLists") or [{}])[0].get("StatList") or []):
            if not isinstance(row, dict):
                continue
            tname = str(row.get("ParticipantName") or "").strip()
            mp = max(1, int(row.get("MatchesPlayed") or 1))
            val = float(row.get("StatValue") or 0.0)
            if tname:
                xg_by_team[tname] = (mp, round(val / mp, 3))

        if r_xga.status_code == 200:
            for row in (((r_xga.json() or {}).get("TopLists") or [{}])[0].get("StatList") or []):
                if not isinstance(row, dict):
                    continue
                tname = str(row.get("ParticipantName") or "").strip()
                mp = max(1, int(row.get("MatchesPlayed") or 1))
                val = float(row.get("StatValue") or 0.0)
                if tname:
                    xga_by_team[tname] = round(val / mp, 3)

        out: dict[str, UnderstatTeamXG] = {}
        for tname, (mp, xg_pm) in xg_by_team.items():
            out[tname] = UnderstatTeamXG(
                team_name=tname,
                matches_played=mp,
                xg_for_per_match=xg_pm,
                xg_against_per_match=xga_by_team.get(tname, 1.25),
                xg_is_derived=False,
            )
        return out, 200, xg_url

    def fetch_league(
        self,
        league_id: LeagueId,
        *,
        season: str | None = None,
        fallback_team_shots: dict[str, tuple[float | None, float | None, float | None, float | None]] | None = None,
    ) -> tuple[UnderstatLeagueData, dict[str, Any]]:
        resolved_season = (season or "").strip() or get_current_season()
        start_year = get_season_start_year(resolved_season)
        result = UnderstatLeagueData(league_id=league_id, start_year=start_year)

        slug = UNDERSTAT_LEAGUE_SLUGS.get(league_id)
        http_status: int | None = None
        used_url = f"https://understat.com/league/{slug}/{start_year}" if slug else "https://understat.com/"
        notes: list[str] = []
        err_msg: str | None = None

        if slug is not None:
            ajax_url = f"https://understat.com/getLeagueData/{slug}/{start_year}"
            page_url = f"https://understat.com/league/{slug}/{start_year}"
            try:
                ajax_resp = self._client.get(
                    ajax_url,
                    headers={
                        "X-Requested-With": "XMLHttpRequest",
                        "Accept": "application/json, text/javascript, */*; q=0.01",
                        "Referer": page_url,
                    },
                )
                http_status = ajax_resp.status_code
                if ajax_resp.status_code == 200:
                    parsed = parse_understat_teams_data(ajax_resp.text)
                    if parsed:
                        result.teams = parsed
                        return result, make_source_diagnostic(
                            self.SOURCE_NAME,
                            ok=True,
                            http_status=200,
                            records=len(parsed),
                            url=ajax_url,
                            note=f"{len(parsed)} takım gerçek Understat xG/xGA verisi alındı",
                        )

                page_resp = self._client.get(page_url)
                http_status = page_resp.status_code
                if page_resp.status_code == 200:
                    parsed = parse_understat_teams_data(page_resp.text)
                    if parsed:
                        result.teams = parsed
                        return result, make_source_diagnostic(
                            self.SOURCE_NAME,
                            ok=True,
                            http_status=200,
                            records=len(parsed),
                            url=page_url,
                            note=f"{len(parsed)} takım HTML gömülü Understat xG/xGA verisi alındı",
                        )
                    if "We will come back soon" in page_resp.text:
                        notes.append("Understat bakım sayfası algılandı")
                else:
                    err_msg = f"HTTP {page_resp.status_code}"
            except Exception as exc:
                err_msg = str(exc)
                logger.warning("Understat erişim hatası (%s): %s", league_id.value, exc)
        else:
            notes.append("Süper Lig Understat kapsamı dışında")

        if self._allow_opta_bridge:
            try:
                bridge_teams, st_code, bridge_url = self._fetch_opta_xg_bridge(
                    league_id, resolved_season
                )
                if bridge_teams:
                    result.teams = bridge_teams
                    notes.append(f"Opta xG/xGA köprüsü ({len(bridge_teams)} takım)")
                    return result, make_source_diagnostic(
                        self.SOURCE_NAME,
                        ok=True,
                        http_status=st_code or 200,
                        records=len(bridge_teams),
                        url=bridge_url,
                        note="; ".join(notes),
                    )
            except Exception as exc:
                logger.debug("Opta xG köprü hatası (%s): %s", league_id.value, exc)

        if fallback_team_shots:
            derived: dict[str, UnderstatTeamXG] = {}
            for tname, (sh_f, sot_f, sh_a, sot_a) in fallback_team_shots.items():
                xg_f, xg_a = derive_xg_from_shots(
                    shots_for_per_match=sh_f,
                    sot_for_per_match=sot_f,
                    shots_against_per_match=sh_a,
                    sot_against_per_match=sot_a,
                )
                if xg_f is not None and xg_a is not None:
                    derived[tname] = UnderstatTeamXG(
                        team_name=tname,
                        matches_played=1,
                        xg_for_per_match=xg_f,
                        xg_against_per_match=xg_a,
                        xg_is_derived=True,
                    )
            if derived:
                result.teams = derived
                notes.append(f"İsabetli şut tabanlı türetilmiş xG ({len(derived)} takım)")
                return result, make_source_diagnostic(
                    self.SOURCE_NAME,
                    ok=True,
                    http_status=http_status or 200,
                    records=len(derived),
                    url=used_url,
                    note="; ".join(notes),
                )

        return result, make_source_diagnostic(
            self.SOURCE_NAME,
            ok=False,
            http_status=http_status,
            records=0,
            url=used_url,
            note="; ".join(notes) if notes else None,
            error=err_msg or "xG verisi alınamadı",
        )
