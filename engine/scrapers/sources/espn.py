"""Kaynak 1 — ESPN Public Soccer API adaptörü (puan durumu, canlı/son fikstür ve oran dengesi)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from engine.config import LeagueId
from engine.scrapers.base import build_browser_headers
from engine.scrapers.sources import make_source_diagnostic

logger = logging.getLogger(__name__)

ESPN_LEAGUE_SLUGS: dict[LeagueId, str] = {
    LeagueId.SUPER_LIG: "tur.1",
    LeagueId.PREMIER_LEAGUE: "eng.1",
    LeagueId.LA_LIGA: "esp.1",
    LeagueId.LIGUE_1: "fra.1",
}

_MINUTE_RE = re.compile(r"^(\d+)")


@dataclass(frozen=True, slots=True)
class ESPNStandingRow:
    team_name: str
    short_name: str | None
    rank: int
    points: int
    games_played: int
    points_for: int
    points_against: int
    point_differential: int


@dataclass(frozen=True, slots=True)
class ESPNFixtureRecord:
    home_team: str
    away_team: str
    match_date: str
    status: str
    home_score: int | None = None
    away_score: int | None = None
    ht_home_score: int | None = None
    ht_away_score: int | None = None
    home_shots: float | None = None
    away_shots: float | None = None
    home_sot: float | None = None
    away_sot: float | None = None
    home_corners: float | None = None
    away_corners: float | None = None
    home_cards: float | None = None
    away_cards: float | None = None
    home_win_prob: float | None = None
    away_win_prob: float | None = None


@dataclass(slots=True)
class ESPNLeagueData:
    league_id: LeagueId
    standings: list[ESPNStandingRow] = field(default_factory=list)
    fixtures: list[ESPNFixtureRecord] = field(default_factory=list)


def _american_to_implied_prob(raw: Any) -> float | None:
    if raw is None:
        return None
    s = str(raw).strip().upper()
    if not s:
        return None
    if s == "EVEN":
        return 0.5
    try:
        val = float(s)
    except ValueError:
        return None
    if val == 0:
        return None
    if val > 0:
        return 100.0 / (val + 100.0)
    return abs(val) / (abs(val) + 100.0)


def _extract_moneyline_probs(comp: dict[str, Any]) -> tuple[float | None, float | None]:
    odds_list = comp.get("odds")
    if not isinstance(odds_list, list) or not odds_list:
        return None, None
    first = odds_list[0] if isinstance(odds_list[0], dict) else {}
    ml = first.get("moneyline")
    if not isinstance(ml, dict):
        return None, None

    def _side_odds(side_key: str) -> float | None:
        side = ml.get(side_key)
        if not isinstance(side, dict):
            return None
        chosen = side.get("close") or side.get("open") or side
        if isinstance(chosen, dict):
            return _american_to_implied_prob(chosen.get("odds"))
        return None

    ph = _side_odds("home")
    pd = _side_odds("draw")
    pa = _side_odds("away")
    if ph is None or pa is None:
        return None, None
    total = ph + (pd or 0.26) + pa
    if total <= 0:
        return None, None
    return round(ph / total, 4), round(pa / total, 4)


def parse_espn_standings_json(payload: dict[str, Any]) -> list[ESPNStandingRow]:
    """ESPN standings JSON yanıtından takım puan durumu satırlarını ayrıştırır."""
    entries: list[dict[str, Any]] = []
    children = payload.get("children")
    if isinstance(children, list) and children:
        for child in children:
            if isinstance(child, dict):
                st = child.get("standings")
                if isinstance(st, dict) and isinstance(st.get("entries"), list):
                    entries.extend(st["entries"])
                    break
    if not entries:
        st_root = payload.get("standings")
        if isinstance(st_root, dict) and isinstance(st_root.get("entries"), list):
            entries.extend(st_root["entries"])

    rows: list[ESPNStandingRow] = []
    for idx, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            continue
        team_info = entry.get("team") or {}
        team_name = str(
            team_info.get("displayName") or team_info.get("name") or ""
        ).strip()
        if not team_name:
            continue
        short_name = str(team_info.get("shortDisplayName") or "").strip() or None

        stat_map: dict[str, float] = {}
        for stat in entry.get("stats") or []:
            if not isinstance(stat, dict):
                continue
            sname = str(stat.get("name") or "")
            sval = stat.get("value")
            if sname and sval is not None:
                try:
                    stat_map[sname] = float(sval)
                except (TypeError, ValueError):
                    pass

        rows.append(
            ESPNStandingRow(
                team_name=team_name,
                short_name=short_name,
                rank=int(stat_map.get("rank", idx)),
                points=int(stat_map.get("points", 0)),
                games_played=int(stat_map.get("gamesPlayed", 0)),
                points_for=int(stat_map.get("pointsFor", 0)),
                points_against=int(stat_map.get("pointsAgainst", 0)),
                point_differential=int(
                    stat_map.get(
                        "pointDifferential",
                        stat_map.get("pointsFor", 0) - stat_map.get("pointsAgainst", 0),
                    )
                ),
            )
        )
    return rows


def parse_espn_scoreboard_json(payload: dict[str, Any]) -> list[ESPNFixtureRecord]:
    """ESPN scoreboard JSON yanıtından maçları, istatistikleri ve oranları ayrıştırır."""
    events = payload.get("events")
    if not isinstance(events, list):
        return []

    records: list[ESPNFixtureRecord] = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        comps = ev.get("competitions")
        if not isinstance(comps, list) or not comps:
            continue
        comp = comps[0] if isinstance(comps[0], dict) else {}
        competitors = comp.get("competitors") or []
        home_c: dict[str, Any] | None = None
        away_c: dict[str, Any] | None = None
        for c in competitors:
            if not isinstance(c, dict):
                continue
            if c.get("homeAway") == "home":
                home_c = c
            elif c.get("homeAway") == "away":
                away_c = c
        if home_c is None or away_c is None:
            continue

        home_team_obj = home_c.get("team") or {}
        away_team_obj = away_c.get("team") or {}
        home_name = str(home_team_obj.get("displayName") or home_team_obj.get("name") or "").strip()
        away_name = str(away_team_obj.get("displayName") or away_team_obj.get("name") or "").strip()
        if not home_name or not away_name:
            continue

        status_type = (ev.get("status") or {}).get("type") or {}
        completed = bool(status_type.get("completed"))
        st_name = str(status_type.get("name") or "").upper()
        if completed or "FINAL" in st_name or "FULL_TIME" in st_name:
            norm_status = "FINISHED"
        elif any(k in st_name for k in ("POSTPONED", "CANCELED", "CANCELLED", "SUSPENDED")):
            norm_status = "POSTPONED"
        else:
            norm_status = "SCHEDULED"

        def _parse_score(comp_side: dict[str, Any], status_val: str = norm_status) -> int | None:
            if status_val != "FINISHED":
                return None
            raw = comp_side.get("score")
            if isinstance(raw, dict):
                raw = raw.get("value")
            try:
                return int(float(str(raw)))
            except (TypeError, ValueError):
                return None

        def _parse_side_stats(comp_side: dict[str, Any]) -> dict[str, float]:
            out: dict[str, float] = {}
            for st in comp_side.get("statistics") or []:
                if not isinstance(st, dict):
                    continue
                nm = str(st.get("name") or "")
                dv = st.get("displayValue") if st.get("displayValue") is not None else st.get("value")
                if nm and dv is not None:
                    try:
                        out[nm] = float(str(dv).replace("%", "").strip())
                    except ValueError:
                        pass
            return out

        def _parse_linescore_ht(comp_side: dict[str, Any]) -> int | None:
            ls = comp_side.get("linescores")
            if isinstance(ls, list) and ls and isinstance(ls[0], dict):
                val = ls[0].get("value")
                if val is not None:
                    try:
                        return int(float(val))
                    except (TypeError, ValueError):
                        pass
            return None

        h_score = _parse_score(home_c)
        a_score = _parse_score(away_c)
        h_stats = _parse_side_stats(home_c)
        a_stats = _parse_side_stats(away_c)

        ht_h = _parse_linescore_ht(home_c)
        ht_a = _parse_linescore_ht(away_c)
        home_tid = str(home_team_obj.get("id") or "")
        away_tid = str(away_team_obj.get("id") or "")
        h_cards = 0.0
        a_cards = 0.0
        has_details = False

        details = comp.get("details")
        if isinstance(details, list) and norm_status == "FINISHED":
            ht_h_calc = 0
            ht_a_calc = 0
            for det in details:
                if not isinstance(det, dict):
                    continue
                has_details = True
                det_team_id = str((det.get("team") or {}).get("id") or "")
                is_goal = bool(det.get("scoringPlay")) or "goal" in str((det.get("type") or {}).get("text") or "").lower()
                is_card = bool(det.get("yellowCard") or det.get("redCard")) or "card" in str((det.get("type") or {}).get("text") or "").lower()
                clock_txt = str((det.get("clock") or {}).get("displayValue") or "")
                m_min = _MINUTE_RE.match(clock_txt.strip())
                minute_val = int(m_min.group(1)) if m_min else 99
                if is_goal and minute_val <= 45:
                    if det_team_id == home_tid:
                        ht_h_calc += 1
                    elif det_team_id == away_tid:
                        ht_a_calc += 1
                if is_card:
                    if det_team_id == home_tid:
                        h_cards += 1.0
                    elif det_team_id == away_tid:
                        a_cards += 1.0
            if ht_h is None and h_score is not None:
                ht_h = min(ht_h_calc, h_score)
            if ht_a is None and a_score is not None:
                ht_a = min(ht_a_calc, a_score)

        hw_prob, aw_prob = _extract_moneyline_probs(comp)

        records.append(
            ESPNFixtureRecord(
                home_team=home_name,
                away_team=away_name,
                match_date=str(ev.get("date") or ""),
                status=norm_status,
                home_score=h_score,
                away_score=a_score,
                ht_home_score=ht_h,
                ht_away_score=ht_a,
                home_shots=h_stats.get("totalShots"),
                away_shots=a_stats.get("totalShots"),
                home_sot=h_stats.get("shotsOnTarget"),
                away_sot=a_stats.get("shotsOnTarget"),
                home_corners=h_stats.get("wonCorners"),
                away_corners=a_stats.get("wonCorners"),
                home_cards=h_cards if has_details else None,
                away_cards=a_cards if has_details else None,
                home_win_prob=hw_prob,
                away_win_prob=aw_prob,
            )
        )
    return records


class ESPNAdapter:
    """ESPN Public API üzerinden 4 ligin puan durumu ve canlı/güncel fikstür verisini çeker."""

    SOURCE_NAME = "ESPN"

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        timeout: float = 14.0,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.Client(
            headers=build_browser_headers(
                referer="https://www.espn.com/",
                accept_language="en-US,en;q=0.9,tr;q=0.8",
            ),
            follow_redirects=True,
            timeout=timeout,
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> ESPNAdapter:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def fetch_league(self, league_id: LeagueId) -> tuple[ESPNLeagueData, dict[str, Any]]:
        slug = ESPN_LEAGUE_SLUGS[league_id]
        scoreboard_url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard"
        standings_primary_url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/standings"
        standings_v2_url = f"https://site.api.espn.com/apis/v2/sports/soccer/{slug}/standings"

        data = ESPNLeagueData(league_id=league_id)
        http_status: int | None = None
        notes: list[str] = []
        errors: list[str] = []

        try:
            sb_resp = self._client.get(scoreboard_url, headers={"Accept": "application/json"})
            http_status = sb_resp.status_code
            if sb_resp.status_code == 200:
                data.fixtures = parse_espn_scoreboard_json(sb_resp.json())
            else:
                errors.append(f"scoreboard HTTP {sb_resp.status_code}")
        except Exception as exc:
            logger.warning("ESPN scoreboard hatası (%s): %s", league_id.value, exc)
            errors.append(f"scoreboard: {exc}")

        used_standings_url = standings_primary_url
        try:
            st_resp = self._client.get(standings_primary_url, headers={"Accept": "application/json"})
            if st_resp.status_code == 404:
                used_standings_url = standings_v2_url
                st_resp = self._client.get(standings_v2_url, headers={"Accept": "application/json"})
                if st_resp.status_code == 200:
                    notes.append("standings apis/v2 uç noktasından alındı")
            if http_status is None or st_resp.status_code == 200:
                http_status = st_resp.status_code
            if st_resp.status_code == 200:
                data.standings = parse_espn_standings_json(st_resp.json())
            else:
                errors.append(f"standings HTTP {st_resp.status_code}")
        except Exception as exc:
            logger.warning("ESPN standings hatası (%s): %s", league_id.value, exc)
            errors.append(f"standings: {exc}")

        total_records = len(data.standings) + len(data.fixtures)
        ok = total_records > 0
        diag = make_source_diagnostic(
            self.SOURCE_NAME,
            ok=ok,
            http_status=http_status,
            records=total_records,
            url=used_standings_url if data.standings else scoreboard_url,
            note="; ".join(notes) if notes else f"{len(data.standings)} takım, {len(data.fixtures)} maç",
            error="; ".join(errors) if (errors and not ok) else None,
        )
        return data, diag
