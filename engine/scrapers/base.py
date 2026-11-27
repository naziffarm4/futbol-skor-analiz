"""Polite HTTP istemcisi, rate-limiting, retry/backoff ve HTML ayrıştırma yardımcıları."""

from __future__ import annotations

import logging
import os
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
WAF_CHALLENGE_STATUS_CODES: frozenset[int] = frozenset({202})

USER_AGENTS: tuple[str, ...] = (
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_1) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) "
        "Gecko/20100101 Firefox/133.0"
    ),
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
    referer: str = "https://www.transfermarkt.com.tr/",
    accept_language: str = "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    user_agent: str | None = None,
) -> dict[str, str]:
    """Bot korumalarına karşı gerçekçi masaüstü tarayıcı başlıkları üretir."""
    ua = user_agent or random.choice(USER_AGENTS)
    return {
        "User-Agent": ua,
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": accept_language,
        "Referer": referer,
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }


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


def _is_waf_challenge(response: httpx.Response) -> bool:
    """CloudFront / AWS WAF JS doğrulama yanıtlarını (HTTP 202 vb.) tespit eder."""
    if response.status_code in WAF_CHALLENGE_STATUS_CODES:
        return True
    if response.headers.get("x-amzn-waf-action", "").lower() == "challenge":
        return True
    return "AwsWafIntegration" in response.text[:4096]


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
        browser_fetcher: Callable[[str], tuple[int, str]] | None = None,
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
        self._browser_fetcher = browser_fetcher
        self._use_browser = False
        self._pw: Any = None
        self._browser: Any = None
        self._browser_context: Any = None
        self._browser_page: Any = None
        self._last_request_ts: float | None = None
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=self.base_url,
            headers=build_browser_headers(referer=f"{self.base_url}/"),
            follow_redirects=True,
            timeout=timeout or settings.http_timeout_seconds,
        )

    def close(self) -> None:
        for attr, method in (
            ("_browser_context", "close"),
            ("_browser", "close"),
            ("_pw", "stop"),
        ):
            obj = getattr(self, attr, None)
            if obj is not None:
                try:
                    getattr(obj, method)()
                except Exception:
                    pass
                setattr(self, attr, None)
        self._browser_page = None
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> BaseScraper:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def _build_full_url(self, url_or_path: str, params: dict[str, Any] | None = None) -> str:
        target = httpx.URL(self.base_url).join(url_or_path)
        if params:
            target = target.copy_merge_params(params)
        return str(target)

    def _ensure_browser_page(self) -> Any:
        # shortcut: Veri merkezi IP'lerinde AWS WAF HTTP 202 JS doğrulamasını yalnızca gerektiğinde çözer;
        # resmi API'ye geçildiğinde kaldırılabilir.
        if self._browser_page is not None:
            return self._browser_page
        from playwright.sync_api import sync_playwright

        headed = os.getenv("SCRAPER_HEADED", "").strip() == "1"
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ]
        self._pw = sync_playwright().start()
        try:
            self._browser = self._pw.chromium.launch(
                channel="chrome", headless=not headed, args=launch_args
            )
        except Exception:
            self._browser = self._pw.chromium.launch(headless=not headed, args=launch_args)

        ua_override: str | None = None
        if not headed:
            tmp_page = self._browser.new_page()
            try:
                raw_ua = str(tmp_page.evaluate("() => navigator.userAgent") or "")
                if "HeadlessChrome/" in raw_ua:
                    ua_override = raw_ua.replace("HeadlessChrome/", "Chrome/")
            finally:
                tmp_page.close()

        ctx_kwargs: dict[str, Any] = {
            "locale": "tr-TR",
            "viewport": {"width": 1366, "height": 768},
            "extra_http_headers": {
                "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
            },
        }
        if ua_override:
            ctx_kwargs["user_agent"] = ua_override

        self._browser_context = self._browser.new_context(**ctx_kwargs)
        self._browser_page = self._browser_context.new_page()
        return self._browser_page

    @staticmethod
    def _safe_page_content(page: Any) -> str:
        for _ in range(3):
            try:
                return str(page.content())
            except Exception:
                page.wait_for_timeout(400)
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        return str(page.content())

    def _run_browser_get(self, full_url: str) -> tuple[int, str]:
        if self._browser_fetcher is not None:
            return self._browser_fetcher(full_url)
        page = self._ensure_browser_page()
        timeout_ms = int(max(settings.http_timeout_seconds, 30.0) * 1500)
        resp = page.goto(full_url, wait_until="domcontentloaded", timeout=timeout_ms)
        status = int(resp.status) if resp is not None else 200
        content = self._safe_page_content(page)

        if status in WAF_CHALLENGE_STATUS_CODES or "AwsWafIntegration" in content[:4096]:
            deadline = time.monotonic() + 25.0
            while time.monotonic() < deadline:
                cookies = self._browser_context.cookies()
                if any(c.get("name") == "aws-waf-token" for c in cookies):
                    break
                page.wait_for_timeout(500)
            try:
                page.wait_for_selector("div.box", timeout=10000)
            except Exception:
                pass
            content = self._safe_page_content(page)
            if 'class="box"' in content and "AwsWafIntegration" not in content[:4096]:
                status = 200
            else:
                resp = page.goto(full_url, wait_until="domcontentloaded", timeout=timeout_ms)
                status = int(resp.status) if resp is not None else 200
                content = self._safe_page_content(page)

        return status, content

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
            status_code: int
            body_text: str
            resp_for_backoff: httpx.Response | None = None

            if not self._use_browser:
                try:
                    response = self._client.get(
                        url_or_path,
                        params=params,
                        headers={"User-Agent": random.choice(USER_AGENTS)},
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

                if _is_waf_challenge(response):
                    logger.warning(
                        "AWS WAF doğrulaması algılandı (HTTP %d: %s); tarayıcı oturumuna geçiliyor.",
                        response.status_code,
                        url_or_path,
                    )
                    self._use_browser = True
                else:
                    resp_for_backoff = response
                    status_code = response.status_code
                    body_text = response.text

            if self._use_browser:
                full_url = self._build_full_url(url_or_path, params)
                try:
                    status_code, body_text = self._run_browser_get(full_url)
                    self._last_request_ts = time.monotonic()
                except Exception as exc:
                    self._last_request_ts = time.monotonic()
                    last_exc = exc
                    if attempt < self.max_retries:
                        wait_s = self._compute_backoff(attempt)
                        logger.warning(
                            "Tarayıcı ağ hatası (%s) - deneme %d/%d, %.2fs bekleniyor: %s",
                            url_or_path,
                            attempt + 1,
                            self.max_retries,
                            wait_s,
                            exc,
                        )
                        self._sleep(wait_s)
                        continue
                    raise ScraperHTTPError(
                        f"Tarayıcı isteği başarısız oldu ({url_or_path}): {exc}",
                        url=url_or_path,
                    ) from exc

            if status_code in RETRYABLE_STATUS_CODES or status_code in WAF_CHALLENGE_STATUS_CODES:
                if attempt < self.max_retries:
                    wait_s = self._compute_backoff(attempt, response=resp_for_backoff)
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

            if status_code >= 400:
                raise ScraperHTTPError(
                    f"HTTP hatası {status_code}: {url_or_path}",
                    status_code=status_code,
                    url=url_or_path,
                )

            return body_text

        raise ScraperHTTPError(
            f"İstek tamamlanamadı ({url_or_path}): {last_exc}",
            url=url_or_path,
        )

    def fetch_soup(
        self, url_or_path: str, *, params: dict[str, Any] | None = None
    ) -> BeautifulSoup:
        """Sayfayı çeker ve BeautifulSoup nesnesi olarak döndürür."""
        return parse_html(self.fetch_text(url_or_path, params=params))
