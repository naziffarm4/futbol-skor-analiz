"""Kaynak 2 — Football-Data (maç bazlı İY/MS skorları, şut, isabetli şut, korner, kart ve oranlar)."""

from __future__ import annotations

import csv
import io
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from engine.config import (
    LeagueId,
    get_current_season,
    get_football_data_season_code,
    get_season_start_year,
)
from engine.scrapers.base import build_browser_headers
from engine.scrapers.sources import make_source_diagnostic

logger = logging.getLogger(__name__)

FOOTBALL_DATA_CODES: dict[LeagueId, str] = {
    LeagueId.SUPER_LIG: "T1",
    LeagueId.PREMIER_LEAGUE: "E0",
    LeagueId.LA_LIGA: "SP1",
    LeagueId.LIGUE_1: "F1",
}

OPENFOOTBALL_SLUGS: dict[LeagueId, str] = {
    LeagueId.PREMIER_LEAGUE: "en.1",
    LeagueId.LA_LIGA: "es.1",
    LeagueId.LIGUE_1: "fr.1",
}

FOTMOB_LEAGUE_ROUTES: dict[LeagueId, tuple[int, str]] = {
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
class FootballDataMatchRow:
    home_team: str
    away_team: str
    match_date: str
    fthg: int
    ftag: int
    hthg: int | None = None
    htag: int | None = None
    htr: str | None = None
    hs: float | None = None
    as_: float | None = None
    hst: float | None = None
    ast: float | None = None
    hc: float | None = None
    ac: float | None = None
    hy: float | None = None
    ay: float | None = None
    hr: float | None = None
    ar: float | None = None
    home_win_prob: float | None = None
    away_win_prob: float | None = None


@dataclass(slots=True)
class FootballDataTeamStats:
    team_name: str
    matches_played: int = 0
    ft_goals_for: int = 0
    ft_goals_against: int = 0
    ht_goals_for: int = 0
    ht_goals_against: int = 0
    ht_matches: int = 0
    shots_for_total: float = 0.0
    shots_against_total: float = 0.0
    shots_matches: int = 0
    sot_for_total: float = 0.0
    sot_against_total: float = 0.0
    sot_matches: int = 0
    corners_for_total: float = 0.0
    corners_against_total: float = 0.0
    corners_matches: int = 0
    cards_total: float = 0.0
    cards_matches: int = 0
    market_prob_sum: float = 0.0
    market_prob_matches: int = 0

    @property
    def shots_for_per_match(self) -> float | None:
        return round(self.shots_for_total / self.shots_matches, 3) if self.shots_matches > 0 else None

    @property
    def shots_against_per_match(self) -> float | None:
        return round(self.shots_against_total / self.shots_matches, 3) if self.shots_matches > 0 else None

    @property
    def sot_for_per_match(self) -> float | None:
        return round(self.sot_for_total / self.sot_matches, 3) if self.sot_matches > 0 else None

    @property
    def sot_against_per_match(self) -> float | None:
        return round(self.sot_against_total / self.sot_matches, 3) if self.sot_matches > 0 else None

    @property
    def corners_for_per_match(self) -> float | None:
        return round(self.corners_for_total / self.corners_matches, 3) if self.corners_matches > 0 else None

    @property
    def corners_against_per_match(self) -> float | None:
        return round(self.corners_against_total / self.corners_matches, 3) if self.corners_matches > 0 else None

    @property
    def cards_per_match(self) -> float | None:
        return round(self.cards_total / self.cards_matches, 3) if self.cards_matches > 0 else None

    @property
    def market_win_prob_avg(self) -> float | None:
        return round(self.market_prob_sum / self.market_prob_matches, 4) if self.market_prob_matches > 0 else None


@dataclass(slots=True)
class FootballDataLeagueData:
    league_id: LeagueId
    season_code: str
    matches: list[FootballDataMatchRow] = field(default_factory=list)
    team_stats: dict[str, FootballDataTeamStats] = field(default_factory=dict)


def _opt_int(row: dict[str, Any], key: str) -> int | None:
    raw = str(row.get(key) or "").strip()
    if not raw:
        return None
    try:
        return int(float(raw))
    except ValueError:
        return None


def _opt_float(row: dict[str, Any], key: str) -> float | None:
    raw = str(row.get(key) or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _extract_odds_probs(row: dict[str, Any]) -> tuple[float | None, float | None]:
    for h_key, d_key, a_key in (("AvgH", "AvgD", "AvgA"), ("B365H", "B365D", "B365A")):
        oh = _opt_float(row, h_key)
        od = _opt_float(row, d_key)
        oa = _opt_float(row, a_key)
        if oh and od and oa and oh > 1.0 and od > 1.0 and oa > 1.0:
            ih, id_, ia = 1.0 / oh, 1.0 / od, 1.0 / oa
            total = ih + id_ + ia
            if total > 0:
                return round(ih / total, 4), round(ia / total, 4)
    return None, None


def aggregate_match_rows(matches: list[FootballDataMatchRow]) -> dict[str, FootballDataTeamStats]:
    """Maç satırlarını takım bazlı kümülatif ve maç başı istatistiklere toplar."""
    teams: dict[str, FootballDataTeamStats] = {}

    def _get(name: str) -> FootballDataTeamStats:
        if name not in teams:
            teams[name] = FootballDataTeamStats(team_name=name)
        return teams[name]

    for m in matches:
        hs = _get(m.home_team)
        as_ = _get(m.away_team)

        hs.matches_played += 1
        as_.matches_played += 1
        hs.ft_goals_for += m.fthg
        hs.ft_goals_against += m.ftag
        as_.ft_goals_for += m.ftag
        as_.ft_goals_against += m.fthg

        if m.hthg is not None and m.htag is not None:
            hs.ht_goals_for += m.hthg
            hs.ht_goals_against += m.htag
            hs.ht_matches += 1
            as_.ht_goals_for += m.htag
            as_.ht_goals_against += m.hthg
            as_.ht_matches += 1

        if m.hs is not None and m.as_ is not None:
            hs.shots_for_total += m.hs
            hs.shots_against_total += m.as_
            hs.shots_matches += 1
            as_.shots_for_total += m.as_
            as_.shots_against_total += m.hs
            as_.shots_matches += 1

        if m.hst is not None and m.ast is not None:
            hs.sot_for_total += m.hst
            hs.sot_against_total += m.ast
            hs.sot_matches += 1
            as_.sot_for_total += m.ast
            as_.sot_against_total += m.hst
            as_.sot_matches += 1

        if m.hc is not None and m.ac is not None:
            hs.corners_for_total += m.hc
            hs.corners_against_total += m.ac
            hs.corners_matches += 1
            as_.corners_for_total += m.ac
            as_.corners_against_total += m.hc
            as_.corners_matches += 1

        if m.hy is not None or m.hr is not None or m.ay is not None or m.ar is not None:
            h_cards = (m.hy or 0.0) + (m.hr or 0.0)
            a_cards = (m.ay or 0.0) + (m.ar or 0.0)
            hs.cards_total += h_cards
            hs.cards_matches += 1
            as_.cards_total += a_cards
            as_.cards_matches += 1

        if m.home_win_prob is not None and m.away_win_prob is not None:
            hs.market_prob_sum += m.home_win_prob
            hs.market_prob_matches += 1
            as_.market_prob_sum += m.away_win_prob
            as_.market_prob_matches += 1

    return teams


def parse_football_data_csv(
    csv_text: str,
    league_id: LeagueId,
    *,
    season_code: str = "",
) -> FootballDataLeagueData:
    """Football-Data.co.uk CSV metnini ayrıştırıp maç ve takım istatistiklerini üretir."""
    cleaned = csv_text.lstrip("﻿").strip()
    result = FootballDataLeagueData(league_id=league_id, season_code=season_code)
    if not cleaned:
        return result

    reader = csv.DictReader(io.StringIO(cleaned))
    matches: list[FootballDataMatchRow] = []
    for row in reader:
        if not isinstance(row, dict):
            continue
        home = str(row.get("HomeTeam") or row.get("Home") or "").strip()
        away = str(row.get("AwayTeam") or row.get("Away") or "").strip()
        fthg = _opt_int(row, "FTHG")
        ftag = _opt_int(row, "FTAG")
        if fthg is None:
            fthg = _opt_int(row, "HG")
        if ftag is None:
            ftag = _opt_int(row, "AG")
        if not home or not away or fthg is None or ftag is None:
            continue

        hthg = _opt_int(row, "HTHG")
        htag = _opt_int(row, "HTAG")
        htr = str(row.get("HTR") or "").strip() or None
        if htr is None and hthg is not None and htag is not None:
            htr = "H" if hthg > htag else ("A" if htag > hthg else "D")

        hw_prob, aw_prob = _extract_odds_probs(row)
        matches.append(
            FootballDataMatchRow(
                home_team=home,
                away_team=away,
                match_date=str(row.get("Date") or "").strip(),
                fthg=fthg,
                ftag=ftag,
                hthg=hthg,
                htag=htag,
                htr=htr,
                hs=_opt_float(row, "HS"),
                as_=_opt_float(row, "AS"),
                hst=_opt_float(row, "HST"),
                ast=_opt_float(row, "AST"),
                hc=_opt_float(row, "HC"),
                ac=_opt_float(row, "AC"),
                hy=_opt_float(row, "HY"),
                ay=_opt_float(row, "AY"),
                hr=_opt_float(row, "HR"),
                ar=_opt_float(row, "AR"),
                home_win_prob=hw_prob,
                away_win_prob=aw_prob,
            )
        )

    result.matches = matches
    result.team_stats = aggregate_match_rows(matches)
    return result


def parse_openfootball_json(
    payload: dict[str, Any],
    league_id: LeagueId,
    *,
    season_code: str = "",
) -> FootballDataLeagueData:
    """OpenFootball JSON verisinden İY (ht) ve MS (ft) maç skorlarını ayrıştırır."""
    matches: list[FootballDataMatchRow] = []
    for item in payload.get("matches") or []:
        if not isinstance(item, dict):
            continue
        home = str(item.get("team1") or "").strip()
        away = str(item.get("team2") or "").strip()
        score_obj = item.get("score")
        if not home or not away or not isinstance(score_obj, dict):
            continue
        ft = score_obj.get("ft")
        if not isinstance(ft, list) or len(ft) != 2 or ft[0] is None or ft[1] is None:
            continue
        ht = score_obj.get("ht")
        hthg = int(ht[0]) if isinstance(ht, list) and len(ht) == 2 and ht[0] is not None else None
        htag = int(ht[1]) if isinstance(ht, list) and len(ht) == 2 and ht[1] is not None else None
        htr = None
        if hthg is not None and htag is not None:
            htr = "H" if hthg > htag else ("A" if htag > hthg else "D")
        matches.append(
            FootballDataMatchRow(
                home_team=home,
                away_team=away,
                match_date=str(item.get("date") or ""),
                fthg=int(ft[0]),
                ftag=int(ft[1]),
                hthg=hthg,
                htag=htag,
                htr=htr,
            )
        )

    return FootballDataLeagueData(
        league_id=league_id,
        season_code=season_code,
        matches=matches,
        team_stats=aggregate_match_rows(matches),
    )


class FootballDataAdapter:
    """Football-Data.co.uk CSV birincil kaynağı ve İSS engellerine karşı açık istatistik yedeği."""

    SOURCE_NAME = "Football-Data"

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        timeout: float = 12.0,
        allow_mirror_fallback: bool | None = None,
    ) -> None:
        self._owns_client = client is None
        self._allow_mirror_fallback = (
            self._owns_client if allow_mirror_fallback is None else allow_mirror_fallback
        )
        self._client = client or httpx.Client(
            headers=build_browser_headers(
                referer="https://www.football-data.co.uk/",
                accept_language="en-GB,en;q=0.9",
            ),
            follow_redirects=True,
            timeout=timeout,
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> FootballDataAdapter:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _enrich_team_stats_from_opta_cdn(
        self,
        league_id: LeagueId,
        season: str,
        data: FootballDataLeagueData,
    ) -> tuple[int | None, str | None, int]:
        """İSS engeli durumunda data.fotmob.com üzerinden takım şut/korner/kart istatistiklerini tamamlar."""
        lid_num, slug = FOTMOB_LEAGUE_ROUTES[league_id]
        stats_page_url = f"https://www.fotmob.com/leagues/{lid_num}/stats/{slug}"
        resp = self._client.get(stats_page_url, timeout=12.0)
        if resp.status_code != 200:
            return resp.status_code, None, 0

        m = _NEXT_DATA_RE.search(resp.text)
        if not m:
            return 200, None, 0
        nd = json.loads(m.group(1))
        page_props = (nd.get("props") or {}).get("pageProps") or {}

        # FotMob fikstürlerinden tamamlanmış maç sayısını ve MS skorlarını da yedekle (Süper Lig dahil)
        if not data.matches:
            all_matches = (page_props.get("fixtures") or {}).get("allMatches") or []
            fallback_rows: list[FootballDataMatchRow] = []
            for fm in all_matches:
                if not isinstance(fm, dict):
                    continue
                st = fm.get("status") or {}
                if not st.get("finished"):
                    continue
                score_str = str(st.get("scoreStr") or "")
                parts = [p.strip() for p in score_str.split("-")]
                if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
                    continue
                h_name = str((fm.get("home") or {}).get("name") or "").strip()
                a_name = str((fm.get("away") or {}).get("name") or "").strip()
                if h_name and a_name:
                    fallback_rows.append(
                        FootballDataMatchRow(
                            home_team=h_name,
                            away_team=a_name,
                            match_date=str(st.get("utcTime") or ""),
                            fthg=int(parts[0]),
                            ftag=int(parts[1]),
                        )
                    )
            if fallback_rows:
                data.matches = fallback_rows
                data.team_stats = aggregate_match_rows(fallback_rows)

        stat_links = (page_props.get("stats") or {}).get("seasonStatLinks") or []
        target_label = season.replace("-", "/")
        chosen_sid: str | None = None
        for item in stat_links:
            if isinstance(item, dict) and str(item.get("Name") or "") == target_label:
                chosen_sid = str(item.get("TournamentId") or "")
                break
        if not chosen_sid and stat_links and isinstance(stat_links[0], dict):
            chosen_sid = str(stat_links[0].get("TournamentId") or "")
        if not chosen_sid:
            return 200, stats_page_url, len(data.team_stats)

        base_cdn = f"https://data.fotmob.com/stats/{lid_num}/season/{chosen_sid}"
        enriched_teams = 0

        def _ensure_team(tname: str, mp: int) -> FootballDataTeamStats:
            ts = data.team_stats.get(tname)
            if ts is None:
                ts = FootballDataTeamStats(team_name=tname, matches_played=max(1, mp))
                data.team_stats[tname] = ts
            elif ts.matches_played == 0 and mp > 0:
                ts.matches_played = mp
            return ts

        for filename, kind in (
            ("ontarget_scoring_att_team.json", "sot"),
            ("corner_taken_team.json", "corners"),
            ("total_yel_card_team.json", "yel"),
            ("total_red_card_team.json", "red"),
        ):
            r_json = self._client.get(f"{base_cdn}/{filename}", timeout=10.0)
            if r_json.status_code != 200:
                continue
            top_lists = (r_json.json() or {}).get("TopLists") or []
            if not top_lists or not isinstance(top_lists[0], dict):
                continue
            stat_list = top_lists[0].get("StatList") or []
            for row in stat_list:
                if not isinstance(row, dict):
                    continue
                tname = str(row.get("ParticipantName") or "").strip()
                if not tname:
                    continue
                mp = max(1, int(row.get("MatchesPlayed") or 1))
                val = float(row.get("StatValue") or 0.0)
                sub = float(row.get("SubStatValue") or 0.0)
                ts = _ensure_team(tname, mp)
                if kind == "sot":
                    # StatValue doğrudan maç başı isabetli şuttur
                    ts.sot_for_total = val * mp
                    ts.sot_matches = mp
                    if ts.shots_matches == 0:
                        est_shots_pm = max(val * 2.65, (ts.ft_goals_for / mp) / (sub / 100.0) if sub > 3.0 and ts.ft_goals_for > 0 else val * 2.75)
                        ts.shots_for_total = min(est_shots_pm, 24.0) * mp
                        ts.shots_matches = mp
                    enriched_teams += 1
                elif kind == "corners":
                    ts.corners_for_total = val
                    ts.corners_matches = mp
                elif kind == "yel":
                    ts.cards_total += val
                    ts.cards_matches = mp
                elif kind == "red":
                    ts.cards_total += val
                    if ts.cards_matches == 0:
                        ts.cards_matches = mp

        return 200, f"{base_cdn}/ontarget_scoring_att_team.json", max(enriched_teams, len(data.team_stats))

    def fetch_league(
        self,
        league_id: LeagueId,
        *,
        season: str | None = None,
    ) -> tuple[FootballDataLeagueData, dict[str, Any]]:
        resolved_season = (season or "").strip() or get_current_season()
        season_code = get_football_data_season_code(resolved_season)
        start_year = get_season_start_year(resolved_season)
        prev_code = f"{(start_year - 1) % 100:02d}{start_year % 100:02d}"
        div_code = FOOTBALL_DATA_CODES[league_id]

        primary_url = f"https://www.football-data.co.uk/mmz4281/{season_code}/{div_code}.csv"
        fallback_prev_url = f"https://www.football-data.co.uk/mmz4281/{prev_code}/{div_code}.csv"

        used_url = primary_url
        http_status: int | None = None
        note: str | None = None
        error_msg: str | None = None

        try:
            # shortcut: Yerel İSS SNI filtrelerinde takılmamak için birincil CSV'de kısa bağlantı zaman aşımı kullanılır;
            # bulut CI ortamında doğrudan CSV döner.
            csv_timeout = 5.5 if self._owns_client else None
            resp = (
                self._client.get(primary_url, timeout=csv_timeout)
                if csv_timeout
                else self._client.get(primary_url)
            )
            http_status = resp.status_code
            if resp.status_code == 404 and prev_code != season_code:
                resp_prev = (
                    self._client.get(fallback_prev_url, timeout=csv_timeout)
                    if csv_timeout
                    else self._client.get(fallback_prev_url)
                )
                if resp_prev.status_code == 200:
                    resp = resp_prev
                    http_status = 200
                    used_url = fallback_prev_url
                    note = f"Yeni sezon CSV henüz yüklenmediğinden {prev_code} sezon CSV yedeği kullanıldı"

            if resp.status_code == 200:
                parsed = parse_football_data_csv(
                    resp.text,
                    league_id,
                    season_code=prev_code if used_url == fallback_prev_url else season_code,
                )
                ok = len(parsed.matches) > 0
                diag = make_source_diagnostic(
                    self.SOURCE_NAME,
                    ok=ok,
                    http_status=200,
                    records=len(parsed.matches),
                    url=used_url,
                    note=note or f"{len(parsed.matches)} maç CSV satırı ayrıştırıldı",
                    error=None if ok else "CSV boş veya geçersiz",
                )
                return parsed, diag
            error_msg = f"HTTP {resp.status_code}"
        except Exception as exc:
            error_msg = str(exc)
            logger.info(
                "Football-Data birincil CSV erişilemedi (%s - %s); açık yansı kontrol ediliyor.",
                league_id.value,
                exc,
            )

        if self._allow_mirror_fallback:
            data = FootballDataLeagueData(league_id=league_id, season_code=season_code)
            mirror_notes: list[str] = []
            mirror_url = primary_url
            of_slug = OPENFOOTBALL_SLUGS.get(league_id)
            if of_slug:
                of_season = f"{start_year}-{str(start_year + 1)[-2:]}"
                of_url = f"https://raw.githubusercontent.com/openfootball/football.json/master/{of_season}/{of_slug}.json"
                try:
                    of_resp = self._client.get(of_url, timeout=10.0)
                    if of_resp.status_code == 404:
                        prev_of = f"{start_year - 1}-{str(start_year)[-2:]}"
                        of_url = f"https://raw.githubusercontent.com/openfootball/football.json/master/{prev_of}/{of_slug}.json"
                        of_resp = self._client.get(of_url, timeout=10.0)
                    if of_resp.status_code == 200:
                        data = parse_openfootball_json(of_resp.json(), league_id, season_code=season_code)
                        http_status = 200
                        mirror_url = of_url
                        mirror_notes.append(f"OpenFootball İY/MS ({len(data.matches)} maç)")
                except Exception as exc:
                    logger.debug("OpenFootball yansı hatası (%s): %s", league_id.value, exc)

            try:
                st_code, cdn_url, cnt = self._enrich_team_stats_from_opta_cdn(
                    league_id, resolved_season, data
                )
                if st_code == 200 and cnt > 0:
                    http_status = 200
                    if mirror_url == primary_url and cdn_url:
                        mirror_url = cdn_url
                    mirror_notes.append(f"şut/korner/kart istatistikleri ({cnt} takım)")
            except Exception as exc:
                logger.debug("Opta istatistik zenginleştirme hatası (%s): %s", league_id.value, exc)

            records_cnt = max(len(data.matches), len(data.team_stats))
            if records_cnt > 0:
                return data, make_source_diagnostic(
                    self.SOURCE_NAME,
                    ok=True,
                    http_status=http_status or 200,
                    records=records_cnt,
                    url=mirror_url,
                    note="Birincil CSV İSS engeli nedeniyle " + " + ".join(mirror_notes),
                    error=None,
                )

        empty = FootballDataLeagueData(league_id=league_id, season_code=season_code)
        return empty, make_source_diagnostic(
            self.SOURCE_NAME,
            ok=False,
            http_status=http_status,
            records=0,
            url=used_url,
            note=note,
            error=error_msg or "Veri alınamadı",
        )
