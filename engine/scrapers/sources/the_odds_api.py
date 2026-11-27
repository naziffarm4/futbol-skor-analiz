"""The Odds API v4 konsensüs piyasa oranları ve marj arındırma (de-vigging) adaptörü."""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

from engine.config import THE_ODDS_API_SPORT_KEYS, LeagueId, Settings
from engine.scrapers.base import clean_text, normalize_team_name
from engine.scrapers.sources import make_source_diagnostic
from engine.scrapers.sources.api_football import QuotaBudgetTracker, redact_secret

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class MarketMatchOdds:
    home_team: str
    away_team: str
    commence_time: str
    p_home: float
    p_draw: float
    p_away: float
    p_over25: float | None = None
    p_under25: float | None = None
    bookmakers_count: int = 0
    overround_1x2: float | None = None

    def to_dict(self) -> dict[str, float | int | str | None]:
        return {
            "home_team": self.home_team,
            "away_team": self.away_team,
            "commence_time": self.commence_time,
            "p_home": self.p_home,
            "p_draw": self.p_draw,
            "p_away": self.p_away,
            "p_over25": self.p_over25,
            "p_under25": self.p_under25,
            "bookmakers_count": self.bookmakers_count,
            "overround_1x2": self.overround_1x2,
        }


@dataclass(slots=True)
class TheOddsLeagueData:
    league_id: LeagueId
    sport_key: str
    matches: list[MarketMatchOdds] = field(default_factory=list)


DevigMethod = Literal["power", "proportional"]


def devig_power(
    odds: Sequence[float],
    *,
    tol: float = 1e-12,
    max_iter: int = 100,
) -> tuple[float, ...]:
    """Bahisçi marjını (overround) Power yöntemiyle arındırır: sum(q_i^k) = 1 (tol <= 1e-10)."""
    if len(odds) < 2:
        raise ValueError("Marj arındırma için en az 2 oran gereklidir.")
    if any(not math.isfinite(o) or o <= 1.0 for o in odds):
        raise ValueError("Oranların tamamı 1.0'dan büyük sonlu sayılar olmalıdır.")

    qs = [1.0 / float(o) for o in odds]
    overround = sum(qs)
    if overround <= 1.0 + tol:
        return tuple(q / overround for q in qs)

    lo = 1.0
    hi = 2.0
    while sum(q**hi for q in qs) > 1.0 and hi < 1e6:
        lo = hi
        hi *= 2.0

    k = 0.5 * (lo + hi)
    for _ in range(max_iter):
        qs_k = [q**k for q in qs]
        f_val = sum(qs_k) - 1.0
        if abs(f_val) <= tol or (hi - lo) <= tol:
            break
        if f_val > 0.0:
            lo = k
        else:
            hi = k
        df_val = sum(qk * math.log(q) for qk, q in zip(qs_k, qs, strict=True))
        if df_val < -1e-15:
            cand = k - f_val / df_val
            k = cand if lo < cand < hi else 0.5 * (lo + hi)
        else:
            k = 0.5 * (lo + hi)

    raw_probs = [q**k for q in qs]
    tot = sum(raw_probs)
    return tuple(p / tot for p in raw_probs)


def devig_three_way(
    odd_home: float,
    odd_draw: float,
    odd_away: float,
    *,
    method: DevigMethod = "power",
) -> tuple[float, float, float, float] | None:
    """1X2 ondalık oranlarından bahisçi marjını (vig/overround) arındırır."""
    if (
        not (math.isfinite(odd_home) and math.isfinite(odd_draw) and math.isfinite(odd_away))
        or odd_home <= 1.0
        or odd_draw <= 1.0
        or odd_away <= 1.0
    ):
        return None
    q_h = 1.0 / odd_home
    q_d = 1.0 / odd_draw
    q_a = 1.0 / odd_away
    overround = q_h + q_d + q_a
    if overround <= 0.0:
        return None
    if method == "proportional":
        return q_h / overround, q_d / overround, q_a / overround, overround
    p_h, p_d, p_a = devig_power((odd_home, odd_draw, odd_away))
    return p_h, p_d, p_a, overround


def devig_two_way(
    odd_over: float,
    odd_under: float,
    *,
    method: DevigMethod = "power",
) -> tuple[float, float] | None:
    """2 yönlü (Alt/Üst 2.5) ondalık oranlardan bahisçi marjını arındırır."""
    if (
        not (math.isfinite(odd_over) and math.isfinite(odd_under))
        or odd_over <= 1.0
        or odd_under <= 1.0
    ):
        return None
    q_o = 1.0 / odd_over
    q_u = 1.0 / odd_under
    total = q_o + q_u
    if total <= 0.0:
        return None
    if method == "proportional":
        return q_o / total, q_u / total
    p_o, p_u = devig_power((odd_over, odd_under))
    return p_o, p_u


def parse_the_odds_events(
    events: list[dict[str, Any]],
    *,
    method: DevigMethod = "power",
) -> list[MarketMatchOdds]:
    """The Odds API etkinlik listesinden konsensüs marjsız 1X2 ve 2.5 Alt/Üst olasılıklarını hesaplar."""
    results: list[MarketMatchOdds] = []

    for ev in events:
        if not isinstance(ev, Mapping):
            continue
        raw_home = clean_text(ev.get("home_team"))
        raw_away = clean_text(ev.get("away_team"))
        home_team = normalize_team_name(raw_home)
        away_team = normalize_team_name(raw_away)
        if not home_team or not away_team:
            continue

        commence_time = clean_text(ev.get("commence_time"))
        bookmakers = ev.get("bookmakers")
        if not isinstance(bookmakers, list) or not bookmakers:
            continue

        h2h_samples: list[tuple[float, float, float]] = []
        overrounds: list[float] = []
        totals_samples: list[tuple[float, float]] = []

        for bm in bookmakers:
            if not isinstance(bm, Mapping):
                continue
            markets = bm.get("markets")
            if not isinstance(markets, list):
                continue

            for mk in markets:
                if not isinstance(mk, Mapping):
                    continue
                mkey = clean_text(mk.get("key")).lower()
                outcomes = mk.get("outcomes")
                if not isinstance(outcomes, list):
                    continue

                if mkey == "h2h":
                    odd_h: float | None = None
                    odd_d: float | None = None
                    odd_a: float | None = None
                    for out in outcomes:
                        if not isinstance(out, Mapping):
                            continue
                        oname = clean_text(out.get("name"))
                        try:
                            price = float(out.get("price") or 0.0)
                        except (TypeError, ValueError):
                            continue
                        if price <= 1.0:
                            continue
                        if oname == raw_home or normalize_team_name(oname) == home_team:
                            odd_h = price
                        elif oname == raw_away or normalize_team_name(oname) == away_team:
                            odd_a = price
                        elif oname.lower() == "draw":
                            odd_d = price

                    if odd_h is not None and odd_d is not None and odd_a is not None:
                        dv = devig_three_way(odd_h, odd_d, odd_a, method=method)
                        if dv is not None:
                            h2h_samples.append((dv[0], dv[1], dv[2]))
                            overrounds.append(dv[3])

                elif mkey == "totals":
                    odd_over: float | None = None
                    odd_under: float | None = None
                    for out in outcomes:
                        if not isinstance(out, Mapping):
                            continue
                        try:
                            point = float(out.get("point") or 0.0)
                            price = float(out.get("price") or 0.0)
                        except (TypeError, ValueError):
                            continue
                        if abs(point - 2.5) > 1e-6 or price <= 1.0:
                            continue
                        oname_low = clean_text(out.get("name")).lower()
                        if oname_low == "over":
                            odd_over = price
                        elif oname_low == "under":
                            odd_under = price

                    if odd_over is not None and odd_under is not None:
                        dv_tot = devig_two_way(odd_over, odd_under, method=method)
                        if dv_tot is not None:
                            totals_samples.append(dv_tot)

        if not h2h_samples:
            continue

        n_bm = len(h2h_samples)
        mean_h = sum(s[0] for s in h2h_samples) / n_bm
        mean_d = sum(s[1] for s in h2h_samples) / n_bm
        mean_a = sum(s[2] for s in h2h_samples) / n_bm
        total_1x2 = mean_h + mean_d + mean_a
        p_home = round(mean_h / total_1x2, 6)
        p_draw = round(mean_d / total_1x2, 6)
        p_away = round(max(0.0, 1.0 - p_home - p_draw), 6)

        p_over25: float | None = None
        p_under25: float | None = None
        if totals_samples:
            n_tot = len(totals_samples)
            mean_o = sum(s[0] for s in totals_samples) / n_tot
            mean_u = sum(s[1] for s in totals_samples) / n_tot
            tot_ou = mean_o + mean_u
            if tot_ou > 0.0:
                p_over25 = round(mean_o / tot_ou, 6)
                p_under25 = round(max(0.0, 1.0 - p_over25), 6)

        avg_overround = round(sum(overrounds) / len(overrounds), 4) if overrounds else None

        results.append(
            MarketMatchOdds(
                home_team=home_team,
                away_team=away_team,
                commence_time=commence_time,
                p_home=p_home,
                p_draw=p_draw,
                p_away=p_away,
                p_over25=p_over25,
                p_under25=p_under25,
                bookmakers_count=n_bm,
                overround_1x2=avg_overround,
            )
        )

    return results


class TheOddsApiAdapter:
    """The Odds API v4 üzerinden Avrupa bahis büroları konsensüs olasılıklarını çeker."""

    SOURCE_NAME = "TheOddsAPI"
    BASE_URL = "https://api.the-odds-api.com"
    PROVIDER_ID = "the_odds_api"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        client: httpx.Client | None = None,
        tracker: QuotaBudgetTracker | None = None,
        cache_ttl_seconds: float = 21600.0,
        timeout: float = 15.0,
    ) -> None:
        resolved_key = api_key if api_key is not None else Settings.from_env().the_odds_api_key
        self._api_key = resolved_key.strip()
        self.tracker = tracker or QuotaBudgetTracker(default_ttl_seconds=cache_ttl_seconds)
        self.cache_ttl_seconds = cache_ttl_seconds
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=self.BASE_URL,
            follow_redirects=True,
            timeout=timeout,
        )

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> TheOddsApiAdapter:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def fetch_league(self, league_id: LeagueId) -> tuple[TheOddsLeagueData | None, dict[str, Any]]:
        sport_key = THE_ODDS_API_SPORT_KEYS[league_id]
        endpoint = f"/v4/sports/{sport_key}/odds"
        public_params = {
            "regions": "eu",
            "markets": "h2h,totals",
            "oddsFormat": "decimal",
        }
        sanitized_url = (
            f"{self.BASE_URL}{endpoint}?regions=eu&markets=h2h,totals&oddsFormat=decimal"
        )

        if not self._api_key:
            return (
                None,
                make_source_diagnostic(
                    self.SOURCE_NAME,
                    ok=False,
                    url=sanitized_url,
                    note="THE_ODDS_API_KEY tanımlı değil; piyasa konsensüs oranları atlandı",
                ),
            )

        cache_key = self.tracker.build_cache_key(self.PROVIDER_ID, endpoint, public_params)
        cached = self.tracker.get_cached(
            self.PROVIDER_ID,
            cache_key,
            ttl_seconds=self.cache_ttl_seconds,
        )
        if cached is not None and isinstance(cached.get("payload"), list):
            parsed_cached = parse_the_odds_events(cached["payload"])
            rem_cached = self.tracker.get_provider_status(self.PROVIDER_ID).get("remaining")
            quota_txt = f", kalan kredi: {rem_cached}" if rem_cached is not None else ""
            return (
                TheOddsLeagueData(league_id=league_id, sport_key=sport_key, matches=parsed_cached),
                make_source_diagnostic(
                    self.SOURCE_NAME,
                    ok=len(parsed_cached) > 0,
                    http_status=int(cached.get("status_code") or 200),
                    records=len(parsed_cached),
                    url=sanitized_url,
                    note=f"{len(parsed_cached)} maç konsensüs oranı (önbellek{quota_txt})",
                ),
            )

        if not self.tracker.can_request(self.PROVIDER_ID):
            stale = self.tracker.get_cached(self.PROVIDER_ID, cache_key, allow_stale=True)
            if stale is not None and isinstance(stale.get("payload"), list):
                parsed_stale = parse_the_odds_events(stale["payload"])
                return (
                    TheOddsLeagueData(
                        league_id=league_id, sport_key=sport_key, matches=parsed_stale
                    ),
                    make_source_diagnostic(
                        self.SOURCE_NAME,
                        ok=len(parsed_stale) > 0,
                        http_status=int(stale.get("status_code") or 200),
                        records=len(parsed_stale),
                        url=sanitized_url,
                        note=f"{len(parsed_stale)} maç (kota koruması nedeniyle bayat önbellek)",
                    ),
                )
            rem = self.tracker.get_provider_status(self.PROVIDER_ID).get("remaining")
            return (
                None,
                make_source_diagnostic(
                    self.SOURCE_NAME,
                    ok=False,
                    url=sanitized_url,
                    note=f"Aylık kota koruma eşiği aktif (kalan={rem} < {self.tracker.min_remaining})",
                ),
            )

        req_params = {**public_params, "apiKey": self._api_key}
        try:
            resp = self._client.get(
                endpoint,
                params=req_params,
                headers={"Accept": "application/json"},
            )
            quota_entry = self.tracker.record_headers(self.PROVIDER_ID, resp.headers)
        except Exception as exc:
            safe_err = redact_secret(str(exc), self._api_key)
            return (
                None,
                make_source_diagnostic(
                    self.SOURCE_NAME,
                    ok=False,
                    url=sanitized_url,
                    error=safe_err,
                ),
            )

        rem_now = quota_entry.get("remaining")
        quota_suffix = f", kalan kredi: {rem_now}" if rem_now is not None else ""

        if resp.status_code != 200:
            err_detail = f"HTTP {resp.status_code}"
            try:
                err_json = resp.json()
                if isinstance(err_json, Mapping) and err_json.get("message"):
                    err_detail = f"HTTP {resp.status_code}: {err_json['message']}"
            except Exception:
                pass
            return (
                None,
                make_source_diagnostic(
                    self.SOURCE_NAME,
                    ok=False,
                    http_status=resp.status_code,
                    url=sanitized_url,
                    note=quota_suffix.lstrip(", ") or None,
                    error=redact_secret(err_detail, self._api_key),
                ),
            )

        try:
            payload = resp.json()
        except Exception as exc:
            return (
                None,
                make_source_diagnostic(
                    self.SOURCE_NAME,
                    ok=False,
                    http_status=resp.status_code,
                    url=sanitized_url,
                    error=redact_secret(f"JSON hatası: {exc}", self._api_key),
                ),
            )

        if not isinstance(payload, list):
            msg = payload.get("message") if isinstance(payload, Mapping) else "Beklenmeyen yanıt"
            return (
                None,
                make_source_diagnostic(
                    self.SOURCE_NAME,
                    ok=False,
                    http_status=resp.status_code,
                    url=sanitized_url,
                    error=redact_secret(str(msg), self._api_key),
                ),
            )

        self.tracker.set_cached(
            self.PROVIDER_ID,
            cache_key,
            payload,
            status_code=resp.status_code,
        )
        matches = parse_the_odds_events(payload)
        return (
            TheOddsLeagueData(league_id=league_id, sport_key=sport_key, matches=matches),
            make_source_diagnostic(
                self.SOURCE_NAME,
                ok=len(matches) > 0,
                http_status=resp.status_code,
                records=len(matches),
                url=sanitized_url,
                note=f"{len(matches)} maç konsensüs oranı{quota_suffix}",
            ),
        )
