"""Polite HTTP istemcisi, rate-limiting, retry/backoff ve HTML ayrıştırma yardımcıları."""

from __future__ import annotations

import logging
import random
import re
import time
from collections.abc import Callable
from typing import Any

import httpx
from bs4 import BeautifulSoup, Tag

from engine.config import settings

logger = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})

DEFAULT_USER_AGENT: str = (
    "FutbolSkorAnaliz/1.0 (+https://github.com/naziffarm4/futbol-skor-analiz)"
)


class ScraperError(Exception):
    """Veri toplama katmanı için temel istisna sınıfı."""


class ScraperHTTPError(ScraperError):
    """HTTP yanıt veya ağ erişim hatası."""

    def __init__(self, message: str, *, status_code: int | None = None, url: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.url = url


class ScraperParseError(ScraperError):
    """HTML yapısının beklenen şablondan sapması durumunda fırlatılan hata."""


def build_browser_headers(
    *,
    referer: str | None = None,
    accept_language: str = "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    user_agent: str | None = None,
) -> dict[str, str]:
    """Proje kimliğini açıkça bildiren dürüst HTTP istemci başlıkları üretir."""
    headers: dict[str, str] = {
        "User-Agent": user_agent or DEFAULT_USER_AGENT,
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "application/json;q=0.8,*/*;q=0.7"
        ),
        "Accept-Language": accept_language,
    }
    if referer and referer.strip():
        headers["Referer"] = referer.strip()
    return headers


def parse_html(html: str) -> BeautifulSoup:
    """HTML metnini öncelikle lxml, bulunamazsa html.parser ile güvenli ayrıştırır."""
    if not html or not html.strip():
        raise ScraperParseError("Ayrıştırılacak HTML içeriği boş.")
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")


_RANK_BADGE_RE = re.compile(r"^\(\d+\.\)\s*|\s*\(\d+\.\)$")


def clean_text(target: object) -> str:
    """HTML düğümü veya metin içindeki fazla boşlukları tek boşluğa indirger."""
    if target is None:
        return ""
    if isinstance(target, Tag):
        raw = target.get_text(" ", strip=True)
    elif isinstance(target, (list, tuple)):
        raw = " ".join(str(item) for item in target)
    else:
        raw = str(target)
    return " ".join(raw.split())


def normalize_team_name(name: str) -> str:
    """Takım adlarındaki sıra rozetlerini (örn. '(1.)') ve fazla boşlukları temizler."""
    cleaned = _RANK_BADGE_RE.sub("", clean_text(name)).strip()
    return " ".join(cleaned.split())


class BaseScraper:
    """Rate-limiting ve exponential backoff destekli temel HTTP + BS4 istemcisi."""

    def __init__(
        self,
        *,
        base_url: str = "https://www.transfermarkt.com.tr",
        min_delay: float = 1.0,
        max_delay: float = 2.0,
        max_retries: int = 3,
        backoff_factor: float = 1.0,
        timeout: float | None = None,
        client: httpx.Client | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        if min_delay < 0 or max_delay < min_delay:
            raise ValueError("Geçersiz rate-limit aralığı: 0 <= min_delay <= max_delay olmalıdır.")
        if max_retries < 0:
            raise ValueError("max_retries negatif olamaz.")

        self.base_url = base_url.rstrip("/")
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self._sleep = sleep_fn
        self._last_request_ts: float | None = None
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=self.base_url,
            headers=build_browser_headers(),
            follow_redirects=True,
            timeout=timeout or settings.http_timeout_seconds,
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> BaseScraper:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def _respect_rate_limit(self) -> None:
        if self._last_request_ts is not None and self.max_delay > 0:
            target_gap = random.uniform(self.min_delay, self.max_delay)
            elapsed = time.monotonic() - self._last_request_ts
            remaining = target_gap - elapsed
            if remaining > 0:
                self._sleep(remaining)

    def _compute_backoff(self, attempt: int, response: httpx.Response | None = None) -> float:
        if response is not None:
            retry_after = response.headers.get("Retry-After", "").strip()
            if retry_after.isdigit():
                return max(float(retry_after), self.backoff_factor)
        jitter = random.uniform(0.0, 0.3 * self.backoff_factor)
        return float(self.backoff_factor * (2**attempt) + jitter)

    def fetch_text(self, url_or_path: str, *, params: dict[str, Any] | None = None) -> str:
        """Verilen URL/yolu rate-limit ve retry/backoff kurallarıyla çeker."""
        last_exc: Exception | None = None

        for attempt in range(self.max_retries + 1):
            self._respect_rate_limit()
            try:
                response = self._client.get(
                    url_or_path,
                    params=params,
                    headers={"User-Agent": DEFAULT_USER_AGENT},
                )
                self._last_request_ts = time.monotonic()
            except httpx.HTTPError as exc:
                self._last_request_ts = time.monotonic()
                last_exc = exc
                if attempt < self.max_retries:
                    wait_s = self._compute_backoff(attempt)
                    logger.warning(
                        "Ağ hatası (%s) - deneme %d/%d, %.2fs bekleniyor: %s",
                        url_or_path,
                        attempt + 1,
                        self.max_retries,
                        wait_s,
                        exc,
                    )
                    self._sleep(wait_s)
                    continue
                raise ScraperHTTPError(
                    f"HTTP isteği başarısız oldu ({url_or_path}): {exc}",
                    url=url_or_path,
                ) from exc

            status_code = response.status_code
            if status_code in RETRYABLE_STATUS_CODES:
                if attempt < self.max_retries:
                    wait_s = self._compute_backoff(attempt, response=response)
                    logger.warning(
                        "Geçici HTTP %d (%s) - deneme %d/%d, %.2fs bekleniyor.",
                        status_code,
                        url_or_path,
                        attempt + 1,
                        self.max_retries,
                        wait_s,
                    )
                    self._sleep(wait_s)
                    continue
                raise ScraperHTTPError(
                    f"Sunucu geçici hata döndürdü: HTTP {status_code} ({url_or_path})",
                    status_code=status_code,
                    url=url_or_path,
                )

            if status_code == 202 or status_code >= 400 or not response.text.strip():
                raise ScraperHTTPError(
                    f"HTTP yanıtı geçersiz veya erişim engeli ({status_code}): {url_or_path}",
                    status_code=status_code,
                    url=url_or_path,
                )

            return response.text

        raise ScraperHTTPError(
            f"İstek tamamlanamadı ({url_or_path}): {last_exc}",
            url=url_or_path,
        )

    def fetch_soup(
        self, url_or_path: str, *, params: dict[str, Any] | None = None
    ) -> BeautifulSoup:
        """Sayfayı çeker ve BeautifulSoup nesnesi olarak döndürür."""
        return parse_html(self.fetch_text(url_or_path, params=params))
