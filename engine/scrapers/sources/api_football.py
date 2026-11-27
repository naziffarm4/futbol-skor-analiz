"""API-Football v3 resmi veri adaptörü ve paylaşımlı kota/önbellek bütçe takipçisi."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from engine.config import (
    API_FOOTBALL_LEAGUE_IDS,
    PROJECT_ROOT,
    LeagueId,
    Settings,
    get_season_start_year,
)
from engine.models.schemas import MatchStatus
from engine.scrapers.base import clean_text, normalize_team_name
from engine.scrapers.fixtures import ScrapedMatch, ScrapedTeam
from engine.scrapers.injuries import (
    ScrapedInjury,
    calculate_impact_level,
    map_player_position,
)
from engine.scrapers.sources import make_source_diagnostic
from engine.scrapers.sources.secondary_check import SecondaryInjuryRecord

logger = logging.getLogger(__name__)

DEFAULT_BUDGET_PATH = PROJECT_ROOT / "engine" / "data" / "quota_budget.json"
DEFAULT_CACHE_DIR = PROJECT_ROOT / "engine" / "data" / "api_cache"
MIN_REMAINING_QUOTA_GUARD = 15

_ROUND_NUM_RE = re.compile(r"(\d+)")
_URL_APIKEY_RE = re.compile(r"([?&](?:apiKey|api_key|key)=)[^&\s\"']+", re.IGNORECASE)


def redact_secret(text: str, *secrets: str) -> str:
    """Metin ve URL'lerdeki API anahtarlarını sızıntıya karşı maskeler."""
    sanitized = _URL_APIKEY_RE.sub(r"\1***REDACTED***", text or "")
    for sec in secrets:
        cleaned = (sec or "").strip()
        if cleaned and len(cleaned) >= 4:
            sanitized = sanitized.replace(cleaned, "***REDACTED***")
    return sanitized


class _SecretRedactingLogFilter(logging.Filter):
    """httpx / httpcore dahili INFO loglarındaki ?apiKey=... sorgu parametrelerini maskeler."""

    def filter(self, record: logging.LogRecord) -> bool:
        rendered = record.getMessage()
        if _URL_APIKEY_RE.search(rendered):
            record.msg = redact_secret(rendered)
            record.args = ()
        return True


def install_httpx_secret_redaction() -> None:
    for logger_name in ("httpx", "httpcore"):
        lg = logging.getLogger(logger_name)
        if not any(isinstance(flt, _SecretRedactingLogFilter) for flt in lg.filters):
            lg.addFilter(_SecretRedactingLogFilter())


install_httpx_secret_redaction()


class QuotaBudgetTracker:
    """API-Football (günlük) ve The Odds API (aylık) kota ve disk önbellek yöneticisi."""

    def __init__(
        self,
        *,
        budget_path: Path | None = None,
        cache_dir: Path | None = None,
        min_remaining: int = MIN_REMAINING_QUOTA_GUARD,
        default_ttl_seconds: float = 21600.0,
    ) -> None:
        self.budget_path = budget_path or DEFAULT_BUDGET_PATH
        self.cache_dir = cache_dir or DEFAULT_CACHE_DIR
        self.min_remaining = min_remaining
        self.default_ttl_seconds = default_ttl_seconds

    @staticmethod
    def build_cache_key(
        provider: str,
        endpoint: str,
        params: Mapping[str, Any] | None = None,
    ) -> str:
        safe_items: list[tuple[str, str]] = []
        for k, v in sorted((params or {}).items()):
            if k.lower() in {"apikey", "api_key", "key", "x-apisports-key"}:
                continue
            safe_items.append((str(k), str(v)))
        raw = f"{provider}|{endpoint}|{json.dumps(safe_items, separators=(',', ':'))}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    def _cache_file(self, provider: str, cache_key: str) -> Path:
        safe_provider = re.sub(r"[^a-z0-9_-]+", "_", provider.lower())
        return self.cache_dir / f"{safe_provider}_{cache_key}.json"

    def get_cached(
        self,
        provider: str,
        cache_key: str,
        *,
        ttl_seconds: float | None = None,
        allow_stale: bool = False,
        now_ts: float | None = None,
    ) -> dict[str, Any] | None:
        path = self._cache_file(provider, cache_key)
        if not path.is_file():
            return None
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(entry, dict) or "payload" not in entry:
            return None
        cached_at = float(entry.get("cached_at") or 0.0)
        ttl = self.default_ttl_seconds if ttl_seconds is None else ttl_seconds
        current = time.time() if now_ts is None else now_ts
        if not allow_stale and (current - cached_at) > ttl:
            return None
        return entry

    def set_cached(
        self,
        provider: str,
        cache_key: str,
        payload: Any,
        *,
        status_code: int = 200,
        now_ts: float | None = None,
    ) -> None:
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            entry = {
                "provider": provider,
                "cached_at": time.time() if now_ts is None else now_ts,
                "status_code": int(status_code),
                "payload": payload,
            }
            self._cache_file(provider, cache_key).write_text(
                json.dumps(entry, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("API önbellek yazma hatası (%s): %s", provider, exc)

    def _load_state(self) -> dict[str, Any]:
        if not self.budget_path.is_file():
            return {}
        try:
            data = json.loads(self.budget_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_state(self, state: dict[str, Any]) -> None:
        try:
            self.budget_path.parent.mkdir(parents=True, exist_ok=True)
            self.budget_path.write_text(
                json.dumps(state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Kota bütçe dosyası yazılamadı: %s", exc)

    @staticmethod
    def _period_key(provider: str, now_utc: datetime | None = None) -> str:
        dt = now_utc or datetime.now(UTC)
        if provider == "api_football":
            return dt.strftime("%Y-%m-%d")
        return dt.strftime("%Y-%m")

    def get_provider_status(
        self,
        provider: str,
        *,
        now_utc: datetime | None = None,
    ) -> dict[str, Any]:
        state = self._load_state()
        raw = state.get(provider)
        if not isinstance(raw, dict):
            return {"remaining": None, "limit": None, "used": None, "period": None}
        current_period = self._period_key(provider, now_utc=now_utc)
        if raw.get("period") and raw.get("period") != current_period:
            return {"remaining": None, "limit": raw.get("limit"), "used": 0, "period": current_period}
        return dict(raw)

    def can_request(self, provider: str, *, now_utc: datetime | None = None) -> bool:
        info = self.get_provider_status(provider, now_utc=now_utc)
        rem = info.get("remaining")
        if isinstance(rem, int) and rem < self.min_remaining:
            return False
        return True

    def record_headers(
        self,
        provider: str,
        headers: Mapping[str, str],
        *,
        now_utc: datetime | None = None,
    ) -> dict[str, Any]:
        lowered = {str(k).lower(): str(v).strip() for k, v in headers.items()}
        dt = now_utc or datetime.now(UTC)
        state = self._load_state()
        raw_prev = state.get(provider)
        entry: dict[str, Any] = dict(raw_prev) if isinstance(raw_prev, dict) else {}
        entry["period"] = self._period_key(provider, now_utc=dt)
        entry["updated_at"] = dt.isoformat()

        def _to_int(val: str | None) -> int | None:
            if val is not None and val.lstrip("-").isdigit():
                return int(val)
            return None

        if provider == "api_football":
            rem = _to_int(lowered.get("x-ratelimit-requests-remaining"))
            lim = _to_int(lowered.get("x-ratelimit-requests-limit"))
            if rem is not None:
                entry["remaining"] = rem
            if lim is not None:
                entry["limit"] = lim
            if rem is not None and lim is not None:
                entry["used"] = max(0, lim - rem)
        elif provider == "the_odds_api":
            rem = _to_int(lowered.get("x-requests-remaining"))
            used = _to_int(lowered.get("x-requests-used"))
            last_cost = _to_int(lowered.get("x-requests-last"))
            if rem is not None:
                entry["remaining"] = rem
            if used is not None:
                entry["used"] = used
            if last_cost is not None:
                entry["last_cost"] = last_cost
            if rem is not None and used is not None:
                entry["limit"] = rem + used

        state[provider] = entry
        self._save_state(state)
        return entry

    def snapshot(self, *, now_utc: datetime | None = None) -> dict[str, Any]:
        return {
            "api_football": self.get_provider_status("api_football", now_utc=now_utc),
            "the_odds_api": self.get_provider_status("the_odds_api", now_utc=now_utc),
        }


@dataclass(slots=True)
class ApiFootballLeagueData:
    league_id: LeagueId
    season_year: int
    teams: list[ScrapedTeam] = field(default_factory=list)
    matches: list[ScrapedMatch] = field(default_factory=list)
    ht_scores: dict[tuple[str, str], tuple[int, int]] = field(default_factory=dict)
    injuries: list[ScrapedInjury] = field(default_factory=list)
    secondary_injuries: list[SecondaryInjuryRecord] = field(default_factory=list)


def _extract_api_errors(payload: Mapping[str, Any]) -> str | None:
    errors = payload.get("errors")
    if isinstance(errors, Mapping) and errors:
        return "; ".join(f"{k}: {v}" for k, v in errors.items() if v)
    if isinstance(errors, list) and errors:
        return "; ".join(str(item) for item in errors if item)
    return None


def _parse_round_number(raw_round: object) -> int:
    text = clean_text(raw_round)
    matches = _ROUND_NUM_RE.findall(text)
    if matches:
        return max(1, int(matches[-1]))
    return 1


def _parse_iso_datetime(raw_date: object) -> datetime:
    text = clean_text(raw_date)
    if text:
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
        except ValueError:
            pass
    return datetime.now(UTC)


def _map_fixture_status(short_code: str) -> MatchStatus:
    code = (short_code or "").upper().strip()
    if code in {"FT", "AET", "PEN"}:
        return MatchStatus.FINISHED
    if code in {"PST", "CANC", "ABD", "SUSP", "AWD", "WO"}:
        return MatchStatus.POSTPONED
    return MatchStatus.SCHEDULED


def parse_api_football_fixtures(
    response_items: list[dict[str, Any]],
    league_id: LeagueId,
) -> tuple[list[ScrapedTeam], list[ScrapedMatch], dict[tuple[str, str], tuple[int, int]]]:
    teams_by_name: dict[str, ScrapedTeam] = {}
    matches: list[ScrapedMatch] = []
    ht_scores: dict[tuple[str, str], tuple[int, int]] = {}

    for item in response_items:
        if not isinstance(item, Mapping):
            continue
        teams_obj = item.get("teams") or {}
        home_obj = teams_obj.get("home") or {}
        away_obj = teams_obj.get("away") or {}
        home_name = normalize_team_name(str(home_obj.get("name") or ""))
        away_name = normalize_team_name(str(away_obj.get("name") or ""))
        if not home_name or not away_name:
            continue

        home_logo = clean_text(home_obj.get("logo")) or None
        away_logo = clean_text(away_obj.get("logo")) or None

        teams_by_name.setdefault(
            home_name,
            ScrapedTeam(
                league_id=league_id,
                name=home_name,
                short_name=home_name[:50],
                logo_url=home_logo,
            ),
        )
        teams_by_name.setdefault(
            away_name,
            ScrapedTeam(
                league_id=league_id,
                name=away_name,
                short_name=away_name[:50],
                logo_url=away_logo,
            ),
        )

        fx_obj = item.get("fixture") or {}
        status_short = str((fx_obj.get("status") or {}).get("short") or "NS")
        status = _map_fixture_status(status_short)
        match_dt = _parse_iso_datetime(fx_obj.get("date"))
        league_obj = item.get("league") or {}
        round_num = _parse_round_number(league_obj.get("round"))

        score_obj = item.get("score") or {}
        ft_obj = score_obj.get("fulltime") or {}
        goals_obj = item.get("goals") or {}
        ht_obj = score_obj.get("halftime") or {}

        raw_h = ft_obj.get("home") if ft_obj.get("home") is not None else goals_obj.get("home")
        raw_a = ft_obj.get("away") if ft_obj.get("away") is not None else goals_obj.get("away")
        home_score = int(raw_h) if isinstance(raw_h, int) and status == MatchStatus.FINISHED else None
        away_score = int(raw_a) if isinstance(raw_a, int) and status == MatchStatus.FINISHED else None

        ht_h = ht_obj.get("home")
        ht_a = ht_obj.get("away")
        if isinstance(ht_h, int) and isinstance(ht_a, int):
            ht_scores[(home_name, away_name)] = (ht_h, ht_a)

        matches.append(
            ScrapedMatch(
                league_id=league_id,
                home_team_name=home_name,
                away_team_name=away_name,
                match_date=match_dt,
                round=round_num,
                status=status,
                home_score=home_score,
                away_score=away_score,
                home_short_name=home_name[:50],
                away_short_name=away_name[:50],
                home_logo_url=home_logo,
                away_logo_url=away_logo,
            )
        )

    return list(teams_by_name.values()), matches, ht_scores


def parse_api_football_injuries(
    response_items: list[dict[str, Any]],
    league_id: LeagueId,
    *,
    reference_date: date | None = None,
) -> tuple[list[ScrapedInjury], list[SecondaryInjuryRecord]]:
    dedup_scraped: dict[tuple[str, str], ScrapedInjury] = {}
    dedup_secondary: dict[tuple[str, str], SecondaryInjuryRecord] = {}

    cutoff_date = (reference_date - timedelta(days=21)) if reference_date is not None else None

    for item in response_items:
        if not isinstance(item, Mapping):
            continue
        if cutoff_date is not None:
            fx_date_raw = clean_text((item.get("fixture") or {}).get("date"))
            if fx_date_raw:
                fx_dt = _parse_iso_datetime(fx_date_raw).date()
                if fx_dt < cutoff_date:
                    continue

        player_obj = item.get("player") or {}
        team_obj = item.get("team") or {}
        player_name = clean_text(player_obj.get("name"))
        team_name = normalize_team_name(str(team_obj.get("name") or ""))
        if not player_name or not team_name:
            continue

        reason_part = clean_text(player_obj.get("reason"))
        type_part = clean_text(player_obj.get("type"))
        reason = reason_part or type_part or "Kadro dışı / sakatlık"
        if type_part and reason_part and type_part.lower() not in reason_part.lower():
            full_reason = f"{reason_part} ({type_part})"
        else:
            full_reason = reason

        pos = map_player_position(clean_text(player_obj.get("pos") or ""))
        impact = calculate_impact_level(full_reason, reference_date=reference_date)
        key = (team_name.lower(), player_name.lower())

        dedup_scraped[key] = ScrapedInjury(
            league_id=league_id,
            team_name=team_name,
            player_name=player_name,
            position=pos,
            reason=full_reason,
            return_date=None,
            impact_level=impact,
        )
        dedup_secondary[key] = SecondaryInjuryRecord(
            team_name=team_name,
            player_name=player_name,
            reason=full_reason,
            return_info=type_part or None,
            source_name="API-Football",
        )

    return list(dedup_scraped.values()), list(dedup_secondary.values())


class ApiFootballAdapter:
    """API-Football v3 (api-sports.io) resmi fikstür ve sakatlık adaptörü."""

    SOURCE_NAME = "API-Football"
    BASE_URL = "https://v3.football.api-sports.io"
    PROVIDER_ID = "api_football"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        client: httpx.Client | None = None,
        tracker: QuotaBudgetTracker | None = None,
        cache_ttl_seconds: float = 21600.0,
        timeout: float = 15.0,
        fetch_injuries: bool = True,
    ) -> None:
        resolved_key = api_key if api_key is not None else Settings.from_env().api_football_key
        self._api_key = resolved_key.strip()
        self.tracker = tracker or QuotaBudgetTracker(default_ttl_seconds=cache_ttl_seconds)
        self.cache_ttl_seconds = cache_ttl_seconds
        self.fetch_injuries = fetch_injuries
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

    def __enter__(self) -> ApiFootballAdapter:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _get_json(
        self,
        endpoint: str,
        params: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, int | None, bool, str | None]:
        """(payload, http_status, from_cache, error_message) döndürür."""
        cache_key = self.tracker.build_cache_key(self.PROVIDER_ID, endpoint, params)
        cached = self.tracker.get_cached(
            self.PROVIDER_ID,
            cache_key,
            ttl_seconds=self.cache_ttl_seconds,
        )
        if cached is not None and isinstance(cached.get("payload"), dict):
            return cached["payload"], int(cached.get("status_code") or 200), True, None

        if not self.tracker.can_request(self.PROVIDER_ID):
            stale = self.tracker.get_cached(self.PROVIDER_ID, cache_key, allow_stale=True)
            if stale is not None and isinstance(stale.get("payload"), dict):
                return stale["payload"], int(stale.get("status_code") or 200), True, None
            rem = self.tracker.get_provider_status(self.PROVIDER_ID).get("remaining")
            return (
                None,
                None,
                False,
                f"Günlük kota koruma eşiği aktif (kalan={rem} < {self.tracker.min_remaining})",
            )

        try:
            resp = self._client.get(
                endpoint,
                params=params,
                headers={
                    "x-apisports-key": self._api_key,
                    "Accept": "application/json",
                },
            )
            self.tracker.record_headers(self.PROVIDER_ID, resp.headers)
        except Exception as exc:
            return None, None, False, redact_secret(str(exc), self._api_key)

        if resp.status_code != 200:
            return (
                None,
                resp.status_code,
                False,
                redact_secret(f"HTTP {resp.status_code}", self._api_key),
            )

        try:
            payload = resp.json()
        except Exception as exc:
            return None, resp.status_code, False, redact_secret(f"JSON hatası: {exc}", self._api_key)

        if not isinstance(payload, dict):
            return None, resp.status_code, False, "Beklenmeyen JSON kök tipi"

        self.tracker.set_cached(
            self.PROVIDER_ID,
            cache_key,
            payload,
            status_code=resp.status_code,
        )
        return payload, resp.status_code, False, None

    def fetch_league(
        self,
        league_id: LeagueId,
        *,
        season: str | None = None,
        reference_date: date | None = None,
    ) -> tuple[ApiFootballLeagueData | None, dict[str, Any]]:
        af_league_id = API_FOOTBALL_LEAGUE_IDS[league_id]
        season_year = get_season_start_year(season, today=reference_date)
        diag_url = f"{self.BASE_URL}/fixtures?league={af_league_id}&season={season_year}"

        if not self._api_key:
            return (
                None,
                make_source_diagnostic(
                    self.SOURCE_NAME,
                    ok=False,
                    url=diag_url,
                    note="API_FOOTBALL_KEY tanımlı değil; resmi API atlandı",
                ),
            )

        fx_payload, fx_status, fx_cached, fx_err = self._get_json(
            "/fixtures",
            {"league": af_league_id, "season": season_year},
        )
        quota_info = self.tracker.get_provider_status(self.PROVIDER_ID)
        rem_quota = quota_info.get("remaining")
        quota_label = f"kalan kota: {rem_quota}" if rem_quota is not None else "kota başlığı yok"

        if fx_payload is None:
            return (
                None,
                make_source_diagnostic(
                    self.SOURCE_NAME,
                    ok=False,
                    http_status=fx_status,
                    url=diag_url,
                    note=quota_label,
                    error=fx_err,
                ),
            )

        api_err = _extract_api_errors(fx_payload)
        if api_err:
            return (
                None,
                make_source_diagnostic(
                    self.SOURCE_NAME,
                    ok=False,
                    http_status=fx_status,
                    records=0,
                    url=diag_url,
                    note=f"{quota_label}{' (önbellek)' if fx_cached else ''}",
                    error=redact_secret(api_err, self._api_key),
                ),
            )

        raw_fixtures = fx_payload.get("response")
        fixture_list = raw_fixtures if isinstance(raw_fixtures, list) else []
        teams, matches, ht_scores = parse_api_football_fixtures(fixture_list, league_id)

        injuries: list[ScrapedInjury] = []
        sec_injuries: list[SecondaryInjuryRecord] = []
        notes: list[str] = [f"{len(matches)} fikstür"]
        if fx_cached:
            notes.append("önbellek")

        if self.fetch_injuries:
            inj_payload, _, inj_cached, inj_err = self._get_json(
                "/injuries",
                {"league": af_league_id, "season": season_year},
            )
            if inj_payload is not None and not _extract_api_errors(inj_payload):
                raw_inj = inj_payload.get("response")
                if isinstance(raw_inj, list):
                    injuries, sec_injuries = parse_api_football_injuries(
                        raw_inj,
                        league_id,
                        reference_date=reference_date,
                    )
                    notes.append(
                        f"{len(injuries)} sakatlık{' (önbellek)' if inj_cached else ''}"
                    )
            elif inj_err:
                notes.append(f"sakatlık uyarısı: {inj_err}")

        rem_after = self.tracker.get_provider_status(self.PROVIDER_ID).get("remaining")
        if rem_after is not None:
            notes.append(f"kalan kota: {rem_after}")

        data = ApiFootballLeagueData(
            league_id=league_id,
            season_year=season_year,
            teams=teams,
            matches=matches,
            ht_scores=ht_scores,
            injuries=injuries,
            secondary_injuries=sec_injuries,
        )
        total_records = len(matches) + len(injuries)
        return (
            data,
            make_source_diagnostic(
                self.SOURCE_NAME,
                ok=total_records > 0,
                http_status=fx_status,
                records=total_records,
                url=diag_url,
                note=", ".join(notes),
            ),
        )
